from backend.app.core.config import Settings
from backend.app.jobs.catalog import enabled_schedules
from backend.app.scoring.evidence_matching import EvidenceJudgment
from backend.app.scoring.pledge_evidence_eval import (
    load_gold_dataset,
    readiness_gate,
    run_gold_evaluation,
)
from backend.app.scoring.types import EvidenceLabel, FulfillmentVerdict
from backend.app.services.pledge_service import PledgeService


def test_gold_set_is_deterministic_and_never_publishes():
    first = run_gold_evaluation()
    second = run_gold_evaluation()
    assert first.dataset_version == "pledge-evidence-gold/v3"
    assert first.case_count >= 28
    assert first.published is False
    assert first.as_dict()["published"] is False
    assert [item.outcome for item in first.retrieval] == [
        item.outcome for item in second.retrieval
    ]
    assert [item.predicted_label for item in first.conservative] == [
        item.predicted_label for item in second.conservative
    ]
    dataset = load_gold_dataset()
    kinds = {case.kind for case in dataset.cases}
    overlaps = {case.overlap_type for case in dataset.cases}
    assert len(dataset.cases) >= 28
    assert {"positive", "negative", "abstain"} <= kinds
    assert {"same_topic", "title_only", "procedural", "implementation"} <= overlaps
    ids = {case.case_id for case in dataset.cases}
    assert {
        "pos-autonomia-law86",
        "title-giudiziario-law114",
        "neg-giudiziario-law86",
        "neg-infrastrutture-tim-note",
        "abstain-sophia-no-later-evidence",
        "proc-104-calendar",
        "same-109-cutro",
        "neg-carceri-sovraffollamento",
        "neg-107-adi-statistica",
    } <= ids
    by_id = {item.case_id: item for item in first.retrieval}
    assert by_id["pos-autonomia-law86"].outcome == "tp"
    assert by_id["pos-carceri-law112"].outcome == "tp"
    assert by_id["pos-107-assegno-inclusione"].outcome == "tp"
    assert by_id["neg-giudiziario-law86"].outcome == "tn"
    assert by_id["neg-infrastrutture-tim-note"].outcome == "tn"
    assert by_id["neg-carceri-sovraffollamento"].outcome == "tn"
    assert by_id["neg-107-adi-statistica"].outcome == "tn"
    assert by_id["proc-104-calendar"].outcome == "tn"
    assert by_id["abstain-sophia-no-later-evidence"].outcome == "tn"
    assert first.conservative_closed_verdicts == 0
    assert first.false_positives == 0
    assert first.false_negatives == 0
    assert first.precision == 1.0
    cons = {item.case_id: item for item in first.conservative}
    assert cons["title-giudiziario-law114"].predicted_label is EvidenceLabel.NOT_ENOUGH_INFO
    assert cons["announce-106-cdm"].predicted_label is EvidenceLabel.NOT_ENOUGH_INFO
    assert cons["contradict-autonomia-corte192"].predicted_label is EvidenceLabel.NOT_ENOUGH_INFO
    assert all(item.excerpt_valid for item in first.conservative)
    assert all(item.compatible for item in first.conservative)
    assert not any(item.predicted_verdict in {FulfillmentVerdict.KEPT, FulfillmentVerdict.BROKEN} for item in first.conservative)


def test_llm_gold_evaluation_cannot_publish(monkeypatch):
    called = []

    def _blocked(*_args, **_kwargs):
        called.append("approve")
        raise AssertionError("gold evaluation must not approve")

    monkeypatch.setattr(PledgeService, "approve", _blocked)
    monkeypatch.setattr(PledgeService, "propose", _blocked)

    class ClosedVerdictJudge:
        name = "qwen-eval-stub"
        version = "test"

        def judge(self, *, pledge_text, commitment_type, passage_text):
            del pledge_text, commitment_type
            excerpt = " ".join(passage_text.split())[:80]
            return EvidenceJudgment(
                EvidenceLabel.SUPPORTS,
                FulfillmentVerdict.KEPT,
                excerpt,
                "eval stub must not publish",
            )

    report = run_gold_evaluation(llm_judge=ClosedVerdictJudge())
    assert report.published is False
    assert called == []
    assert report.llm
    assert any(item.closed_verdict for item in report.llm)


def test_scheduler_readiness_requires_disabled_cron():
    report = run_gold_evaluation()
    ready = readiness_gate(report, schedule_cron="")
    assert ready["schedule_disabled"] is True
    assert ready["human_approval_required"] is True
    assert ready["conservative_verdict_semantics"] is True
    assert ready["gold_set_at_least_20"] is True
    assert "retrieval_precision_at_least_0_90" in ready
    blocked = readiness_gate(report, schedule_cron="0 4 * * *")
    assert blocked["schedule_disabled"] is False
    settings = Settings(schedule_pledge_evidence_cron="")
    assert "pledge-evidence" not in [spec.job_name for spec, _ in enabled_schedules(settings)]
