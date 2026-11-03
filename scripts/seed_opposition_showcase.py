"""Publish short official-URL schede for Elly Schlein and Giuseppe Conte.

Uses only complete pages already listed in the reference fixtures. Schlein
biography and career rows in the fixture point at homepages, so this script
publishes a Camera act she first-signed (A.C. 1741) as career + classified
promise. Conte uses Treccani, the Senato activity card, and the 2018 contract
page already in the fixture.

    python -m scripts.seed_opposition_showcase --author "Amedeo" --approver "Verificatore"

Four-eyes. Idempotent. Does not invent URLs.
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
from scripts.prepare_reference_profile import _load_fixture
from scripts.seed_meloni_showcase import _official_sources


AUTHOR_DEFAULT = "Sincronizzazione schede opposizione"
FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "reference_profiles"

SCHLEIN_BILL_URL = "https://www.camera.it/leg19/126?idDocumento=1741&leg=19"
SCHLEIN_BILL_TITLE = "Finanziamento della sanità pubblica"
SCHLEIN_BILL_STATEMENT = (
    "Incremento delle risorse destinate al Servizio sanitario nazionale "
    "per garantire l'accesso universale alle cure."
)
CONTE_CAREER_KEY = "pdc-conte-i"
CONTE_PLEDGE_KEY = "reddito-cittadinanza"


@dataclass
class PersonReport:
    politician_id: int | None = None
    published: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class Report:
    schlein: PersonReport = field(default_factory=PersonReport)
    conte: PersonReport = field(default_factory=PersonReport)
    errors: list[str] = field(default_factory=list)


def _published(session: Session, given: str, family: str) -> Politician | None:
    return session.scalar(
        select(Politician).where(
            Politician.normalized_name == normalize_person_name(given, family),
            Politician.current_version_id.is_not(None),
        )
    )


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


def _approve_block(
    service: RedazioneService,
    report: PersonReport,
    politician_id: int,
    kind: str,
    payload: dict,
    *,
    author: str,
    approver: str,
    label: str,
    note: str,
) -> None:
    try:
        saved = service.save_profile_block(politician_id, kind, payload, member=author)
        service.approve(kind, saved["id"], member=approver, note=note)
        report.published.append(label)
    except RedazioneError as error:
        report.errors.append(f"{label} ({error})")


def _approve_promise(
    service: RedazioneService,
    report: PersonReport,
    politician_id: int,
    payload: dict,
    *,
    author: str,
    approver: str,
    label: str,
    note: str,
) -> None:
    try:
        created = service.create_promise(politician_id, payload, member=author)
        service.approve("promise", created["draft_id"], member=approver, note=note)
        report.published.append(label)
    except RedazioneError as error:
        report.errors.append(f"{label} ({error})")


def _seed_schlein(
    service: RedazioneService,
    session_factory: sessionmaker[Session],
    *,
    author: str,
    approver: str,
) -> PersonReport:
    report = PersonReport()
    with session_factory() as session:
        politician = _published(session, "Elly", "Schlein")
        if politician is None:
            report.errors.append(
                "Elly Schlein pubblicata non trovata: importa Camera e pubblica la scheda prima"
            )
            return report
        report.politician_id = politician.id
        has_career = _has_published(session, PoliticianCareerEntry, politician.id, "ac-1741")
        has_promise = _existing_promise(session, politician.id, SCHLEIN_BILL_TITLE)
    if has_career:
        report.skipped.append("incarico A.C. 1741 (già pubblicato)")
    else:
        _approve_block(
            service,
            report,
            report.politician_id,
            "career_entry",
            {
                "identity_key": "ac-1741",
                "role": "Deputata, prima firmataria della proposta di legge A.C. 1741",
                "institution": "Camera dei deputati",
                "start_date": "2022-10-13",
                "end_date": None,
                "is_current": True,
                "start_precision": "day",
                "sources": [
                    {
                        "name": "Camera dei deputati — A.C. 1741",
                        "url": SCHLEIN_BILL_URL,
                        "area": "istituzionale",
                    }
                ],
            },
            author=author,
            approver=approver,
            label="incarico A.C. 1741",
            note="Atto ufficiale della Camera; la scheda fixture non ha URL completi per la biografia.",
        )
    if has_promise:
        report.skipped.append("promessa sanità A.C. 1741 (già pubblicata)")
    else:
        _approve_promise(
            service,
            report,
            report.politician_id,
            {
                "title": SCHLEIN_BILL_TITLE,
                "exact_statement": SCHLEIN_BILL_STATEMENT,
                "introduced_at": "2022-10-13",
                "where": "A.C. 1741, Camera dei deputati, XIX legislatura",
                "source": {
                    "name": "Camera dei deputati",
                    "url": SCHLEIN_BILL_URL,
                },
                "classification": {
                    "specificity": "medium",
                    "commitment_type": "action",
                    "holder_role": "opposition",
                    "cap_topic_code": "3",
                    "mandate_start": "2022-10-13",
                    "note": "Prima firmataria dell'atto ufficiale; nessuno stato senza stralcio.",
                },
            },
            author=author,
            approver=approver,
            label="promessa sanità A.C. 1741",
            note="Proposta ufficiale della Camera; stato ancora da valutare.",
        )
    return report


def _seed_conte(
    service: RedazioneService,
    session_factory: sessionmaker[Session],
    *,
    author: str,
    approver: str,
) -> PersonReport:
    report = PersonReport()
    fixture = _load_fixture(FIXTURES / "giuseppe_conte_v1.json")
    with session_factory() as session:
        politician = _published(session, "Giuseppe", "Conte")
        if politician is None:
            report.errors.append(
                "Giuseppe Conte pubblicato non trovato: importa Camera/Senato e pubblica la scheda prima"
            )
            return report
        report.politician_id = politician.id
        has_bio = _has_published(session, PoliticianBiography, politician.id, "primary")
        has_career = _has_published(
            session, PoliticianCareerEntry, politician.id, CONTE_CAREER_KEY
        )
        pledge = next(item for item in fixture["pledges"] if item["identity_key"] == CONTE_PLEDGE_KEY)
        has_promise = _existing_promise(session, politician.id, pledge["title"])
    if has_bio:
        report.skipped.append("chi è (già pubblicato)")
    else:
        _approve_block(
            service,
            report,
            report.politician_id,
            "biography",
            {
                "identity_key": "primary",
                "body": fixture["biography"]["body"],
                "sources": _official_sources(fixture["biography"]["sources"]),
            },
            author=author,
            approver=approver,
            label="chi è",
            note="Voce Treccani e curriculum ufficiale M5S già in archivio.",
        )
    if has_career:
        report.skipped.append("incarico Conte I (già pubblicato)")
    else:
        career = next(
            item for item in fixture["career_entries"] if item["identity_key"] == CONTE_CAREER_KEY
        )
        _approve_block(
            service,
            report,
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
            author=author,
            approver=approver,
            label="incarico Conte I",
            note="Scheda attività del Senato, XVIII legislatura.",
        )
    if has_promise:
        report.skipped.append("promessa reddito di cittadinanza (già pubblicata)")
    else:
        _approve_promise(
            service,
            report,
            report.politician_id,
            {
                "title": pledge["title"],
                "exact_statement": pledge["exact_statement"],
                "introduced_at": pledge["introduced_at"],
                "where": pledge["origin_label"],
                "source": {
                    "name": "Contratto per il governo del cambiamento",
                    "url": pledge["declaration_url"],
                },
                "classification": {
                    "specificity": pledge["specificity"],
                    "commitment_type": pledge["commitment_type"],
                    "holder_role": "government_coalition",
                    "cap_topic_code": pledge["cap_topic_code"],
                    "mandate_start": pledge.get("suggested_mandate_start") or "2018-06-01",
                    "mandate_end": pledge.get("suggested_mandate_end") or "2019-09-04",
                    "note": "Dichiarazione del contratto 2018; nessuno stato senza stralcio ufficiale.",
                },
            },
            author=author,
            approver=approver,
            label="promessa reddito di cittadinanza",
            note="Pagina del contratto già in archivio; stato ancora da valutare.",
        )
    return report


def seed(
    service: RedazioneService,
    session_factory: sessionmaker[Session],
    *,
    author: str,
    approver: str,
) -> Report:
    if author.strip() == approver.strip():
        raise ValueError("chi approva deve essere diverso da chi scrive")
    report = Report()
    report.schlein = _seed_schlein(service, session_factory, author=author, approver=approver)
    report.conte = _seed_conte(service, session_factory, author=author, approver=approver)
    report.errors.extend(report.schlein.errors)
    report.errors.extend(report.conte.errors)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--author", default=AUTHOR_DEFAULT)
    parser.add_argument("--approver", required=True)
    parser.add_argument("--database-url")
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
        )
    finally:
        engine.dispose()
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 2 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
