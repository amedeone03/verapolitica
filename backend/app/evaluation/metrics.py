import re
import unicodedata
from collections import defaultdict
from decimal import Decimal

from backend.app.pipeline.document_chunking import DocumentChunkData
from backend.app.schemas.ai_evaluation import (
    CaseMetricCounts,
    ClaimMatch,
    ClassMetrics,
    EvaluationCaseResult,
    EvaluationCaseStatus,
    EvaluationMetrics,
    GoldClaim,
    GoldExtractionCase,
)
from backend.app.schemas.ai_extraction import ExtractedPoliticalClaim


def normalize_evaluation_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip().casefold()


def _actor_set(items) -> set[tuple[str, str]]:
    return {
        (normalize_evaluation_text(item.name), item.role.value)
        for item in items
    }


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _f1(precision: float, recall: float) -> float:
    return (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )


def extract_numeric_commitments(statement: str) -> set[tuple[str, str]]:
    values: set[tuple[str, str]] = set()
    month_names = {
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
        "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
    }
    for raw_value, unit in re.findall(
        r"\b(\d+(?:[.,]\d+)?)\s+([^\W\d_]+)\b",
        unicodedata.normalize("NFC", statement),
    ):
        normalized_value = raw_value.replace(",", ".")
        value = Decimal(normalized_value)
        if value == value.to_integral():
            normalized_value = str(int(value))
        else:
            normalized_value = format(value.normalize(), "f")
        if (
            normalized_value.isdigit()
            and 1900 <= int(normalized_value) <= 2100
        ):
            continue
        normalized_unit = normalize_evaluation_text(unit)
        if normalized_unit in month_names:
            continue
        values.add((normalized_value, normalized_unit))
    return values


def match_claims(
    predictions: tuple[ExtractedPoliticalClaim, ...],
    gold_claims: tuple[GoldClaim, ...],
) -> tuple[tuple[ClaimMatch, ...], dict[int, GoldClaim]]:
    non_abstaining = [
        (index, claim)
        for index, claim in enumerate(predictions)
        if claim.abstention_reason is None
    ]
    remaining = {claim.claim_id: claim for claim in gold_claims}
    matches: list[ClaimMatch] = []
    matched: dict[int, GoldClaim] = {}
    deferred: list[tuple[int, ExtractedPoliticalClaim]] = []

    for index, prediction in non_abstaining:
        statement = normalize_evaluation_text(prediction.exact_statement or "")
        candidates = [
            claim
            for claim in remaining.values()
            if normalize_evaluation_text(claim.exact_statement) == statement
        ]
        if len(candidates) == 1:
            claim = candidates[0]
            matched[index] = claim
            remaining.pop(claim.claim_id)
            matches.append(
                ClaimMatch(
                    prediction_index=index,
                    gold_claim_id=claim.claim_id,
                    method="exact_statement",
                )
            )
        elif len(candidates) > 1:
            matches.append(
                ClaimMatch(
                    prediction_index=index,
                    method="ambiguous",
                    ambiguous_gold_claim_ids=tuple(
                        sorted(claim.claim_id for claim in candidates)
                    ),
                )
            )
        else:
            deferred.append((index, prediction))

    for index, prediction in deferred:
        candidates = [
            claim
            for claim in remaining.values()
            if (
                normalize_evaluation_text(claim.normalized_title)
                == normalize_evaluation_text(prediction.normalized_title or "")
                and _actor_set(claim.actors) == _actor_set(prediction.actor_mentions)
                and prediction.claim_type == claim.claim_type
            )
        ]
        if len(candidates) == 1:
            claim = candidates[0]
            matched[index] = claim
            remaining.pop(claim.claim_id)
            matches.append(
                ClaimMatch(
                    prediction_index=index,
                    gold_claim_id=claim.claim_id,
                    method="title_actor_type",
                )
            )
        elif len(candidates) > 1:
            matches.append(
                ClaimMatch(
                    prediction_index=index,
                    method="ambiguous",
                    ambiguous_gold_claim_ids=tuple(
                        sorted(claim.claim_id for claim in candidates)
                    ),
                )
            )
        else:
            matches.append(
                ClaimMatch(prediction_index=index, method="unmatched")
            )
    return tuple(sorted(matches, key=lambda item: item.prediction_index)), matched


