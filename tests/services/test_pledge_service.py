from datetime import date

import pytest
from sqlalchemy import func, select

from backend.app.models import (
    ImmutablePledgeRecordError,
    PledgeAssessment,
    PledgeAssessmentDraft,
    PledgeAssessmentDraftStatus,
    PledgeAssessmentOrigin,
)
from backend.app.schemas.pledge import PledgeAssessmentProposal, PledgeClassificationRequest
from backend.app.scoring import (
    CommitmentType,
    EvidenceLabel,
    FulfillmentVerdict,
    HolderRole,
    PledgeSpecificity,
)
from backend.app.scoring.evidence_matching import EvidenceJudgment
from backend.app.services.pledge_evidence_service import PledgeEvidenceService
from backend.app.services.pledge_service import (
    NewAssessmentDraft,
    PledgeConflictError,
    PledgeNotFoundError,
    PledgeService,
    PledgeValidationError,
)
from tests.services.pledge_seed import ACT_TEXT, add_extra_pledges, seed

EXCERPT = "approvato in via definitiva la legge che aumenta le pensioni minime"


def classification(**overrides) -> PledgeClassificationRequest:
    values = dict(
        specificity=PledgeSpecificity.HIGH,
        commitment_type=CommitmentType.ACTION,
        holder_role=HolderRole.GOVERNMENT_COALITION,
        cap_topic_code="13",
        mandate_start=date(2022, 10, 13),
        mandate_end=date(2027, 10, 13),
    )
    values.update(overrides)
    return PledgeClassificationRequest(**values)


def editor_draft(service, data, proposal_id, verdict, label, *, by="editor-a", excerpt=EXCERPT, chunk=True, effective=None):
    return service.propose(
        NewAssessmentDraft(
            proposal_id=proposal_id,
            proposal=PledgeAssessmentProposal(
                verdict=verdict,
                evidence_label=label,
                rationale="La legge approvata realizza l'impegno.",
                quoted_excerpt=excerpt,
                raw_document_id=data.raw_document_id,
                document_chunk_id=data.chunk_id if chunk else None,
                effective_at=effective,
            ),
            origin=PledgeAssessmentOrigin.EDITOR,
            created_by=by,
        )
    )


@pytest.fixture
def data(session_factory):
    return seed(session_factory)


@pytest.fixture
def service(session_factory):
    return PledgeService(session_factory)


def test_only_published_explicit_promises_can_be_classified(service, data):
    with pytest.raises(PledgeNotFoundError):
        service.classify(data.unpublished_id, classification(), classified_by="ed")
    with pytest.raises(PledgeNotFoundError):
        service.classify(data.bill_id, classification(), classified_by="ed")
    with pytest.raises(PledgeValidationError):
        service.classify(
            data.pledge_id,
            classification(mandate_start=date(2027, 1, 1), mandate_end=date(2026, 1, 1)),
            classified_by="ed",
        )
    result = service.classify(data.pledge_id, classification(), classified_by="ed")
    assert result.included_in_score is True
    again = service.classify(
        data.pledge_id, classification(specificity=PledgeSpecificity.VAGUE), classified_by="ed2"
    )
    assert again.included_in_score is False and again.classified_by == "ed2"


def test_drafts_require_classification_compatible_label_and_verbatim_excerpt(service, data):
    with pytest.raises(PledgeValidationError, match="classify"):
        editor_draft(service, data, data.pledge_id, FulfillmentVerdict.KEPT, EvidenceLabel.SUPPORTS)
    service.classify(data.pledge_id, classification(), classified_by="ed")
    with pytest.raises(PledgeValidationError, match="incompatible"):
        editor_draft(service, data, data.pledge_id, FulfillmentVerdict.KEPT, EvidenceLabel.REFUTES)
    with pytest.raises(PledgeValidationError, match="verbatim"):
        editor_draft(
            service, data, data.pledge_id, FulfillmentVerdict.KEPT, EvidenceLabel.SUPPORTS,
            excerpt="approvato all'unanimità dalla Camera",
        )
    # Without a chunk the excerpt is checked against the whole document text.
    draft, created = editor_draft(
        service, data, data.pledge_id, FulfillmentVerdict.KEPT, EvidenceLabel.SUPPORTS, chunk=False
    )
    assert created and draft.status == "pending" and draft.approvals_required == 1
    replay, created_again = editor_draft(
        service, data, data.pledge_id, FulfillmentVerdict.KEPT, EvidenceLabel.SUPPORTS, chunk=False
    )
    assert replay.id == draft.id and created_again is False


def test_single_approval_publishes_and_editor_cannot_self_approve(service, data, session_factory):
    service.classify(data.pledge_id, classification(), classified_by="ed")
    draft, _ = editor_draft(service, data, data.pledge_id, FulfillmentVerdict.KEPT, EvidenceLabel.SUPPORTS)
    with pytest.raises(PledgeConflictError, match="only approver"):
        service.approve(draft.id, reviewer="editor-a")
    updated, published = service.approve(draft.id, reviewer="caporedattore")
    assert updated.status == "approved"
    assert published.verdict is FulfillmentVerdict.KEPT
    assert published.methodology_version == "pledge-score/v1"
    with pytest.raises(PledgeConflictError):
        service.approve(draft.id, reviewer="altro")
    with session_factory() as session:
        row = session.get(PledgeAssessment, published.id)
        row.rationale = "edited"
        with pytest.raises(ImmutablePledgeRecordError):
            session.flush()


