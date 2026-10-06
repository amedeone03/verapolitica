from __future__ import annotations

import argparse
import json
import sys

from backend.app.core.config import get_settings
from backend.app.db.schema import require_persistent_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.jobs import (
    JOB_CATALOG,
    IngestionJobConflictError,
    IngestionJobService,
    IngestionJobValidationError,
)
from backend.app.models import IngestionJobStatus, IngestionJobTrigger


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run or inspect official ingestion jobs"
    )
    parser.add_argument(
        "job",
        choices=(*sorted(JOB_CATALOG), "list"),
        help="job name, or list to print recent runs",
    )
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    try:
        require_persistent_schema(engine, settings)
        service = IngestionJobService(create_session_factory(engine), settings)
        if args.job == "list":
            history = service.list(limit=max(1, min(args.limit, 100)))
            print(json.dumps(history.model_dump(mode="json"), indent=2))
            return 0
        try:
            result = service.execute(
                args.job, trigger_type=IngestionJobTrigger.CLI
            )
        except IngestionJobConflictError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except IngestionJobValidationError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(result.model_dump(mode="json"), indent=2))
        if result.status == IngestionJobStatus.FAILED:
            return 1
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
