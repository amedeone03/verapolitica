"""Institutional rank of current Government offices.

Used by the public politician list (``role=governo``) and by operator scripts
that collect official portraits. Matching is case-insensitive and accepts the
wording published by governo.it (``Presidente del Consiglio``) as well as the
normalized key used in the citizen UI.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

GOVERNMENT_RANK: tuple[str, ...] = (
    "presidente del consiglio",
    "vice presidente del consiglio",
    "ministro",
    "ministro senza portafoglio",
    "sottosegretario",
)


def _folded(value: str | None) -> str:
    return " ".join(str(value or "").casefold().split())


def government_office_rank(office: str | None) -> int:
    key = _folded(office)
    if key in GOVERNMENT_RANK:
        return GOVERNMENT_RANK.index(key)
    if "vice presidente" in key or "vicepresidente" in key:
        return 1
    if "presidente del consiglio" in key:
        return 0
    if "ministro senza portafoglio" in key:
        return 3
    if "viceministro" in key or "vice ministro" in key:
        return 3
    if "ministro" in key:
        return 2
    if "sottosegretario" in key:
        return 4
    return len(GOVERNMENT_RANK)


def is_government_office(office: str | None) -> bool:
    return government_office_rank(office) < len(GOVERNMENT_RANK)


def _mandate_office(mandate: Any) -> str | None:
    if isinstance(mandate, Mapping):
        value = mandate.get("office")
        return value if isinstance(value, str) else None
    value = getattr(mandate, "office", None)
    return value if isinstance(value, str) else None


def _mandate_open(mandate: Any) -> bool:
    if isinstance(mandate, Mapping):
        return not mandate.get("end_date")
    return getattr(mandate, "end_date", None) is None


def has_government_office(mandates: Iterable[Any] | None) -> bool:
    return any(is_government_office(_mandate_office(item)) for item in mandates or ())


def cabinet_office(mandates: Iterable[Any] | None) -> str | None:
    """Best current Government office, or the best closed one if none is open."""

    rows = list(mandates or ())
    open_rows = [item for item in rows if _mandate_open(item)]
    pool = open_rows or rows
    ranked = [
        (government_office_rank(_mandate_office(item)), _mandate_office(item))
        for item in pool
        if is_government_office(_mandate_office(item))
    ]
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1] if ranked else None