def _evidence_correct(
    prediction: ExtractedPoliticalClaim,
    gold: GoldClaim,
    chunks: dict[int, DocumentChunkData],
) -> tuple[bool, str | None]:
    if not prediction.evidence:
        return False, "missing evidence"
    for item in prediction.evidence:
        chunk = chunks.get(item.chunk_index)
        if chunk is None:
            return False, f"missing chunk {item.chunk_index}"
        if item.page is not None and not (
            chunk.page_start is not None
            and chunk.page_end is not None
            and chunk.page_start <= item.page <= chunk.page_end
        ):
            return False, f"wrong page {item.page}"
        excerpt = normalize_evaluation_text(item.supporting_text)
        if excerpt not in normalize_evaluation_text(chunk.text):
            return False, "excerpt absent from chunk"
    for expected in gold.evidence:
        expected_text = normalize_evaluation_text(expected.supporting_text)
        if not any(
            item.chunk_index == expected.chunk_index
            and (expected.page is None or item.page == expected.page)
            and (
                expected_text in normalize_evaluation_text(item.supporting_text)
                or normalize_evaluation_text(item.supporting_text) in expected_text
            )
            for item in prediction.evidence
        ):
            return False, f"expected evidence missing for chunk {expected.chunk_index}"
    return True, None


def score_case(
    case: GoldExtractionCase,
    predictions: tuple[ExtractedPoliticalClaim, ...],
    chunks: tuple[DocumentChunkData, ...],
    *,
    status: EvaluationCaseStatus = EvaluationCaseStatus.COMPLETED,
    error: str | None = None,
) -> EvaluationCaseResult:
    matches, matched = match_claims(predictions, case.claims)
    non_abstaining_indexes = {
        index
        for index, prediction in enumerate(predictions)
        if prediction.abstention_reason is None
    }
    matched_indexes = set(matched)
    false_positive_indexes = tuple(sorted(non_abstaining_indexes - matched_indexes))
    matched_gold_ids = {claim.claim_id for claim in matched.values()}
    false_negative_ids = tuple(
        claim.claim_id
        for claim in case.claims
        if claim.claim_id not in matched_gold_ids
    )
    type_errors: list[str] = []
    evidence_errors: list[str] = []
    actor_errors: list[str] = []
    topic_errors: list[str] = []
    type_correct = evidence_correct_count = evidence_wrong = evidence_missing = 0
    actor_tp = actor_fp = actor_fn = topic_correct = topic_total = 0
    date_correct = date_total = numeric_correct = numeric_total = 0
    unsupported = len(false_positive_indexes)
    chunk_map = {chunk.chunk_index: chunk for chunk in chunks}

    for index, gold in matched.items():
        prediction = predictions[index]
        if prediction.claim_type == gold.claim_type:
            type_correct += 1
        else:
            type_errors.append(
                f"{gold.claim_id}: expected {gold.claim_type.value}, "
                f"predicted {prediction.claim_type.value if prediction.claim_type else 'missing'}"
            )
        grounded, evidence_error = _evidence_correct(prediction, gold, chunk_map)
        if grounded:
            evidence_correct_count += 1
        elif not prediction.evidence:
            evidence_missing += 1
            evidence_errors.append(f"{gold.claim_id}: missing evidence")
            unsupported += 1
        else:
            evidence_wrong += 1
            evidence_errors.append(f"{gold.claim_id}: {evidence_error}")
            unsupported += 1
        expected_actors = _actor_set(gold.actors)
        predicted_actors = _actor_set(prediction.actor_mentions)
        actor_tp += len(expected_actors & predicted_actors)
        actor_fp += len(predicted_actors - expected_actors)
        actor_fn += len(expected_actors - predicted_actors)
        if expected_actors != predicted_actors:
            actor_errors.append(f"{gold.claim_id}: actor set differs")
        if gold.topic is not None:
            topic_total += 1
            if prediction.topic == gold.topic:
                topic_correct += 1
            else:
                topic_errors.append(f"{gold.claim_id}: topic differs")
        for expected, predicted in (
            (gold.announced_at, prediction.announced_at),
            (gold.target_date, prediction.target_date),
        ):
            if expected is not None:
                date_total += 1
                date_correct += int(expected == predicted)
        if gold.numeric_commitments:
            numeric_total += 1
            expected_numeric = {
                (item.value, normalize_evaluation_text(item.unit))
                for item in gold.numeric_commitments
            }
            numeric_correct += int(
                extract_numeric_commitments(prediction.exact_statement or "")
                == expected_numeric
            )

    predicted_abstention = (
        not non_abstaining_indexes
        and (
            not predictions
            or any(item.abstention_reason is not None for item in predictions)
        )
    )
    counts = CaseMetricCounts(
        true_positives=len(matched),
        false_positives=len(false_positive_indexes),
        false_negatives=len(false_negative_ids),
        type_correct=type_correct,
        type_total=len(matched),
        evidence_correct=evidence_correct_count,
        evidence_wrong=evidence_wrong,
        evidence_missing=evidence_missing,
        actor_true_positives=actor_tp,
        actor_false_positives=actor_fp,
        actor_false_negatives=actor_fn,
        topic_correct=topic_correct,
        topic_total=topic_total,
        date_correct=date_correct,
        date_total=date_total,
        numeric_correct=numeric_correct,
        numeric_total=numeric_total,
        unsupported_predictions=unsupported,
    )
    return EvaluationCaseResult(
        case_id=case.case_id,
        status=status,
        expected_claims=case.claims,
        predicted_claims=predictions,
        matches=matches,
        false_positive_indexes=false_positive_indexes,
        false_negative_claim_ids=false_negative_ids,
        claim_type_errors=tuple(type_errors),
        evidence_errors=tuple(evidence_errors),
        actor_errors=tuple(actor_errors),
        topic_errors=tuple(topic_errors),
        predicted_abstention=predicted_abstention,
        abstention_correct=predicted_abstention == case.expects_abstention,
        counts=counts,
        error=error,
    )


