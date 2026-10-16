"""Read-only source-completeness audit for a reference politician profile.

  python -m scripts.audit_reference_profile giorgia-meloni

Never approves, never publishes, never invents URLs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url

from backend.app.core.config import AppEnvironment, configured_environment, get_settings
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.services.reference_profile_audit import (
    DEFAULT_FIXTURE,
    audit_from_factory,
    format_audit_text,
)
from scripts.prepare_demo import DemoSafetyError
from scripts.unified_demo import UnifiedDemoPaths


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _readonly_engine(database_url: str):
    engine = create_db_engine(database_url)
    parsed = make_url(database_url)
    if parsed.drivername.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _query_only(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
            dbapi_connection.execute("PRAGMA query_only = ON")

    return engine


def resolve_database_url(args: argparse.Namespace) -> str:
    if args.database_url:
        return args.database_url
    if args.unified_demo or not args.database_url:
        paths = UnifiedDemoPaths.for_workspace(REPOSITORY_ROOT)
        if paths.database.exists():
            return f"sqlite:///{paths.database}"
    return get_settings().database_url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only source-completeness audit for reference profile content."
    )
    parser.add_argument("slug", help="politician slug, e.g. giorgia-meloni")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--unified-demo", action="store_true")
    parser.add_argument("--database-url")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if configured_environment() is AppEnvironment.PRODUCTION:
        raise DemoSafetyError("audit_reference_profile refuses VERAPOLITICA_ENV=production")
    url = resolve_database_url(args)
    engine = _readonly_engine(url)
    factory = create_session_factory(engine)
    try:
        audit = audit_from_factory(
            factory, args.slug, fixture_path=args.fixture
        )
        if args.json:
            print(json.dumps(audit.to_dict(), indent=2, default=str))
        else:
            print(format_audit_text(audit))
        return 0
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
