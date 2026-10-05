import json
from pathlib import Path

from backend.app.schemas.ai_evaluation import (
    EvaluationComparison,
    EvaluationReport,
)


COMPARISON_METRICS = (
    "precision",
    "recall",
    "f1",
    "claim_type_accuracy",
    "evidence_accuracy",
    "actor_f1",
    "topic_accuracy",
    "date_accuracy",
    "numeric_accuracy",
    "abstention_accuracy",
    "abstention_precision",
    "abstention_recall",
    "hallucination_rate",
)


def render_markdown_report(report: EvaluationReport) -> str:
    metrics = report.metrics
    failures = []
    for result in report.case_results:
        if (
            result.false_positive_indexes
            or result.false_negative_claim_ids
            or result.claim_type_errors
            or result.evidence_errors
            or result.error
        ):
            details = []
            if result.false_positive_indexes:
                details.append(f"FP={list(result.false_positive_indexes)}")
            if result.false_negative_claim_ids:
                details.append(f"FN={list(result.false_negative_claim_ids)}")
            if result.claim_type_errors:
                details.append("type error")
            if result.evidence_errors:
                details.append("evidence error")
            if result.error:
                details.append(result.error)
            failures.append(f"- `{result.case_id}`: " + "; ".join(details))
    failure_text = "\n".join(failures) if failures else "- None"
    threshold_text = (
        "PASS"
        if report.threshold_result.passed
        else "FAIL: " + "; ".join(report.threshold_result.failures)
    )
    return f"""# AI Extraction Evaluation

- Dataset: `{report.dataset_version}`
- Cases: {report.case_count}
- Provider/model: `{report.provider}` / `{report.model}`
- Prompt/schema: `{report.prompt_version}` / `{report.schema_version}`
- Status: `{report.status.value}`
- Engineering thresholds: **{threshold_text}**

## Aggregate metrics

- Claim precision: {metrics.precision:.4f}
- Claim recall: {metrics.recall:.4f}
- Claim F1: {metrics.f1:.4f}
- Proposal/promise accuracy: {metrics.claim_type_accuracy:.4f}
- Evidence accuracy: {metrics.evidence_accuracy:.4f}
- Actor F1: {metrics.actor_f1:.4f}
- Topic accuracy: {metrics.topic_accuracy:.4f}
- Date accuracy: {metrics.date_accuracy:.4f}
- Numeric accuracy: {metrics.numeric_accuracy:.4f}
- Abstention accuracy: {metrics.abstention_accuracy:.4f}
- Hallucination rate: {metrics.hallucination_rate:.4f}
- Failed cases: {metrics.failed_cases}

## Usage metadata

- Requests: {report.usage.request_count}
- Input tokens: {report.usage.input_tokens}
- Output tokens: {report.usage.output_tokens}

## Failures and regressions

{failure_text}
"""


def write_evaluation_reports(
    report: EvaluationReport, output_directory: Path
) -> tuple[Path, Path]:
    directory = output_directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "report.json"
    markdown_path = directory / "report.md"
    json_path.write_text(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def compare_reports(
    run_a: EvaluationReport, run_b: EvaluationReport
) -> EvaluationComparison:
    return EvaluationComparison(
        run_a={
            "dataset_version": run_a.dataset_version,
            "provider": run_a.provider,
            "model": run_a.model,
            "prompt_version": run_a.prompt_version,
        },
        run_b={
            "dataset_version": run_b.dataset_version,
            "provider": run_b.provider,
            "model": run_b.model,
            "prompt_version": run_b.prompt_version,
        },
        metric_deltas={
            name: getattr(run_b.metrics, name) - getattr(run_a.metrics, name)
            for name in COMPARISON_METRICS
        },
    )


def load_evaluation_report(path: Path) -> EvaluationReport:
    return EvaluationReport.model_validate_json(path.read_text(encoding="utf-8"))
