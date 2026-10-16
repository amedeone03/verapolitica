"""CLI for the curated Ask VeraPolitica gold evaluation.

Calls AskVeraPoliticaService directly. Does not start an HTTP server and does
not require Ollama.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.app.evaluation.ask_metrics import report_to_dict
from backend.app.evaluation.ask_runner import (
    _safe_fake_completer,
    render_ask_report,
    run_ask_evaluation,
)
from backend.app.evaluation.dataset import EvaluationDatasetError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate Ask VeraPolitica against the curated gold set. "
            "Figures describe this gold set only, not universal model accuracy."
        )
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Gold dataset directory (default: evaluation/ask_verapolitica/v1)",
    )
    parser.add_argument("--category", help="Run only this gold category")
    parser.add_argument("--case-id", help="Run only this gold case id")
    parser.add_argument(
        "--ai",
        choices=("off", "fake"),
        default="off",
        help="off = deterministic path; fake = FakeTextCompleter (no Ollama)",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Optional path to write the report JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    completer = _safe_fake_completer() if args.ai == "fake" else None
    mode = "ai-fake" if args.ai == "fake" else "deterministic"
    try:
        report = run_ask_evaluation(
            dataset_root=args.dataset,
            category=args.category,
            case_id=args.case_id,
            completer=completer,
            mode=mode,
        )
    except EvaluationDatasetError as exc:
        print(f"Ask evaluation failed: {exc}", file=sys.stderr)
        return 1
    print(render_ask_report(report))
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report_to_dict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
