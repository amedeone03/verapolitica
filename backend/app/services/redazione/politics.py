"""«Politica attuale»: editorial corrections to everything the Politica page shows.

Keys and their fields:

    government:{politician_id}         party_name, party_abbreviation, tier, role_label, hidden
                                       (a politician not in the official Government list is added)
    region:{region_id}                 coalition, president_name, president_politician_id, next_election
    chamber:{camera|senato}:group:{id} name, abbreviation, seats, hidden
    chamber:{camera|senato}:extra:{slug}  name, abbreviation, seats (a group the official data lacks)
    text:{name}                        body (the notes and captions under the blocks)

The official value is never overwritten: a published correction is shown in
its place, with source and reason, and the public page marks it.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models.politics_edit import PoliticsEdit
from backend.app.models.territory_block import TerritoryBlockStatus
from backend.app.services.redazione import style
from backend.app.services.redazione.territory import COALITIONS

GOVERNMENT_TIERS = {
    "0": "Presidente del Consiglio",
    "1": "Vicepresidente del Consiglio",
    "2": "Ministro con portafoglio",
    "3": "Ministro senza portafoglio",
    "4": "Sottosegretario",
}
TEXTS = {
    "government_note": "Nota sotto il Governo",
    "regions_caption": "Nota sotto le Regioni",
    "camera_caption": "Nota sotto la Camera",
    "senato_caption": "Nota sotto il Senato",
}
KEY = re.compile(
    r"^(government:\d{1,9}|region:\d{1,9}|chamber:(camera|senato):group:\d{1,9}|chamber:(camera|senato):extra:[a-z0-9-]{1,40}|text:(" + "|".join(TEXTS) + "))$"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _line(value: Any, limit: int = 300) -> str:
    return " ".join(str(value or "").split())[:limit]


class PoliticsEditError(RuntimeError):
    status_code = 422

    def __init__(self, message: str, findings: list[dict] | None = None) -> None:
        super().__init__(message)
        self.findings = findings or []


class PoliticsEditNotFound(PoliticsEditError):
    status_code = 404


def kind_of(key: str) -> str:
    if key.startswith("government:"):
        return "government"
    if key.startswith("region:"):
        return "region"
    if key.startswith("chamber:"):
        return "chamber_extra" if ":extra:" in key else "chamber_group"
    return "text"


def label_of(key: str) -> str:
    kind = kind_of(key)
    if kind == "government":
        return "Governo"
    if kind == "region":
        return "Regioni"
    if kind.startswith("chamber"):
        return "Camera" if ":camera:" in key else "Senato"
    return TEXTS.get(key.split(":", 1)[1], "Testo")


def sanitize(key: str, payload: dict) -> dict:
    kind = kind_of(key)
    if kind == "government":
        tier = str(payload.get("tier") if payload.get("tier") is not None else "")
        return {
            "party_name": _line(payload.get("party_name"), 200),
            "party_abbreviation": _line(payload.get("party_abbreviation"), 40),
            "tier": tier if tier in GOVERNMENT_TIERS else "",
            "role_label": _line(payload.get("role_label"), 160),
            "hidden": bool(payload.get("hidden")),
        }
    if kind == "region":
        coalition = payload.get("coalition")
        president_id = str(payload.get("president_politician_id") or "")
        return {
            "coalition": coalition if coalition in COALITIONS else "",
            "president_name": _line(payload.get("president_name"), 160),
            "president_politician_id": int(president_id) if president_id.isdigit() else None,
            "next_election": _line(payload.get("next_election"), 160),
        }
    if kind in {"chamber_group", "chamber_extra"}:
        seats = str(payload.get("seats") if payload.get("seats") is not None else "").strip()
        return {
            "name": _line(payload.get("name"), 200),
            "abbreviation": _line(payload.get("abbreviation"), 40),
            "seats": int(seats) if seats.isdigit() and int(seats) <= 700 else None,
            "hidden": bool(payload.get("hidden")) if kind == "chamber_group" else False,
        }
    return {"body": str(payload.get("body") or "").strip()[:800]}


def findings(key: str, data: dict, sources: list[dict], reason: str) -> list[dict]:
    kind = kind_of(key)
    found: list[style.Finding] = []
    if not reason.strip():
        found.append(style.Finding("error", "motivo_mancante", "Scrivi perché correggi il dato ufficiale: comparirà nel registro.", "motivo"))
    if data.get("restore"):
        return [item.as_dict() for item in found]
    if kind != "text":
        found.extend(style.source_findings(sources))
    if kind == "government" and not data.get("hidden") and not any(data.get(field) for field in ("party_name", "tier", "role_label")):
        found.append(style.Finding("error", "vuoto", "Indica almeno partito, ruolo o etichetta (oppure nascondi la persona).", "dati"))
    if kind == "chamber_extra" and (not data.get("name") or data.get("seats") is None):
        found.append(style.Finding("error", "vuoto", "Un gruppo aggiunto ha bisogno di nome e seggi.", "dati"))
    if kind == "text" and not data.get("body"):
        found.append(style.Finding("warning", "vuoto", "Testo vuoto: sul sito torna la nota predefinita.", "testo"))
    for field, value in data.items():
        if isinstance(value, str) and value:
            found.extend(style.text_findings(value, field=field))
    found.extend(style.text_findings(reason, field="motivo"))
    return [item.as_dict() for item in found]


class PoliticsEdits:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def _item(self, row: PoliticsEdit, member: str | None = None) -> dict:
        return {
            "id": row.id,
            "key": row.key,
            "kind": kind_of(row.key),
            "label": label_of(row.key),
            "status": row.status.value,
            "data": row.data,
            "sources": row.sources,
            "reason": row.reason,
            "created_by": row.created_by,
            "created_at": _iso(row.created_at),
            "reviewed_by": row.reviewed_by,
            "review_note": row.review_note,
            "published_at": _iso(row.published_at),
            "own": member is not None and row.created_by == member,
            "findings": findings(row.key, row.data or {}, row.sources or [], row.reason or ""),
        }

    def save(self, key: str, payload: dict, *, member: str) -> dict:
        if not KEY.fullmatch(key):
            raise PoliticsEditNotFound("Elemento sconosciuto.")
        data = sanitize(key, payload)
        sources = []
        for item in payload.get("sources") or []:
            if isinstance(item, dict) and (item.get("url") or item.get("name")):
                sources.append({"name": _line(item.get("name"), 200), "url": _line(item.get("url"), 500), "date": _line(item.get("date"), 20) or None})
        reason = _line(payload.get("reason"), 600)
        with self.session_factory.begin() as session:
            for row in session.scalars(select(PoliticsEdit).where(
                PoliticsEdit.key == key, PoliticsEdit.status == TerritoryBlockStatus.PENDING, PoliticsEdit.created_by == member,
            )):
                row.status = TerritoryBlockStatus.SUPERSEDED
                row.review_note = "Sostituita da una nuova versione dello stesso autore."
            row = PoliticsEdit(key=key, data=data, sources=sources[:12], reason=reason, status=TerritoryBlockStatus.PENDING, created_by=member)
            session.add(row)
            session.flush()
            return {**self._item(row, member), "title": f"Politica attuale — {label_of(key)}"}

    def restore(self, key: str, *, member: str, reason: str) -> dict:
        """Back to the official value: a version that, once published, clears the correction."""

        if not KEY.fullmatch(key):
            raise PoliticsEditNotFound("Elemento sconosciuto.")
        with self.session_factory.begin() as session:
            row = PoliticsEdit(key=key, data={"restore": True}, sources=[], reason=_line(reason, 600) or "Torna il dato ufficiale.", status=TerritoryBlockStatus.PENDING, created_by=member)
            session.add(row)
            session.flush()
            item = self._item(row, member)
            return {**item, "title": f"Politica attuale — {label_of(key)}: torna il dato ufficiale"}

    def pending(self) -> list[dict]:
        with self.session_factory() as session:
            rows = session.scalars(select(PoliticsEdit).where(PoliticsEdit.status == TerritoryBlockStatus.PENDING).order_by(PoliticsEdit.created_at, PoliticsEdit.id))
            items = []
            for row in rows:
                item = self._item(row)
                if row.data.get("restore"):
                    item["title"] = f"Politica attuale — {label_of(row.key)}: torna il dato ufficiale"
                else:
                    item["title"] = f"Politica attuale — {label_of(row.key)}"
                items.append(item)
            return items

    def publish(self, item_id: int, *, reviewer: str, note: str | None = None) -> PoliticsEdit:
        with self.session_factory.begin() as session:
            row = session.get(PoliticsEdit, item_id)
            if row is None or row.status is not TerritoryBlockStatus.PENDING:
                raise PoliticsEditError("Versione non più in attesa.")
            for previous in session.scalars(select(PoliticsEdit).where(PoliticsEdit.key == row.key, PoliticsEdit.status == TerritoryBlockStatus.PUBLISHED)):
                previous.status = TerritoryBlockStatus.SUPERSEDED
            row.status = TerritoryBlockStatus.PUBLISHED
            row.reviewed_by = reviewer
            row.review_note = note
            row.published_at = _now()
            session.flush()
            return row

    def reject(self, item_id: int, *, reviewer: str, note: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(PoliticsEdit, item_id)
            if row is None or row.status is not TerritoryBlockStatus.PENDING:
                raise PoliticsEditError("Versione non più in attesa.")
            row.status = TerritoryBlockStatus.REJECTED
            row.reviewed_by = reviewer
            row.review_note = note

    def published(self, session: Session | None = None) -> dict[str, dict]:
        """The live corrections, by key (a published «restore» removes the key)."""

        def read(active: Session) -> dict[str, dict]:
            rows = active.scalars(select(PoliticsEdit).where(PoliticsEdit.status == TerritoryBlockStatus.PUBLISHED).order_by(PoliticsEdit.published_at, PoliticsEdit.id))
            live: dict[str, dict] = {}
            for row in rows:
                if row.data.get("restore"):
                    live.pop(row.key, None)
                    continue
                live[row.key] = {
                    **row.data,
                    "sources": row.sources,
                    "reason": row.reason,
                    "published_by": row.reviewed_by,
                    "published_at": _iso(row.published_at),
                }
            return live

        if session is not None:
            return read(session)
        with self.session_factory() as active:
            return read(active)

    def console(self, *, member: str) -> dict:
        """Live corrections and every open version, for the «Politica attuale» page."""

        with self.session_factory() as session:
            live = self.published(session)
            open_rows = session.scalars(select(PoliticsEdit).where(PoliticsEdit.status.in_((TerritoryBlockStatus.PENDING, TerritoryBlockStatus.REJECTED))).order_by(PoliticsEdit.created_at))
            pending: dict[str, list[dict]] = {}
            for row in open_rows:
                if row.status is TerritoryBlockStatus.REJECTED and row.key in live:
                    continue
                pending.setdefault(row.key, []).append(self._item(row, member))
            return {
                "published": live,
                "pending": pending,
                "tiers": GOVERNMENT_TIERS,
                "coalitions": COALITIONS,
                "texts": TEXTS,
            }


def apply_regions(overview: dict, live: dict[str, dict]) -> dict:
    """Region corrections over the overview; the official values stay alongside."""

    for item in overview["items"]:
        edit = live.get(f"region:{item['id']}")
        if not edit:
            continue
        item["official"] = {"coalition": item["coalition"], "president": item["president"], "next_election": item["next_election"]}
        if edit.get("coalition"):
            item["coalition"] = edit["coalition"]
            item["coalition_label"] = COALITIONS[edit["coalition"]]
        if edit.get("president_name"):
            item["president"] = {"role": "Presidente della Regione", "politician_id": edit.get("president_politician_id"), "name": edit["president_name"], "since": None}
        if edit.get("next_election"):
            item["next_election"] = edit["next_election"]
        item["edited"] = {"reason": edit.get("reason"), "sources": edit.get("sources"), "published_at": edit.get("published_at")}
    counts = {key: sum(1 for item in overview["items"] if item["coalition"] == key) for key in COALITIONS}
    counts["da_compilare"] = sum(1 for item in overview["items"] if not item["coalition"])
    overview["counts"] = counts
    return overview


def apply_chamber(data: dict, live: dict[str, dict]) -> dict:
    """Group corrections and added groups over the official seat counts."""

    chamber = data["chamber"]
    groups = []
    for group in data["groups"]:
        edit = live.get(f"chamber:{chamber}:group:{group['id']}")
        if edit:
            if edit.get("hidden"):
                continue
            group = {**group, "official": {"name": group["name"], "abbreviation": group["abbreviation"], "seats": group["seats"]}}
            if edit.get("name"):
                group["name"] = edit["name"]
            if edit.get("abbreviation"):
                group["abbreviation"] = edit["abbreviation"]
            if edit.get("seats") is not None:
                group["seats"] = edit["seats"]
            group["edited"] = {"reason": edit.get("reason"), "sources": edit.get("sources")}
        groups.append(group)
    prefix = f"chamber:{chamber}:extra:"
    for key, edit in live.items():
        if key.startswith(prefix) and edit.get("name") and edit.get("seats"):
            groups.append({"id": None, "key": key.removeprefix(prefix), "name": edit["name"], "abbreviation": edit.get("abbreviation") or None, "seats": edit["seats"], "edited": {"reason": edit.get("reason"), "sources": edit.get("sources"), "added": True}})
    groups = [group for group in groups if group["seats"]]
    groups.sort(key=lambda group: (-group["seats"], group["name"]))
    total = sum(group["seats"] for group in groups)
    data.update({"groups": groups, "counted": total, "majority": total // 2 + 1 if total else None})
    if f"text:{chamber}_caption" in live and live[f"text:{chamber}_caption"].get("body"):
        data["caption"] = live[f"text:{chamber}_caption"]["body"]
    return data
