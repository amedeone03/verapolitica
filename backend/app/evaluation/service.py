from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.ai import (
    ExtractionProviderError,
    StructuredExtractionProvider,
    StructuredExtractionRequest,
)
from backend.app.evaluation.dataset import LoadedEvaluationDataset
from backend.app.evaluation.metrics import aggregate_metrics, score_case
from backend.app.models import (
    AIExtractionEvaluationRun,
    AIExtractionEvaluationRunStatus,
)
from backend.app.pipeline.prompts import load_proposal_extraction_prompt
from backend.app.schemas.ai_evaluation import (
    EVALUATOR_VERSION,
    EvaluationCaseStatus,
    EvaluationReport,
    EvaluationRunStatus,
    EvaluationThresholds,
    EvaluationUsage,
    ThresholdResult,
)


def evaluate_thresholds(metrics, thresholds: EvaluationThresholds) -> ThresholdResult:
    failures: list[str] = []
    if metrics.precision < thresholds.min_precision:
        failures.append(
            f"precision {metrics.precision:.4f} < {thresholds.min_precision:.4f}"
        )
    if metrics.evidence_accuracy < thresholds.min_evidence_accuracy:
        failures.append(
            "evidence_accuracy "
            f"{metrics.evidence_accuracy:.4f} < {thresholds.min_evidence_accuracy:.4f}"
        )
    if metrics.hallucination_rate > thresholds.max_hallucination_rate:
        failures.append(
            "hallucination_rate "
            f"{metrics.hallucination_rate:.4f} > "
            f"{thresholds.max_hallucination_rate:.4f}"
        )
    return ThresholdResult(passed=not failures, failures=tuple(failures))


class ExtractionEvaluationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        provider: StructuredExtractionProvider,
        *,
        thresholds: EvaluationThresholds,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.thresholds = thresholds

    def evaluate(self, dataset: LoadedEvaluationDataset) -> EvaluationReport:
        started_at = datetime.now(timezone.utc)
        with self.session_factory() as session:
            run = AIExtractionEvaluationRun(
                dataset_version=dataset.manifest.dataset_version,
                provider=self.provider.provider_name,
                model=self.provider.model_name,
                prompt_version=dataset.manifest.prompt_version,
                schema_version=dataset.manifest.schema_version,
                evaluator_version=EVALUATOR_VERSION,
                status=AIExtractionEvaluationRunStatus.RUNNING,
                case_count=len(dataset.cases),
                started_at=started_at,
            )
            session.add(run)
            session.commit()
            run_id = run.id

        results = []
        errors: list[str] = []
        request_count = input_tokens = output_tokens = 0
        for loaded_case in dataset.cases:
            try:
                provider_result = self.provider.extract(
                    StructuredExtractionRequest(
                        source_url=loaded_case.gold.source_url,
                        prompt=load_proposal_extraction_prompt(),
                        chunks=loaded_case.provider_chunks(),
                    )
                )
                request_count += provider_result.usage.request_count
                input_tokens += provider_result.usage.input_tokens or 0
                output_tokens += provider_result.usage.output_tokens or 0
                results.append(
                    score_case(
                        loaded_case.gold,
                        provider_result.output.candidates,
                        loaded_case.chunks,
                    )
                )
            except ExtractionProviderError as exc:
                message = f"{loaded_case.gold.case_id}: {type(exc).__name__}: {exc}"
                errors.append(message)
                results.append(
                    score_case(
                        loaded_case.gold,
                        (),
                        loaded_case.chunks,
                        status=EvaluationCaseStatus.PROVIDER_FAILED,
                        error=str(exc),
                    )
                )
            except ValidationError as exc:
                message = f"{loaded_case.gold.case_id}: schema failure: {exc}"
                errors.append(message)
                results.append(
                    score_case(
                        loaded_case.gold,
                        (),
                        loaded_case.chunks,
                        status=EvaluationCaseStatus.SCHEMA_FAILED,
                        error=str(exc),
                    )
                )
            except Exception as exc:
                message = (
                    f"{loaded_case.gold.case_id}: extraction failure: "
                    f"{type(exc).__name__}: {exc}"
                )
                errors.append(message)
                results.append(
                    score_case(
                        loaded_case.gold,
                        (),
                        loaded_case.chunks,
                        status=EvaluationCaseStatus.EXTRACTION_FAILED,
                        error=str(exc),
                    )
                )

        case_results = tuple(results)
        metrics = aggregate_metrics(
            tuple(item.gold for item in dataset.cases), case_results
        )
        threshold_result = evaluate_thresholds(metrics, self.thresholds)
        completed_at = datetime.now(timezone.utc)
        status = (
            EvaluationRunStatus.FAILED
            if metrics.failed_cases == len(dataset.cases)
            else EvaluationRunStatus.PARTIAL
            if metrics.failed_cases
            else EvaluationRunStatus.COMPLETED
        )
        report = EvaluationReport(
            run_id=run_id,
            dataset_version=dataset.manifest.dataset_version,
            provider=self.provider.provider_name,
            model=self.provider.model_name,
            prompt_version=dataset.manifest.prompt_version,
            schema_version=dataset.manifest.schema_version,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            case_count=len(case_results),
            metrics=metrics,
            thresholds=self.thresholds,
            threshold_result=threshold_result,
            usage=EvaluationUsage(
                request_count=request_count,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            case_results=case_results,
            error_summary=tuple(errors),
        )
        with self.session_factory() as session:
            run = session.get(AIExtractionEvaluationRun, run_id)
            if run is None:
                raise RuntimeError("evaluation run disappeared")
            run.status = AIExtractionEvaluationRunStatus(status.value)
            run.failed_case_count = metrics.failed_cases
            run.aggregate_metrics = metrics.model_dump(mode="json")
            run.case_results = [
                item.model_dump(mode="json") for item in case_results
            ]
            run.request_count = request_count
            run.input_tokens = input_tokens
            run.output_tokens = output_tokens
            run.thresholds_passed = threshold_result.passed
            run.error_summary = errors
            run.completed_at = completed_at
            session.commit()
        return report
