"""Deterministic v1 planner for Ask VeraPolitica.

Parses Italian (and a few English synonyms) into a constrained intent. It does
not call an LLM and does not search the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from backend.app.core.text import normalize_search_text, search_tokens
from backend.app.scoring.public_presentation import PUBLIC_VERDICT_STYLES
from backend.app.scoring.retrieval_profile import TOPIC_KEYWORDS
from backend.app.scoring.types import FulfillmentVerdict


class AskIntent(StrEnum):
    POLITICIAN_PLEDGES = "politician_pledges"
    PLEDGES_BY_VERDICT = "pledges_by_verdict"
    PLEDGES_BY_TOPIC = "pledges_by_topic"
    PLEDGE_EXPLANATION = "pledge_explanation"
    PLEDGE_SOURCES = "pledge_sources"
    UNSUPPORTED = "unsupported"


class AskRetrieveMode(StrEnum):
    """Retrieval switch used by Ask evaluation.

    ``keyword`` is the pre-paraphrase planner: public topic keywords only.
    ``hybrid`` adds Italian paraphrase phrases, then lexical overlap / FTS.
    """

    KEYWORD = "keyword"
    HYBRID = "hybrid"


# Public topic keywords as they existed before paraphrase retrieval.
KEYWORD_TOPIC_SYNONYMS: dict[str, tuple[str, ...]] = {
    "1": (
        "tasse",
        "fisco",
        "fiscalita",
        "imposte",
        "economia",
        "entrate",
        "cuneo fiscale",
        "cuneo",
    ),
    "3": (
        "sanita",
        "salute",
        "liste d attesa",
        "liste di attesa",
        "liste attesa",
        "ospedali",
        "ospedale",
    ),
    "5": ("lavoro", "occupazione"),
    "6": ("istruzione", "scuola", "scuole"),
    "9": ("immigrazione", "migranti"),
    "10": ("infrastrutture", "trasporti"),
    "12": ("giustizia", "magistratura"),
    "13": ("welfare", "pensioni", "pensione", "sociale"),
    "14": ("casa", "affitti", "housing"),
    "20": ("autonomia", "istituzioni"),
}

# Extra phrases from hybrid lexical retrieval. Not used in keyword-only mode.
HYBRID_TOPIC_EXTRA: dict[str, tuple[str, ...]] = {
    "1": ("tassazione", "irpef"),
    "3": ("tempi in ospedale", "tempi di attesa", "pronto soccorso", "ssn"),
    "5": ("disoccupazione", "assunzioni"),
    "6": ("universita", "studenti"),
    "12": ("carceri",),
}


def ask_topic_synonyms(retrieve_mode: AskRetrieveMode | str = AskRetrieveMode.HYBRID) -> dict[str, tuple[str, ...]]:
    mode = AskRetrieveMode(retrieve_mode)
    if mode is AskRetrieveMode.KEYWORD:
        return KEYWORD_TOPIC_SYNONYMS
    merged = dict(KEYWORD_TOPIC_SYNONYMS)
    for code, extra in HYBRID_TOPIC_EXTRA.items():
        merged[code] = merged.get(code, ()) + extra
    return merged


ASK_TOPIC_SYNONYMS: dict[str, tuple[str, ...]] = ask_topic_synonyms(AskRetrieveMode.HYBRID)

TOPIC_PUBLIC_LABELS: dict[str, str] = {
    "1": "fiscalità",
    "3": "sanità",
    "5": "lavoro",
    "6": "istruzione",
    "9": "immigrazione",
    "10": "infrastrutture",
    "12": "giustizia",
    "13": "welfare e pensioni",
    "14": "casa",
    "20": "istituzioni",
}

_STOPWORDS = frozenset(
    {
        "a",
        "ai",
        "al",
        "alla",
        "alle",
        "ancora",
        "che",
        "chi",
        "classificata",
        "classificato",
        "come",
        "con",
        "cosa",
        "da",
        "dal",
        "dalla",
        "dei",
        "del",
        "della",
        "delle",
        "dello",
        "di",
        "dimmi",
        "dove",
        "e",
        "elenca",
        "elenco",
        "fatto",
        "governo",
        "gli",
        "ha",
        "hanno",
        "i",
        "il",
        "in",
        "la",
        "le",
        "lista",
        "lo",
        "nel",
        "nella",
        "per",
        "promessa",
        "promesse",
        "promesso",
        "pubblicata",
        "pubblicate",
        "pubblicati",
        "quale",
        "quali",
        "quante",
        "quanto",
        "questa",
        "queste",
        "questi",
        "questo",
        "riguarda",
        "riguardano",
        "risulta",
        "risultano",
        "si",
        "sono",
        "sull",
        "suo",
        "sua",
        "suoi",
        "sue",
        "qual",
        "spiega",
        "spiegami",
        "stata",
        "state",
        "stati",
        "stato",
        "su",
        "sui",
        "sul",
        "sulla",
        "sulle",
        "una",
        "un",
        "valutazione",
        "viene",
    }
)

# Hybrid leftover stripping also drops generic "impegno/impegni" so they are
# not treated as a politician name. Keyword-only keeps the older stopword set.
_HYBRID_STOPWORDS = _STOPWORDS | frozenset({"impegni", "impegno"})


def _stopwords_for(retrieve_mode: AskRetrieveMode | str) -> frozenset[str]:
    if AskRetrieveMode(retrieve_mode) is AskRetrieveMode.KEYWORD:
        return _STOPWORDS
    return _HYBRID_STOPWORDS

_COUNT_CUES = ("quante", "quanto", "numero di")
_EXPLAIN_CUES = (
    "perche",
    "motivo",
    "spiega",
    "spiegami",
    "classificata",
    "classificato",
)
_SOURCE_CUES = (
    "fonte",
    "fonti",
    "evidenza",
    "evidenze",
    "da dove",
    "url",
    "estratto",
)
_RANKING_CUES = (
    "miglior",
    "migliore",
    "peggior",
    "peggiore",
    "meglio",
    "peggio",
    "affidabile",
    "affidabili",
    "classifica",
    "ranking",
)

_VERDICT_PHRASES: tuple[tuple[str, FulfillmentVerdict], ...] = (
    ("non sono ancora valutate", FulfillmentVerdict.NOT_YET_RATED),
    ("non sono ancora valutati", FulfillmentVerdict.NOT_YET_RATED),
    ("non e ancora valutata", FulfillmentVerdict.NOT_YET_RATED),
    ("non e ancora valutato", FulfillmentVerdict.NOT_YET_RATED),
    ("non ancora valutata", FulfillmentVerdict.NOT_YET_RATED),
    ("non ancora valutate", FulfillmentVerdict.NOT_YET_RATED),
    ("non ancora valutati", FulfillmentVerdict.NOT_YET_RATED),
    ("non valutata", FulfillmentVerdict.NOT_YET_RATED),
    ("not yet rated", FulfillmentVerdict.NOT_YET_RATED),
    ("not_yet_rated", FulfillmentVerdict.NOT_YET_RATED),
    ("mantenuta parzialmente", FulfillmentVerdict.PARTIALLY_KEPT),
    ("mantenute parzialmente", FulfillmentVerdict.PARTIALLY_KEPT),
    ("partially kept", FulfillmentVerdict.PARTIALLY_KEPT),
    ("partially_kept", FulfillmentVerdict.PARTIALLY_KEPT),
    ("non mantenuta", FulfillmentVerdict.BROKEN),
    ("non mantenute", FulfillmentVerdict.BROKEN),
    ("iter bloccato", FulfillmentVerdict.STALLED),
    ("iter bloccati", FulfillmentVerdict.STALLED),
    ("in corso", FulfillmentVerdict.IN_PROGRESS),
    ("in_progress", FulfillmentVerdict.IN_PROGRESS),
    ("ha mantenuto", FulfillmentVerdict.KEPT),
    ("hanno mantenuto", FulfillmentVerdict.KEPT),
    ("sono state mantenute", FulfillmentVerdict.KEPT),
    ("bloccate", FulfillmentVerdict.STALLED),
    ("bloccata", FulfillmentVerdict.STALLED),
    ("bloccati", FulfillmentVerdict.STALLED),
    ("stalled", FulfillmentVerdict.STALLED),
    ("broken", FulfillmentVerdict.BROKEN),
    ("mantenute", FulfillmentVerdict.KEPT),
    ("mantenuta", FulfillmentVerdict.KEPT),
    ("kept", FulfillmentVerdict.KEPT),
)


@dataclass(frozen=True, slots=True)
class AskPlan:
    intent: AskIntent
    entity_query: str | None
    verdict: FulfillmentVerdict | None
    topic_code: str | None
    topic_label: str | None
    wants_count: bool
    wants_explanation: bool
    wants_sources: bool
    asks_specific_status: bool


def _phrase_in(haystack: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", haystack) is not None


def _strip_phrase(haystack: str, phrase: str) -> str:
    return re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", " ", haystack).strip()


def _topic_phrases(
    synonyms: dict[str, tuple[str, ...]] | None = None,
) -> list[tuple[str, str]]:
    merged: dict[str, list[str]] = {}
    for code, phrases in TOPIC_KEYWORDS.items():
        merged.setdefault(code, []).extend(phrases)
    for code, phrases in (synonyms or ASK_TOPIC_SYNONYMS).items():
        merged.setdefault(code, []).extend(phrases)
    items: list[tuple[str, str]] = []
    for code, phrases in merged.items():
        seen: set[str] = set()
        for phrase in phrases:
            key = normalize_search_text(phrase)
            if key and key not in seen:
                seen.add(key)
                items.append((key, code))
    items.sort(key=lambda item: len(item[0]), reverse=True)
    return items


def detect_verdict(normalized: str) -> FulfillmentVerdict | None:
    for phrase, verdict in _VERDICT_PHRASES:
        if _phrase_in(normalized, phrase):
            return verdict
    for verdict, style in PUBLIC_VERDICT_STYLES.items():
        label = normalize_search_text(style.label)
        if label and _phrase_in(normalized, label):
            return verdict
        if _phrase_in(normalized, verdict.value):
            return verdict
    return None


def detect_topic(
    normalized: str,
    synonyms: dict[str, tuple[str, ...]] | None = None,
) -> tuple[str, str] | None:
    for phrase, code in _topic_phrases(synonyms):
        if _phrase_in(normalized, phrase):
            return code, TOPIC_PUBLIC_LABELS.get(code, phrase)
    return None


def _leftover_query(
    normalized: str,
    *,
    verdict: FulfillmentVerdict | None,
    topic_code: str | None,
    synonyms: dict[str, tuple[str, ...]] | None = None,
    stopwords: frozenset[str] | None = None,
) -> str | None:
    remainder = normalized
    if verdict is not None:
        for phrase, item in _VERDICT_PHRASES:
            if item is verdict:
                remainder = _strip_phrase(remainder, phrase)
        remainder = _strip_phrase(remainder, normalize_search_text(PUBLIC_VERDICT_STYLES[verdict].label))
        remainder = _strip_phrase(remainder, verdict.value)
    if topic_code is not None:
        for phrase, code in _topic_phrases(synonyms):
            if code == topic_code:
                remainder = _strip_phrase(remainder, phrase)
    for cue in (*_EXPLAIN_CUES, *_SOURCE_CUES, *_COUNT_CUES, *_RANKING_CUES):
        remainder = _strip_phrase(remainder, cue)
    dropped = stopwords if stopwords is not None else _HYBRID_STOPWORDS
    tokens = [
        token
        for token in remainder.split()
        if token not in dropped and len(token) >= 2
    ]
    if not tokens:
        return None
    return " ".join(tokens)


def plan_ask_question(
    question: str,
    *,
    retrieve_mode: AskRetrieveMode | str = AskRetrieveMode.HYBRID,
) -> AskPlan:
    mode = AskRetrieveMode(retrieve_mode)
    synonyms = ask_topic_synonyms(mode)
    stopwords = _stopwords_for(mode)
    normalized = normalize_search_text(question)
    verdict = detect_verdict(normalized)
    topic = detect_topic(normalized, synonyms)
    topic_code = topic[0] if topic else None
    topic_label = topic[1] if topic else None
    wants_count = any(_phrase_in(normalized, cue) for cue in _COUNT_CUES)
    wants_explanation = any(_phrase_in(normalized, cue) for cue in _EXPLAIN_CUES)
    wants_sources = any(_phrase_in(normalized, cue) for cue in _SOURCE_CUES)
    entity_query = _leftover_query(
        normalized,
        verdict=verdict,
        topic_code=topic_code,
        synonyms=synonyms,
        stopwords=stopwords,
    )
    asks_specific_status = verdict is not None and not wants_explanation
    leftover_tokens = search_tokens(entity_query or "")
    has_entity = bool(leftover_tokens or (entity_query and len(entity_query) >= 3))
    name_like = bool(entity_query) and len(entity_query.split()) <= 3
    ranking = any(_phrase_in(normalized, cue) for cue in _RANKING_CUES)

    if ranking and not wants_explanation and not wants_sources:
        intent = AskIntent.UNSUPPORTED
    elif wants_sources and not wants_explanation:
        intent = (
            AskIntent.PLEDGE_SOURCES
            if has_entity or topic_code is not None
            else AskIntent.UNSUPPORTED
        )
    elif wants_explanation:
        intent = (
            AskIntent.PLEDGE_EXPLANATION
            if has_entity or topic_code is not None or verdict is not None
            else AskIntent.UNSUPPORTED
        )
    elif name_like:
        intent = AskIntent.POLITICIAN_PLEDGES
    elif topic_code is not None:
        intent = AskIntent.PLEDGES_BY_TOPIC
    elif verdict is not None:
        intent = AskIntent.PLEDGES_BY_VERDICT
    else:
        intent = AskIntent.UNSUPPORTED

    return AskPlan(
        intent=intent,
        entity_query=entity_query,
        verdict=verdict,
        topic_code=topic_code,
        topic_label=topic_label,
        wants_count=wants_count,
        wants_explanation=wants_explanation,
        wants_sources=wants_sources,
        asks_specific_status=asks_specific_status,
    )
