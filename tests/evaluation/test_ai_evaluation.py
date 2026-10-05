import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.app.ai import ExtractionProviderError
from backend.app.evaluation import (
    DatasetFakeExtractionProvider,
    EvaluationDatasetError,
    EvaluationFakeProfile,
    ExtractionEvaluationService,
    compare_reports,
    load_evaluation_report,
    load_gold_dataset,
    match_claims,
    render_markdown_report,
    write_evaluation_reports,
)
from backend.app.models import (
    AIExtractionEvaluationRun,
    Proposal,
    ProposalDraft,
)
from backend.app.schemas import (
    EvaluationThresholds,
    ExtractedPoliticalClaim,
    GoldClaim,
)


DATASET_ROOT = Path(__file__).resolve().parents[2] / "evaluation" / "gold" / "v1"


def _evaluate(session_factory, profile=EvaluationFakeProfile.PERFECT, thresholds=None):
    dataset = load_gold_dataset(DATASET_ROOT)
    provider = DatasetFakeExtractionProvider(
        tuple(item.gold for item in dataset.cases), profile
    )
    return ExtractionEvaluationService(
        session_factory,
        provider,
        thresholds=thresholds or EvaluationThresholds(),
    ).evaluate(dataset)


def test_gold_dataset_loading_and_validation():
    dataset = load_gold_dataset(DATASET_ROOT)

    assert dataset.manifest.dataset_version == "v1"
    assert len(dataset.cases) == 10
    assert all(case.gold.synthetic for case in dataset.cases)
    assert dataset.cases[7].chunks[1].chunk_index == 1


def test_gold_dataset_rejects_escaping_document_path(tmp_path):
    manifest = json.loads((DATASET_ROOT / "manifest.json").read_text())
    manifest["cases"][0]["document"] = "../outside.html"
    root = tmp_path / "v1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(EvaluationDatasetError, match="escapes root"):
        load_gold_dataset(root)


def test_perfect_provider_scores_one_and_persists_only_evaluation_run(
    session_factory,
):
    report = _evaluate(session_factory)

    assert report.metrics.precision == 1
    assert report.metrics.recall == 1
    assert report.metrics.f1 == 1
    assert report.metrics.claim_type_accuracy == 1
    assert report.metrics.evidence_accuracy == 1
    assert report.metrics.actor_f1 == 1
    assert report.metrics.topic_accuracy == 1
    assert report.metrics.topic_counts["education"] == {
        "expected": 2,
        "correct": 2,
    }
    assert report.metrics.date_accuracy == 1
    assert report.metrics.date_field_accuracy == {
        "announced_at": 1,
        "target_date": 1,
    }
    assert report.metrics.numeric_accuracy == 1
    assert report.metrics.abstention_accuracy == 1
    assert report.metrics.hallucination_rate == 0
    assert report.threshold_result.passed
    with session_factory() as session:
        run = session.get(AIExtractionEvaluationRun, report.run_id)
        assert run.aggregate_metrics["f1"] == 1
        assert len(run.case_results) == 10
        assert session.scalar(select(func.count()).select_from(Proposal)) == 0
        assert session.scalar(select(func.count()).select_from(ProposalDraft)) == 0


def test_noisy_provider_scores_false_positive_false_negative_and_hallucination(
    session_factory,
):
    report = _evaluate(session_factory, EvaluationFakeProfile.NOISY)

    assert report.metrics.false_positives == 1
    assert report.metrics.false_negatives == 1
    assert report.metrics.precision < 1
    assert report.metrics.recall < 1
    assert report.metrics.f1 < 1
    assert report.metrics.hallucination_rate > 0
    assert not report.threshold_result.passed


def test_wrong_evidence_drops_grounding_without_losing_claim_detection(
    session_factory,
):
    report = _evaluate(session_factory, EvaluationFakeProfile.WRONG_EVIDENCE)

    assert report.metrics.precision == 1
    assert report.metrics.recall == 1
    assert report.metrics.evidence_accuracy == 0
    assert report.metrics.wrong_evidence > 0
    assert report.metrics.hallucination_rate > 0


def test_wrong_type_and_abstention_profiles_score_independently(session_factory):
    wrong_type = _evaluate(session_factory, EvaluationFakeProfile.WRONG_TYPE)
    abstention = _evaluate(session_factory, EvaluationFakeProfile.ABSTENTION)

    assert wrong_type.metrics.f1 == 1
    assert wrong_type.metrics.claim_type_accuracy < 1
    assert (
        wrong_type.metrics.claim_type_confusion["explicit_promise"]["proposal"] > 0
    )
    assert abstention.metrics.false_negatives > 0
    assert abstention.metrics.incorrect_abstentions > 0
    assert abstention.metrics.abstention_precision < 1


def test_ambiguous_matching_is_conservative():
    gold = (
        GoldClaim(
            claim_id="a",
            claim_type="proposal",
            exact_statement="Same statement",
            normalized_title="First",
        ),
        GoldClaim(
            claim_id="b",
            claim_type="proposal",
            exact_statement="Same statement",
            normalized_title="Second",
        ),
    )
    prediction = ExtractedPoliticalClaim(
        claim_type="proposal",
        exact_statement="Same statement",
        normalized_title="Same",
        confidence="high",
        evidence=[
            {"chunk_index": 0, "supporting_text": "Same statement"}
        ],
    )

    matches, matched = match_claims((prediction,), gold)

    assert matched == {}
    assert matches[0].method == "ambiguous"
    assert matches[0].ambiguous_gold_claim_ids == ("a", "b")


class _FailOneProvider:
    provider_name = "failure-fixture"
    model_name = "failure-fixture-v1"

    def __init__(self, delegate):
        self.delegate = delegate

    def extract(self, request):
        if request.source_url.endswith("/two-claims"):
            raise ExtractionProviderError("synthetic case failure")
        return self.delegate.extract(request)


def test_provider_case_failure_keeps_remaining_results(session_factory):
    dataset = load_gold_dataset(DATASET_ROOT)
    perfect = DatasetFakeExtractionProvider(
        tuple(item.gold for item in dataset.cases),
        EvaluationFakeProfile.PERFECT,
    )
    report = ExtractionEvaluationService(
        session_factory,
        _FailOneProvider(perfect),
        thresholds=EvaluationThresholds(),
    ).evaluate(dataset)

    assert report.status == "partial"
    assert report.metrics.failed_cases == 1
    assert len(report.case_results) == 10
    assert report.metrics.false_negatives == 2
    assert "synthetic case failure" in report.error_summary[0]


def test_reports_comparison_and_threshold_pass_fail(session_factory, tmp_path):
    perfect = _evaluate(session_factory)
    noisy = _evaluate(
        session_factory,
        EvaluationFakeProfile.NOISY,
        EvaluationThresholds(
            min_precision=1,
            min_evidence_accuracy=1,
            max_hallucination_rate=0,
        ),
    )

    json_path, markdown_path = write_evaluation_reports(perfect, tmp_path / "perfect")
    loaded = load_evaluation_report(json_path)
    markdown = markdown_path.read_text()
    comparison = compare_reports(perfect, noisy)

    assert loaded.metrics.f1 == 1
    assert "# AI Extraction Evaluation" in markdown
    assert "Claim precision: 1.0000" in render_markdown_report(perfect)
    assert comparison.metric_deltas["f1"] < 0
    assert perfect.threshold_result.passed
    assert not noisy.threshold_result.passed
