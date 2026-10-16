"""Public labels and CSS tones for fulfilment verdicts.

Internal enum values (``kept``, ``partially_kept``, ``in_progress``, ``stalled``,
``broken``, ``not_yet_rated``) are unchanged. This module is display-only: it
must not be used by scoring, approval, or evidence matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape

from backend.app.scoring.types import CLOSED_VERDICTS, FulfillmentVerdict, OPEN_VERDICTS

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_URL_WRAPPER_RE = re.compile(r"\[(?:URL|url|Url):\s*(https?://[^\]\s]+)\]")
_INTERNAL_VERDICT_RE = re.compile(
    r"\b("
    + "|".join(
        sorted((item.value for item in FulfillmentVerdict), key=len, reverse=True)
    )
    + r")\b",
    re.IGNORECASE,
)


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


def scrub_public_ai_text(text: str) -> str:
    """Strip model markup and replace internal enum tokens with public labels."""
    cleaned = text.replace("**", "").replace("__", "").replace("`", "")
    cleaned = _MARKDOWN_LINK_RE.sub(r"\1", cleaned)
    cleaned = _URL_WRAPPER_RE.sub("", cleaned)
    cleaned = re.sub(r"(?<!\w)\*+|\*+(?!\w)", "", cleaned)

    def _replace(match: re.Match[str]) -> str:
        try:
            return public_verdict_label(match.group(1).casefold())
        except ValueError:
            return match.group(0)

    return _INTERNAL_VERDICT_RE.sub(_replace, cleaned).strip()


def is_open_verdict(value: str | FulfillmentVerdict) -> bool:
    return _as_verdict(value) in OPEN_VERDICTS


def is_closed_verdict(value: str | FulfillmentVerdict) -> bool:
    return _as_verdict(value) in CLOSED_VERDICTS
