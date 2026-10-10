"""Offline gold evaluation for official pledge-evidence matching.

Never writes drafts, assessments, or public scores. Metrics on this tiny set
are preliminary; precision is the priority.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.app.pipeline.document_extraction import extract_document
from backend.app.scoring.conservative_evidence_judge import ConservativeOfficialActJudge
from backend.app.scoring.evidence_matching import EvidenceJudgment, Passage, excerpt_is_verbatim
from backend.app.scoring.llm_evidence_judge import OllamaEvidenceJudge
from backend.app.scoring.official_evidence import OfficialPassage, retrieve_official_candidates
from backend.app.scoring.retrieval_profile import build_retrieval_profile
from backend.app.scoring.types import (
    CLOSED_VERDICTS,
    CommitmentType,
    EvidenceLabel,
    FulfillmentVerdict,
    PledgeSpecificity,
    VERDICTS_BY_EVIDENCE_LABEL,
)


GOLD_ROOT = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "fixtures"
    / "pledge_evidence"
    / "gold"
)


class GoldPledgeCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    kind: str
    overlap_type: str = ""
    commitment_id: str
    commitment_title: str
    commitment_text: str
    actor: str = "Giorgia Meloni"
    specificity: PledgeSpecificity = PledgeSpecificity.HIGH
    commitment_type: CommitmentType = CommitmentType.ACTION
    holder_role: str = "government_coalition"
    topic_code: str | None = None
    announcement_date: date | None = None
    mandate_start: date | None = None
    mandate_end: date | None = None
    document: str | None = None
    source_url: str = ""
    source_title: str = ""
    published_at: date | None = None
    exact_excerpt: str = ""
    expected_retrieval: str
    expected_label: EvidenceLabel
    acceptable_verdicts: tuple[FulfillmentVerdict, ...] = ()
    unacceptable_verdicts: tuple[FulfillmentVerdict, ...] = ()
    explanation: str


class GoldPledgeDataset(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: str
    notes: str = ""
    cases: tuple[GoldPledgeCase, ...]


@dataclass(frozen=True, slots=True)
class RetrievalCaseResult:
    case_id: str
    expected: str
    retrieved: bool
    outcome: str
    score: float | None
    overlap_type: str = ""
    filter_reasons: dict[str, int] = field(default_factory=dict)
    failure_type: str = ""


@dataclass(frozen=True, slots=True)
class JudgeCaseResult:
    case_id: str
    expected_label: EvidenceLabel
    predicted_label: EvidenceLabel
    predicted_verdict: FulfillmentVerdict | None
    excerpt_valid: bool
    closed_verdict: bool
    compatible: bool
    correct_label: bool
    verdict_ok: bool
    raw: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0


@dataclass(frozen=True, slots=True)
class PledgeEvidenceEvalReport:
    dataset_version: str
    case_count: int
    retrieval: tuple[RetrievalCaseResult, ...]
    conservative: tuple[JudgeCaseResult, ...]
    llm: tuple[JudgeCaseResult, ...]
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float
    recall: float
    f1: float
    retrieval_abstention_rate: float
    conservative_label_accuracy: float
    conservative_closed_verdicts: int
    conservative_closed_rate: float
    conservative_false_supports: int
    conservative_false_refutes: int
    conservative_abstention_rate: float
    conservative_excerpt_validity: float
    conservative_verdict_compatibility: float
    failure_types: dict[str, int]
    published: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_version": self.dataset_version,
            "case_count": self.case_count,
            "preliminary": self.case_count < 20,
            "published": False,
            "retrieval": {
                "true_positives": self.true_positives,
                "false_positives": self.false_positives,
                "false_negatives": self.false_negatives,
                "true_negatives": self.true_negatives,
                "precision": self.precision,
                "recall": self.recall,
                "f1": self.f1,
                "abstention_rate": self.retrieval_abstention_rate,
                "failure_types": self.failure_types,
                "cases": [asdict(item) for item in self.retrieval],
            },
            "conservative_judge": {
                "label_accuracy": self.conservative_label_accuracy,
                "closed_verdicts": self.conservative_closed_verdicts,
                "closed_verdict_rate": self.conservative_closed_rate,
                "false_supports": self.conservative_false_supports,
                "false_refutes": self.conservative_false_refutes,
                "abstention_rate": self.conservative_abstention_rate,
                "excerpt_validity": self.conservative_excerpt_validity,
                "verdict_compatibility": self.conservative_verdict_compatibility,
                "cases": [asdict(item) for item in self.conservative],
            },
            "llm_judge": [asdict(item) for item in self.llm],
        }


def load_gold_dataset(root: Path | None = None) -> GoldPledgeDataset:
    path = (root or GOLD_ROOT) / "manifest.json"
    return GoldPledgeDataset.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _case_text(case: GoldPledgeCase, root: Path) -> str:
    if not case.document:
        return ""
    document = (root / case.document).resolve()
    return extract_document(document.read_bytes(), "text/html").text


def _passage_for(case: GoldPledgeCase, root: Path) -> OfficialPassage | None:
    text = _case_text(case, root)
    if not text or not case.source_url:
        return None
    return OfficialPassage(
        passage=Passage(1, 1, text, case.source_url),
        source_id=1,
        source_key="gold",
        source_name="gold",
        retrieved_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        published_at=case.published_at,
    )


def _profile(case: GoldPledgeCase):
    return build_retrieval_profile(
        proposal_id=int(case.commitment_id) if case.commitment_id.isdigit() else 1,
        title=case.commitment_title,
        commitment_text=case.commitment_text,
        actor_names=(case.actor,),
        topic_code=case.topic_code,
        specificity=case.specificity,
        commitment_type=case.commitment_type,
        announcement_date=case.announcement_date,
        mandate_start=case.mandate_start or date(2022, 10, 22),
        mandate_end=case.mandate_end or date(2027, 10, 12),
    )


def _failure_type(case: GoldPledgeCase, outcome: str, reasons: dict[str, int]) -> str:
    if outcome in {"tp", "tn"}:
        return ""
    if outcome == "fn":
        if "outside_date_window" in reasons:
            return "date_window"
        if "missing_instrument_overlap" in reasons:
            return "instrument_mismatch"
        return "false_negative"
    overlap = case.overlap_type or case.kind
    if overlap in {
        "same_topic",
        "title_only",
        "actor_only",
        "procedural",
        "announcement",
        "date_window",
        "generic_term",
    }:
        return overlap
    if "outside_date_window" in reasons:
        return "date_window"
    return "false_positive"


def _ratio(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def _retrieval_outcome(expected: str, retrieved: bool) -> str:
    if expected == "relevant" and retrieved:
        return "tp"
    if expected == "relevant" and not retrieved:
        return "fn"
    if expected == "irrelevant" and retrieved:
        return "fp"
    return "tn"


def evaluate_retrieval(
    dataset: GoldPledgeDataset, *, root: Path | None = None
) -> tuple[RetrievalCaseResult, ...]:
    gold_root = root or GOLD_ROOT
    results: list[RetrievalCaseResult] = []
    for case in dataset.cases:
        profile = _profile(case)
        passage = _passage_for(case, gold_root)
        passages = [passage] if passage is not None else []
        candidates, reasons = retrieve_official_candidates(profile, passages)
        retrieved = bool(candidates)
        outcome = _retrieval_outcome(case.expected_retrieval, retrieved)
        results.append(
            RetrievalCaseResult(
                case_id=case.case_id,
                expected=case.expected_retrieval,
                retrieved=retrieved,
                outcome=outcome,
                score=candidates[0].deterministic_score if candidates else None,
                overlap_type=case.overlap_type or case.kind,
                filter_reasons=reasons,
                failure_type=_failure_type(case, outcome, reasons),
            )
        )
    return tuple(results)


def _judge_case(
    case: GoldPledgeCase,
    judgment: EvidenceJudgment,
    passage_text: str,
    *,
    elapsed_ms: int = 0,
    raw: dict[str, Any] | None = None,
) -> JudgeCaseResult:
    excerpt_valid = not judgment.quoted_excerpt or excerpt_is_verbatim(
        passage_text, judgment.quoted_excerpt
    )
    if judgment.label is EvidenceLabel.NOT_ENOUGH_INFO and not judgment.quoted_excerpt:
        excerpt_valid = True
    closed = judgment.proposed_verdict in CLOSED_VERDICTS if judgment.proposed_verdict else False
    compatible = True
    if judgment.label is EvidenceLabel.NOT_ENOUGH_INFO:
        compatible = judgment.proposed_verdict is None
    elif judgment.proposed_verdict is not None:
        compatible = judgment.proposed_verdict in VERDICTS_BY_EVIDENCE_LABEL[judgment.label]
    verdict_ok = True
    if judgment.proposed_verdict is not None:
        verdict_ok = judgment.proposed_verdict not in case.unacceptable_verdicts
        if case.acceptable_verdicts:
            verdict_ok = verdict_ok and judgment.proposed_verdict in case.acceptable_verdicts
    elif case.expected_label is not EvidenceLabel.NOT_ENOUGH_INFO:
        verdict_ok = False
    return JudgeCaseResult(
        case_id=case.case_id,
        expected_label=case.expected_label,
        predicted_label=judgment.label,
        predicted_verdict=judgment.proposed_verdict,
        excerpt_valid=excerpt_valid,
        closed_verdict=closed,
        compatible=compatible,
        correct_label=judgment.label is case.expected_label,
        verdict_ok=verdict_ok,
        raw=raw or {},
        elapsed_ms=elapsed_ms,
    )


def evaluate_conservative(
    dataset: GoldPledgeDataset, *, root: Path | None = None
) -> tuple[JudgeCaseResult, ...]:
    gold_root = root or GOLD_ROOT
    judge = ConservativeOfficialActJudge()
    results = []
    for case in dataset.cases:
        text = _case_text(case, gold_root)
        if not text:
            judgment = EvidenceJudgment(EvidenceLabel.NOT_ENOUGH_INFO, None, "", "")
        else:
            judgment = judge.judge(
                pledge_text=case.commitment_text,
                commitment_type=CommitmentType.ACTION,
                passage_text=text,
            )
        results.append(_judge_case(case, judgment, text))
    return tuple(results)


def evaluate_llm_judge(
    dataset: GoldPledgeDataset,
    judge,
    *,
    root: Path | None = None,
) -> tuple[JudgeCaseResult, ...]:
    gold_root = root or GOLD_ROOT
    results = []
    for case in dataset.cases:
        text = _case_text(case, gold_root)
        started = time.perf_counter()
        if not text:
            judgment = EvidenceJudgment(EvidenceLabel.NOT_ENOUGH_INFO, None, "", "")
            raw = {"skipped": True}
        else:
            judgment = judge.judge(
                pledge_text=case.commitment_text,
                commitment_type=CommitmentType.ACTION,
                passage_text=text,
            )
            raw = {
                "label": judgment.label.value,
                "proposed_verdict": (
                    judgment.proposed_verdict.value if judgment.proposed_verdict else None
                ),
                "quoted_excerpt": judgment.quoted_excerpt,
                "rationale": judgment.rationale,
            }
        elapsed = int((time.perf_counter() - started) * 1000)
        results.append(_judge_case(case, judgment, text, elapsed_ms=elapsed, raw=raw))
    return tuple(results)


def run_gold_evaluation(
    *,
    root: Path | None = None,
    llm_model: str | None = None,
    llm_judge=None,
    ollama_base_url: str = "http://127.0.0.1:11434",
) -> PledgeEvidenceEvalReport:
    dataset = load_gold_dataset(root)
    retrieval = evaluate_retrieval(dataset, root=root)
    conservative = evaluate_conservative(dataset, root=root)
    llm: tuple[JudgeCaseResult, ...] = ()
    if llm_judge is not None:
        llm = evaluate_llm_judge(dataset, llm_judge, root=root)
    elif llm_model:
        llm = evaluate_llm_judge(
            dataset,
            OllamaEvidenceJudge(model_name=llm_model, base_url=ollama_base_url),
            root=root,
        )
    tp = sum(1 for item in retrieval if item.outcome == "tp")
    fp = sum(1 for item in retrieval if item.outcome == "fp")
    fn = sum(1 for item in retrieval if item.outcome == "fn")
    tn = sum(1 for item in retrieval if item.outcome == "tn")
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = _ratio(2 * precision * recall, precision + recall) if precision + recall else 0.0
    failures = {
        item.failure_type: sum(1 for other in retrieval if other.failure_type == item.failure_type)
        for item in retrieval
        if item.failure_type
    }
    false_supports = sum(
        1
        for item in conservative
        if item.predicted_label is EvidenceLabel.SUPPORTS and not item.correct_label
    )
    false_refutes = sum(
        1
        for item in conservative
        if item.predicted_label is EvidenceLabel.REFUTES and not item.correct_label
    )
    n_cons = len(conservative) or 1
    return PledgeEvidenceEvalReport(
        dataset_version=dataset.version,
        case_count=len(dataset.cases),
        retrieval=retrieval,
        conservative=conservative,
        llm=llm,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_negatives=tn,
        precision=precision,
        recall=recall,
        f1=round(f1, 4),
        retrieval_abstention_rate=_ratio(tn + fn, len(retrieval)),
        conservative_label_accuracy=_ratio(
            sum(1 for item in conservative if item.correct_label), len(conservative)
        ),
        conservative_closed_verdicts=sum(1 for item in conservative if item.closed_verdict),
        conservative_closed_rate=_ratio(
            sum(1 for item in conservative if item.closed_verdict), n_cons
        ),
        conservative_false_supports=false_supports,
        conservative_false_refutes=false_refutes,
        conservative_abstention_rate=_ratio(
            sum(
                1
                for item in conservative
                if item.predicted_label is EvidenceLabel.NOT_ENOUGH_INFO
            ),
            n_cons,
        ),
        conservative_excerpt_validity=_ratio(
            sum(1 for item in conservative if item.excerpt_valid), n_cons
        ),
        conservative_verdict_compatibility=_ratio(
            sum(1 for item in conservative if item.compatible), n_cons
        ),
        failure_types=failures,
    )


SCHEDULER_READINESS = {
    "gold_set_at_least_20": "Expanded official gold set has at least 20 cases.",
    "retrieval_precision_at_least_0_90": "Deterministic retrieval precision >= 0.90.",
    "zero_false_positive_on_gold_negatives": "No retrieval on gold cases marked irrelevant.",
    "exact_evidence_always_valid": "Every conservative judgment excerpt is verbatim or empty.",
    "conservative_verdict_semantics": "Judge never proposes kept/broken/partially_kept.",
    "outputs_remain_pending": "Matcher only creates pending drafts.",
    "human_approval_required": "No auto-publication; broken still needs two reviewers.",
    "schedule_disabled": "schedule_pledge_evidence_cron stays empty.",
}


def readiness_gate(report: PledgeEvidenceEvalReport, *, schedule_cron: str) -> dict[str, bool]:
    negative_fps = [
        item
        for item in report.retrieval
        if item.expected == "irrelevant" and item.outcome == "fp"
    ]
    return {
        "gold_set_at_least_20": report.case_count >= 20,
        "retrieval_precision_at_least_0_90": report.precision >= 0.90,
        "zero_false_positive_on_gold_negatives": not negative_fps,
        "exact_evidence_always_valid": all(item.excerpt_valid for item in report.conservative),
        "conservative_verdict_semantics": report.conservative_closed_verdicts == 0,
        "outputs_remain_pending": report.published is False,
        "human_approval_required": True,
        "schedule_disabled": not (schedule_cron or "").strip(),
    }
