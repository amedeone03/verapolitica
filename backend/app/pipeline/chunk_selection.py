from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

CHUNK_SELECTION_VERSION = "deterministic_relevance_v2"
EARLY_METADATA_PAGES = 3
CHARS_PER_TOKEN = 4
DEFAULT_DOCUMENT_TOKEN_BUDGET = 4_500
TIER_METADATA = "metadata"
TIER_SUBSTANCE = "substance"
TIER_SUPPORTING = "supporting"
TIER_RANK = {TIER_METADATA: 0, TIER_SUBSTANCE: 1, TIER_SUPPORTING: 2}
MAX_METADATA_CHUNKS = 4
MAX_SUBSTANCE_CHUNKS = 4
PREFERRED_SELECTED_CHUNKS = MAX_METADATA_CHUNKS + MAX_SUBSTANCE_CHUNKS
DUPLICATE_JACCARD = 0.82
DUPLICATE_PREFIX_CHARS = 240

_TERM_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("disegno di legge", 12),
    ("atto senato", 12),
    ("dati generali", 10),
    ("presentato da", 10),
    ("iniziativa", 8),
    ("assegnazione", 8),
    ("relatori", 7),
    ("relatore", 6),
    ("approvato", 7),
    ("trasmesso", 7),
    ("governo", 6),
    ("articolo", 6),
    ("articoli", 5),
    ("titolo", 5),
    ("iter", 5),
    ("stato", 3),
    ("impegna", 8),
    ("si impegna", 10),
    ("dispone", 5),
    ("commit", 6),
    ("pledge", 6),
    ("we will", 6),
)

_METADATA_SIGNALS: tuple[tuple[str, str, int], ...] = (
    (r"(?<!d['’])iniziativa governativa", "iniziativa_governativa", 18),
    (r"iniziativa parlamentare", "iniziativa", 12),
    (r"(?:^|[\n.])\s*(?:\d+(?:\.\d+)*\.?\s*)?dati generali\b", "dati_generali", 16),
    (r"atto senato n\.", "atto_senato", 10),
    (r"classificazione\s+teseo", "classificazione", 10),
    (r"(?:^|[\n.\)])\s*presentazione\b(?!\s+di\b)", "presentazione", 14),
    (r"(?:^|[\n.\)])\s*assegnazione\b(?!\s+di\b)", "assegnazione", 14),
    (r"(?:^|[\n.\)])\s*relatori\b", "relatori", 12),
    (r"presentato dal\s+presidente", "presentato_dal", 16),
    (r"disegno di legge\s+presentato dal", "presentato_dal", 14),
    (r"presentato da\b", "presentato_da", 8),
    (r"\biter\b.{0,80}approvato definitivamente", "iter_status", 16),
    (r"approvato definitivamente", "approvato", 8),
    (r"\btrasmesso\b", "trasmesso", 6),
    (r"fascicolo iter ddl", "identity", 14),
    (
        r"pres(?:idente)?\.?\s+consiglio|governo meloni|giorgia meloni",
        "government_actor",
        10,
    ),
)

_SUBSTANCE_SIGNALS: tuple[tuple[str, str, int], ...] = (
    (r"disegno di legge", "disegno_di_legge", 12),
    (r"\bart(?:icolo|\.)\s*\d+", "articolo", 10),
    (r"\bè convertito\b", "convertito", 12),
    (r"\bsi istituisce\b|\bistituisce\b", "istituisce", 8),
    (r"\bautorizza\b", "autorizza", 8),
    (r"\bmodific(?:a|he)\b", "modifiche", 6),
    (r"\bdispone\b", "dispone", 5),
    (r"\bsi impegna\b", "impegna", 10),
)

