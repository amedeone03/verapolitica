"""Deterministic retrieval profile derived from a classified commitment.

The profile is used only to *find* later official documents. It never decides
a fulfilment verdict. Topic overlap alone is not enough: at least one policy
instrument phrase from the commitment must appear in the candidate passage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from backend.app.core.text import normalize_search_text
from backend.app.scoring.evidence_matching import ITALIAN_STOPWORDS
from backend.app.scoring.types import CommitmentType, PledgeSpecificity


KNOWN_INSTRUMENTS: tuple[str, ...] = (
    "autonomia differenziata",
    "ordinamento giudiziario",
    "infrastrutture strategiche",
    "proprieta pubblica",
    "proprieta' pubblica",
    "clausola di salvaguardia",
    "piano carceri",
    "certezza della pena",
    "agenzia delle entrate",
    "occupazione femminile",
    "asili nido",
    "missione navale",
    "missione sophia",
    "reti di comunicazioni",
    "concessioni di infrastrutture",
    "logiche correntizie",
    "criteri di valutazione",
)

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "1": ("fisco", "entrate", "agenzia", "imposte"),
    "9": ("immigrazione", "migranti", "sophia", "navale", "hotspot"),
    "10": ("infrastrutture", "reti", "concessioni", "autostrade", "aeroporti"),
    "12": ("giustizia", "magistratura", "carceri", "ordinamento"),
    "13": ("welfare", "pensioni", "invalidi", "sostegno"),
    "20": ("autonomia", "regioni", "sussidiarieta", "asili"),
}


@dataclass(frozen=True, slots=True)
class RetrievalProfile:
    proposal_id: int
    actor_names: tuple[str, ...]
    title: str
    commitment_text: str
    topic_code: str | None
    specificity: PledgeSpecificity
    commitment_type: CommitmentType
    instrument_phrases: tuple[str, ...]
    topic_terms: tuple[str, ...]
    query: str
    announcement_date: date | None
    mandate_start: date | None
    mandate_end: date | None
    origin_urls: tuple[str, ...]
    origin_document_ids: tuple[int, ...]

    @property
    def earliest_evidence_date(self) -> date | None:
        return self.announcement_date or self.mandate_start


def _unique(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return tuple(ordered)


def extract_instrument_phrases(*texts: str) -> tuple[str, ...]:
    blob = normalize_search_text(" ".join(part for part in texts if part))
    found = [phrase for phrase in KNOWN_INSTRUMENTS if normalize_search_text(phrase) in blob]
    words = [
        token
        for token in blob.split()
        if len(token) >= 8 and token not in ITALIAN_STOPWORDS
    ]
    return _unique([*found, *words[:12]])


def topic_terms_for(topic_code: str | None, *texts: str) -> tuple[str, ...]:
    configured = list(TOPIC_KEYWORDS.get(topic_code or "", ()))
    return _unique([*configured, *extract_instrument_phrases(*texts)[:6]])


def build_retrieval_profile(
    *,
    proposal_id: int,
    title: str,
    commitment_text: str,
    actor_names: tuple[str, ...],
    topic_code: str | None,
    specificity: PledgeSpecificity,
    commitment_type: CommitmentType,
    announcement_date: date | None,
    mandate_start: date | None,
    mandate_end: date | None,
    origin_urls: tuple[str, ...] = (),
    origin_document_ids: tuple[int, ...] = (),
) -> RetrievalProfile:
    instruments = extract_instrument_phrases(title, commitment_text)
    topics = topic_terms_for(topic_code, title, commitment_text)
    query = " ".join(part for part in (commitment_text, title, *instruments) if part)
    return RetrievalProfile(
        proposal_id=proposal_id,
        actor_names=tuple(name for name in actor_names if name.strip()),
        title=title,
        commitment_text=commitment_text,
        topic_code=topic_code,
        specificity=specificity,
        commitment_type=commitment_type,
        instrument_phrases=instruments,
        topic_terms=topics,
        query=query,
        announcement_date=announcement_date,
        mandate_start=mandate_start,
        mandate_end=mandate_end,
        origin_urls=tuple(url.rstrip("/") for url in origin_urls if url),
        origin_document_ids=origin_document_ids,
    )
