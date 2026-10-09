"""Versioned, hand-curated instrument aliases for official-evidence retrieval.

Aliases never replace the commitment's own wording. They are added only when
the source phrase is already present in the pledge. Runtime code does not
invent mappings.
"""

from __future__ import annotations

from dataclasses import dataclass


ALIAS_POLICY_VERSION = "instrument-alias/v1"


@dataclass(frozen=True, slots=True)
class InstrumentAlias:
    source: str
    alias: str
    topics: tuple[str, ...]
    reason: str


INSTRUMENT_ALIASES: tuple[InstrumentAlias, ...] = (
    InstrumentAlias(
        source="piano carceri",
        alias="edilizia penitenziaria",
        topics=("12",),
        reason=(
            "Later official acts (d.l. 92/2024, l. 112/2024) name the prison-building "
            "programme as edilizia penitenziaria, including the commissario and the "
            "programma degli interventi. This is the same instrument, not a new pledge."
        ),
    ),
    InstrumentAlias(
        source="piano carceri",
        alias="strutture penitenziarie",
        topics=("12",),
        reason=(
            "Ministero della giustizia and DAP use strutture penitenziarie for the "
            "prison estate that a piano carceri would expand. Alias-only hits still "
            "need topic, date, official source, and promulgation language."
        ),
    ),
    InstrumentAlias(
        source="soggetti effettivamente fragili",
        alias="assegno di inclusione",
        topics=("13",),
        reason=(
            "The pledge promises cash support for people who cannot work: invalidi, "
            "pensioners in difficulty, and households without income with minor "
            "children. L. 85/2023 institutes the Assegno di inclusione for nuclei "
            "with disability, a minor, or a member aged 60+. That is the later "
            "official income-support instrument, not generic welfare."
        ),
    ),
)


def aliases_for(
    source_phrases: tuple[str, ...], *, topic_code: str | None = None
) -> tuple[str, ...]:
    """Return aliases whose source phrase is already in the pledge."""

    sources = {item.casefold() for item in source_phrases}
    found: list[str] = []
    seen: set[str] = set()
    for item in INSTRUMENT_ALIASES:
        if item.source.casefold() not in sources:
            continue
        if topic_code and item.topics and topic_code not in item.topics:
            continue
        key = item.alias.casefold()
        if key in seen:
            continue
        seen.add(key)
        found.append(item.alias)
    return tuple(found)