_MONEY_RE = re.compile(
    r"(€|eur(?:o|i)?|mln|miliard[io]|million|billion|\d[\d.\s]{2,}\d{2})",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"(\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b|"
    r"\b(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|"
    r"agosto|settembre|ottobre|novembre|dicembre)\b)",
    re.IGNORECASE,
)
_ARTICLE_RE = re.compile(r"\bart(?:icolo|\.)\s*\d+", re.IGNORECASE)
_METADATA_TIER_LABELS = {
    "iniziativa_governativa",
    "dati_generali",
    "presentazione",
    "assegnazione",
    "relatori",
    "presentato_dal",
    "iter_status",
    "identity",
    "government_actor",
}
_DOSSIER_NAV_RE = re.compile(
    r"disegni di legge\s+atto senato n\.\s*\d+\s+"
    r"(?:xviii|xix|xx|xxi)\s+legislatura\s+"
    r"dati generali-\s*testi ed emendamenti-\s*dossier-\s*"
    r"trattazione in commissione-\s*trattazione in consultiva-\s*"
    r"trattazione in assemblea-?",
    re.IGNORECASE,
)
_RUNNING_FOOTER_RE = re.compile(
    r"ddl s\.\s*\d+\s*-\s*senato della repubblica.{0,160}?pag\.\s*\d+",
    re.IGNORECASE | re.DOTALL,
)
_LINK_CHROME_RE = re.compile(
    r"collegamento al documento su www\.senato\.it",
    re.IGNORECASE,
)
_TESEO_ART_RE = re.compile(r"\(artt?\.?\s*\d+", re.IGNORECASE)
_DEBATE_TERMS = (
    "applausi",
    "il seguito dell'esame",
    "resoconto sommario",
    "resoconto stenografico",
    "discussione generale",
)
_SEDUTA_RE = re.compile(r"seduta n\.", re.IGNORECASE)
_TOC_NUMBERED_RE = re.compile(r"\d+(?:\.\d+){2,}\s+\S+")
_WORD_RE = re.compile(r"[a-z0-9]+")


class SelectableChunk(Protocol):
    chunk_index: int
    text: str
    page_start: int | None
    page_end: int | None


@dataclass(frozen=True, slots=True)
class ChunkPreview:
    chunk_index: int
    page: int | None
    tier: str
    score: int
    matched_signals: tuple[str, ...]
    estimated_tokens: int
    sent: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "chunk_index": self.chunk_index,
            "page": self.page,
            "tier": self.tier,
            "score": self.score,
            "matched_signals": list(self.matched_signals),
            "estimated_tokens": self.estimated_tokens,
            "sent": self.sent,
        }


@dataclass(frozen=True, slots=True)
class ChunkSelection:
    chunks: tuple[SelectableChunk, ...]
    selected_indexes: tuple[int, ...]
    scores: tuple[tuple[int, int], ...]
    page_count: int
    total_chunk_count: int
    full_document_coverage: bool
    method: str = CHUNK_SELECTION_VERSION
    sent_indexes: tuple[int, ...] = ()
    omitted_indexes: tuple[int, ...] = ()
    document_token_estimate: int = 0
    max_document_tokens: int | None = None
    preview: tuple[ChunkPreview, ...] = ()

    def resolved_sent_indexes(self) -> tuple[int, ...]:
        if self.sent_indexes:
            return self.sent_indexes
        return tuple(chunk.chunk_index for chunk in self.chunks)

    def as_dict(self) -> dict[str, object]:
        sent = list(self.resolved_sent_indexes())
        omitted = list(self.omitted_indexes)
        payload = {
            "method": self.method,
            "full_document_coverage": self.full_document_coverage,
            "total_chunk_count": self.total_chunk_count,
            "page_count": self.page_count,
            "selected_chunk_indexes": list(self.selected_indexes),
            "sent_chunk_indexes": sent,
            "omitted_chunk_indexes": omitted,
            "document_token_estimate": self.document_token_estimate,
            "max_document_tokens": self.max_document_tokens,
            "selected_pages": sorted(
                {
                    page
                    for chunk in self.chunks
                    for page in (chunk.page_start, chunk.page_end)
                    if page is not None
                }
            ),
            "scores": [
                {"chunk_index": index, "score": score} for index, score in self.scores
            ],
            "preview": [item.as_dict() for item in self.preview],
        }
        payload["evidence_summary"] = evidence_summary_from_payload(payload)
        return payload

    def coverage_note(self) -> str:
        return coverage_note_from_payload(self.as_dict())


