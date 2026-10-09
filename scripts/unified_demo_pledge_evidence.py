"""Safe unified-demo wrapper for official pledge evidence.

Writes only to data/unified_demo/. Refuses data/ceo_demo/ and data/demo/.
Never approves drafts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.app.core.config import Settings
from scripts.prepare_demo import DemoSafetyError
from scripts.run_pledge_evidence import parse_args as _base_parse
from scripts.run_pledge_evidence import run as run_pledge_evidence
from scripts.unified_demo import (
    UnifiedDemoPaths,
    assert_settings_are_unified,
    validate_unified_paths,
)


WORKSPACE = Path(__file__).resolve().parents[1]
ARCHIVED_LAW_86 = (
    WORKSPACE / "data" / "fixtures" / "pledge_evidence" / "legge_86_2024_autonomia.html"
)
TEST_EVIDENCE = (
    {
        "proposal_id": 106,
        "source_url": "https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg",
        "source_name": "Gazzetta Ufficiale — Legge 26 giugno 2024, n. 86",
        "source_key": "gazzetta-ufficiale",
        "published_at": "2024-06-26",
        "file": ARCHIVED_LAW_86,
    },
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run official pledge evidence against data/unified_demo only."
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--proposal-id", type=int)
    target.add_argument("--all-unrated", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--conservative-judge", action="store_true")
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--ingest-archived-test-set", action="store_true")
    return parser.parse_args(argv)


def _settings(paths: UnifiedDemoPaths) -> Settings:
    validate_unified_paths(paths)
    settings = Settings().model_copy(update=paths.settings_kwargs())
    assert_settings_are_unified(settings.database_url, settings.raw_storage_path, paths.workspace_root)
    return settings


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = UnifiedDemoPaths.for_workspace(WORKSPACE)
    try:
        settings = _settings(paths)
    except DemoSafetyError as exc:
        print(f"unified demo isolation failed: {exc}", file=sys.stderr)
        return 2
    summaries = []
    if args.ingest_archived_test_set:
        for item in TEST_EVIDENCE:
            ingest_args = _base_parse(
                [
                    "--ingest-file",
                    str(item["file"]),
                    "--ingest-url",
                    item["source_url"],
                    "--source-name",
                    item["source_name"],
                    "--source-key",
                    item["source_key"],
                    "--published-at",
                    item["published_at"],
                    "--proposal-id",
                    str(item["proposal_id"]),
                    *(["--dry-run"] if args.dry_run else []),
                    *(["--conservative-judge"] if args.conservative_judge else []),
                    *(["--use-llm"] if args.use_llm else []),
                ]
            )
            summaries.append(run_pledge_evidence(ingest_args, settings=settings))
    else:
        cli = []
        if args.proposal_id:
            cli.extend(["--proposal-id", str(args.proposal_id)])
        if args.all_unrated:
            cli.append("--all-unrated")
        if args.dry_run:
            cli.append("--dry-run")
        if args.conservative_judge:
            cli.append("--conservative-judge")
        if args.use_llm:
            cli.append("--use-llm")
        if not cli:
            print("pass --proposal-id, --all-unrated, or --ingest-archived-test-set", file=sys.stderr)
            return 1
        summaries.append(run_pledge_evidence(_base_parse(cli), settings=settings))
    print(json.dumps(summaries if len(summaries) > 1 else summaries[0], indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
