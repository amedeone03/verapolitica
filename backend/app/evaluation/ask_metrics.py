"""Score Ask VeraPolitica answers against gold cases. No prose sentence matching."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlsplit

from backend.app.evaluation.ask_dataset import AskGoldCase
from backend.app.evaluation.ask_fixture import AskEvalCatalog
from backend.app.schemas.ask import AskResponse
from backend.app.scoring.public_presentation import public_verdict_label
from backend.app.services.ask_verapolitica_service import UNRATED_MESSAGE, UNSUPPORTED_ANSWER
from backend.app.services.pledge_explanation_service import UNRATED_MESSAGE as EXPLAIN_UNRATED


_HTTP_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class AskCaseScore:
    case_id: str
    category: str
    passed: bool
    reasons: tuple[str, ...]
    intent_ok: bool | None = None
    politician_ok: bool | None = None
    topic_ok: bool | None = None
    verdict_ok: bool | None = None
    source_ok: bool | None = None
    abstention_ok: bool | None = None
    clarification_ok: bool | None = None
    zero_result_ok: bool | None = None
    pledge_tp: int = 0
    pledge_fp: int = 0
    pledge_fn: int = 0
    forbidden_claim_hits: int = 0
    invented_url_hits: int = 0


@dataclass(frozen=True, slots=True)
class AskEvalReport:
    dataset_version: str
    total: int
    passed: int
    failed: int
    metrics: dict[str, float]
    category_totals: dict[str, dict[str, int]]
    failures: tuple[tuple[str, str], ...]
    case_scores: tuple[AskCaseScore, ...]
    mode: str


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _pledge_result_ids(response: AskResponse | None) -> set[int]:
    if response is None:
        return set()
    return {item.id for item in response.results if item.type == "pledge"}


def _result_verdicts(response: AskResponse | None) -> set[str]:
    if response is None:
        return set()
    return {item.verdict.value for item in response.results if item.verdict is not None}


def _urls_in_payload(response: AskResponse | None) -> set[str]:
    found: set[str] = set()
    if response is None:
        return found
    for match in _HTTP_URL.findall(response.answer):
        found.add(match.rstrip(".,);"))
    for source in response.sources:
        found.add(source.url)
    return found


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").casefold()


def score_ask_case(
    case: AskGoldCase,
    catalog: AskEvalCatalog,
    *,
    response: AskResponse | None,
    invalid: bool = False,
) -> AskCaseScore:
    reasons: list[str] = []
    intent_ok: bool | None = None
    politician_ok: bool | None = None
    topic_ok: bool | None = None
    verdict_ok: bool | None = None
    source_ok: bool | None = None
    abstention_ok: bool | None = None
    clarification_ok: bool | None = None
    zero_result_ok: bool | None = None
    tp = fp = fn = 0

    if case.expect_invalid:
        if not invalid:
            reasons.append("expected invalid request")
        return AskCaseScore(
            case_id=case.id,
            category=case.category,
            passed=not reasons,
            reasons=tuple(reasons),
        )

    if invalid or response is None:
        reasons.append("request failed unexpectedly")
        return AskCaseScore(
            case_id=case.id,
            category=case.category,
            passed=False,
            reasons=tuple(reasons),
        )

    answer = response.answer
    lowered = answer.casefold()

    if case.expected_intent is not None:
        intent_ok = response.intent == case.expected_intent
        if not intent_ok:
            reasons.append(f"intent {response.intent!r} != {case.expected_intent!r}")

    if case.should_abstain:
        abstention_ok = (
            response.intent == "unsupported" or answer == UNSUPPORTED_ANSWER
        )
        if not abstention_ok:
            reasons.append("expected bounded unsupported abstention")

    if case.should_require_clarification:
        titles = {item.title for item in response.results}
        expected_names = set(catalog.clarification_names)
        if not expected_names:
            expected_names = {
                catalog.politician_names[key]
                for key in ("mario-rossi", "anna-rossi")
                if key in catalog.politician_names
            }
        clarification_ok = (
            "precisa" in lowered
            and bool(response.results)
            and all(item.type == "politician" for item in response.results)
        )
        if expected_names:
            clarification_ok = bool(clarification_ok and expected_names <= titles)
        if not clarification_ok:
            reasons.append("expected identity clarification, not a guessed politician")

    expected_name = case.expected_politician_name
    if case.expected_politician_key and case.expected_politician_key in catalog.politician_names:
        expected_name = catalog.politician_names[case.expected_politician_key]
    if expected_name and not case.should_require_clarification:
        politician_ok = response.entities.get("politician") == expected_name
        if not politician_ok:
            reasons.append(
                f"politician {response.entities.get('politician')!r} != {expected_name!r}"
            )

    if case.expected_topic is not None:
        topic_ok = response.entities.get("topic") == case.expected_topic
        if not topic_ok:
            reasons.append(
                f"topic {response.entities.get('topic')!r} != {case.expected_topic!r}"
            )

    retrieved = _pledge_result_ids(response)
    expects_empty = case.expect_zero_results or (
        case.expected_pledge_keys is not None and len(case.expected_pledge_keys) == 0
    )
    if expects_empty:
        zero_result_ok = not retrieved
        if not zero_result_ok:
            reasons.append("expected zero pledge results")

    if case.expected_pledge_keys is not None:
        missing = [key for key in case.expected_pledge_keys if key not in catalog.pledge_ids]
        if missing:
            reasons.append(f"unresolved pledge keys {missing!r}")
        else:
            expected_ids = {catalog.pledge_ids[key] for key in case.expected_pledge_keys}
            tp = len(expected_ids & retrieved)
            fp = len(retrieved - expected_ids)
            fn = len(expected_ids - retrieved)
            if fp or fn:
                reasons.append(f"pledge retrieval tp={tp} fp={fp} fn={fn}")

    if case.expected_count is not None and len(retrieved) != case.expected_count:
        reasons.append(f"count {len(retrieved)} != {case.expected_count}")

    if case.expected_verdict is not None:
        result_verdicts = _result_verdicts(response)
        entity_verdict = response.entities.get("verdict")
        if expects_empty:
            verdict_ok = not result_verdicts or result_verdicts <= {case.expected_verdict}
        elif case.expected_pledge_keys:
            ids = {
                catalog.pledge_ids[key]
                for key in case.expected_pledge_keys
                if key in catalog.pledge_ids
            }
            matched = [
                item.verdict.value
                for item in response.results
                if item.type == "pledge" and item.id in ids and item.verdict is not None
            ]
            verdict_ok = bool(matched) and all(value == case.expected_verdict for value in matched)
        else:
            verdict_ok = case.expected_verdict in result_verdicts or entity_verdict == case.expected_verdict
        if not verdict_ok:
            reasons.append(f"published verdict {case.expected_verdict!r} not preserved")

    if case.expect_unrated:
        unrated_ok = (
            answer in {UNRATED_MESSAGE, EXPLAIN_UNRATED}
            or "non ha ancora pubblicato una valutazione" in lowered
            or "not_yet_rated" in _result_verdicts(response)
        )
        if response.sources:
            unrated_ok = False
        if not unrated_ok:
            reasons.append("expected no published evaluation")
        public_kept = public_verdict_label("kept")
        if public_kept.casefold() in lowered and "non ancora" not in lowered:
            reasons.append("invented a published verdict")

    if case.expected_source_url is not None:
        urls = {source.url for source in response.sources}
        source_ok = case.expected_source_url in urls
        if not source_ok:
            reasons.append("missing expected source URL")

    if case.expected_source_host is not None:
        hosts = {_host(source.url) for source in response.sources}
        host_ok = case.expected_source_host.casefold() in hosts
        source_ok = host_ok if source_ok is None else (source_ok and host_ok)
        if not host_ok:
            reasons.append(f"missing source host {case.expected_source_host!r}")

    forbidden_hits = 0
    for claim in case.forbidden_claims:
        if claim.casefold() in lowered:
            forbidden_hits += 1
            reasons.append(f"forbidden claim {claim!r}")

    for verdict in case.forbidden_verdicts:
        if verdict in _result_verdicts(response):
            forbidden_hits += 1
            reasons.append(f"forbidden result verdict {verdict!r}")

    for title in (*case.forbidden_titles, *catalog.unpublished_titles):
        if title.casefold() in lowered or any(
            item.title == title for item in response.results
        ):
            forbidden_hits += 1
            reasons.append(f"unpublished title leaked: {title!r}")

    allowed_urls = set(catalog.published_source_urls)
    invented = 0
    for url in _urls_in_payload(response):
        if url not in allowed_urls and not any(allowed in url for allowed in allowed_urls):
            invented += 1
            reasons.append(f"invented URL {url}")

    return AskCaseScore(
        case_id=case.id,
        category=case.category,
        passed=not reasons,
        reasons=tuple(reasons),
        intent_ok=intent_ok,
        politician_ok=politician_ok,
        topic_ok=topic_ok,
        verdict_ok=verdict_ok,
        source_ok=source_ok,
        abstention_ok=abstention_ok,
        clarification_ok=clarification_ok,
        zero_result_ok=zero_result_ok,
        pledge_tp=tp,
        pledge_fp=fp,
        pledge_fn=fn,
        forbidden_claim_hits=forbidden_hits,
        invented_url_hits=invented,
    )


def aggregate_ask_scores(
    dataset_version: str,
    scores: tuple[AskCaseScore, ...],
    *,
    mode: str,
) -> AskEvalReport:
    passed = sum(1 for item in scores if item.passed)
    category_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
    for item in scores:
        bucket = category_totals[item.category]
        bucket["total"] += 1
        bucket["passed" if item.passed else "failed"] += 1

    def _flag_rate(attr: str) -> float:
        values = [getattr(item, attr) for item in scores if getattr(item, attr) is not None]
        return _ratio(sum(1 for value in values if value), len(values))

    tp = sum(item.pledge_tp for item in scores)
    fp = sum(item.pledge_fp for item in scores)
    fn = sum(item.pledge_fn for item in scores)
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    forbidden = sum(item.forbidden_claim_hits for item in scores)
    invented = sum(item.invented_url_hits for item in scores)
    scored = len(scores)
    metrics = {
        "pass_rate": _ratio(passed, scored),
        "intent_accuracy": _flag_rate("intent_ok"),
        "politician_accuracy": _flag_rate("politician_ok"),
        "pledge_precision": precision,
        "pledge_recall": recall,
        "pledge_f1": _f1(precision, recall),
        "verdict_consistency": _flag_rate("verdict_ok"),
        "topic_accuracy": _flag_rate("topic_ok"),
        "source_accuracy": _flag_rate("source_ok"),
        "abstention_accuracy": _flag_rate("abstention_ok"),
        "clarification_accuracy": _flag_rate("clarification_ok"),
        "unsupported_query_accuracy": _flag_rate("abstention_ok"),
        "zero_result_precision": _flag_rate("zero_result_ok"),
        "forbidden_claim_rate": _ratio(forbidden, scored),
        "invented_url_rate": _ratio(invented, scored),
    }
    failures = tuple(
        (item.case_id, "; ".join(item.reasons) or "failed")
        for item in scores
        if not item.passed
    )
    return AskEvalReport(
        dataset_version=dataset_version,
        total=scored,
        passed=passed,
        failed=scored - passed,
        metrics=metrics,
        category_totals={key: dict(value) for key, value in sorted(category_totals.items())},
        failures=failures,
        case_scores=scores,
        mode=mode,
    )


def report_to_dict(report: AskEvalReport) -> dict[str, object]:
    return {
        "dataset_version": report.dataset_version,
        "mode": report.mode,
        "disclaimer": (
            "These metrics describe performance on this curated gold set only. "
            "They are not a universal accuracy claim for Ask VeraPolitica."
        ),
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "metrics": report.metrics,
        "category_totals": report.category_totals,
        "failures": [{"id": case_id, "reason": reason} for case_id, reason in report.failures],
    }
