"""Verify Archivio timeline drafts against official sources.

Wikipedia and Tuttitalia stay visible as bozze. A published verification only
marks that one event as checked. It does not invent a sindaco or a mandate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models.archive_timeline import (
    ArchiveTimelineVerification,
    ArchiveTimelineVerificationStatus,
)
from backend.app.services.archive_timelines import load_timeline, load_timeline_index
from backend.app.services.redazione import style

SECONDARY_HOSTS = ("wikipedia.org", "tuttitalia.it", "wikimedia.org")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def official_source_host(url: str) -> str:
    return (urlsplit(url or "").hostname or "").casefold().removeprefix("www.")


def is_secondary_source(url: str) -> bool:
    host = official_source_host(url)
    return any(host == item or host.endswith(f".{item}") for item in SECONDARY_HOSTS)


class ArchiveTimelineError(RuntimeError):
    status_code = 400

    def __init__(self, message: str, findings: list[dict] | None = None) -> None:
        super().__init__(message)
        self.findings = findings or []


class ArchiveTimelineNotFound(ArchiveTimelineError):
    status_code = 404


def verification_findings(official_url: str, official_name: str) -> list[dict]:
    found = list(style.source_findings([{"name": official_name, "url": official_url}]))
    if is_secondary_source(official_url):
        found.append(
            style.Finding(
                "error",
                "fonte_secondaria",
                "Wikipedia e Tuttitalia restano bozze. Serve una fonte ufficiale (Ministero dell'Interno, Eligendo, ente).",
                "fonte",
            )
        )
    return [item.as_dict() for item in found]


class ArchiveTimelineDesk:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def catalog(self) -> list[dict]:
        with self.session_factory() as session:
            published = list(
                session.scalars(
                    select(ArchiveTimelineVerification).where(
                        ArchiveTimelineVerification.status == ArchiveTimelineVerificationStatus.PUBLISHED
                    )
                )
            )
            pending = list(
                session.scalars(
                    select(ArchiveTimelineVerification).where(
                        ArchiveTimelineVerification.status == ArchiveTimelineVerificationStatus.PENDING
                    )
                )
            )
        by_slug_pub: dict[str, int] = {}
        by_slug_pending: dict[str, int] = {}
        for row in published:
            by_slug_pub[row.slug] = by_slug_pub.get(row.slug, 0) + 1
        for row in pending:
            by_slug_pending[row.slug] = by_slug_pending.get(row.slug, 0) + 1
        items = []
        for item in load_timeline_index():
            total = int(item["events"])
            verified = by_slug_pub.get(item["slug"], 0)
            items.append(
                {
                    "slug": item["slug"],
                    "name": item["name"],
                    "kind": item["kind"],
                    "event_count": total,
                    "verified_count": verified,
                    "pending_count": by_slug_pending.get(item["slug"], 0),
                    "draft": verified < total,
                }
            )
        return items

    def detail(self, slug: str) -> dict:
        try:
            data = load_timeline(slug)
        except FileNotFoundError as error:
            raise ArchiveTimelineNotFound("Questa cronologia non è in archivio.") from error
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(ArchiveTimelineVerification)
                    .where(ArchiveTimelineVerification.slug == slug)
                    .order_by(ArchiveTimelineVerification.event_index, ArchiveTimelineVerification.id)
                )
            )
        by_index: dict[int, list[ArchiveTimelineVerification]] = {}
        for row in rows:
            by_index.setdefault(row.event_index, []).append(row)
        events = []
        for index, event in enumerate(data.get("events") or []):
            versions = by_index.get(index) or []
            published = next(
                (row for row in reversed(versions) if row.status is ArchiveTimelineVerificationStatus.PUBLISHED),
                None,
            )
            pending = next(
                (row for row in reversed(versions) if row.status is ArchiveTimelineVerificationStatus.PENDING),
                None,
            )
            events.append(
                {
                    "index": index,
                    "date": event.get("date"),
                    "date_label": event.get("date_label") or str(event.get("date") or "")[:4],
                    "title": event.get("title"),
                    "body": event.get("body") or "",
                    "draft_sources": event.get("sources") or [],
                    "verified": published is not None,
                    "official_url": published.official_url if published else None,
                    "official_name": published.official_name if published else None,
                    "pending": self._item(pending) if pending else None,
                }
            )
        verified = sum(1 for event in events if event["verified"])
        return {
            "slug": data["slug"],
            "name": data["name"],
            "kind": data["kind"],
            "mayor": data.get("mayor"),
            "disclaimer": data.get("disclaimer"),
            "draft": verified < len(events),
            "verified_count": verified,
            "event_count": len(events),
            "events": events,
        }

    def propose(
        self,
        slug: str,
        event_index: int,
        *,
        official_url: str,
        official_name: str,
        member: str,
    ) -> dict:
        detail = self.detail(slug)
        if event_index < 0 or event_index >= len(detail["events"]):
            raise ArchiveTimelineNotFound("Questa voce non è nella cronologia.")
        findings = verification_findings(official_url, official_name)
        if style.has_errors(findings):
            raise ArchiveTimelineError("La fonte non è accettabile per una verifica.", findings)
        event = detail["events"][event_index]
        if event["pending"]:
            raise ArchiveTimelineError("C'è già una verifica in attesa per questa voce.")
        with self.session_factory.begin() as session:
            row = ArchiveTimelineVerification(
                slug=slug,
                event_index=event_index,
                official_url=official_url.strip(),
                official_name=official_name.strip()[:300],
                created_by=member,
            )
            session.add(row)
            session.flush()
            return {"id": row.id, "slug": slug, "event_index": event_index}

    def pending(self) -> list[dict]:
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(ArchiveTimelineVerification)
                    .where(ArchiveTimelineVerification.status == ArchiveTimelineVerificationStatus.PENDING)
                    .order_by(ArchiveTimelineVerification.created_at, ArchiveTimelineVerification.id)
                )
            )
        items = []
        for row in rows:
            try:
                data = load_timeline(row.slug)
            except FileNotFoundError:
                continue
            events = data.get("events") or []
            event = events[row.event_index] if 0 <= row.event_index < len(events) else {}
            items.append(
                {
                    **self._item(row),
                    "timeline_name": data.get("name"),
                    "event_title": event.get("title") or f"Voce {row.event_index + 1}",
                    "event_body": event.get("body") or "",
                    "findings": verification_findings(row.official_url, row.official_name),
                }
            )
        return items

    def publish(self, item_id: int, *, reviewer: str, note: str | None = None) -> dict:
        with self.session_factory.begin() as session:
            row = session.get(ArchiveTimelineVerification, item_id)
            if row is None or row.status is not ArchiveTimelineVerificationStatus.PENDING:
                raise ArchiveTimelineNotFound("Questa verifica non è in attesa.")
            findings = verification_findings(row.official_url, row.official_name)
            if style.has_errors(findings):
                raise ArchiveTimelineError("La fonte non è accettabile per una verifica.", findings)
            for older in session.scalars(
                select(ArchiveTimelineVerification).where(
                    ArchiveTimelineVerification.slug == row.slug,
                    ArchiveTimelineVerification.event_index == row.event_index,
                    ArchiveTimelineVerification.status == ArchiveTimelineVerificationStatus.PUBLISHED,
                    ArchiveTimelineVerification.id != row.id,
                )
            ):
                older.status = ArchiveTimelineVerificationStatus.REJECTED
                older.reviewed_by = reviewer
                older.review_note = "Sostituita da una verifica più recente."
            row.status = ArchiveTimelineVerificationStatus.PUBLISHED
            row.reviewed_by = reviewer
            row.review_note = note
            row.published_at = _now()
            return {"id": row.id, "slug": row.slug, "event_index": row.event_index}

    def reject(self, item_id: int, *, reviewer: str, note: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(ArchiveTimelineVerification, item_id)
            if row is None or row.status is not ArchiveTimelineVerificationStatus.PENDING:
                raise ArchiveTimelineNotFound("Questa verifica non è in attesa.")
            row.status = ArchiveTimelineVerificationStatus.REJECTED
            row.reviewed_by = reviewer
            row.review_note = note

    @staticmethod
    def _item(row: ArchiveTimelineVerification | None) -> dict | None:
        if row is None:
            return None
        return {
            "id": row.id,
            "slug": row.slug,
            "event_index": row.event_index,
            "official_url": row.official_url,
            "official_name": row.official_name,
            "status": row.status.value,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "reviewed_by": row.reviewed_by,
            "review_note": row.review_note,
        }
