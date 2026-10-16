"""Public labels and CSS tones for fulfilment verdicts.

Internal enum values (``kept``, ``partially_kept``, ``in_progress``, ``stalled``,
``broken``, ``not_yet_rated``) are unchanged. This module is display-only: it
must not be used by scoring, approval, or evidence matching.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from backend.app.scoring.types import CLOSED_VERDICTS, FulfillmentVerdict, OPEN_VERDICTS


@dataclass(frozen=True, slots=True)
class PublicVerdictStyle:
    verdict: FulfillmentVerdict
    label: str
    tone: str
    color_name: str


PUBLIC_VERDICT_STYLES: dict[FulfillmentVerdict, PublicVerdictStyle] = {
    FulfillmentVerdict.KEPT: PublicVerdictStyle(
        FulfillmentVerdict.KEPT, "Mantenuta", "kept", "green"
    ),
    FulfillmentVerdict.PARTIALLY_KEPT: PublicVerdictStyle(
        FulfillmentVerdict.PARTIALLY_KEPT, "Mantenuta parzialmente", "partial", "yellow"
    ),
    FulfillmentVerdict.IN_PROGRESS: PublicVerdictStyle(
        FulfillmentVerdict.IN_PROGRESS, "In corso", "progress", "blue"
    ),
    FulfillmentVerdict.STALLED: PublicVerdictStyle(
        FulfillmentVerdict.STALLED, "Iter bloccato", "stalled", "black"
    ),
    FulfillmentVerdict.BROKEN: PublicVerdictStyle(
        FulfillmentVerdict.BROKEN, "Non mantenuta", "broken", "red"
    ),
    FulfillmentVerdict.NOT_YET_RATED: PublicVerdictStyle(
        FulfillmentVerdict.NOT_YET_RATED, "Non ancora valutata", "unrated", "grey"
    ),
}

PUBLIC_VERDICT_LEGEND_ORDER: tuple[FulfillmentVerdict, ...] = (
    FulfillmentVerdict.KEPT,
    FulfillmentVerdict.PARTIALLY_KEPT,
    FulfillmentVerdict.IN_PROGRESS,
    FulfillmentVerdict.STALLED,
    FulfillmentVerdict.BROKEN,
    FulfillmentVerdict.NOT_YET_RATED,
)


def _as_verdict(value: str | FulfillmentVerdict) -> FulfillmentVerdict:
    if isinstance(value, FulfillmentVerdict):
        return value
    return FulfillmentVerdict(value)


def public_verdict_style(value: str | FulfillmentVerdict) -> PublicVerdictStyle:
    return PUBLIC_VERDICT_STYLES[_as_verdict(value)]


def public_verdict_label(value: str | FulfillmentVerdict) -> str:
    return public_verdict_style(value).label


def public_verdict_tone(value: str | FulfillmentVerdict) -> str:
    return public_verdict_style(value).tone


def public_verdict_chip_html(value: str | FulfillmentVerdict) -> str:
    style = public_verdict_style(value)
    return (
        f'<span class="verdict-chip tone-{escape(style.tone, quote=True)}">'
        f"{escape(style.label)}</span>"
    )


def is_open_verdict(value: str | FulfillmentVerdict) -> bool:
    return _as_verdict(value) in OPEN_VERDICTS


def is_closed_verdict(value: str | FulfillmentVerdict) -> bool:
    return _as_verdict(value) in CLOSED_VERDICTS
