"""Attach pending DAIT mayor identity cases to existing people.

DAIT current-mayor rows usually lack a birth date, so automatic bootstrap
cannot create those identities. Same rule as Governo: unique normalized
name already in the archive → link; homonyms stay pending for the
redazione identity queue.

    python -m scripts.attach_territorial_identities --dry-run
    python -m scripts.attach_territorial_identities --apply

Does not invent source URLs. Does not publish: run
``publish_territorial_profiles --region Lazio`` afterwards.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from backend.app.core.config import get_settings
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from scripts.attach_governo_identities import apply_attachments, plan_attachments


SOURCE_KEY = "dait-current-mayors"


def finish(session_factory, *, reviewer: str, create_new: bool = False, dry_run: bool = False):
    plans = plan_attachments(session_factory, source_key=SOURCE_KEY)
    return apply_attachments(
        session_factory,
        plans,
        reviewer=reviewer,
        create_new=create_new,
        dry_run=dry_run,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--also-create-new",
        action="store_true",
        help="also create identities for unique DAIT names with no archive match",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    try:
        prepare_runtime_schema(engine, settings)
        report = finish(
            create_session_factory(engine),
            reviewer=settings.admin_reviewer_identity,
            create_new=args.also_create_new,
            dry_run=args.dry_run,
        )
    finally:
        engine.dispose()
    print(json.dumps(
        {
            "dry_run": report.dry_run,
            "linked": report.linked,
            "created": report.created,
            "left_pending": report.left_pending,
            "errors": report.errors,
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 2 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
