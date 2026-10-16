"""Attach a missing source URL to a pending profile-content item.

Never auto-publishes. Refuses production. Unified-demo/test only.

  python -m scripts.attach_profile_source proceeding 1 --source-id 20 --url https://example.it/x --dry-run
  python -m scripts.attach_profile_source proceeding 1 --source-id 20 --url https://example.it/x --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.app.core.config import AppEnvironment, configured_environment
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models.politician_profile import ProfileContentKind
from backend.app.services.politician_profile_service import (
    PoliticianProfileConflictError,
    PoliticianProfileNotFoundError,
    PoliticianProfileService,
    PoliticianProfileValidationError,
)
from scripts.audit_reference_profile import resolve_database_url
from scripts.prepare_demo import DemoSafetyError
from scripts.unified_demo import UnifiedDemoPaths, assert_settings_are_unified


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REVIEWER = "reference-profile-editor"


def attach_profile_source(
    kind: str,
    content_id: int,
    source_id: int,
    url: str,
    *,
    dry_run: bool = True,
    allow_non_unified: bool = False,
    database_url: str | None = None,
    session_factory=None,
    reviewer: str = REVIEWER,
) -> dict:
    if configured_environment() is AppEnvironment.PRODUCTION:
        raise DemoSafetyError("attach_profile_source refuses VERAPOLITICA_ENV=production")
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
        service = PoliticianProfileService(session_factory)
        parsed_kind = ProfileContentKind(kind)
        before = service.get_admin(parsed_kind, content_id)
        report = {
            "dry_run": dry_run,
            "kind": parsed_kind.value,
            "content_id": content_id,
            "source_id": source_id,
            "url": url,
            "status": before.status.value,
            "action": "would_attach" if dry_run else "attached",
            "auto_published": False,
        }
        if dry_run:
            return report
        detail = service.attach_source_url(
            parsed_kind, content_id, source_id, url, reviewer=reviewer
        )
        report["status"] = detail.status.value
        report["source_completeness"] = detail.source_completeness.value
        report["sources_incomplete"] = detail.sources_incomplete
        return report
    finally:
        if engine is not None:
            engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Attach a source URL to pending profile content. Never auto-publishes."
    )
    parser.add_argument("kind", choices=[item.value for item in ProfileContentKind])
    parser.add_argument("content_id", type=int)
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument("--url", required=True)
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
        report = attach_profile_source(
            args.kind,
            args.content_id,
            args.source_id,
            args.url,
            dry_run=dry_run,
            database_url=args.database_url,
        )
    except (
        DemoSafetyError,
        PoliticianProfileValidationError,
        PoliticianProfileConflictError,
        PoliticianProfileNotFoundError,
        LookupError,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(
            f"{'DRY-RUN' if dry_run else 'APPLY'}  {report['kind']} #{report['content_id']} "
            f"source {report['source_id']} -> {report['action']} status={report['status']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