def test_broken_requires_two_distinct_reviewers(service, data):
    service.classify(data.pledge_id, classification(), classified_by="ed")
    draft, _ = editor_draft(
        service, data, data.pledge_id, FulfillmentVerdict.BROKEN, EvidenceLabel.REFUTES
    )
    assert draft.approvals_required == 2
    first, published = service.approve(draft.id, reviewer="rev-1")
    assert first.status == "awaiting_second_approval" and published is None
    with pytest.raises(PledgeConflictError, match="already approved"):
        service.approve(draft.id, reviewer="rev-1")
    second, published = service.approve(draft.id, reviewer="rev-2")
    assert second.status == "approved"
    assert published.verdict is FulfillmentVerdict.BROKEN


def test_reject_and_stale_drafts(service, data):
    service.classify(data.pledge_id, classification(), classified_by="ed")
    newer, _ = editor_draft(
        service, data, data.pledge_id, FulfillmentVerdict.KEPT, EvidenceLabel.SUPPORTS,
        effective=date(2026, 1, 1),
    )
    older, _ = editor_draft(
        service, data, data.pledge_id, FulfillmentVerdict.IN_PROGRESS, EvidenceLabel.SUPPORTS,
        effective=date(2025, 6, 1),
    )
    service.approve(newer.id, reviewer="rev")
    with pytest.raises(PledgeConflictError, match="older"):
        service.approve(older.id, reviewer="rev")
    rejected = service.reject(older.id, reviewer="rev", note="superata")
    assert rejected.status == "rejected"
    assert [d.id for d in service.list_drafts(status=PledgeAssessmentDraftStatus.REJECTED)] == [older.id]


def test_scorecard_reflects_latest_verdicts_by_role(service, data, session_factory):
    service.classify(data.pledge_id, classification(), classified_by="ed")
    service.classify(
        data.outcome_pledge_id,
        classification(commitment_type=CommitmentType.OUTCOME, specificity=PledgeSpecificity.VAGUE),
        classified_by="ed",
    )
    draft, _ = editor_draft(service, data, data.pledge_id, FulfillmentVerdict.KEPT, EvidenceLabel.SUPPORTS)
    service.approve(draft.id, reviewer="rev")

    card = service.scorecard_for_politician(data.politician_id, as_of=date(2025, 4, 13))
    assert card.tracked_pledges == 2
    assert card.excluded_vague_pledges == 1
    assert card.unclassified_pledges == 0
    (stratum,) = card.strata
    assert stratum.role is HolderRole.GOVERNMENT_COALITION
    assert stratum.closed_pledges == 1
    assert stratum.rate is None  # below the minimum of 8 closed pledges
    assert stratum.credible_interval is not None
    assert 0.49 < card.mandate_progress.elapsed_fraction < 0.51
    verdicts = {p.proposal_id: p.verdict for p in card.pledges}
    assert verdicts == {
        data.pledge_id: FulfillmentVerdict.KEPT,
        data.outcome_pledge_id: FulfillmentVerdict.NOT_YET_RATED,
    }

    # With enough closed pledges the rate is published.
    extra = add_extra_pledges(session_factory, data, 8)
    for index, proposal_id in enumerate(extra):
        service.classify(proposal_id, classification(), classified_by="ed")
        verdict, label = (
            (FulfillmentVerdict.KEPT, EvidenceLabel.SUPPORTS)
            if index < 4
            else (FulfillmentVerdict.PARTIALLY_KEPT, EvidenceLabel.SUPPORTS)
        )
        draft, _ = editor_draft(service, data, proposal_id, verdict, label)
        service.approve(draft.id, reviewer="rev")
    stratum = service.scorecard_for_politician(data.politician_id).strata[0]
    assert stratum.closed_pledges == 9
    assert stratum.rate == round((5 + 0.5 * 4) / 9, 4)


