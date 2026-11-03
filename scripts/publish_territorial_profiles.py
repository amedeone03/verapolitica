"""Publish pending territorial-office profile drafts for a region.

DAIT mayors become public only after a PoliticianVersion is published.
This publishes existing pending drafts for people who already have a
territorial mandate in the named region (default: Lazio). It does not
create identities and does not invent source URLs.

    python -m scripts.publish_territorial_profiles --dry-run
    python -m scripts.publish_territorial_profiles --apply --region Lazio
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    Municipality,
    Politician,
    ProfileDraft,
    ProfileDraftStatus,
    Region,
    TerritorialOfficeMandate,
)
from backend.app.services import PublishService, PublishServiceError
from backend.app.services.review_service import ReviewServiceError


@dataclass
class Report:
    dry_run: bool
    region: str
    published: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _holders(session: Session, region_name: str) -> list[tuple[Politician, TerritorialOfficeMandate, str]]:
    region = session.scalar(select(Region).where(Region.canonical_name == region_name))
    if region is None:
        return []
    mayor_rows = session.execute(
        select(Politician, TerritorialOfficeMandate, Municipality)
        .join(TerritorialOfficeMandate, TerritorialOfficeMandate.politician_id == Politician.id)
        .join(Municipality, Municipality.id == TerritorialOfficeMandate.municipality_id)
        .where(
            Municipality.region_id == region.id,
            TerritorialOfficeMandate.end_date.is_(None),
        )
    ).all()
    president_rows = session.execute(
        select(Politician, TerritorialOfficeMandate)
        .join(TerritorialOfficeMandate, TerritorialOfficeMandate.politician_id == Politician.id)
        .where(
            TerritorialOfficeMandate.region_id == region.id,
            TerritorialOfficeMandate.end_date.is_(None),
        )
    ).all()
    result = []
    for politician, mandate, municipality in mayor_rows:
        result.append((politician, mandate, f"Sindaco di {municipality.canonical_name}"))
    for politician, mandate in president_rows:
        result.append((politician, mandate, f"Presidente della Regione {region.canonical_name}"))
    return result


def publish(
    session_factory: sessionmaker[Session],
    *,
    region: str,
    reviewer: str,
    dry_run: bool,
) -> Report:
    report = Report(dry_run=dry_run, region=region)
    with session_factory() as session:
        holders = _holders(session, region)
        if not holders and session.scalar(select(Region.id).where(Region.canonical_name == region)) is None:
            report.errors.append(f"regione {region} assente: importa ISTAT prima")
            return report
        seen: set[int] = set()
        pending_by_politician: dict[int, ProfileDraft] = {}
        for draft in session.scalars(
            select(ProfileDraft).where(
                ProfileDraft.status.in_(
                    (ProfileDraftStatus.PENDING, ProfileDraftStatus.IN_REVIEW)
                )
            )
        ):
            pending_by_politician[draft.politician_id] = draft
        for politician, _mandate, label in holders:
            if politician.id in seen:
                continue
            seen.add(politician.id)
            name = f"{politician.canonical_given_name} {politician.canonical_family_name}"
            if politician.current_version_id is not None:
                report.skipped.append(f"{name} ({label}, già pubblicato)")
                continue
            draft = pending_by_politician.get(politician.id)
            if draft is None:
                report.skipped.append(f"{name} ({label}, nessuna bozza da pubblicare)")
                continue
            if dry_run:
                report.published.append(f"{name} ({label}, bozza {draft.id})")
                continue
            try:
                PublishService(session_factory).approve(
                    draft.id,
                    reviewer=reviewer,
                    note=f"Incarico territoriale ufficiale: {label}.",
                )
                report.published.append(f"{name} ({label})")
            except (PublishServiceError, ReviewServiceError) as error:
                report.errors.append(f"{name} ({error})")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--region", default="Lazio")
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
        report = publish(
            create_session_factory(engine),
            region=args.region,
            reviewer=settings.admin_reviewer_identity,
            dry_run=args.dry_run,
        )
    finally:
        engine.dispose()
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 2 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
