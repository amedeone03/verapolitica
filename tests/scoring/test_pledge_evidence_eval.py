from urllib.parse import urlsplit

from backend.app.core.config import Settings
from backend.app.jobs.catalog import enabled_schedules
from backend.app.scoring.evidence_matching import EvidenceJudgment
from backend.app.scoring.instrument_aliases import ALIAS_POLICY_VERSION, INSTRUMENT_ALIASES
from backend.app.scoring.official_sources import is_official_source_url
from backend.app.scoring.pledge_evidence_eval import (
    load_gold_dataset,
    readiness_gate,
    run_gold_evaluation,
)
from backend.app.scoring.retrieval_profile import (
    KNOWN_INSTRUMENT_VOCABULARY_VERSION,
    RETRIEVAL_POLICY_VERSION,
)
from backend.app.scoring.types import EvidenceLabel, FulfillmentVerdict
from backend.app.services.pledge_service import PledgeService

FROZEN_V3_IDS = {
    "pos-autonomia-law86",
    "title-giudiziario-law114",
    "neg-giudiziario-law86",
    "neg-infrastrutture-tim-note",
    "abstain-sophia-no-later-evidence",
    "contradict-autonomia-corte192",
    "pos-carceri-law112",
    "neg-carceri-law114",
    "neg-carceri-law86",
    "same-102-tim",
    "same-102-sky-alps",
    "title-102-a24",
    "same-105-riscossione",
    "same-105-concordato",
    "abstain-105-no-criteria",
    "pos-107-assegno-inclusione",
    "neg-107-law86",
    "pos-108-asili-nido",
    "neg-108-law114",
    "same-109-cutro",
    "proc-104-calendar",
    "announce-106-cdm",
    "actor-108-esteri",
    "date-106-legge42",
    "neg-carceri-sovraffollamento",
    "neg-carceri-organigramma",
    "neg-carceri-polizia",
    "neg-107-linee-guida",
    "neg-107-adi-statistica",
    "neg-107-assegno-unico",
}


def test_gold_set_is_deterministic_and_never_publishes():
    first = run_gold_evaluation()
    second = run_gold_evaluation()
    assert first.dataset_version == "pledge-evidence-gold/v5"
    assert first.case_count >= 66
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
    assert len(dataset.cases) >= 66
    assert {"positive", "negative", "abstain"} <= kinds
    assert {
        "same_topic",
        "title_only",
        "procedural",
        "implementation",
        "announcement",
        "actor_only",
        "date_window",
        "contradictory",
        "no_evidence",
    } <= overlaps
    ids = {case.case_id for case in dataset.cases}
    assert FROZEN_V3_IDS <= ids
    by_id = {item.case_id: item for item in first.retrieval}
    frozen = [item for item in first.retrieval if item.case_id in FROZEN_V3_IDS]
    assert all(item.outcome in {"tp", "tn"} for item in frozen)
    assert not any(item.outcome == "fp" for item in frozen)
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
    assert by_id["pos-conte-rdc"].outcome == "tp"
    assert by_id["pos-draghi-pnrr"].outcome == "tp"
    assert by_id["pos-speranza-greenpass"].outcome == "tp"
    assert by_id["pos-schillaci-liste"].outcome == "tp"
    assert by_id["pos-giorgetti-cuneo"].outcome == "tp"
    assert by_id["pos-draghi-assegno-unico"].outcome == "tp"
    assert by_id["same-conte-lavoro-poverta"].outcome == "tn"
    assert by_id["date-draghi-pnrr-2024"].outcome == "tn"
    assert by_id["same-speranza-influenza"].outcome == "tn"
    assert by_id["same-giorgetti-mef-circolare"].outcome == "tn"
    assert by_id["same-draghi-natalita"].outcome == "tn"
    assert by_id["date-giorgetti-pre-cuneo"].outcome == "tn"
    cons = {item.case_id: item for item in first.conservative}
    assert cons["title-giudiziario-law114"].predicted_label is EvidenceLabel.NOT_ENOUGH_INFO
    assert cons["announce-106-cdm"].predicted_label is EvidenceLabel.NOT_ENOUGH_INFO
    assert cons["announce-conte-rdc"].predicted_label is EvidenceLabel.NOT_ENOUGH_INFO
    assert cons["contradict-autonomia-corte192"].predicted_label is EvidenceLabel.NOT_ENOUGH_INFO
    assert cons["date-tajani-post-mandate"].predicted_label is EvidenceLabel.NOT_ENOUGH_INFO
    assert first.conservative_false_supports == 0
    assert first.conservative_false_refutes == 0
    assert all(item.excerpt_valid for item in first.conservative)
    assert all(item.compatible for item in first.conservative)
    assert not any(item.predicted_verdict in {FulfillmentVerdict.KEPT, FulfillmentVerdict.BROKEN} for item in first.conservative)


def test_expanded_gold_has_required_fields_and_diversity():
    dataset = load_gold_dataset()
    actors = {case.actor for case in dataset.cases}
    topics = {case.topic_code for case in dataset.cases if case.topic_code}
    hosts = {
        (urlsplit(case.source_url).hostname or "").casefold()
        for case in dataset.cases
        if case.source_url
    }
    assert len(dataset.cases) >= 66
    assert len(actors) >= 5
    assert len(topics) >= 5
    assert len(hosts) >= 5
    for case in dataset.cases:
        assert case.commitment_id
        assert case.actor
        assert case.commitment_text
        assert case.expected_retrieval in {"relevant", "irrelevant"}
        assert case.expected_label
        assert case.explanation
        if case.source_url:
            assert is_official_source_url(case.source_url)
            assert case.source_title
            assert case.published_at is not None
            assert case.exact_excerpt
            assert case.document
    assert ALIAS_POLICY_VERSION == "instrument-alias/v1"
    assert RETRIEVAL_POLICY_VERSION == "pledge_evidence_retrieval_v2"
    assert KNOWN_INSTRUMENT_VOCABULARY_VERSION == "known-instruments/v2"
    assert {item.source for item in INSTRUMENT_ALIASES} == {
        "piano carceri",
        "soggetti effettivamente fragili",
    }


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
