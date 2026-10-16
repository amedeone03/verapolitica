"""Read-only showcase readiness report for a reference politician profile.

  python -m scripts.report_reference_profile giorgia-meloni

Counts come from the live database. Nothing is approved or published.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dataclasses import asdict

from backend.app.core.config import AppEnvironment, configured_environment
from backend.app.services.reference_profile_audit import (
    DEFAULT_FIXTURE,
    audit_from_factory,
    format_report_text,
)
from backend.app.db.session import create_session_factory
from scripts.audit_reference_profile import _readonly_engine, resolve_database_url
from scripts.prepare_demo import DemoSafetyError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only showcase readiness report for reference profile content."
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
        raise DemoSafetyError("report_reference_profile refuses VERAPOLITICA_ENV=production")
    url = resolve_database_url(args)
    engine = _readonly_engine(url)
    factory = create_session_factory(engine)
    try:
        audit = audit_from_factory(
            factory, args.slug, fixture_path=args.fixture
        )
        if args.json:
            print(json.dumps(asdict(audit.readiness), indent=2, default=str))
        else:
            print(format_report_text(audit))
        return 0
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