def coverage_note_from_payload(payload: dict[str, object]) -> str:
    selected = payload.get("selected_chunk_indexes") or []
    count = len(selected) if isinstance(selected, list) else int(payload.get("selected_count") or 0)
    sent = payload.get("sent_chunk_indexes") or selected
    sent_count = len(sent) if isinstance(sent, list) else count
    omitted = payload.get("omitted_chunk_indexes") or []
    omitted_count = len(omitted) if isinstance(omitted, list) else 0
    total = int(payload.get("total_chunk_count") or 0)
    page_count = int(payload.get("page_count") or 0)
    if payload.get("full_document_coverage") and omitted_count == 0:
        return (
            f"AI analysis based on the full extracted document "
            f"({total} section{'' if total == 1 else 's'})."
        )
    if page_count:
        pages = f"{page_count:,}-page document"
    elif total:
        pages = f"document with {total:,} extracted sections"
    else:
        pages = "document"
    if omitted_count:
        return (
            f"AI analysis based on {sent_count} packed evidence section"
            f"{'' if sent_count == 1 else 's'} from a {pages} "
            f"({count} relevant section{'' if count == 1 else 's'} selected; "
            f"{omitted_count} omitted to fit the local context budget)."
        )
    return (
        f"AI analysis based on {count} selected evidence section"
        f"{'' if count == 1 else 's'} from a {pages}."
    )


def evidence_summary_from_payload(payload: dict[str, object]) -> list[str]:
    sent = payload.get("sent_chunk_indexes") or []
    sent_ids = {int(index) for index in sent} if isinstance(sent, list) else set()
    labels: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        if label not in seen:
            seen.add(label)
            labels.append(label)

    for row in payload.get("preview") or []:
        if not isinstance(row, dict):
            continue
        index = row.get("chunk_index")
        if sent_ids and index not in sent_ids and row.get("sent") is False:
            continue
        signals = {str(item) for item in (row.get("matched_signals") or [])}
        tier = str(row.get("tier") or "")
        if {
            "iniziativa_governativa",
            "iniziativa",
            "government_actor",
            "presentato_dal",
        } & signals:
            add("Government initiative")
        if {
            "dati_generali",
            "iter_status",
            "identity",
            "atto_senato",
            "approvato",
        } & signals:
            add("Metadata / status")
        if {"presentazione", "assegnazione", "relatori"} & signals:
            add("Presentation / assignment")
        if {"articolo", "disegno_di_legge", "convertito", "istituisce"} & signals:
            add("Legislative text")
        if tier == TIER_SUBSTANCE and "Legislative text" not in seen:
            add("Legislative text")
        if tier == TIER_METADATA and "Metadata / status" not in seen:
            add("Metadata / status")
    return labels


def estimate_tokens(text: str, *, chars_per_token: int = CHARS_PER_TOKEN) -> int:
    if not text:
        return 0
    if chars_per_token < 1:
        raise ValueError("chars_per_token must be positive")
    return (len(text) + chars_per_token - 1) // chars_per_token


def chunk_prompt_text(chunk: SelectableChunk) -> str:
    page_label = ""
    if chunk.page_start is not None:
        page_label = f" (pages {chunk.page_start}-{chunk.page_end})"
    return f"--- CHUNK {chunk.chunk_index}{page_label} ---\n{chunk.text}"


def chunk_page(chunk: SelectableChunk) -> int | None:
    return chunk.page_start if chunk.page_start is not None else chunk.page_end


def strip_repeating_chrome(text: str) -> str:
    cleaned = _LINK_CHROME_RE.sub(" ", text)
    cleaned = _DOSSIER_NAV_RE.sub(" ", cleaned)
    cleaned = _RUNNING_FOOTER_RE.sub(" ", cleaned)
    return re.sub(r"[ \t]+", " ", cleaned).strip()


def looks_like_table_of_contents(text: str) -> bool:
    stripped = text.lstrip()
    lowered = stripped.casefold()
    if lowered.startswith("indice"):
        return True
    if len(_SEDUTA_RE.findall(text)) >= 3:
        return True
    if len(_TOC_NUMBERED_RE.findall(stripped)) >= 6:
        return True
    return False


def looks_like_subject_catalog(text: str) -> bool:
    return len(_TESEO_ART_RE.findall(text)) >= 8


def looks_like_parliamentary_debate(text: str) -> bool:
    lowered = text.casefold()
    return any(term in lowered for term in _DEBATE_TERMS)


def _match_signals(
    text: str, patterns: tuple[tuple[str, str, int], ...]
) -> tuple[tuple[str, ...], int]:
    lowered = text.casefold()
    labels: list[str] = []
    bonus = 0
    seen: set[str] = set()
    for pattern, label, weight in patterns:
        if re.search(pattern, lowered):
            bonus += weight
            if label not in seen:
                seen.add(label)
                labels.append(label)
    return tuple(labels), bonus


