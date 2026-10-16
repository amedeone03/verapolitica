"""Approve review-ready reference profile content in the unified demo.

Uses the existing PoliticianProfileService approval path. Never approves
blocked items, proceedings, the conflicting PdC career row, or pledge drafts.
Never creates assessments.

  python -m scripts.approve_reference_profile giorgia-meloni --dry-run
  python -m scripts.approve_reference_profile giorgia-meloni --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import AppEnvironment, configured_environment
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import PledgeAssessment
from backend.app.models.politician_profile import (
    ProfileContentKind,
    ProfileContentStatus,
)
from backend.app.schemas.politician_profile import SourceCompleteness
from backend.app.services.politician_profile_service import PoliticianProfileService
from backend.app.services.reference_profile_audit import (
    DEFAULT_FIXTURE,
    ProfileItemAudit,
    audit_from_factory,
    resolve_politician,
)
from scripts.audit_reference_profile import resolve_database_url
from scripts.prepare_demo import DemoSafetyError
from scripts.prepare_reference_profile import PROTECTED_ASSESSMENT_TITLE_PREFIX
from scripts.unified_demo import UnifiedDemoPaths, assert_settings_are_unified


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REVIEWER = "reference-profile-editor"
REVIEW_NOTE = "Approved as review-ready showcase content for the unified demo."
APPROVABLE_KINDS = frozenset(
    {
        ProfileContentKind.BIOGRAPHY,
        ProfileContentKind.CAREER_ENTRY,
        ProfileContentKind.POSITION,
    }
)


def _row(item: ProfileItemAudit, action: str, reason: str) -> dict[str, Any]:
    return {
        "action": action,
        "reason": reason,
        "kind": item.content_type,
        "id": item.id,
        "identity_key": item.identity_key,
        "title": item.item,
        "source_completeness": item.source_completeness,
        "publication_status": item.publication_status,
        "blocker": item.blocker,
    }


def _classify_item(item: ProfileItemAudit) -> tuple[str, str]:
    if item.id is None:
        return "skipped", "missing content id"
    if item.publication_status == ProfileContentStatus.PUBLISHED.value:
        return "already_published", "already published"
    if item.publication_status != ProfileContentStatus.PENDING.value:
        return "skipped", f"status is {item.publication_status}"
    kind = ProfileContentKind(item.content_type)
    if kind is ProfileContentKind.PROCEEDING:
        return "blocked", "proceedings are not part of this approval pass"
    if kind not in APPROVABLE_KINDS:
        return "blocked", f"{item.content_type} is not approvable in this pass"
    if item.source_completeness != SourceCompleteness.READY_FOR_EDITORIAL_REVIEW.value:
        return "blocked", item.blocker or item.source_completeness
    return "approve", "READY_FOR_EDITORIAL_REVIEW"


def approve_reference_profile(
    slug: str,
    *,
    session_factory: sessionmaker[Session] | None = None,
    fixture_path: Path = DEFAULT_FIXTURE,
    dry_run: bool = True,
    allow_non_unified: bool = False,
    database_url: str | None = None,
    reviewer: str = REVIEWER,
    note: str = REVIEW_NOTE,
) -> dict[str, Any]:
    if configured_environment() is AppEnvironment.PRODUCTION:
        raise DemoSafetyError("approve_reference_profile refuses VERAPOLITICA_ENV=production")
    engine = None
    if session_factory is None:

        class _Args:
            unified_demo = True

        _Args.database_url = database_url
        url = resolve_database_url(_Args())
        if not allow_non_unified:
            paths = UnifiedDemoPaths.for_workspace(REPOSITORY_ROOT)
            assert_settings_are_unified(url, paths.raw_storage, REPOSITORY_ROOT)
        engine = create_db_engine(url)
        session_factory = create_session_factory(engine)

    report: dict[str, Any] = {
        "slug": slug,
        "dry_run": dry_run,
        "politician_id": None,
        "politician_name": None,
        "approved": [],
        "already_published": [],
        "blocked": [],
        "skipped": [],
        "pledges_untouched": True,
        "assessments_untouched": [],
        "notes": [
            "Approves only READY_FOR_EDITORIAL_REVIEW biography, career and position rows.",
            "Does not approve proceedings, the PdC date-conflict career row, or pledge drafts.",
            "Does not create assessments.",
        ],
    }
    try:
        audit = audit_from_factory(session_factory, slug, fixture_path=fixture_path)
        report["politician_id"] = audit.politician_id
        report["politician_name"] = audit.politician_name
        service = PoliticianProfileService(session_factory)
        for item in audit.profile_items:
            bucket, reason = _classify_item(item)
            row = _row(item, bucket if bucket != "approve" else "would_approve", reason)
            if bucket == "approve":
                if dry_run:
                    report["approved"].append(row)
                    continue
                kind = ProfileContentKind(item.content_type)
                detail = service.approve(
                    kind, item.id, reviewer=reviewer, note=note
                )
                row["action"] = "approved"
                row["publication_status"] = detail.status.value
                report["approved"].append(row)
            else:
                report[bucket].append(row)

        with session_factory() as session:
            politician = resolve_politician(session, slug)
            assessments = list(
                session.scalars(
                    select_assessments_for(session, politician.id)
                )
            )
            report["assessments_untouched"] = [
                {
                    "id": item.id,
                    "proposal_id": item.proposal_id,
                    "verdict": item.verdict.value,
                    "protected": item.proposal.canonical_title.startswith(
                        PROTECTED_ASSESSMENT_TITLE_PREFIX
                    )
                    if item.proposal is not None
                    else False,
                }
                for item in assessments
            ]
            report["counts"] = _counts(session, politician.id)
        return report
    finally:
        if engine is not None:
            engine.dispose()


def select_assessments_for(session: Session, politician_id: int):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from backend.app.models import Proposal, ProposalActor, ProposalActorRole, ProposalType

    return (
        select(PledgeAssessment)
        .options(selectinload(PledgeAssessment.proposal))
        .join(Proposal, PledgeAssessment.proposal_id == Proposal.id)
        .join(ProposalActor, ProposalActor.proposal_id == Proposal.id)
        .where(
            ProposalActor.politician_id == politician_id,
            ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
            Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
        )
        .distinct()
    )


def _counts(session: Session, politician_id: int) -> dict[str, dict[str, int]]:
    from sqlalchemy import func, select

    from backend.app.models.politician_profile import (
        PoliticianBiography,
        PoliticianCareerEntry,
        PoliticianPosition,
        PoliticianProceeding,
    )

    result: dict[str, dict[str, int]] = {}
    for name, model in (
        ("biography", PoliticianBiography),
        ("career", PoliticianCareerEntry),
        ("positions", PoliticianPosition),
        ("proceedings", PoliticianProceeding),
    ):
        pending = session.scalar(
            select(func.count())
            .select_from(model)
            .where(
                model.politician_id == politician_id,
                model.status == ProfileContentStatus.PENDING,
            )
        )
        published = session.scalar(
            select(func.count())
            .select_from(model)
            .where(
                model.politician_id == politician_id,
                model.status == ProfileContentStatus.PUBLISHED,
            )
        )
        result[name] = {"pending": int(pending or 0), "published": int(published or 0)}
    return result


def format_approval_text(report: dict[str, Any]) -> str:
    mode = "DRY-RUN" if report["dry_run"] else "APPLY"
    lines = [
        f"{mode}  {report['politician_name']} (id {report['politician_id']})",
        "",
        f"approved: {len(report['approved'])}",
        f"already_published: {len(report['already_published'])}",
        f"blocked: {len(report['blocked'])}",
        f"skipped: {len(report['skipped'])}",
        "",
    ]
    for bucket in ("approved", "already_published", "blocked", "skipped"):
        if not report[bucket]:
            continue
        lines.append(bucket.upper())
        for item in report[bucket]:
            lines.append(
                f"  {item['kind']}  {item['identity_key']}  #{item['id']}  {item['reason']}"
            )
        lines.append("")
    counts = report.get("counts") or {}
    if counts:
        lines.append("COUNTS")
        for name, values in counts.items():
            lines.append(
                f"  {name}: {values['published']} published / {values['pending']} pending"
            )
    lines.append("")
    lines.append(f"pledges_untouched: {report['pledges_untouched']}")
    for item in report["assessments_untouched"]:
        lines.append(
            f"assessment {item['id']} proposal {item['proposal_id']} "
            f"{item['verdict']} protected={item['protected']}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Approve review-ready reference profile content in the unified demo."
    )
    parser.add_argument("slug", help="politician slug, e.g. giorgia-meloni")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--unified-demo", action="store_true")
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
        report = approve_reference_profile(
            args.slug,
            fixture_path=args.fixture,
            dry_run=dry_run,
            allow_non_unified=False,
            database_url=args.database_url,
        )
    except (DemoSafetyError, LookupError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_approval_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
