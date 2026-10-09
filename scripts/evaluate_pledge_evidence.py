"""Evaluate pledge-evidence retrieval and judges on the gold set. Never publishes."""

from __future__ import annotations

import argparse
import json
import sys

from backend.app.core.config import get_settings
from backend.app.scoring.pledge_evidence_eval import readiness_gate, run_gold_evaluation


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline gold evaluation for official pledge evidence. Never publishes."
    )
    parser.add_argument("--use-llm", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    report = run_gold_evaluation(
        llm_model=(settings.llm_model or "qwen3:8b") if args.use_llm else None,
        ollama_base_url=settings.ollama_base_url,
    )
    payload = report.as_dict()
    payload["readiness"] = readiness_gate(
        report, schedule_cron=settings.schedule_pledge_evidence_cron
    )
    llm = report.llm
    if llm:
        n = len(llm)
        closed = sum(1 for item in llm if item.closed_verdict)
        payload["llm_summary"] = {
            "schema_pass_rate": round(
                sum(1 for item in llm if item.raw.get("skipped") or item.compatible) / n, 4
            ),
            "evidence_validity_rate": round(sum(1 for item in llm if item.excerpt_valid) / n, 4),
            "fever_accuracy": round(sum(1 for item in llm if item.correct_label) / n, 4),
            "closed_verdict_overreach_rate": round(closed / n, 4),
            "false_positive_rate": round(
                sum(
                    1
                    for item in llm
                    if item.predicted_label.value != "not_enough_info" and not item.correct_label
                )
                / n,
                4,
            ),
            "false_negative_rate": round(
                sum(
                    1
                    for item in llm
                    if item.expected_label.value != "not_enough_info"
                    and item.predicted_label.value == "not_enough_info"
                )
                / n,
                4,
            ),
            "mean_elapsed_ms": int(sum(item.elapsed_ms for item in llm) / n),
        }
    payload["comparison"] = {
        "deterministic_retrieval": {
            "precision": report.precision,
            "recall": report.recall,
            "abstention": report.retrieval_abstention_rate,
            "evidence_validity": None,
            "unsafe_closed_verdicts": 0,
        },
        "conservative_judge": {
            "precision": report.conservative_label_accuracy,
            "recall": None,
            "abstention": report.conservative_abstention_rate,
            "evidence_validity": report.conservative_excerpt_validity,
            "unsafe_closed_verdicts": report.conservative_closed_verdicts,
        },
        "qwen3": payload.get("llm_summary") or "not_run",
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