def score_chunk(text: str) -> int:
    lowered = text.casefold()
    score = 0
    for term, weight in _TERM_WEIGHTS:
        if term in lowered:
            score += weight
    if _MONEY_RE.search(text):
        score += 8
    if _DATE_RE.search(text):
        score += 4
    if _ARTICLE_RE.search(text):
        score += 5
    return score


def looks_like_session_transcript(text: str) -> bool:
    if looks_like_table_of_contents(text):
        return True
    lowered = text.casefold()
    if re.search(r"resocont[io]\s+(?:sommari|stenografici)", lowered):
        return True
    sedute = len(_SEDUTA_RE.findall(text))
    if sedute >= 3:
        return True
    if sedute >= 2 and re.search(
        r"commissione permanente.{0,120}seduta n\.",
        lowered,
        re.DOTALL,
    ):
        return True
    if "la seduta inizia" in lowered:
        return True
    if (
        "presidenza del" in lowered
        and "commissione permanente" in lowered
        and "seduta" in lowered
    ):
        return True
    return False


def classify_chunk(text: str) -> tuple[str, tuple[str, ...], int]:
    cleaned = strip_repeating_chrome(text)
    haystack = cleaned or text
    base = score_chunk(haystack)
    if looks_like_table_of_contents(haystack):
        return TIER_SUPPORTING, ("toc",), max(base // 4, 0)
    metadata, meta_bonus = _match_signals(haystack, _METADATA_SIGNALS)
    substance, subst_bonus = _match_signals(haystack, _SUBSTANCE_SIGNALS)
    if _MONEY_RE.search(haystack) and "money" not in substance:
        substance = (*substance, "money")
        subst_bonus += 8
    session_like = looks_like_session_transcript(haystack)
    debate_like = looks_like_parliamentary_debate(haystack)
    catalog_like = looks_like_subject_catalog(haystack)
    strong_metadata = tuple(
        label for label in metadata if label in _METADATA_TIER_LABELS
    )
    heading_metadata = {
        "dati_generali",
        "iniziativa_governativa",
        "presentazione",
        "assegnazione",
        "relatori",
        "presentato_dal",
        "iter_status",
        "identity",
    } & set(strong_metadata)
    allow_metadata = bool(heading_metadata) and not session_like and not debate_like
    if allow_metadata:
        return TIER_METADATA, metadata, base + meta_bonus
    if session_like or debate_like:
        return TIER_SUPPORTING, metadata + substance, max(base // 3, 0)
    if substance and not catalog_like:
        return TIER_SUBSTANCE, substance + metadata, base + subst_bonus
    if catalog_like and heading_metadata:
        return TIER_METADATA, metadata, base + meta_bonus
    return TIER_SUPPORTING, metadata + substance, base


def _normalized_words(text: str) -> tuple[str, ...]:
    return tuple(_WORD_RE.findall(text.casefold()))


def is_near_duplicate(left: str, right: str) -> bool:
    left_words = _normalized_words(left)
    right_words = _normalized_words(right)
    if not left_words or not right_words:
        return False
    left_prefix = "".join(left_words)[:DUPLICATE_PREFIX_CHARS]
    right_prefix = "".join(right_words)[:DUPLICATE_PREFIX_CHARS]
    if (
        len(left_prefix) >= 80
        and len(right_prefix) >= 80
        and left_prefix == right_prefix
    ):
        return True
    left_set = set(left_words[:80])
    right_set = set(right_words[:80])
    union = left_set | right_set
    if not union:
        return False
    return (len(left_set & right_set) / len(union)) >= DUPLICATE_JACCARD


def _is_duplicate_of_selected(
    chunk: SelectableChunk, selected: tuple[SelectableChunk, ...]
) -> bool:
    return any(is_near_duplicate(chunk.text, item.text) for item in selected)


def pack_chunks_for_context(
    chunks: tuple[SelectableChunk, ...],
    *,
    max_document_tokens: int = DEFAULT_DOCUMENT_TOKEN_BUDGET,
    early_pages: int = EARLY_METADATA_PAGES,
    chars_per_token: int = CHARS_PER_TOKEN,
    scores: dict[int, int] | None = None,
    tiers: dict[int, str] | None = None,
) -> tuple[tuple[SelectableChunk, ...], int]:
    del early_pages
    if max_document_tokens < 1:
        raise ValueError("max_document_tokens must be positive")
    ordered = tuple(sorted(chunks, key=lambda item: item.chunk_index))
    if not ordered:
        return (), 0
    score_map = scores or {
        chunk.chunk_index: classify_chunk(chunk.text)[2] for chunk in ordered
    }
    tier_map = tiers or {
        chunk.chunk_index: classify_chunk(chunk.text)[0] for chunk in ordered
    }
    ranked = sorted(
        ordered,
        key=lambda chunk: (
            TIER_RANK.get(tier_map.get(chunk.chunk_index, TIER_SUPPORTING), 9),
            -score_map.get(chunk.chunk_index, 0),
            chunk.chunk_index,
        ),
    )
    packed: list[SelectableChunk] = []
    used = 0
    for chunk in ranked:
        if _is_duplicate_of_selected(chunk, tuple(packed)):
            continue
        cost = estimate_tokens(chunk_prompt_text(chunk), chars_per_token=chars_per_token)
        if packed and used + cost > max_document_tokens:
            continue
        packed.append(chunk)
        used += cost
        if not packed[1:] and used > max_document_tokens:
            break
    packed.sort(key=lambda chunk: chunk.chunk_index)
    return tuple(packed), used


def document_page_count(chunks: tuple[SelectableChunk, ...]) -> int:
    pages = [
        max(filter(None, (chunk.page_start, chunk.page_end)))
        for chunk in chunks
        if chunk.page_start is not None or chunk.page_end is not None
    ]
    return max(pages) if pages else 0


def _take_tier(
    ranked: list[tuple[SelectableChunk, str, tuple[str, ...], int]],
    *,
    tier: str,
    limit: int,
    selected: dict[int, SelectableChunk],
    proximity_indexes: tuple[int, ...] = (),
    proximity_window: int = 8,
) -> None:
    taken = 0
    chosen = tuple(selected[index] for index in sorted(selected))
    candidates = [
        item for item in ranked if item[1] == tier and item[0].chunk_index not in selected
    ]
    if proximity_indexes:
        candidates.sort(
            key=lambda item: (
                0
                if any(
                    abs(item[0].chunk_index - index) <= proximity_window
                    for index in proximity_indexes
                )
                else 1,
                -item[3],
                item[0].chunk_index,
            )
        )
    for chunk, _chunk_tier, signals, _score in candidates:
        if taken >= limit:
            return
        if "toc" in signals:
            continue
        if _is_duplicate_of_selected(chunk, chosen):
            continue
        selected[chunk.chunk_index] = chunk
        chosen = (*chosen, chunk)
        taken += 1


def _with_token_budget(
    *,
    chosen: tuple[SelectableChunk, ...],
    selected_indexes: tuple[int, ...],
    scores: tuple[tuple[int, int], ...],
    page_count: int,
    total_chunk_count: int,
    full_document_coverage: bool,
    max_document_tokens: int | None,
    early_pages: int,
    classifications: dict[int, tuple[str, tuple[str, ...], int]],
) -> ChunkSelection:
    score_map = {index: score for index, score in scores}
    tier_map = {index: item[0] for index, item in classifications.items()}
    if max_document_tokens is None:
        packed = chosen
        used = sum(estimate_tokens(chunk_prompt_text(chunk)) for chunk in packed)
        omitted: tuple[int, ...] = ()
    else:
        packed, used = pack_chunks_for_context(
            chosen,
            max_document_tokens=max_document_tokens,
            early_pages=early_pages,
            scores=score_map,
            tiers=tier_map,
        )
        packed_ids = {chunk.chunk_index for chunk in packed}
        omitted = tuple(
            index for index in selected_indexes if index not in packed_ids
        )
    sent_ids = {chunk.chunk_index for chunk in packed}
    chosen_by_index = {chunk.chunk_index: chunk for chunk in chosen}
    preview = tuple(
        ChunkPreview(
            chunk_index=index,
            page=chunk_page(chosen_by_index[index]),
            tier=classifications.get(index, (TIER_SUPPORTING, (), 0))[0],
            score=score_map.get(index, 0),
            matched_signals=classifications.get(index, (TIER_SUPPORTING, (), 0))[1],
            estimated_tokens=estimate_tokens(chunk_prompt_text(chosen_by_index[index])),
            sent=index in sent_ids,
        )
        for index in selected_indexes
        if index in chosen_by_index
    )
    return ChunkSelection(
        chunks=packed,
        selected_indexes=selected_indexes,
        scores=scores,
        page_count=page_count,
        total_chunk_count=total_chunk_count,
        full_document_coverage=full_document_coverage and not omitted,
        sent_indexes=tuple(chunk.chunk_index for chunk in packed),
        omitted_indexes=omitted,
        document_token_estimate=used,
        max_document_tokens=max_document_tokens,
        preview=preview,
    )


def select_relevant_chunks(
    chunks: tuple[SelectableChunk, ...],
    *,
    max_selected: int,
    early_pages: int = EARLY_METADATA_PAGES,
    max_document_tokens: int | None = None,
) -> ChunkSelection:
    if max_selected < 1:
        raise ValueError("max_selected must be positive")
    ordered = tuple(sorted(chunks, key=lambda item: item.chunk_index))
    page_count = document_page_count(ordered)
    classifications = {
        chunk.chunk_index: classify_chunk(chunk.text) for chunk in ordered
    }
    ranked = sorted(
        (
            (chunk, *classifications[chunk.chunk_index])
            for chunk in ordered
        ),
        key=lambda item: (
            TIER_RANK.get(item[1], 9),
            -item[3],
            item[0].chunk_index,
        ),
    )
    if len(ordered) <= max_selected:
        return _with_token_budget(
            chosen=ordered,
            selected_indexes=tuple(chunk.chunk_index for chunk in ordered),
            scores=tuple(
                (chunk.chunk_index, classifications[chunk.chunk_index][2])
                for chunk in ordered
            ),
            page_count=page_count,
            total_chunk_count=len(ordered),
            full_document_coverage=True,
            max_document_tokens=max_document_tokens,
            early_pages=early_pages,
            classifications=classifications,
        )
    selected: dict[int, SelectableChunk] = {}
    _take_tier(ranked, tier=TIER_METADATA, limit=MAX_METADATA_CHUNKS, selected=selected)
    if not selected:
        for chunk in ordered:
            page = chunk_page(chunk)
            if page is not None and page <= early_pages:
                selected[chunk.chunk_index] = chunk
            elif page is None and chunk.chunk_index < early_pages:
                selected[chunk.chunk_index] = chunk
            if len(selected) >= MAX_METADATA_CHUNKS:
                break
    _take_tier(
        ranked,
        tier=TIER_SUBSTANCE,
        limit=MAX_SUBSTANCE_CHUNKS,
        selected=selected,
        proximity_indexes=tuple(selected),
    )
    preferred_cap = min(max_selected, PREFERRED_SELECTED_CHUNKS)
    if len(selected) < 4:
        remaining = preferred_cap - len(selected)
        if remaining > 0:
            _take_tier(
                ranked,
                tier=TIER_SUPPORTING,
                limit=remaining,
                selected=selected,
            )
    if not selected:
        for chunk, _tier, _signals, _score in ranked[:max_selected]:
            selected[chunk.chunk_index] = chunk
    chosen = tuple(selected[index] for index in sorted(selected)[:max_selected])
    return _with_token_budget(
        chosen=chosen,
        selected_indexes=tuple(chunk.chunk_index for chunk in chosen),
        scores=tuple(
            (chunk.chunk_index, classifications[chunk.chunk_index][2])
            for chunk in chosen
        ),
        page_count=page_count,
        total_chunk_count=len(ordered),
        full_document_coverage=False,
        max_document_tokens=max_document_tokens,
        early_pages=early_pages,
        classifications=classifications,
    )


def preview_chunk_selection_details(
    chunks: tuple[SelectableChunk, ...],
    *,
    max_selected: int,
    max_document_tokens: int | None = DEFAULT_DOCUMENT_TOKEN_BUDGET,
) -> dict[str, object]:
    selection = select_relevant_chunks(
        chunks,
        max_selected=max_selected,
        max_document_tokens=max_document_tokens,
    )
    return selection.as_dict()


def selection_payload(selection: ChunkSelection) -> str:
    return json.dumps(selection.as_dict(), ensure_ascii=False, sort_keys=True)
