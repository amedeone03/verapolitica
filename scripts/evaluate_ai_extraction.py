import argparse
import json
import sys
from pathlib import Path

from backend.app.ai import OpenAIExtractionProvider
from backend.app.core.config import Settings, get_settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.evaluation import (
    DatasetFakeExtractionProvider,
    EvaluationDatasetError,
    EvaluationFakeProfile,
    ExtractionEvaluationService,
    compare_reports,
    load_evaluation_report,
    load_gold_dataset,
    write_evaluation_reports,
)
from backend.app.schemas import (
    EvaluationComparison,
    EvaluationReport,
    EvaluationThresholds,
)


DEFAULT_DATASET = Path("evaluation/gold/v1")
DEFAULT_OUTPUT = Path("evaluation/reports/latest")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic AI extraction evaluation; never publishes proposals."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--provider", choices=("fake", "openai"), default="fake")
    parser.add_argument(
        "--profile",
        choices=tuple(item.value for item in EvaluationFakeProfile),
        default=EvaluationFakeProfile.PERFECT.value,
    )
    parser.add_argument("--model")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-precision", type=float)
    parser.add_argument("--min-evidence-accuracy", type=float)
    parser.add_argument("--max-hallucination-rate", type=float)
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("RUN_A", "RUN_B"))
    return parser


def _thresholds(args: argparse.Namespace, settings: Settings) -> EvaluationThresholds:
    return EvaluationThresholds(
        min_precision=(
            args.min_precision
            if args.min_precision is not None
            else settings.ai_eval_min_precision
        ),
        min_evidence_accuracy=(
            args.min_evidence_accuracy
            if args.min_evidence_accuracy is not None
            else settings.ai_eval_min_evidence_accuracy
        ),
        max_hallucination_rate=(
            args.max_hallucination_rate
            if args.max_hallucination_rate is not None
            else settings.ai_eval_max_hallucination_rate
        ),
    )


def run(
    args: argparse.Namespace, *, settings: Settings | None = None
) -> EvaluationReport | EvaluationComparison:
    if args.compare:
        return compare_reports(
            load_evaluation_report(args.compare[0]),
            load_evaluation_report(args.compare[1]),
        )
    runtime = settings or get_settings()
    dataset = load_gold_dataset(args.dataset)
    if args.provider == "fake":
        provider = DatasetFakeExtractionProvider(
            tuple(item.gold for item in dataset.cases),
            EvaluationFakeProfile(args.profile),
        )
    else:
        model = args.model or runtime.llm_model
        if runtime.llm_api_key is None or not model:
            raise ValueError(
                "real evaluation requires an explicit model and "
                "VERAPOLITICA_LLM_API_KEY"
            )
        provider = OpenAIExtractionProvider(
            api_key=runtime.llm_api_key.get_secret_value(),
            model_name=model,
            timeout_seconds=runtime.llm_timeout_seconds,
            max_retries=runtime.llm_max_retries,
        )
    engine = create_db_engine(runtime.database_url)
    try:
        Base.metadata.create_all(engine)
        report = ExtractionEvaluationService(
            create_session_factory(engine),
            provider,
            thresholds=_thresholds(args, runtime),
        ).evaluate(dataset)
        write_evaluation_reports(report, args.output_dir)
        return report
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except (EvaluationDatasetError, OSError, ValueError) as exc:
        print(f"AI evaluation failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    if isinstance(result, EvaluationReport) and not result.threshold_result.passed:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