def aggregate_metrics(
    cases: tuple[GoldExtractionCase, ...],
    results: tuple[EvaluationCaseResult, ...],
) -> EvaluationMetrics:
    totals = defaultdict(int)
    case_by_id = {case.case_id: case for case in cases}
    type_counts = {
        "proposal": defaultdict(int),
        "explicit_promise": defaultdict(int),
    }
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    topic_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"expected": 0, "correct": 0}
    )
    date_fields = {
        "announced_at": {"correct": 0, "total": 0},
        "target_date": {"correct": 0, "total": 0},
    }
    predicted_abstentions = expected_abstentions = correct_abstentions = 0
    inappropriate_claims = 0
    total_predictions = 0

    for result in results:
        for field in type(result.counts).model_fields:
            totals[field] += getattr(result.counts, field)
        case = case_by_id[result.case_id]
        predicted_abstentions += int(result.predicted_abstention)
        expected_abstentions += int(case.expects_abstention)
        correct_abstentions += int(
            case.expects_abstention and result.predicted_abstention
        )
        if case.expects_abstention:
            inappropriate_claims += result.counts.false_positives
        total_predictions += sum(
            item.abstention_reason is None for item in result.predicted_claims
        )
        matched_by_index = {
            item.prediction_index: item.gold_claim_id
            for item in result.matches
            if item.gold_claim_id is not None
        }
        gold_by_id = {claim.claim_id: claim for claim in case.claims}
        for gold_claim in case.claims:
            if gold_claim.topic is not None:
                topic_counts[gold_claim.topic.value]["expected"] += 1
        for index, prediction in enumerate(result.predicted_claims):
            if prediction.abstention_reason is not None:
                continue
            gold_id = matched_by_index.get(index)
            predicted_type = prediction.claim_type.value
            if gold_id is None:
                type_counts[predicted_type]["fp"] += 1
                confusion["__spurious__"][predicted_type] += 1
                continue
            expected_type = gold_by_id[gold_id].claim_type.value
            matched_gold = gold_by_id[gold_id]
            confusion[expected_type][predicted_type] += 1
            if expected_type == predicted_type:
                type_counts[expected_type]["tp"] += 1
            else:
                type_counts[predicted_type]["fp"] += 1
                type_counts[expected_type]["fn"] += 1
            if matched_gold.topic is not None:
                topic = matched_gold.topic.value
                topic_counts[topic]["correct"] += int(
                    prediction.topic == matched_gold.topic
                )
            for field_name in ("announced_at", "target_date"):
                expected_date = getattr(matched_gold, field_name)
                if expected_date is not None:
                    date_fields[field_name]["total"] += 1
                    date_fields[field_name]["correct"] += int(
                        getattr(prediction, field_name) == expected_date
                    )
        for claim_id in result.false_negative_claim_ids:
            expected_type = gold_by_id[claim_id].claim_type.value
            type_counts[expected_type]["fn"] += 1
            confusion[expected_type]["__missing__"] += 1

    precision = _ratio(totals["true_positives"], totals["true_positives"] + totals["false_positives"])
    recall = _ratio(totals["true_positives"], totals["true_positives"] + totals["false_negatives"])
    actor_precision = _ratio(
        totals["actor_true_positives"],
        totals["actor_true_positives"] + totals["actor_false_positives"],
    )
    actor_recall = _ratio(
        totals["actor_true_positives"],
        totals["actor_true_positives"] + totals["actor_false_negatives"],
    )
    class_metrics = {}
    for claim_type, values in type_counts.items():
        class_precision = _ratio(values["tp"], values["tp"] + values["fp"])
        class_recall = _ratio(values["tp"], values["tp"] + values["fn"])
        class_metrics[claim_type] = ClassMetrics(
            true_positives=values["tp"],
            false_positives=values["fp"],
            false_negatives=values["fn"],
            precision=class_precision,
            recall=class_recall,
            f1=_f1(class_precision, class_recall),
        )
    failed_cases = sum(
        result.status is not EvaluationCaseStatus.COMPLETED for result in results
    )
    return EvaluationMetrics(
        true_positives=totals["true_positives"],
        false_positives=totals["false_positives"],
        false_negatives=totals["false_negatives"],
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        claim_type_accuracy=_ratio(totals["type_correct"], totals["type_total"]),
        claim_type_metrics=class_metrics,
        claim_type_confusion={
            expected: dict(predicted)
            for expected, predicted in confusion.items()
        },
        evidence_accuracy=_ratio(
            totals["evidence_correct"],
            totals["evidence_correct"]
            + totals["evidence_wrong"]
            + totals["evidence_missing"],
        ),
        grounded_correctly=totals["evidence_correct"],
        wrong_evidence=totals["evidence_wrong"],
        missing_evidence=totals["evidence_missing"],
        actor_precision=actor_precision,
        actor_recall=actor_recall,
        actor_f1=_f1(actor_precision, actor_recall),
        topic_accuracy=_ratio(totals["topic_correct"], totals["topic_total"]),
        topic_counts=dict(topic_counts),
        date_accuracy=_ratio(totals["date_correct"], totals["date_total"]),
        date_field_accuracy={
            name: _ratio(values["correct"], values["total"])
            for name, values in date_fields.items()
        },
        numeric_accuracy=_ratio(totals["numeric_correct"], totals["numeric_total"]),
        abstention_accuracy=_ratio(
            sum(result.abstention_correct for result in results), len(results)
        ),
        abstention_precision=_ratio(correct_abstentions, predicted_abstentions),
        abstention_recall=_ratio(correct_abstentions, expected_abstentions),
        correct_abstentions=correct_abstentions,
        incorrect_abstentions=predicted_abstentions - correct_abstentions,
        missed_abstentions=expected_abstentions - correct_abstentions,
        inappropriate_claim_generations=inappropriate_claims,
        hallucination_rate=(
            totals["unsupported_predictions"] / total_predictions
            if total_predictions
            else 0.0
        ),
        failed_cases=failed_cases,
    )
