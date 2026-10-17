"""Read-only completeness audit of the CEO Meloni PDF against published data.

Never writes. Never publishes. Never invents URLs.

  python -m scripts.audit_meloni_pdf_completeness
  python -m scripts.audit_meloni_pdf_completeness --json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import AppEnvironment, configured_environment
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    Politician,
    PoliticianVersion,
    PoliticalPartyAffiliation,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalDraft,
    ProposalType,
)
from backend.app.models.politician_profile import (
    PoliticianBiography,
    PoliticianCareerEntry,
    PoliticianPosition,
    PoliticianProceeding,
    PoliticianProfileSource,
    ProfileContentKind,
    ProfileContentStatus,
)
from backend.app.services.pledge_service import PledgeService
from backend.app.services.reference_profile_audit import (
    DEFAULT_FIXTURE,
    is_complete_source_url,
    resolve_politician,
)
from scripts.audit_reference_profile import resolve_database_url
from scripts.prepare_demo import DemoSafetyError
from scripts.prepare_reference_profile import _load_fixture
from scripts.reconcile_meloni_showcase import CEO_PROPOSAL_IDS, SHOWCASE_EXTRAS


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PDC_START = date(2022, 10, 21)
PDF_PDC_START = date(2022, 10, 22)

MATCHES_PUBLISHED = "MATCHES_PUBLISHED"
UPDATE_PUBLISHED_TEXT = "UPDATE_PUBLISHED_TEXT"
CREATE_PENDING = "CREATE_PENDING"
PUBLISH_VERIFIED = "PUBLISH_VERIFIED"
REUSE_EXISTING = "REUSE_EXISTING"
SUPERSEDE_DUPLICATE = "SUPERSEDE_DUPLICATE"
BLOCKED_SOURCE = "BLOCKED_SOURCE"
NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"

PUBLISHED = "PUBLISHED"
PENDING = "PENDING"
BLOCKED = "BLOCKED"
MISSING = "MISSING"


@dataclass
class InventoryRow:
    section: str
    item: str
    db_representation: str
    publication_state: str
    source_state: str
    status: str
    action: str
    notes: str = ""


@dataclass
class CompletenessReport:
    politician_id: int
    politician_name: str
    canonical_pdc_start: str
    pdf_pdc_start: str
    pdc_date_discrepancy: bool
    identity: list[InventoryRow] = field(default_factory=list)
    biography: list[InventoryRow] = field(default_factory=list)
    career: list[InventoryRow] = field(default_factory=list)
    positions: list[InventoryRow] = field(default_factory=list)
    promises: list[InventoryRow] = field(default_factory=list)
    proceedings: list[InventoryRow] = field(default_factory=list)
    sources: list[InventoryRow] = field(default_factory=list)

    def all_rows(self) -> list[InventoryRow]:
        return [
            *self.identity,
            *self.biography,
            *self.career,
            *self.positions,
            *self.promises,
            *self.proceedings,
            *self.sources,
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "politician_id": self.politician_id,
            "politician_name": self.politician_name,
            "canonical_pdc_start": self.canonical_pdc_start,
            "pdf_pdc_start": self.pdf_pdc_start,
            "pdc_date_discrepancy": self.pdc_date_discrepancy,
            "counts": {
                "published": sum(1 for row in self.all_rows() if row.status == PUBLISHED),
                "pending": sum(1 for row in self.all_rows() if row.status == PENDING),
                "blocked": sum(1 for row in self.all_rows() if row.status == BLOCKED),
                "missing": sum(1 for row in self.all_rows() if row.status == MISSING),
            },
            "identity": [asdict(row) for row in self.identity],
            "biography": [asdict(row) for row in self.biography],
            "career": [asdict(row) for row in self.career],
            "positions": [asdict(row) for row in self.positions],
            "promises": [asdict(row) for row in self.promises],
            "proceedings": [asdict(row) for row in self.proceedings],
            "sources": [asdict(row) for row in self.sources],
        }


def _readonly_engine(database_url: str):
    from sqlalchemy import event

    engine = create_db_engine(database_url)
    parsed = make_url(database_url)
    if parsed.drivername.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _query_only(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
            dbapi_connection.execute("PRAGMA query_only = ON")

    return engine


def _sources(session: Session, kind: ProfileContentKind, content_id: int) -> list[PoliticianProfileSource]:
    return list(
        session.scalars(
            select(PoliticianProfileSource)
            .where(
                PoliticianProfileSource.content_kind == kind,
                PoliticianProfileSource.content_id == content_id,
            )
            .order_by(PoliticianProfileSource.sort_index, PoliticianProfileSource.id)
        )
    )


def _source_state(sources: list[PoliticianProfileSource]) -> str:
    if not sources:
        return "none"
    complete = [row for row in sources if is_complete_source_url(row.url)]
    incomplete = [row for row in sources if not is_complete_source_url(row.url)]
    if complete and not incomplete:
        return "verified"
    if complete and incomplete:
        return "partial"
    return "incomplete"


def _latest(session: Session, model, politician_id: int, identity_key: str):
    rows = list(
        session.scalars(
            select(model)
            .where(model.politician_id == politician_id, model.identity_key == identity_key)
            .order_by(model.id.desc())
        )
    )
    published = [row for row in rows if row.status is ProfileContentStatus.PUBLISHED]
    if published:
        return published[0]
    return rows[0] if rows else None


def _meloni_pledges(session: Session, politician_id: int) -> list[Proposal]:
    return list(
        session.scalars(
            select(Proposal)
            .join(ProposalActor, ProposalActor.proposal_id == Proposal.id)
            .where(
                ProposalActor.politician_id == politician_id,
                ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
                Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
            )
            .order_by(Proposal.id)
            .distinct()
        )
    )


def audit_completeness(
    session: Session,
    politician: Politician,
    *,
    fixture_path: Path = DEFAULT_FIXTURE,
) -> CompletenessReport:
    fixture = _load_fixture(fixture_path)
    version = (
        session.get(PoliticianVersion, politician.current_version_id)
        if politician.current_version_id
        else None
    )
    profile = version.profile_data if version is not None else {}
    birth_place = ((profile or {}).get("birth_place") or {}).get("city")
    mandates = list((profile or {}).get("mandates") or [])
    pdc = next(
        (
            row
            for row in mandates
            if "presidente del consiglio" in " ".join(
                str(row.get(key) or "") for key in ("office", "mandate_type", "institution")
            ).casefold()
        ),
        None,
    )
    affiliations = list(
        session.scalars(
            select(PoliticalPartyAffiliation).where(
                PoliticalPartyAffiliation.politician_id == politician.id
            )
        )
    )
    career_fdi = _latest(
        session, PoliticianCareerEntry, politician.id, "presidente-fdi-2014"
    )
    report = CompletenessReport(
        politician_id=politician.id,
        politician_name=f"{politician.canonical_given_name} {politician.canonical_family_name}",
        canonical_pdc_start=CANONICAL_PDC_START.isoformat(),
        pdf_pdc_start=PDF_PDC_START.isoformat(),
        pdc_date_discrepancy=True,
    )

    report.identity = [
        InventoryRow(
            "identity",
            "Nome e cognome: Giorgia Meloni",
            f"{politician.canonical_given_name} {politician.canonical_family_name}",
            PUBLISHED.lower(),
            "canonical politician record",
            PUBLISHED,
            MATCHES_PUBLISHED,
        ),
        InventoryRow(
            "identity",
            "Data di nascita: 15 gennaio 1977",
            str(politician.birth_date),
            PUBLISHED.lower(),
            "canonical politician record",
            PUBLISHED,
            MATCHES_PUBLISHED,
        ),
        InventoryRow(
            "identity",
            "Luogo di nascita: Roma",
            str(birth_place or ""),
            PUBLISHED.lower() if birth_place == "Roma" else "missing",
            "published politician version",
            PUBLISHED if birth_place == "Roma" else MISSING,
            MATCHES_PUBLISHED if birth_place == "Roma" else CREATE_PENDING,
        ),
        InventoryRow(
            "identity",
            "Partito politico: Fratelli d’Italia",
            (
                f"career {career_fdi.identity_key} party_or_group={career_fdi.party_or_group}"
                if career_fdi is not None and career_fdi.status is ProfileContentStatus.PUBLISHED
                else f"{len(affiliations)} party affiliations"
            ),
            "published_career" if career_fdi is not None else "missing",
            "no political_parties table rows in unified demo",
            PUBLISHED if career_fdi is not None else MISSING,
            REUSE_EXISTING,
            "No PoliticalPartyAffiliation exists. The published FdI career row carries the party name. A party record is not invented.",
        ),
        InventoryRow(
            "identity",
            "Incarico attuale: Presidente del Consiglio dei ministri",
            (pdc or {}).get("mandate_type") or "",
            PUBLISHED.lower() if pdc else "missing",
            "published mandate",
            PUBLISHED if pdc else MISSING,
            MATCHES_PUBLISHED if pdc else MISSING,
        ),
        InventoryRow(
            "identity",
            "In carica dal: 22 ottobre 2022 (PDF) vs 21 ottobre 2022 (canonical)",
            (pdc or {}).get("start_date") or "",
            PUBLISHED.lower(),
            "Governo/Gazzetta appointment",
            PUBLISHED,
            MATCHES_PUBLISHED,
            "Canonical verified mandate start 2022-10-21 is preserved. PDF/curriculum 2022-10-22 is not published as a second current office.",
        ),
    ]

    bio = _latest(session, PoliticianBiography, politician.id, "primary")
    bio_sources = _sources(session, ProfileContentKind.BIOGRAPHY, bio.id) if bio else []
    report.biography = [
        InventoryRow(
            "biography",
            "CHI È narrative",
            f"biography:{bio.id}" if bio else "missing",
            bio.status.value if bio else "missing",
            _source_state(bio_sources),
            PUBLISHED if bio and bio.status is ProfileContentStatus.PUBLISHED else MISSING,
            MATCHES_PUBLISHED,
            "Published biography keeps month-precision 'dall’ottobre 2022' instead of the weaker/conflicting PDF day date.",
        )
    ]
    for source in fixture.get("biography", {}).get("sources") or []:
        url = source.get("url")
        attached = next((row for row in bio_sources if row.name == source.get("name")), None)
        complete = is_complete_source_url(url) or (
            attached is not None and is_complete_source_url(attached.url)
        )
        report.sources.append(
            InventoryRow(
                "sources",
                f"biography / {source.get('name')}",
                f"source:{attached.id}" if attached else "named only",
                bio.status.value if bio else "missing",
                "verified" if complete else "incomplete",
                PUBLISHED if complete and attached else BLOCKED,
                MATCHES_PUBLISHED if complete else BLOCKED_SOURCE,
                "Exact URL is missing in the PDF/fixture; not invented." if not complete else "",
            )
        )

    published_career = {
        row.identity_key: row
        for row in session.scalars(
            select(PoliticianCareerEntry).where(
                PoliticianCareerEntry.politician_id == politician.id,
                PoliticianCareerEntry.status == ProfileContentStatus.PUBLISHED,
            )
        )
    }
    for item in fixture.get("career_entries") or []:
        row = published_career.get(item["identity_key"])
        rejected = _latest(session, PoliticianCareerEntry, politician.id, item["identity_key"])
        sources = _sources(session, ProfileContentKind.CAREER_ENTRY, row.id) if row else []
        report.career.append(
            InventoryRow(
                "career",
                f"{item['start_date']} {item['role']}",
                f"career:{row.id}" if row else (
                    f"career:{rejected.id}:{rejected.status.value}" if rejected else "missing"
                ),
                row.status.value if row else (rejected.status.value if rejected else "missing"),
                _source_state(sources) if row else "none",
                PUBLISHED if row else PENDING if rejected else MISSING,
                MATCHES_PUBLISHED if row else NEEDS_MANUAL_REVIEW,
            )
        )
    pdc_career = _latest(session, PoliticianCareerEntry, politician.id, "presidente-consiglio-2022")
    report.career.append(
        InventoryRow(
            "career",
            "22 ottobre 2022–oggi: Presidente del Consiglio",
            (
                f"rejected career:{pdc_career.id}; public mandate {CANONICAL_PDC_START.isoformat()}"
                if pdc_career is not None
                else f"public mandate {CANONICAL_PDC_START.isoformat()}"
            ),
            "rejected+mandate" if pdc_career is not None else "mandate_only",
            "canonical Governo/Gazzetta appointment",
            PUBLISHED,
            SUPERSEDE_DUPLICATE,
            "PDF day date 2022-10-22 is not published. The verified mandate 2022-10-21 is the public current office.",
        )
    )

    for item in fixture.get("positions") or []:
        row = _latest(session, PoliticianPosition, politician.id, item["identity_key"])
        sources = _sources(session, ProfileContentKind.POSITION, row.id) if row else []
        report.positions.append(
            InventoryRow(
                "positions",
                item["topic"],
                f"position:{row.id}" if row else "missing",
                row.status.value if row else "missing",
                _source_state(sources),
                PUBLISHED if row and row.status is ProfileContentStatus.PUBLISHED else MISSING,
                MATCHES_PUBLISHED if row and row.status is ProfileContentStatus.PUBLISHED else CREATE_PENDING,
            )
        )
        for source in item.get("sources") or []:
            report.sources.append(
                InventoryRow(
                    "sources",
                    f"position / {item['identity_key']} / {source.get('name')}",
                    source.get("url") or "",
                    row.status.value if row else "missing",
                    "verified" if is_complete_source_url(source.get("url")) else "incomplete",
                    PUBLISHED if row and is_complete_source_url(source.get("url")) else BLOCKED,
                    MATCHES_PUBLISHED if is_complete_source_url(source.get("url")) else BLOCKED_SOURCE,
                )
            )

    pledges = _meloni_pledges(session, politician.id)
    published = [row for row in pledges if row.published_at is not None]
    latest = PledgeService._latest_assessments(session, [row.id for row in published])
    drafts = {
        str((row.proposed_data or {}).get("proposal_identifier") or ""): row
        for row in session.scalars(select(ProposalDraft))
    }
    for item in fixture.get("pledges") or []:
        number = int(item["number"])
        proposal_id = CEO_PROPOSAL_IDS.get(number)
        proposal = next((row for row in pledges if row.id == proposal_id), None)
        if proposal is None:
            proposal = next(
                (
                    row
                    for row in pledges
                    if row.canonical_title.casefold() == item["title"].casefold()
                    or (row.exact_statement or "").casefold()
                    == str(item.get("exact_statement") or "").casefold()
                ),
                None,
            )
        identifier = f"reference-profile:giorgia_meloni_v1:pledge:{item['identity_key']}"
        draft = drafts.get(identifier)
        assessment = latest.get(proposal.id) if proposal and proposal.published_at else None
        if number == 10:
            status, action, note = BLOCKED, BLOCKED_SOURCE, "Fact-check declaration URL; original statement URL is not stored."
        elif number == 16:
            status, action, note = BLOCKED, NEEDS_MANUAL_REVIEW, "Declaration date is explicitly unverified."
        elif proposal is not None and proposal.published_at is not None and assessment is not None:
            status, action = PUBLISHED, MATCHES_PUBLISHED
            note = (
                f"declaration {item.get('declaration_url')}; evidence {assessment.source_url}"
            )
            if proposal.canonical_title.casefold() != item["title"].casefold():
                note = (
                    f"Public title keeps the longer official statement "
                    f"{proposal.id!r}; PDF short title is not overwritten. {note}"
                )
        else:
            status, action, note = PENDING, CREATE_PENDING, ""
        report.promises.append(
            InventoryRow(
                "promises",
                f"#{number} {item['title']}",
                (
                    f"proposal:{proposal.id} verdict={assessment.verdict.value}"
                    if proposal is not None and assessment is not None
                    else (
                        f"proposal:{proposal.id}:unpublished"
                        if proposal is not None
                        else (
                            f"draft:{draft.id}:{draft.status.value}"
                            if draft is not None
                            else "missing"
                        )
                    )
                ),
                (
                    "published"
                    if proposal is not None and proposal.published_at is not None
                    else "pending"
                ),
                "declaration+assessment separated" if assessment is not None else "declaration only",
                status,
                action,
                note,
            )
        )
        report.sources.append(
            InventoryRow(
                "sources",
                f"promise #{number} declaration",
                item.get("declaration_url") or "",
                "published" if status == PUBLISHED else "pending",
                (
                    "fact_check"
                    if "pagellapolitica.it" in str(item.get("declaration_url") or "")
                    else (
                        "verified"
                        if is_complete_source_url(item.get("declaration_url"))
                        else "incomplete"
                    )
                ),
                PUBLISHED if status == PUBLISHED else BLOCKED if status == BLOCKED else PENDING,
                BLOCKED_SOURCE if number in {10, 16} else MATCHES_PUBLISHED,
            )
        )
    report.promises.append(
        InventoryRow(
            "promises",
            "declaration context (origin_label)",
            "no generic Proposal column; public UI uses introduced_at + declaration source",
            "fixture_only",
            "n/a",
            PENDING,
            NEEDS_MANUAL_REVIEW,
            "PDF context phrases are stored on the fixture only. No schema migration is added.",
        )
    )

    extras = [row.id for row in published if row.id in SHOWCASE_EXTRAS]
    if extras:
        report.promises.append(
            InventoryRow(
                "promises",
                "non-CEO extras still public",
                ",".join(str(item) for item in extras),
                "published",
                "n/a",
                PUBLISHED,
                SUPERSEDE_DUPLICATE,
                "These IDs should have been unpublished from the showcase.",
            )
        )

    for item in fixture.get("proceedings") or []:
        row = _latest(session, PoliticianProceeding, politician.id, item["identity_key"])
        sources = _sources(session, ProfileContentKind.PROCEEDING, row.id) if row else []
        has_text = bool(row and row.summary and item["title"][:20] in (row.title or ""))
        report.proceedings.append(
            InventoryRow(
                "proceedings",
                item["title"],
                f"proceeding:{row.id}" if row else "missing",
                row.status.value if row else "missing",
                _source_state(sources),
                PENDING if row and row.status is ProfileContentStatus.PENDING else (
                    PUBLISHED if row and row.status is ProfileContentStatus.PUBLISHED else MISSING
                ),
                BLOCKED_SOURCE if row else CREATE_PENDING,
                "Full PDF narrative is stored. Exact source URLs are missing, so the row stays unpublished."
                if has_text
                else "Structured record missing or incomplete.",
            )
        )
        for source in item.get("sources") or []:
            report.sources.append(
                InventoryRow(
                    "sources",
                    f"proceeding / {item['identity_key']} / {source.get('name')}",
                    source.get("url") or "",
                    row.status.value if row else "missing",
                    "incomplete",
                    BLOCKED,
                    BLOCKED_SOURCE,
                    "PDF names the outlet but does not give a verified exact URL.",
                )
            )

    for source in (
        {
            "name": "Presidenza del Consiglio dei Ministri",
            "url": "https://presidenza.governo.it/AmministrazioneTrasparente/Organizzazione/OrganiIndirizzoPolitico/GovernoMeloni/PresMeloni/PresMeloni_curriculum.pdf",
            "kind": "official",
        },
        {
            "name": "Ministero dell’Interno",
            "url": "https://dait.interno.gov.it/documenti/trasparenza/POLITICHE_20220925/CAMERA_ITALIA_20220925/candidati/CI17/CU1713/1353601/5277_1353601_giorgia_meloni_25092022_cv.pdf",
            "kind": "official",
        },
        {
            "name": "Senato della Repubblica",
            "url": "https://www.senato.it/leg/16/BGT/Schede/Attsen/00023006.htm",
            "kind": "official",
        },
        {
            "name": "Partito dei Conservatori e Riformisti Europei",
            "url": "https://ecrparty.eu/2025/01/14/election-of-the-new-presidency-of-the-european-conservatives-and-reformists-party-ecr-brussels-january-14-2025/",
            "kind": "party_politician",
        },
    ):
        host = (urlsplit(source["url"]).hostname or "")
        attached = session.scalar(
            select(PoliticianProfileSource.id).where(
                PoliticianProfileSource.url == source["url"]
            )
        )
        report.sources.append(
            InventoryRow(
                "sources",
                f"career section / {source['name']}",
                f"attached:{attached}" if attached else f"available:{host}",
                "published" if attached else "not_attached",
                "verified",
                PUBLISHED if attached else PENDING,
                MATCHES_PUBLISHED if attached else REUSE_EXISTING,
                "Official URL is in the repository. Senato page is listed in the PDF; career rows already use Interno/Presidenza sources."
                if not attached and "senato.it" in host
                else "",
            )
        )

    return report


def format_report(report: CompletenessReport) -> str:
    lines = [
        f"Meloni PDF completeness — politician {report.politician_id} {report.politician_name}",
        f"Canonical PdC start: {report.canonical_pdc_start} (PDF {report.pdf_pdc_start}; discrepancy preserved)",
        "",
    ]
    for section in (
        "identity",
        "biography",
        "career",
        "positions",
        "promises",
        "proceedings",
        "sources",
    ):
        rows: list[InventoryRow] = getattr(report, section)
        lines.append(section.upper())
        for row in rows:
            lines.append(
                f"  [{row.status}] {row.item} | {row.publication_state} | "
                f"{row.source_state} | {row.action}"
            )
            if row.notes:
                lines.append(f"           {row.notes}")
        lines.append("")
    counts = report.to_dict()["counts"]
    lines.append(
        "SUMMARY: "
        + ", ".join(f"{key}={value}" for key, value in counts.items())
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only CEO PDF completeness audit for Giorgia Meloni."
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--database-url")
    parser.add_argument("--unified-demo", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if configured_environment() is AppEnvironment.PRODUCTION:
        raise DemoSafetyError("audit_meloni_pdf_completeness refuses VERAPOLITICA_ENV=production")
    url = resolve_database_url(args)
    engine = _readonly_engine(url)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            politician = resolve_politician(session, "giorgia-meloni")
            report = audit_completeness(session, politician, fixture_path=args.fixture)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(format_report(report))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
