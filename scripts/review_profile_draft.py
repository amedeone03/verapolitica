import argparse
import json
import sys
from collections.abc import Sequence

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.services import (
    PublishService,
    PublishServiceError,
    ReviewService,
    ReviewServiceError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Approve or reject one reviewable ProfileDraft."
    )
    parser.add_argument("--draft-id", required=True, type=int)
    decision = parser.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--note")
    return parser


def _error_payload(exc: Exception) -> str:
    return json.dumps(
        {"error": str(exc), "error_type": type(exc).__name__},
        indent=2,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.draft_id <= 0:
        print(
            _error_payload(ValueError("--draft-id must be positive")),
            file=sys.stderr,
        )
        return 1

    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    try:
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)
        if args.approve:
            result = PublishService(session_factory).approve(
                args.draft_id,
                reviewer=args.reviewer,
                note=args.note,
            )
        else:
            result = ReviewService(session_factory).reject(
                args.draft_id,
                reviewer=args.reviewer,
                note=args.note,
            )
        print(result.model_dump_json(indent=2))
        return 0
    except (ReviewServiceError, PublishServiceError) as exc:
        print(_error_payload(exc), file=sys.stderr)
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
