"""Pledge -> official-act evidence matching, FEVER style.

Pipeline (Thorne et al. 2018; Lewis et al. 2020; Gao et al. 2023):

1. **Retrieve** candidate passages for an open pledge with a hybrid ranker:
   lexical BM25 over Italian-normalised tokens, optionally fused with an
   embedding ranker by reciprocal rank fusion. No embedding backend ships with
   the repository; :class:`Embedder` is the extension point.
2. **Judge** each passage with an :class:`EvidenceJudge`: supports / refutes /
   not enough info, plus a proposed fulfilment verdict and an exact excerpt.
3. **Verify** the citation: the excerpt must appear verbatim in the stored
   passage, and the proposed verdict must be compatible with the label.
   Anything that fails becomes a rejection, never a draft.

"Not enough info" is the default outcome and never produces a draft, which is
the code-level form of the rule "no status change without a sourced history
entry". Matching only ever *proposes*; a human approves.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from backend.app.core.text import normalize_search_text
from backend.app.scoring.types import (
    CommitmentType,
    EvidenceLabel,
    FulfillmentVerdict,
    VERDICTS_BY_EVIDENCE_LABEL,
)

MATCHER_VERSION = "pledge-evidence/v2"

# Short, high-frequency Italian function words. Content words are kept.
ITALIAN_STOPWORDS: frozenset[str] = frozenset(
    """
    alla alle allo agli anche anno anni come con contro dal dalla dalle dagli dei
    del della delle dello degli dopo fra gli governo il in lo la le nel nella nelle
    nello negli non per piu poi quale quali quando questa queste questo questi
    sara saranno sono sua sue suo suoi sul sulla sulle sullo sugli tra una uno che
    chi cui essere stato stata stati state verra verranno nostro nostra nostri
    nostre loro ogni tutti tutte tutto tutta entro ancora presso
    """.split()
)

_PREFIX_STEM = 6


def analyze(text: str) -> tuple[str, ...]:
    """Accent-insensitive tokens with light prefix stemming for Italian.

    Prefix truncation is a crude but well-known stemmer for Romance languages
    that conflates ``riforma/riforme/riformare`` without a dictionary.
    """

    tokens = []
    for token in normalize_search_text(text).split():
        if len(token) < 3 or token in ITALIAN_STOPWORDS or token.isdigit() and len(token) < 4:
            continue
        tokens.append(token[:_PREFIX_STEM])
    return tuple(tokens)


@dataclass(frozen=True, slots=True)
class Passage:
    passage_id: int
    raw_document_id: int
    text: str
    source_url: str
    retrieved_at: datetime | None = None
    source_key: str = ""
    source_name: str = ""
    published_at: date | None = None


@dataclass(frozen=True, slots=True)
class RankedPassage:
    passage: Passage
    score: float
    lexical_rank: int | None
    semantic_rank: int | None


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class BM25Index:
    def __init__(self, passages: Sequence[Passage], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.passages = tuple(passages)
        self.k1 = k1
        self.b = b
        self._terms = [Counter(analyze(passage.text)) for passage in self.passages]
        self._lengths = [sum(terms.values()) for terms in self._terms]
        self._avg_length = (
            sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        )
        document_frequency: Counter = Counter()
        for terms in self._terms:
            document_frequency.update(terms.keys())
        total = len(self.passages)
        self._idf = {
            term: math.log(1 + (total - df + 0.5) / (df + 0.5))
            for term, df in document_frequency.items()
        }

    def search(self, query: str, *, limit: int) -> list[tuple[int, float]]:
        query_terms = set(analyze(query))
        scored = []
        for index, terms in enumerate(self._terms):
            score = 0.0
            length_norm = 1 - self.b + self.b * (
                self._lengths[index] / self._avg_length if self._avg_length else 0.0
            )
            for term in query_terms:
                frequency = terms.get(term, 0)
                if frequency:
                    score += self._idf[term] * (
                        frequency * (self.k1 + 1) / (frequency + self.k1 * length_norm)
                    )
            if score > 0:
                scored.append((index, score))
        scored.sort(key=lambda pair: (-pair[1], self.passages[pair[0]].passage_id))
        return scored[:limit]


def _cosine(first: Sequence[float], second: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(first, second, strict=True))
    norm = math.sqrt(sum(a * a for a in first)) * math.sqrt(sum(b * b for b in second))
    return dot / norm if norm else 0.0


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[int]], *, k: int = 60
) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            fused[item] = fused.get(item, 0.0) + 1.0 / (k + rank)
    return fused


def retrieve(
    query: str,
    passages: Sequence[Passage],
    *,
    limit: int = 5,
    candidate_pool: int = 50,
    embedder: Embedder | None = None,
) -> list[RankedPassage]:
    if not passages:
        return []
    index = BM25Index(passages)
    lexical = index.search(query, limit=candidate_pool)
    lexical_ranking = [position for position, _score in lexical]
    rankings = [lexical_ranking]
    semantic_ranking: list[int] = []
    if embedder is not None:
        vectors = embedder.embed([query, *(passage.text for passage in passages)])
        query_vector, passage_vectors = vectors[0], vectors[1:]
        similarities = sorted(
            ((position, _cosine(query_vector, vector)) for position, vector in enumerate(passage_vectors)),
            key=lambda pair: (-pair[1], passages[pair[0]].passage_id),
        )
        semantic_ranking = [position for position, sim in similarities[:candidate_pool] if sim > 0]
        rankings.append(semantic_ranking)
    fused = reciprocal_rank_fusion(rankings)
    lexical_rank = {position: rank for rank, position in enumerate(lexical_ranking, start=1)}
    semantic_rank = {position: rank for rank, position in enumerate(semantic_ranking, start=1)}
    ordered = sorted(fused.items(), key=lambda pair: (-pair[1], passages[pair[0]].passage_id))
    return [
        RankedPassage(
            passage=passages[position],
            score=round(score, 6),
            lexical_rank=lexical_rank.get(position),
            semantic_rank=semantic_rank.get(position),
        )
        for position, score in ordered[:limit]
    ]


@dataclass(frozen=True, slots=True)
class EvidenceJudgment:
    label: EvidenceLabel
    proposed_verdict: FulfillmentVerdict | None
    quoted_excerpt: str
    rationale: str


class EvidenceJudge(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def judge(
        self, *, pledge_text: str, commitment_type: CommitmentType, passage_text: str
    ) -> EvidenceJudgment: ...


class AbstainingJudge:
    """Default judge: never claims evidence. Safe until a real judge is validated."""

    name = "abstaining"
    version = "v1"

    def judge(
        self, *, pledge_text: str, commitment_type: CommitmentType, passage_text: str
    ) -> EvidenceJudgment:
        del pledge_text, commitment_type, passage_text
        return EvidenceJudgment(EvidenceLabel.NOT_ENOUGH_INFO, None, "", "")


_WHITESPACE = re.compile(r"\s+")


def _collapse(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def excerpt_is_verbatim(passage_text: str, excerpt: str, *, min_length: int = 12) -> bool:
    """Citation check: the excerpt must exist in the stored passage text."""

    collapsed = _collapse(excerpt)
    return len(collapsed) >= min_length and collapsed in _collapse(passage_text)


@dataclass(frozen=True, slots=True)
class MatchProposal:
    passage: RankedPassage
    judgment: EvidenceJudgment


@dataclass(frozen=True, slots=True)
class MatchRejection:
    passage: RankedPassage
    judgment: EvidenceJudgment
    reason: str


def validate_judgment(
    judgment: EvidenceJudgment, passage_text: str
) -> str | None:
    """Return a rejection reason, or ``None`` when the judgment may become a draft."""

    if judgment.label is EvidenceLabel.NOT_ENOUGH_INFO:
        return "not_enough_info"
    allowed = VERDICTS_BY_EVIDENCE_LABEL[judgment.label]
    if judgment.proposed_verdict is None or judgment.proposed_verdict not in allowed:
        return "verdict_incompatible_with_label"
    if not excerpt_is_verbatim(passage_text, judgment.quoted_excerpt):
        return "excerpt_not_found_in_source"
    if not judgment.rationale.strip():
        return "missing_rationale"
    return None