def test_blind_audit_quality_and_bias_reports(service, data, session_factory):
    extra = add_extra_pledges(session_factory, data, 10)
    published_ids = []
    for index, proposal_id in enumerate(extra):
        service.classify(proposal_id, classification(), classified_by="ed")
        draft, _ = editor_draft(service, data, proposal_id, FulfillmentVerdict.KEPT, EvidenceLabel.SUPPORTS)
        _, published = service.approve(draft.id, reviewer="rev")
        published_ids.append(published.id)

    sample = service.draw_audit_sample(sample_key="2026-Q4", size=4, seed=11, created_by="admin")
    assert sample.population_size == 10
    assert sample.inclusion_probability == 0.4
    assert len(sample.items) == 4
    assert "verdict" not in sample.items[0].model_dump()
    with pytest.raises(PledgeConflictError):
        service.draw_audit_sample(sample_key="2026-Q4", size=4, seed=11, created_by="admin")
    assert service.get_audit_sample("2026-Q4") == sample

    first = sample.items[0].assessment_id
    with pytest.raises(PledgeConflictError, match="own verdict"):
        service.record_audit_coding("2026-Q4", first, coder="rev", verdict=FulfillmentVerdict.KEPT)
    with pytest.raises(PledgeValidationError):
        service.record_audit_coding("2026-Q4", first, coder="aud", verdict=FulfillmentVerdict.IN_PROGRESS)
    outside = next(i for i in published_ids if i not in {item.assessment_id for item in sample.items})
    with pytest.raises(PledgeValidationError):
        service.record_audit_coding("2026-Q4", outside, coder="aud", verdict=FulfillmentVerdict.KEPT)

    # The auditor disagrees on half of the sample.
    for position, item in enumerate(sample.items):
        verdict = FulfillmentVerdict.KEPT if position % 2 == 0 else FulfillmentVerdict.BROKEN
        service.record_audit_coding("2026-Q4", item.assessment_id, coder="aud", verdict=verdict)
    with pytest.raises(PledgeConflictError):
        service.record_audit_coding("2026-Q4", first, coder="aud", verdict=FulfillmentVerdict.KEPT)

    quality = service.audit_quality("2026-Q4")
    assert quality.coded_items == 4
    assert quality.nominal_agreement.alpha is not None
    assert quality.nominal_agreement.alpha < 0.5
    (rate,) = quality.corrected_rates
    assert rate.naive_rate == 1.0
    assert rate.corrected_rate == pytest.approx(0.5)
    assert rate.disagreement_rate == 0.5

    # New assessments after the draw do not change the frozen population.
    more = add_extra_pledges(session_factory, data, 1)
    service.classify(more[0], classification(), classified_by="ed")
    draft, _ = editor_draft(service, data, more[0], FulfillmentVerdict.KEPT, EvidenceLabel.SUPPORTS)
    service.approve(draft.id, reviewer="rev")
    assert service.audit_quality("2026-Q4").corrected_rates[0].population_size == 10

    bias = service.bias_audit(min_per_group=2)
    assert bias.comparisons == ()  # a single bloc: nothing to compare
    assert bias.skipped_strata == 1


class FakeJudge:
    name = "fake-judge"
    version = "test"

    def __init__(self):
        self.calls = 0

    def judge(self, *, pledge_text, commitment_type, passage_text):
        self.calls += 1
        if "pensioni minime" in passage_text:
            return EvidenceJudgment(
                EvidenceLabel.SUPPORTS,
                FulfillmentVerdict.KEPT,
                "approvato in via definitiva la legge che aumenta le pensioni minime",
                "L'atto approva l'aumento promesso.",
            )
        return EvidenceJudgment(EvidenceLabel.SUPPORTS, FulfillmentVerdict.KEPT, "testo inventato dal modello", "x")


def test_evidence_matcher_creates_only_verified_drafts(session_factory, data):
    service = PledgeService(session_factory)
    service.classify(data.pledge_id, classification(), classified_by="ed")
    service.classify(
        data.outcome_pledge_id,
        classification(commitment_type=CommitmentType.OUTCOME),
        classified_by="ed",
    )

    abstaining = PledgeEvidenceService(session_factory).run()
    assert abstaining.drafts_created == 0
    assert abstaining.rejections == {"not_enough_info": abstaining.passages_judged}
    assert abstaining.skipped_outcome_pledges == 1

    judge = FakeJudge()
    report = PledgeEvidenceService(session_factory, judge=judge).run()
    assert report.pledges_considered == 1
    assert report.drafts_created == 1
    assert report.rejections.get("excerpt_not_found_in_source", 0) == report.passages_judged - 1
    (draft,) = service.list_drafts()
    assert draft.origin == "evidence_matcher"
    assert draft.document_chunk_id == data.chunk_id
    assert draft.judge_name == "fake-judge"
    assert draft.quoted_excerpt in ACT_TEXT

    replay = PledgeEvidenceService(session_factory, judge=FakeJudge()).run()
    assert replay.drafts_created == 0 and replay.drafts_replayed == 1

    # Once a closed verdict is published the pledge is no longer matched.
    service.approve(draft.id, reviewer="rev")
    after = PledgeEvidenceService(session_factory, judge=FakeJudge()).run()
    assert after.pledges_considered == 0
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PledgeAssessmentDraft)) == 1


def test_pledge_evidence_job_reports_metrics_without_publishing(session_factory, data):
    from backend.app.core.config import Settings
    from backend.app.jobs.catalog import JOB_CATALOG

    PledgeService(session_factory).classify(data.pledge_id, classification(), classified_by="ed")
    spec = JOB_CATALOG["pledge-evidence"]
    assert spec.schedule_attr == "schedule_pledge_evidence_cron"
    metrics = spec.runner(Settings(), session_factory)
    assert metrics.records_processed == 1
    assert metrics.records_created == 0
    assert metrics.metadata["judge"] == "abstaining/v1"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PledgeAssessment)) == 0
