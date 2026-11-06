"""Fill the live demo surfaces without resetting the database.

Production-safe orchestrator. It does not drop data, does not enable the
scheduler, and does not invent newspaper URLs. Each step uses the ordinary
redazione four-eyes path or stored official raw files.

Prerequisites already on the VPS: ISTAT territories, Camera/Senato/Governo
ingest, published identities, Governo attach if ministers were pending.

    python -m scripts.prepare_live_demo --author "Amedeo" --approver "Verificatore"

Individual steps remain available if one of them needs a retry.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.services.redazione.service import RedazioneService
from backend.app.storage import LocalRawStorage
from scripts.attach_governo_identities import finish as finish_cabinet
from scripts.attach_territorial_identities import finish as finish_territorial
from scripts.publish_territorial_profiles import publish as publish_offices
from scripts.reprocess_parliamentary_groups import reprocess as reprocess_groups
from scripts.seed_government_parties import seed as seed_parties
from scripts.seed_meloni_showcase import seed as seed_meloni
from scripts.seed_official_feed import seed as seed_feed
from scripts.seed_official_notizia import seed as seed_notizia
from scripts.seed_opposition_showcase import seed as seed_opposition
from scripts.seed_party_affiliations import seed as seed_affiliations
from scripts.seed_rdc_verdict import seed as seed_verdict
from scripts import sync_symbols


@dataclass
class Report:
    parties: dict = field(default_factory=dict)
    groups: dict = field(default_factory=dict)
    cabinet: dict = field(default_factory=dict)
    territorial: dict = field(default_factory=dict)
    meloni: dict = field(default_factory=dict)
    opposition: dict = field(default_factory=dict)
    affiliations: dict = field(default_factory=dict)
    verdict: dict = field(default_factory=dict)
    feed: dict = field(default_factory=dict)
    notizia: dict = field(default_factory=dict)
    offices: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def prepare(
    session_factory,
    *,
    author: str,
    approver: str,
    party_approver: str,
    raw_storage: Path,
    camera_legislature: int | str = 19,
    get=sync_symbols.quick_get,
) -> Report:
    if author.strip() == approver.strip():
        raise ValueError("chi approva le schede deve essere diverso da chi scrive")
    report = Report()
    service = RedazioneService(session_factory)

    try:
        parties = seed_parties(service, get, approver=party_approver)
        report.parties = asdict(parties)
    except Exception as error:  # one step must not hide the others
        report.errors.append(f"partiti: {error}")

    try:
        groups = reprocess_groups(
            session_factory,
            LocalRawStorage(raw_storage),
            camera_legislature=camera_legislature,
            dry_run=False,
        )
        report.groups = asdict(groups)
    except Exception as error:
        report.errors.append(f"gruppi: {error}")

    try:
        cabinet = finish_cabinet(session_factory, reviewer=approver)
        report.cabinet = asdict(cabinet)
        if cabinet.errors:
            report.errors.extend(f"governo: {item}" for item in cabinet.errors)
    except Exception as error:
        report.errors.append(f"governo: {error}")

    try:
        territorial = finish_territorial(session_factory, reviewer=approver)
        report.territorial = asdict(territorial)
        if territorial.errors:
            report.errors.extend(f"sindaci: {item}" for item in territorial.errors)
    except Exception as error:
        report.errors.append(f"sindaci: {error}")

    try:
        meloni = seed_meloni(service, session_factory, author=author, approver=approver)
        report.meloni = asdict(meloni)
        if meloni.errors:
            report.errors.extend(f"meloni: {item}" for item in meloni.errors)
    except Exception as error:
        report.errors.append(f"meloni: {error}")

    try:
        opposition = seed_opposition(service, session_factory, author=author, approver=approver)
        report.opposition = asdict(opposition)
        if opposition.errors:
            report.errors.extend(f"opposizione: {item}" for item in opposition.errors)
    except Exception as error:
        report.errors.append(f"opposizione: {error}")

    try:
        affiliations = seed_affiliations(session_factory)
        report.affiliations = asdict(affiliations)
        if affiliations.errors:
            report.errors.extend(f"partiti-scheda: {item}" for item in affiliations.errors)
    except Exception as error:
        report.errors.append(f"partiti-scheda: {error}")

    try:
        verdict = seed_verdict(service, session_factory, author=author, approver=approver)
        report.verdict = asdict(verdict)
        if verdict.errors:
            report.errors.extend(f"stato-rdc: {item}" for item in verdict.errors)
    except Exception as error:
        report.errors.append(f"stato-rdc: {error}")

    try:
        feed = seed_feed(service, session_factory, author=author, approver=approver)
        report.feed = asdict(feed)
        if feed.errors:
            report.errors.extend(f"feed: {item}" for item in feed.errors)
    except Exception as error:
        report.errors.append(f"feed: {error}")

    try:
        notizia = seed_notizia(service, session_factory, author=author, approver=approver)
        report.notizia = asdict(notizia)
        if notizia.errors:
            report.errors.extend(f"notizia: {item}" for item in notizia.errors)
    except Exception as error:
        report.errors.append(f"notizia: {error}")

    try:
        offices = publish_offices(
            session_factory, region="Lazio", reviewer=approver, dry_run=False
        )
        report.offices = asdict(offices)
        if offices.errors:
            report.errors.extend(f"territorio: {item}" for item in offices.errors)
    except Exception as error:
        report.errors.append(f"territorio: {error}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--author", default="Amedeo")
    parser.add_argument("--approver", required=True)
    parser.add_argument("--party-approver", default="Direzione VeraPolitica")
    parser.add_argument("--database-url")
    args = parser.parse_args(argv)
    if args.author.strip() == args.approver.strip():
        raise SystemExit("chi approva deve essere diverso da chi scrive")
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
        report = prepare(
            create_session_factory(engine),
            author=args.author,
            approver=args.approver,
            party_approver=args.party_approver,
            raw_storage=settings.raw_storage_path,
            camera_legislature=settings.camera_legislature,
        )
    finally:
        engine.dispose()
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 2 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
