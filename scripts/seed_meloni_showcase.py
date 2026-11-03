"""Publish a short, sourced Meloni scheda and one classified promise.

Uses only official URLs already listed in the Giorgia Meloni reference fixture.
Goes through RedazioneService (author ≠ approver). Does not invent a fulfilment
verdict: a verdict needs a verbatim official excerpt.

Safe to run in production. Idempotent: already published blocks are skipped.

    python -m scripts.seed_meloni_showcase --author "Amedeo" --approver "Verificatore"
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import Politician, Proposal, ProposalActor, ProposalActorRole, ProposalType
from backend.app.models.politician_profile import (
    PoliticianBiography,
    PoliticianCareerEntry,
    ProfileContentStatus,
)
from backend.app.services.matching_service import normalize_person_name
from backend.app.services.redazione.service import RedazioneError, RedazioneService
from scripts.prepare_reference_profile import DEFAULT_FIXTURE, _load_fixture


AUTHOR_DEFAULT = "Sincronizzazione scheda Meloni"
CAREER_KEY = "ministra-gioventu-2008"
PLEDGE_KEY = "rdc"


@dataclass
class Report:
    politician_id: int | None = None
    published: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _published_meloni(session: Session) -> Politician | None:
    key = normalize_person_name("Giorgia", "Meloni")
    return session.scalar(
        select(Politician).where(
            Politician.normalized_name == key,
            Politician.current_version_id.is_not(None),
        )
    )


def _official_sources(items: list[dict]) -> list[dict]:
    sources = []
    for item in items:
        url = item.get("url")
        if not url or not str(url).startswith("https://"):
            continue
        sources.append(
            {
                "name": item["name"],
                "url": url,
                "area": "istituzionale" if item.get("kind") in {"official", "institutional"} else item.get("kind") or "istituzionale",
            }
        )
    return sources


def _has_published(session: Session, model, politician_id: int, identity_key: str) -> bool:
    return session.scalar(
        select(model.id).where(
            model.politician_id == politician_id,
            model.identity_key == identity_key,
            model.status == ProfileContentStatus.PUBLISHED,
        )
    ) is not None


def _existing_promise(session: Session, politician_id: int, title: str) -> bool:
    return session.scalar(
        select(Proposal.id)
        .join(ProposalActor, ProposalActor.proposal_id == Proposal.id)
        .where(
            ProposalActor.politician_id == politician_id,
            ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
            Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
            Proposal.canonical_title == title,
            Proposal.published_at.is_not(None),
        )
    ) is not None


def seed(
    service: RedazioneService,
    session_factory: sessionmaker[Session],
    *,
    author: str,
    approver: str,
    fixture_path: Path = DEFAULT_FIXTURE,
) -> Report:
    if author.strip() == approver.strip():
        raise ValueError("chi approva deve essere diverso da chi scrive")
    fixture = _load_fixture(fixture_path)
    report = Report()
    with session_factory() as session:
        politician = _published_meloni(session)
        if politician is None:
            report.errors.append(
                "Giorgia Meloni pubblicata non trovata: importa Camera/Senato/Governo e pubblica la scheda prima"
            )
            return report
        report.politician_id = politician.id
        has_bio = _has_published(session, PoliticianBiography, politician.id, "primary")
        has_career = _has_published(session, PoliticianCareerEntry, politician.id, CAREER_KEY)
        pledge = next(item for item in fixture["pledges"] if item["identity_key"] == PLEDGE_KEY)
        has_promise = _existing_promise(session, politician.id, pledge["title"])

    if has_bio:
        report.skipped.append("chi è (già pubblicato)")
    else:
        try:
            saved = service.save_profile_block(
                report.politician_id,
                "biography",
                {
                    "identity_key": "primary",
                    "body": fixture["biography"]["body"],
                    "sources": _official_sources(fixture["biography"]["sources"]),
                },
                member=author,
            )
            service.approve(
                "biography",
                saved["id"],
                member=approver,
                note="Curriculum ufficiale della Presidenza del Consiglio.",
            )
            report.published.append("chi è")
        except RedazioneError as error:
            report.errors.append(f"chi è ({error})")

    if has_career:
        report.skipped.append("incarico 2008–2011 (già pubblicato)")
    else:
        career = next(item for item in fixture["career_entries"] if item["identity_key"] == CAREER_KEY)
        try:
            saved = service.save_profile_block(
                report.politician_id,
                "career_entry",
                {
                    "identity_key": career["identity_key"],
                    "role": career["role"],
                    "institution": career["institution"],
                    "start_date": career["start_date"],
                    "end_date": career["end_date"],
                    "is_current": False,
                    "start_precision": career.get("start_precision") or "day",
                    "sources": _official_sources(career["sources"]),
                },
                member=author,
            )
            service.approve(
                "career_entry",
                saved["id"],
                member=approver,
                note="Incarico del curriculum ufficiale della Presidenza.",
            )
            report.published.append("incarico 2008–2011")
        except RedazioneError as error:
            report.errors.append(f"incarico ({error})")

    if has_promise:
        report.skipped.append("promessa reddito di cittadinanza (già pubblicata)")
    else:
        try:
            created = service.create_promise(
                report.politician_id,
                {
                    "title": pledge["title"],
                    "exact_statement": pledge["exact_statement"],
                    "introduced_at": pledge["introduced_at"],
                    "where": pledge["origin_label"],
                    "source": {
                        "name": "Senato della Repubblica",
                        "url": pledge["declaration_url"],
                    },
                    "classification": {
                        "specificity": pledge["specificity"],
                        "commitment_type": pledge["commitment_type"],
                        "holder_role": "government_coalition",
                        "cap_topic_code": pledge["cap_topic_code"],
                        "mandate_start": "2022-10-21",
                        "note": "Dichiarazioni programmatiche; nessuno stato di adempimento è assegnato senza stralcio ufficiale.",
                    },
                },
                member=author,
            )
            service.approve(
                "promise",
                created["draft_id"],
                member=approver,
                note="Promessa delle dichiarazioni programmatiche; stato ancora da valutare.",
            )
            report.published.append("promessa reddito di cittadinanza")
        except RedazioneError as error:
            report.errors.append(f"promessa ({error})")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--author", default=AUTHOR_DEFAULT)
    parser.add_argument("--approver", required=True)
    parser.add_argument("--database-url")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args(argv)
    settings = get_settings()
    runtime = (
        settings.model_copy(update={"database_url": args.database_url})
        if args.database_url
        else settings
    )
    engine = create_db_engine(runtime.database_url)
    try:
        prepare_runtime_schema(engine, runtime)
        Base.metadata.create_all(engine)
        factory = create_session_factory(engine)
        report = seed(
            RedazioneService(factory),
            factory,
            author=args.author,
            approver=args.approver,
            fixture_path=args.fixture,
        )
    finally:
        engine.dispose()
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 2 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
