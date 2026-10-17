"""Attach verified proceeding sources and publish only supported Meloni records.

Idempotent editorial operator. Never invents URLs. Never publishes a proceeding
whose stored claims are not covered by exact attached sources. Second run
creates no duplicate sources and does not re-approve published rows.

  python -m scripts.resolve_meloni_proceedings --dry-run
  python -m scripts.resolve_meloni_proceedings --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import AppEnvironment, configured_environment
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models.politician_profile import (
    PoliticianProceeding,
    PoliticianProfileSource,
    ProfileContentKind,
    ProfileContentStatus,
    ProfileSourceKind,
)
from backend.app.services.politician_profile_service import PoliticianProfileService
from backend.app.services.reference_profile_audit import (
    is_complete_source_url,
    resolve_politician,
)
from scripts.audit_reference_profile import resolve_database_url
from scripts.prepare_demo import DemoSafetyError
from scripts.unified_demo import UnifiedDemoPaths, assert_settings_are_unified


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REVIEWER = "reference-profile-editor"
APPROVE_NOTE = (
    "Exact source URLs verified against the stored claims; published through "
    "the generic PoliticianProceeding approval workflow."
)

ATTACH_AND_PUBLISH = "ATTACH_AND_PUBLISH"
REUSE_EXISTING = "REUSE_EXISTING"
NARROWED = "NARROWED"
ALREADY_PUBLISHED = "ALREADY_PUBLISHED"


def _strip_tracking(url: str) -> str:
    parsed = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


@dataclass(frozen=True)
class SourceSpec:
    name: str
    url: str
    kind: ProfileSourceKind
    title: str
    supports: str
    excerpt: str | None = None


@dataclass(frozen=True)
class ProceedingPlan:
    identity_key: str
    action: str
    sources: tuple[SourceSpec, ...]
    summary: str | None = None
    outcome_summary: str | None = None
    wording_notes: tuple[str, ...] = ()


# Verified exact URLs. Do not add a URL that was not fetched and checked.
PLANS: tuple[ProceedingPlan, ...] = (
    ProceedingPlan(
        identity_key="caso-almasri-2025",
        action=ATTACH_AND_PUBLISH,
        wording_notes=(
            "outcome_summary drops the unsupported 'insufficienti gli elementi' "
            "reason; ANSA 4 August 2025 confirms only the archiving of Meloni's position.",
        ),
        outcome_summary=(
            "Nell’agosto 2025 il Tribunale dei ministri ha disposto l’archiviazione "
            "della posizione di Giorgia Meloni."
        ),
        sources=(
            SourceSpec(
                name="ANSA",
                url=(
                    "https://www.ansa.it/sito/notizie/politica/2025/01/28/"
                    "meloni-ho-ricevuto-un-avviso-di-garanzia-da-lo-voi-per-almasri_"
                    "49373c04-8411-41a6-b20d-e1662403728e.html"
                ),
                kind=ProfileSourceKind.NEWS,
                title="Meloni annuncia: indagata su Almasri per favoreggiamento e peculato",
                supports=(
                    "January 2025 announcement; favoreggiamento and peculato; "
                    "Nordio, Piantedosi, Mantovano; Almasri CPI/repatriation"
                ),
            ),
            SourceSpec(
                name="ANSA",
                url=(
                    "https://www.ansa.it/sito/notizie/politica/2025/08/04/"
                    "meloni-tribunale-dei-ministri-archivia-mia-posizione-su-almasri_"
                    "03f758bc-c290-434f-8e3e-fe8eb0b1dad5.html"
                ),
                kind=ProfileSourceKind.NEWS,
                title="Tribunale dei ministri archivia la posizione di Meloni su Almasri",
                supports="August 2025 archive of Meloni's position; other ministers remain involved",
            ),
            SourceSpec(
                name="Camera dei deputati",
                url="https://comunicazione.camera.it/archivio-prima-pagina/19-53004",
                kind=ProfileSourceKind.OFFICIAL,
                title="Camera: negata l’autorizzazione a procedere per Nordio, Piantedosi e Mantovano",
                supports="Parliamentary handling of Nordio, Piantedosi and Mantovano",
            ),
        ),
    ),
    ProceedingPlan(
        identity_key="naufragio-cutro-2023",
        action=ATTACH_AND_PUBLISH,
        sources=(
            SourceSpec(
                name="RaiNews",
                url=(
                    "https://www.rainews.it/articoli/2024/02/"
                    "un-anno-fa-il-naufragio-di-cutro-94-morti-di-cui-35-minori-oggi-la-commemorazione-"
                    "63da637f-3a1b-4742-abea-c7e3142c915b.html"
                ),
                kind=ProfileSourceKind.NEWS,
                title="Un anno fa il naufragio di Cutro, 94 morti di cui 35 minori",
                supports="26 February 2023, Steccato di Cutro, 94 victims; opposition/family criticism",
            ),
            SourceSpec(
                name="ANSA",
                url=(
                    "https://www.ansa.it/sito/notizie/speciali/editoriali/2024/02/22/"
                    "cutro-due-anni-fa-la-strage-di-migranti_"
                    "6af1423c-1de4-44f3-8705-587f293a2faf.html"
                ),
                kind=ProfileSourceKind.NEWS,
                title="Cutro, due anni fa la strage di migranti",
                supports="Night of 25–26 February 2023 at Steccato di Cutro; 94 victims",
            ),
            SourceSpec(
                name="RaiNews",
                url=(
                    "https://www.rainews.it/articoli/2024/07/"
                    "strage-a-cutro-chiusa-inchiesta-della-procura-indagati-gdf-guardia-costiera-"
                    "d82184a1-a336-45a2-8bcb-22d70ca684db.html"
                ),
                kind=ProfileSourceKind.NEWS,
                title="Inchiesta Cutro: indagati tra Guardia di Finanza e Guardia Costiera",
                supports="Investigations concern rescue personnel, not a personal criminal case against Meloni",
            ),
            SourceSpec(
                name="RaiNews",
                url=(
                    "https://www.rainews.it/maratona/2023/03/"
                    "migranti-consiglio-dei-ministri-a-cutro-allesame-la-bozza-del-nuovo-decreto-"
                    "fd290e3d-75a6-4706-8c53-f46a7b9b0a54.html"
                ),
                kind=ProfileSourceKind.NEWS,
                title="Consiglio dei ministri a Cutro: Meloni respinge la tesi della volontà di non soccorrere",
                supports="Meloni denied institutional will to look the other way / not rescue",
            ),
        ),
    ),
    ProceedingPlan(
        identity_key="accordo-italia-albania-2023",
        action=ATTACH_AND_PUBLISH,
        sources=(
            SourceSpec(
                name="Governo italiano",
                url=(
                    "https://www.governo.it/it/articolo/"
                    "il-presidente-meloni-incontra-il-primo-ministro-della-repubblica-d-albania/24178"
                ),
                kind=ProfileSourceKind.OFFICIAL,
                title="6 novembre 2023: Meloni e Rama firmano il protocollo sui flussi migratori",
                supports="November 2023 signing by Meloni and Edi Rama",
            ),
            SourceSpec(
                name="Governo italiano",
                url=(
                    "https://www.governo.it/en/articolo/"
                    "president-meloni-s-press-statement-prime-minister-albania/24195"
                ),
                kind=ProfileSourceKind.OFFICIAL,
                title="Meloni: Italy–Albania facilities to prevent illegal migration",
                supports="Albanian facilities under Italian jurisdiction; government presents project as anti-irregular-migration tool",
            ),
            SourceSpec(
                name="Corte di giustizia dell'Unione europea",
                url="https://curia.europa.eu/jcms/upload/docs/application/pdf/2025-08/cp250103en.pdf",
                kind=ProfileSourceKind.INSTITUTIONAL,
                title="CURIA press release 103/25 — Alace and Canpelli, 1 August 2025",
                supports="Legal controversy: Albania detention centre and EU safe-country judicial review",
            ),
        ),
    ),
    ProceedingPlan(
        identity_key="gioventu-nazionale-2024",
        action=ATTACH_AND_PUBLISH,
        sources=(
            SourceSpec(
                name="Fanpage – Testata autrice dell’inchiesta",
                url=(
                    "https://www.fanpage.it/politica/"
                    "saluti-romani-inni-al-duce-e-sieg-heil-dentro-gioventu-nazionale-"
                    "il-movimento-giovanile-di-fratelli-ditalia/"
                ),
                kind=ProfileSourceKind.NEWS,
                title="Saluti romani, inni al Duce e Sieg Heil: dentro Gioventù Nazionale",
                supports="June 2024 undercover investigation; fascist salutes and Nazi references in GN",
            ),
            SourceSpec(
                name="Fanpage – Testata autrice dell’inchiesta",
                url=(
                    "https://www.fanpage.it/politica/"
                    "antisemitismo-e-razzismo-cosi-parlano-i-dirigenti-di-gn-che-fanno-carriera-con-i-big-di-fdi/"
                ),
                kind=ProfileSourceKind.NEWS,
                title="Antisemitismo e razzismo: la seconda puntata su Gioventù Nazionale",
                supports="Antisemitic and racist statements documented in GN environments",
            ),
            SourceSpec(
                name="Giorgia Meloni — lettera ai dirigenti di Fratelli d’Italia",
                url="https://www.ansa.it/documents/1719933754592_letterameloni.pdf",
                kind=ProfileSourceKind.PARTY_POLITICIAN,
                title="Lettera di Meloni: non c’è spazio per posizioni razziste o antisemite",
                supports="Meloni condemned racist and antisemitic positions; no automatic personal responsibility",
            ),
            SourceSpec(
                name="Corriere della Sera",
                url=(
                    "https://www.corriere.it/politica/24_giugno_28/"
                    "bufera-fdi-meloni-razzismo-e-antisemistismo-incompatibili-con-noi-"
                    "dc0109e4-8f2f-452f-b93c-811b79a20xlk.shtml"
                ),
                kind=ProfileSourceKind.NEWS,
                title="Meloni: infiltrarsi nelle riunioni dei partiti è un metodo da regime",
                supports="Meloni criticized the undercover journalistic method while condemning the expressions",
            ),
        ),
    ),
)


@dataclass
class ResolveReport:
    dry_run: bool
    politician_id: int
    actions: list[dict[str, Any]] = field(default_factory=list)
    created_sources: int = 0
    reused_sources: int = 0
    published: list[str] = field(default_factory=list)
    already_published: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    wording_changes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pending_or_published(
    session: Session, politician_id: int, identity_key: str
) -> PoliticianProceeding | None:
    published = session.scalar(
        select(PoliticianProceeding).where(
            PoliticianProceeding.politician_id == politician_id,
            PoliticianProceeding.identity_key == identity_key,
            PoliticianProceeding.status == ProfileContentStatus.PUBLISHED,
        )
    )
    if published is not None:
        return published
    return session.scalar(
        select(PoliticianProceeding)
        .where(
            PoliticianProceeding.politician_id == politician_id,
            PoliticianProceeding.identity_key == identity_key,
            PoliticianProceeding.status == ProfileContentStatus.PENDING,
        )
        .order_by(PoliticianProceeding.id.desc())
    )


def _sources(session: Session, content_id: int) -> list[PoliticianProfileSource]:
    return list(
        session.scalars(
            select(PoliticianProfileSource)
            .where(
                PoliticianProfileSource.content_kind == ProfileContentKind.PROCEEDING,
                PoliticianProfileSource.content_id == content_id,
            )
            .order_by(PoliticianProfileSource.sort_index, PoliticianProfileSource.id)
        )
    )


def _ensure_source(
    session: Session,
    proceeding: PoliticianProceeding,
    spec: SourceSpec,
) -> str:
    url = _strip_tracking(spec.url)
    if not is_complete_source_url(url):
        raise ValueError(f"incomplete source URL: {url}")
    existing = _sources(session, proceeding.id)
    for row in existing:
        if row.url == url:
            if row.incomplete:
                row.incomplete = False
            if not row.title:
                row.title = spec.title
            return REUSE_EXISTING
    named_empty = next(
        (
            row
            for row in existing
            if row.name == spec.name and not is_complete_source_url(row.url)
        ),
        None,
    )
    if named_empty is not None:
        named_empty.url = url
        named_empty.incomplete = False
        named_empty.title = spec.title
        named_empty.kind = spec.kind
        if spec.excerpt:
            named_empty.excerpt = spec.excerpt
        return "ATTACHED"
    next_index = (max((row.sort_index for row in existing), default=-1) + 1)
    session.add(
        PoliticianProfileSource(
            content_kind=ProfileContentKind.PROCEEDING,
            content_id=proceeding.id,
            sort_index=next_index,
            title=spec.title,
            name=spec.name,
            url=url,
            kind=spec.kind,
            excerpt=spec.excerpt,
            incomplete=False,
        )
    )
    return "CREATED"


def _apply_wording(proceeding: PoliticianProceeding, plan: ProceedingPlan) -> list[str]:
    changed: list[str] = []
    if plan.summary and proceeding.summary != plan.summary:
        proceeding.summary = plan.summary
        changed.append("summary")
    if plan.outcome_summary and proceeding.outcome_summary != plan.outcome_summary:
        proceeding.outcome_summary = plan.outcome_summary
        changed.append("outcome_summary")
    return changed


def resolve_meloni_proceedings(
    *,
    dry_run: bool = True,
    allow_non_unified: bool = False,
    database_url: str | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> dict[str, Any]:
    if configured_environment() is AppEnvironment.PRODUCTION:
        raise DemoSafetyError("resolve_meloni_proceedings refuses VERAPOLITICA_ENV=production")
    engine = None
    if session_factory is None:

        class _Args:
            unified_demo = True

        _Args.database_url = database_url
        resolved = resolve_database_url(_Args())
        if not allow_non_unified:
            paths = UnifiedDemoPaths.for_workspace(REPOSITORY_ROOT)
            assert_settings_are_unified(resolved, paths.raw_storage, REPOSITORY_ROOT)
        engine = create_db_engine(resolved)
        session_factory = create_session_factory(engine)
    try:
        with session_factory() as session:
            politician = resolve_politician(session, "giorgia-meloni")
            report = ResolveReport(dry_run=dry_run, politician_id=politician.id)
            service = PoliticianProfileService(session_factory)
            for plan in PLANS:
                row = _pending_or_published(session, politician.id, plan.identity_key)
                if row is None:
                    report.pending.append(plan.identity_key)
                    report.actions.append(
                        {
                            "identity_key": plan.identity_key,
                            "action": "MISSING",
                            "status": None,
                        }
                    )
                    continue
                if row.status is ProfileContentStatus.PUBLISHED:
                    report.already_published.append(plan.identity_key)
                    report.actions.append(
                        {
                            "identity_key": plan.identity_key,
                            "content_id": row.id,
                            "action": ALREADY_PUBLISHED,
                            "status": row.status.value,
                        }
                    )
                    continue
                source_actions = []
                if not dry_run:
                    for spec in plan.sources:
                        source_actions.append(_ensure_source(session, row, spec))
                    wording = _apply_wording(row, plan)
                    session.flush()
                    for note in plan.wording_notes:
                        if wording:
                            report.wording_changes.append(f"{plan.identity_key}: {note}")
                    created = source_actions.count("CREATED")
                    attached = source_actions.count("ATTACHED")
                    reused = source_actions.count(REUSE_EXISTING)
                    report.created_sources += created
                    report.reused_sources += reused + attached
                    session.commit()
                    stored = _sources(session, row.id)
                    if any(not is_complete_source_url(item.url) for item in stored):
                        raise RuntimeError(
                            f"{plan.identity_key} still has incomplete sources"
                        )
                    service.approve(
                        ProfileContentKind.PROCEEDING,
                        row.id,
                        reviewer=REVIEWER,
                        note=APPROVE_NOTE,
                    )
                    report.published.append(plan.identity_key)
                    report.actions.append(
                        {
                            "identity_key": plan.identity_key,
                            "content_id": row.id,
                            "action": ATTACH_AND_PUBLISH,
                            "status": "published",
                            "sources": [
                                {"name": spec.name, "url": _strip_tracking(spec.url)}
                                for spec in plan.sources
                            ],
                            "wording": wording,
                        }
                    )
                else:
                    report.actions.append(
                        {
                            "identity_key": plan.identity_key,
                            "content_id": row.id,
                            "action": "would_attach_and_publish",
                            "status": row.status.value,
                            "sources": [spec.url for spec in plan.sources],
                            "wording_notes": list(plan.wording_notes),
                        }
                    )
            return report.to_dict()
    finally:
        if engine is not None:
            engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Attach verified Meloni proceeding sources and publish supported records."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--database-url")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.apply and args.dry_run:
        print("choose either --dry-run or --apply", file=sys.stderr)
        return 2
    dry_run = not args.apply
    try:
        report = resolve_meloni_proceedings(
            dry_run=dry_run, database_url=args.database_url
        )
    except (DemoSafetyError, LookupError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            f"{'DRY-RUN' if dry_run else 'APPLY'}  published={report['published']} "
            f"already={report['already_published']} created_sources={report['created_sources']} "
            f"reused_sources={report['reused_sources']}"
        )
        for item in report["actions"]:
            print(f"  {item['identity_key']}: {item['action']}")
        for note in report["wording_changes"]:
            print(f"  wording: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
