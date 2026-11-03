"""Attach pending Governo identity cases to existing people, then publish.

governo.it usually omits birth dates, so automatic bootstrap cannot create
those identities. This is the explicit operator path:

- exactly one archived politician with the same normalized name → link
- no archived politician, unique name in this Governo batch → create only
  if ``--also-create-new`` is set (avoids a second person when Camera used
  a slightly different official name)
- two archived people, or two Governo pages sharing a name → leave pending

Dry-run first. Does not invent source URLs. Does not guess from a partial name.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    IdentityResolutionCase,
    IdentityResolutionStatus,
    Politician,
    Source,
)
from backend.app.schemas import CandidateProfile, DraftCreatedResult, MatchedResult, NoChangesResult
from backend.app.services import (
    DraftService,
    DraftServiceError,
    IdentityResolutionService,
    IdentityResolutionServiceError,
    MatchingService,
    PublishService,
    RawDocumentCandidateRebuilder,
    normalize_person_name,
)

SOURCE_KEY = "governo-italiano"
LINK_NOTE = (
    "Nome ufficiale governo.it coincide con un'unica persona già in archivio "
    "(stesso nome normalizzato)."
)
CREATE_NOTE = (
    "Titolare ufficiale governo.it senza omonimo in archivio; identità distinta "
    "dall'URL della pagina istituzionale."
)
PUBLISH_NOTE = "Incarico ufficiale Governo"


class Action(StrEnum):
    LINK_EXISTING = "link_existing"
    CREATE_NEW = "create_new"
    LEAVE_PENDING = "leave_pending"


@dataclass(frozen=True)
class CasePlan:
    case_id: int
    display_name: str
    normalized_name: str
    action: Action
    reason: str
    politician_id: int | None = None
    existing_politician_ids: tuple[int, ...] = ()


@dataclass
class AttachmentReport:
    dry_run: bool
    linked: list[dict] = field(default_factory=list)
    created: list[dict] = field(default_factory=list)
    left_pending: list[dict] = field(default_factory=list)
    published: int = 0
    unchanged: int = 0
    skipped: int = 0
    errors: list[dict] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def _candidate(case: IdentityResolutionCase) -> CandidateProfile:
    return CandidateProfile.model_validate(case.candidate_snapshot)


def plan_attachments(
    session_factory: sessionmaker[Session],
    *,
    source_key: str = SOURCE_KEY,
) -> tuple[CasePlan, ...]:
    with session_factory() as session:
        cases = list(
            session.scalars(
                select(IdentityResolutionCase)
                .join(Source)
                .where(
                    Source.key == source_key,
                    IdentityResolutionCase.status == IdentityResolutionStatus.PENDING,
                )
                .order_by(IdentityResolutionCase.id)
            )
        )
        names: list[str] = []
        snapshots: list[tuple[IdentityResolutionCase, CandidateProfile, str]] = []
        for case in cases:
            candidate = _candidate(case)
            normalized = normalize_person_name(
                candidate.identity.given_name,
                candidate.identity.family_name,
            )
            names.append(normalized)
            snapshots.append((case, candidate, normalized))
        name_counts = Counter(names)
        ids_by_name: dict[str, tuple[int, ...]] = {}
        unique_names = {name for name in names if name}
        if unique_names:
            rows = session.execute(
                select(Politician.normalized_name, Politician.id).where(
                    Politician.normalized_name.in_(unique_names)
                )
            )
            grouped: dict[str, list[int]] = defaultdict(list)
            for normalized, politician_id in rows:
                grouped[normalized].append(politician_id)
            ids_by_name = {
                name: tuple(sorted(ids)) for name, ids in grouped.items()
            }

    plans: list[CasePlan] = []
    for case, candidate, normalized in snapshots:
        display = (
            candidate.identity.display_name
            or f"{candidate.identity.given_name} {candidate.identity.family_name}"
        ).strip()
        existing = ids_by_name.get(normalized, ())
        if not normalized:
            plans.append(
                CasePlan(
                    case_id=case.id,
                    display_name=display,
                    normalized_name=normalized,
                    action=Action.LEAVE_PENDING,
                    reason="canonical name has no normalizable characters",
                )
            )
            continue
        if name_counts[normalized] > 1:
            plans.append(
                CasePlan(
                    case_id=case.id,
                    display_name=display,
                    normalized_name=normalized,
                    action=Action.LEAVE_PENDING,
                    reason="two Governo pages share this normalized name"
                        if source_key == SOURCE_KEY
                        else f"two {source_key} pages share this normalized name",
                    existing_politician_ids=existing,
                )
            )
            continue
        if len(existing) > 1:
            plans.append(
                CasePlan(
                    case_id=case.id,
                    display_name=display,
                    normalized_name=normalized,
                    action=Action.LEAVE_PENDING,
                    reason="more than one archived politician has this normalized name",
                    existing_politician_ids=existing,
                )
            )
            continue
        if len(existing) == 1:
            plans.append(
                CasePlan(
                    case_id=case.id,
                    display_name=display,
                    normalized_name=normalized,
                    action=Action.LINK_EXISTING,
                    reason="unique archived person with the same normalized name",
                    politician_id=existing[0],
                    existing_politician_ids=existing,
                )
            )
            continue
        plans.append(
            CasePlan(
                case_id=case.id,
                display_name=display,
                normalized_name=normalized,
                action=Action.CREATE_NEW,
                reason=(
                    "no archived person with this name; create only with "
                    "--also-create-new"
                ),
            )
        )
    return tuple(plans)


def finish(
    session_factory: sessionmaker[Session],
    *,
    reviewer: str,
    create_new: bool = False,
    dry_run: bool = False,
    skip_publish: bool = False,
    source_key: str = SOURCE_KEY,
) -> AttachmentReport:
    """Link unique pending cases, then publish matched Governo profiles."""

    plans = plan_attachments(session_factory, source_key=source_key)
    report = apply_attachments(
        session_factory,
        plans,
        reviewer=reviewer,
        create_new=create_new,
        dry_run=dry_run,
    )
    if (
        source_key == SOURCE_KEY
        and not dry_run
        and not skip_publish
        and not report.errors
    ):
        publish_governo_profiles(session_factory, reviewer=reviewer, report=report)
    return report


def apply_attachments(
    session_factory: sessionmaker[Session],
    plans: Sequence[CasePlan],
    *,
    reviewer: str,
    create_new: bool,
    dry_run: bool,
) -> AttachmentReport:
    report = AttachmentReport(dry_run=dry_run)
    resolutions = IdentityResolutionService(session_factory)
    for item in plans:
        row = {
            "case_id": item.case_id,
            "display_name": item.display_name,
            "politician_id": item.politician_id,
            "reason": item.reason,
        }
        if item.action is Action.LEAVE_PENDING:
            report.left_pending.append(row)
            continue
        if item.action is Action.CREATE_NEW and not create_new:
            report.left_pending.append(
                {**row, "reason": "create-new skipped; pass --also-create-new"}
            )
            continue
        if dry_run:
            if item.action is Action.LINK_EXISTING:
                report.linked.append(row)
            else:
                report.created.append(row)
            continue
        try:
            if item.action is Action.LINK_EXISTING:
                if item.politician_id is None:
                    raise IdentityResolutionServiceError(
                        f"case {item.case_id} marked link_existing without politician_id"
                    )
                resolutions.resolve_to_existing(
                    item.case_id,
                    item.politician_id,
                    reviewer_identity=reviewer,
                    note=LINK_NOTE,
                )
                report.linked.append(row)
            else:
                created = resolutions.resolve_as_new(
                    item.case_id,
                    reviewer_identity=reviewer,
                    note=CREATE_NOTE,
                )
                row["politician_id"] = created.resolved_politician_id
                report.created.append(row)
        except IdentityResolutionServiceError as exc:
            report.errors.append(
                {
                    "case_id": item.case_id,
                    "display_name": item.display_name,
                    "reason": type(exc).__name__,
                    "detail": str(exc)[:200],
                }
            )
    return report


def publish_governo_profiles(
    session_factory: sessionmaker[Session],
    *,
    reviewer: str,
    report: AttachmentReport,
) -> AttachmentReport:
    rebuilt = RawDocumentCandidateRebuilder(session_factory).rebuild(
        source_key=SOURCE_KEY
    )
    drafts = DraftService(session_factory)
    publish = PublishService(session_factory)
    for item in rebuilt.candidates:
        name = item.profile.identity.display_name
        try:
            with session_factory() as session:
                match = MatchingService(session).match(item.profile)
            if not isinstance(match, MatchedResult):
                report.skipped += 1
                continue
            created = drafts.create(item.profile, match)
            if isinstance(created, NoChangesResult):
                report.unchanged += 1
                continue
            if not isinstance(created, DraftCreatedResult):
                report.skipped += 1
                continue
            publish.approve(
                created.draft_id,
                reviewer=reviewer,
                note=PUBLISH_NOTE,
            )
            report.published += 1
        except (DraftServiceError, Exception) as exc:
            if len(report.errors) < 12:
                report.errors.append(
                    {
                        "display_name": name,
                        "reason": type(exc).__name__,
                        "detail": str(exc)[:200],
                    }
                )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Link pending Governo identity cases, then publish matched profiles."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="classify pending cases without writing",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="link unique existing people and publish matched Governo profiles",
    )
    parser.add_argument(
        "--also-create-new",
        action="store_true",
        help="also create identities for unique Governo names with no archive match",
    )
    parser.add_argument(
        "--skip-publish",
        action="store_true",
        help="resolve cases only; do not create or approve profile drafts",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    try:
        prepare_runtime_schema(engine, settings)
        factory = create_session_factory(engine)
        report = finish(
            factory,
            reviewer=settings.admin_reviewer_identity,
            create_new=args.also_create_new,
            dry_run=args.dry_run,
            skip_publish=args.skip_publish or args.dry_run,
        )
        print(report.to_json())
        if report.errors:
            return 2
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
