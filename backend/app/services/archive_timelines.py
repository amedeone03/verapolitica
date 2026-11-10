"""Draft political timelines for Archivio (cities, regions, national).

These files are unverified editorial drafts (Tuttitalia / Wikipedia). They are
shown as drafts until a second person checks them against official sources.
They do not invent office holders or publish assessments.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.text import normalize_search_text
from backend.app.models import Municipality, Region

TIMELINE_ROOT = Path(__file__).resolve().parents[3] / "data/fixtures/archive/timelines"


def _fold(value: str) -> str:
    return normalize_search_text(value or "")


@lru_cache(maxsize=1)
def load_timeline_index() -> tuple[dict, ...]:
    path = TIMELINE_ROOT / "index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(payload["items"])


@lru_cache(maxsize=64)
def load_timeline(slug: str) -> dict:
    path = TIMELINE_ROOT / f"{slug}.json"
    if not path.is_file():
        raise FileNotFoundError(slug)
    return json.loads(path.read_text(encoding="utf-8"))


def timeline_summaries() -> list[dict]:
    """Public index: name, slug, kind, event count. No event bodies."""

    return [
        {
            "kind": item["kind"],
            "name": item["name"],
            "slug": item["slug"],
            "event_count": item["events"],
            "draft": True,
        }
        for item in load_timeline_index()
    ]


def public_timeline(slug: str) -> dict:
    data = load_timeline(slug)
    events = [
        {
            "date": event["date"],
            "date_label": event.get("date_label") or event["date"][:4],
            "title": event["title"],
            "body": event.get("body") or "",
            "status": event.get("status") or "",
            "sources": event.get("sources") or [],
        }
        for event in data.get("events") or []
    ]
    return {
        "kind": data["kind"],
        "name": data["name"],
        "slug": data["slug"],
        "draft": True,
        "updated": data.get("updated"),
        "mayor": data.get("mayor"),
        "disclaimer": data.get("disclaimer") or "",
        "events": events,
    }


def _lookup(folded: str, mapping: dict):
    """Match 'Valle d'Aosta' to ISTAT 'Valle d'Aosta/Vallée d'Aoste'."""

    if folded in mapping:
        return mapping[folded]
    hits = [
        value
        for key, value in mapping.items()
        if key.startswith(folded) or folded.startswith(key)
    ]
    if len(hits) == 1:
        return hits[0]
    return None


def attach_live_keys(session: Session, items: list[dict]) -> list[dict]:
    """Add live region/municipality ids when the ISTAT names match."""

    regions = {_fold(row.canonical_name): row.id for row in session.scalars(select(Region))}
    towns = {
        _fold(row.canonical_name): (row.id, row.province_abbreviation, row.region_id)
        for row in session.scalars(select(Municipality))
    }
    attached = []
    for item in items:
        extra = dict(item)
        folded = _fold(item["name"])
        extra.setdefault("region_id", None)
        extra.setdefault("municipality_id", None)
        extra.setdefault("province_abbreviation", None)
        if item["kind"] == "region":
            extra["region_id"] = _lookup(folded, regions)
        elif item["kind"] == "city":
            hit = _lookup(folded, towns)
            if hit:
                extra["municipality_id"], extra["province_abbreviation"], extra["region_id"] = hit
        attached.append(extra)
    return attached


DRAFT_DISCLAIMER = (
    "Bozze non verificate. Fonti secondarie (Tuttitalia, Wikipedia). "
    "Ogni voce va confrontata con l'archivio del Ministero dell'Interno "
    "o con l'ente prima di considerarla un fatto."
)
