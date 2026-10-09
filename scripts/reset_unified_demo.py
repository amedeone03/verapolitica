"""Reset operator AI artifacts in the unified demo only.

Preserves Senate / Government / territory / pledge / portrait baseline data.
Never points at data/ceo_demo or data/demo.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.core.config import AppEnvironment, Settings, configured_environment, get_settings
from scripts.prepare_demo import DemoSafetyError
from scripts.prepare_real_demo import PROGRAMME_SOURCE, PROGRAMME_URL
from scripts.reset_ceo_ai_demo import reset_ceo_ai_demo
from scripts.unified_demo import (
    UnifiedDemoPaths,
    assert_settings_are_unified,
    validate_unified_paths,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def reset_unified_demo(
    *,
    workspace_root: Path = REPOSITORY_ROOT,
    settings: Settings | None = None,
    source_url: str | None = None,
    dry_run: bool = False,
) -> dict:
    if configured_environment() is AppEnvironment.PRODUCTION:
        raise DemoSafetyError("reset_unified_demo refuses VERAPOLITICA_ENV=production")
    paths = UnifiedDemoPaths.for_workspace(workspace_root)
    validate_unified_paths(paths)
    runtime = settings or get_settings()
    runtime = runtime.model_copy(update=paths.settings_kwargs())
    assert_settings_are_unified(runtime.database_url, runtime.raw_storage_path, workspace_root)
    if not paths.database.is_file():
        raise DemoSafetyError("unified demo database does not exist; run prepare_unified_demo first")
    summary = reset_ceo_ai_demo(
        settings=runtime,
        source_url=source_url,
        dry_run=dry_run,
        demo_upload_path=paths.uploads,
        protected_source_keys=(PROGRAMME_SOURCE[0],),
        protected_source_urls=(PROGRAMME_URL,),
    )
    summary["environment"] = "unified_demo"
    summary["preserved"] = (
        "Senate/Camera/Governo/ISTAT/DAIT collectors, published SPARQL and "
        "governo.it profiles, programme pledges and classifications, portraits, "
        "and territories. Only operator official-document AI uploads, runs, "
        "and unpublished AI drafts are removed."
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset AI operator artifacts in the unified demo")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source-url")
    args = parser.parse_args(argv)
    summary = reset_unified_demo(source_url=args.source_url, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
