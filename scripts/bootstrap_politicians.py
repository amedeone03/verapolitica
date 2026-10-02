import argparse
import json
import sys
from collections.abc import Sequence

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.services import (
    BootstrapApplyError,
    BootstrapConflictError,
    CandidateRebuildError,
    PoliticianBootstrapService,
    RawDocumentCandidateRebuilder,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explicitly bootstrap politician identities from a parsed RawDocument."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="classify and report without writing",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="create all safe new identities in one transaction",
    )
    parser.add_argument(
        "--raw-document-id",
        type=int,
        help="rebuild candidates from this successfully parsed RawDocument",
    )
    parser.add_argument(
        "--source-key",
        default="senato-repubblica",
        help="source authority (default: senato-repubblica)",
    )
    return parser


def _error_payload(exc: Exception) -> str:
    return json.dumps(
        {"error": str(exc), "error_type": type(exc).__name__},
        indent=2,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.raw_document_id is not None and args.raw_document_id <= 0:
        print(
            _error_payload(ValueError("--raw-document-id must be positive")),
            file=sys.stderr,
        )
        return 1

    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    try:
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)
        rebuilder = RawDocumentCandidateRebuilder(session_factory)
        service = PoliticianBootstrapService(session_factory)
        rebuilt = rebuilder.rebuild(
            raw_document_id=args.raw_document_id,
            source_key=args.source_key,
        )
        plan = service.plan(rebuilt, dry_run=args.dry_run)

        if args.dry_run:
            print(plan.report.model_dump_json(indent=2))
            return 0

        if not plan.report.safe_to_apply:
            print(plan.report.model_dump_json(indent=2))
            return 2

        report = service.apply(plan)
        print(report.model_dump_json(indent=2))
        return 0
    except (
        CandidateRebuildError,
        BootstrapConflictError,
        BootstrapApplyError,
    ) as exc:
        print(_error_payload(exc), file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
