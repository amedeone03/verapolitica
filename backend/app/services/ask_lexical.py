"""Free lexical retrieval for Ask VeraPolitica.

Ranks already-published pledges by overlapping Italian tokens and a small
paraphrase map. No embeddings, no paid API, no unpublished rows. Postgres
full-text search is an optional extra rank when the dialect supports it.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.core.text import normalize_search_text, search_tokens

# Extra query tokens that should count as a hit on the pledge text.
# Keys and values are already accent-folded, lowercase, length >= 3.
TOKEN_EXPANSION: dict[str, tuple[str, ...]] = {
    "attese": ("attesa", "liste"),
    "ospedale": ("sanita", "attesa", "liste"),
    "ospedali": ("sanita", "attesa", "liste"),
    "tempi": ("attesa", "liste"),
    "salute": ("sanita",),
    "ssn": ("sanita",),
    "tassazione": ("tasse", "fisco", "cuneo"),
    "irpef": ("fisco", "tasse"),
    "disoccupazione": ("lavoro", "occupazione"),
    "assunzioni": ("lavoro", "occupazione"),
    "universita": ("istruzione", "scuola"),
    "studenti": ("istruzione", "scuola"),
    "migranti": ("immigrazione",),
    "carcere": ("giustizia",),
    "carceri": ("giustizia",),
}

# Minimum overlapping expanded tokens before a paraphrase is treated as a match.
MIN_PARAPHRASE_OVERLAP = 2


def expand_tokens(tokens: tuple[str, ...] | list[str]) -> frozenset[str]:
    expanded: set[str] = set(tokens)
    for token in tokens:
        expanded.update(TOKEN_EXPANSION.get(token, ()))
    return frozenset(expanded)


def question_tokens(question: str) -> frozenset[str]:
    return expand_tokens(search_tokens(normalize_search_text(question)))


def pledge_blob(title: str, statement: str | None) -> str:
    return normalize_search_text(f"{title} {statement or ''}")


def lexical_overlap(question: str, title: str, statement: str | None) -> int:
    tokens = question_tokens(question)
    if not tokens:
        return 0
    blob = set(search_tokens(pledge_blob(title, statement)))
    return len(tokens & blob)


def postgres_pledge_ranks(session: Session, question: str) -> dict[int, float]:
    """Optional tsvector ranks. Empty on SQLite. Uses the 'simple' config."""

    bind = session.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return {}
    query = normalize_search_text(question)
    if len(query) < 3:
        return {}
    rows = session.execute(
        text(
            """
            SELECT id,
                   ts_rank_cd(
                     to_tsvector(
                       'simple',
                       coalesce(canonical_title, '') || ' ' || coalesce(exact_statement, '')
                     ),
                     plainto_tsquery('simple', :q)
                   ) AS rank
            FROM proposals
            WHERE published_at IS NOT NULL
              AND proposal_type = 'explicit_promise'
              AND to_tsvector(
                    'simple',
                    coalesce(canonical_title, '') || ' ' || coalesce(exact_statement, '')
                  ) @@ plainto_tsquery('simple', :q)
            ORDER BY rank DESC
            LIMIT 24
            """
        ),
        {"q": query},
    )
    return {int(item.id): float(item.rank) for item in rows}


def sort_pledge_ids(
    *,
    ordered_ids: list[int],
    overlaps: dict[int, int],
    fts_ranks: dict[int, float],
) -> list[int]:
    """Stable reorder: higher overlap, then FTS rank, then original order."""

    index = {pledge_id: position for position, pledge_id in enumerate(ordered_ids)}
    return sorted(
        ordered_ids,
        key=lambda pledge_id: (
            -overlaps.get(pledge_id, 0),
            -fts_ranks.get(pledge_id, 0.0),
            index[pledge_id],
        ),
    )


def unique_paraphrase_match(
    *,
    question: str,
    candidates: list[tuple[int, str, str | None]],
) -> int | None:
    """Return the only candidate with a clear paraphrase overlap, or None."""

    scored = [
        (lexical_overlap(question, title, statement), pledge_id)
        for pledge_id, title, statement in candidates
    ]
    scored = [item for item in scored if item[0] >= MIN_PARAPHRASE_OVERLAP]
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1]))
    best_score, best_id = scored[0]
    if len(scored) > 1 and scored[1][0] == best_score:
        return None
    return best_id
