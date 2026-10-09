"""Deterministic official-evidence retrieval and fail-closed extra validation.

This layer never publishes a verdict. It only decides whether a stored passage
is an admissible *candidate* and whether a judge output may become a draft.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlsplit

from backend.app.core.text import normalize_search_text
from backend.app.scoring.evidence_matching import (
    Passage,
    excerpt_is_verbatim,
    retrieve,
    validate_judgment,
)
from backend.app.scoring.official_sources import classify_source_url
from backend.app.scoring.retrieval_profile import RetrievalProfile
from backend.app.scoring.types import EvidenceLabel, FulfillmentVerdict, VERDICTS_BY_EVIDENCE_LABEL


MATCHER_VERSION = "pledge-evidence/v2"
MIN_INSTRUMENT_HITS = 1
MIN_DETERMINISTIC_SCORE = 1.5


@dataclass(frozen=True, slots=True)
class OfficialPassage:
    passage: Passage
    source_id: int
    source_key: str
    source_name: str
    retrieved_at: datetime | None
    published_at: date | None


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    proposal_id: int
    source_id: int
    raw_document_id: int
    document_chunk_id: int
    source_url: str
    source_title: str
    published_at: date | None
    retrieved_at: datetime | None
    exact_excerpt: str
    retrieval_reason: str
    deterministic_score: float
    lexical_rank: int | None
    instrument_hits: tuple[str, ...]
    topic_hits: tuple[str, ...]


def normalize_url(url: str) -> str:
    return urlsplit(url)._replace(fragment="").geturl().rstrip("/")


def is_origin_document(passage: OfficialPassage, profile: RetrievalProfile) -> bool:
    if passage.passage.raw_document_id in profile.origin_document_ids:
        return True
    url = normalize_url(passage.passage.source_url)
    return url in {normalize_url(item) for item in profile.origin_urls}


def document_date(passage: OfficialPassage) -> date | None:
    if passage.published_at is not None:
        return passage.published_at
    if passage.retrieved_at is not None:
        return passage.retrieved_at.date()
    return None


def date_is_usable(passage: OfficialPassage, profile: RetrievalProfile) -> bool:
    observed = document_date(passage)
    start = profile.earliest_evidence_date
    if observed is None or start is None:
        return True
    if observed < start:
        return False
    if profile.mandate_end is not None and observed > profile.mandate_end:
        return False
    return True


def _hits(phrases: tuple[str, ...], text: str) -> tuple[str, ...]:
    blob = normalize_search_text(text)
    words = set(blob.split())
    matched: list[str] = []
    for phrase in phrases:
        norm = normalize_search_text(phrase)
        if not norm:
            continue
        if " " in norm:
            if norm in blob:
                matched.append(phrase)
            continue
        if len(norm) >= 8 and norm in words:
            matched.append(phrase)
    return tuple(matched)


def instrument_hits(profile: RetrievalProfile, text: str) -> tuple[str, ...]:
    return _hits(profile.instrument_phrases, text)


def topic_hits(profile: RetrievalProfile, text: str) -> tuple[str, ...]:
    return _hits(profile.topic_terms, text)


def deterministic_score(
    profile: RetrievalProfile, text: str, *, lexical_score: float = 0.0
) -> float:
    instruments = instrument_hits(profile, text)
    topics = topic_hits(profile, text)
    return round(3.0 * len(instruments) + 0.5 * len(topics) + min(lexical_score, 2.0), 4)


def excerpt_window(text: str, phrases: tuple[str, ...], *, limit: int = 400) -> str:
    collapsed = " ".join(text.split())
    blob = normalize_search_text(collapsed)
    for phrase in phrases:
        needle = normalize_search_text(phrase)
        index = blob.find(needle)
        if index < 0:
            continue
        start = max(0, collapsed.lower().find(phrase.split()[0][:4].lower()) )
        snippet = collapsed[start : start + limit]
        if snippet:
            return snippet
    return collapsed[:limit]


def filter_official_passages(
    passages: list[OfficialPassage], profile: RetrievalProfile
) -> tuple[list[OfficialPassage], dict[str, int]]:
    reasons: dict[str, int] = {}
    kept: list[OfficialPassage] = []
    for passage in passages:
        decision = classify_source_url(passage.passage.source_url)
        if not decision.official:
            reasons[decision.reason] = reasons.get(decision.reason, 0) + 1
            continue
        if is_origin_document(passage, profile):
            reasons["origin_document"] = reasons.get("origin_document", 0) + 1
            continue
        if not date_is_usable(passage, profile):
            reasons["outside_date_window"] = reasons.get("outside_date_window", 0) + 1
            continue
        if len(instrument_hits(profile, passage.passage.text)) < MIN_INSTRUMENT_HITS:
            reasons["missing_instrument_overlap"] = reasons.get(
                "missing_instrument_overlap", 0
            ) + 1
            continue
        kept.append(passage)
    return kept, reasons


def retrieve_official_candidates(
    profile: RetrievalProfile,
    passages: list[OfficialPassage],
    *,
    limit: int = 5,
) -> tuple[list[EvidenceCandidate], dict[str, int]]:
    usable, reasons = filter_official_passages(passages, profile)
    if not usable:
        return [], reasons
    ranked = retrieve(
        profile.query,
        [item.passage for item in usable],
        limit=limit,
    )
    by_id = {item.passage.passage_id: item for item in usable}
    candidates: list[EvidenceCandidate] = []
    for item in ranked:
        official = by_id[item.passage.passage_id]
        instruments = instrument_hits(profile, item.passage.text)
        score = deterministic_score(profile, item.passage.text, lexical_score=item.score)
        if score < MIN_DETERMINISTIC_SCORE:
            reasons["low_deterministic_score"] = reasons.get("low_deterministic_score", 0) + 1
            continue
        candidates.append(
            EvidenceCandidate(
                proposal_id=profile.proposal_id,
                source_id=official.source_id,
                raw_document_id=item.passage.raw_document_id,
                document_chunk_id=item.passage.passage_id,
                source_url=item.passage.source_url,
                source_title=official.source_name,
                published_at=official.published_at,
                retrieved_at=official.retrieved_at,
                exact_excerpt=excerpt_window(item.passage.text, instruments),
                retrieval_reason="official_instrument_and_date_match",
                deterministic_score=score,
                lexical_rank=item.lexical_rank,
                instrument_hits=instruments,
                topic_hits=topic_hits(profile, item.passage.text),
            )
        )
    return candidates, reasons


def actor_or_institution_plausible(profile: RetrievalProfile, text: str) -> bool:
    blob = normalize_search_text(text)
    if "governo" in blob or "stato" in blob or "legge" in blob or "decreto" in blob:
        return True
    for name in profile.actor_names:
        if normalize_search_text(name) and normalize_search_text(name) in blob:
            return True
    return bool(instrument_hits(profile, text))


def validate_official_judgment(
    judgment,
    passage_text: str,
    *,
    source_url: str,
    profile: RetrievalProfile,
    published_at: date | None,
    is_origin: bool,
) -> str | None:
    """Return a rejection reason. Never rewrites the judgment."""

    base = validate_judgment(judgment, passage_text)
    if base is not None:
        return base
    decision = classify_source_url(source_url)
    if not decision.official:
        return decision.reason
    if is_origin:
        return "origin_document"
    if published_at is not None and profile.earliest_evidence_date is not None:
        if published_at < profile.earliest_evidence_date:
            return "outside_date_window"
    if len(instrument_hits(profile, passage_text)) < MIN_INSTRUMENT_HITS:
        return "missing_instrument_overlap"
    if judgment.label is not EvidenceLabel.NOT_ENOUGH_INFO:
        if judgment.proposed_verdict not in VERDICTS_BY_EVIDENCE_LABEL[judgment.label]:
            return "verdict_incompatible_with_label"
        if not excerpt_is_verbatim(passage_text, judgment.quoted_excerpt):
            return "excerpt_not_found_in_source"
        if not actor_or_institution_plausible(profile, judgment.quoted_excerpt):
            return "actor_topic_not_plausible"
        if judgment.label is EvidenceLabel.SUPPORTS and judgment.proposed_verdict is FulfillmentVerdict.KEPT:
            # Announcement language in the excerpt is not fulfilment.
            lowered = normalize_search_text(judgment.quoted_excerpt)
            if "intendiamo" in lowered or "vogliamo" in lowered:
                return "announcement_is_not_fulfilment"
    return None
