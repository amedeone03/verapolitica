"""Citizen email/password accounts. Separate from redazione tokens."""

from __future__ import annotations

import re
import threading
import time
from datetime import date
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models.civic_account import CivicAccount, utc_now


_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_HASHER = PasswordHasher()
_DUMMY_HASH = _HASHER.hash("not-a-real-password-placeholder")
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
MAX_FAVORITES = 24
MAX_PARTIES = 24
MAX_SAVED = 50


class CivicAuthError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class CivicAuthConflict(CivicAuthError):
    def __init__(self, message: str = "questa email è già registrata") -> None:
        super().__init__(message, status_code=409)


class CivicAuthRejected(CivicAuthError):
    def __init__(self, message: str = "email o password non corretti") -> None:
        super().__init__(message, status_code=401)


class CivicAuthNotFound(CivicAuthError):
    def __init__(self) -> None:
        super().__init__("accesso non valido", status_code=401)


class AttemptLimiter:
    """In-process sliding window. Not shared across workers; proxy rate limits later."""

    def __init__(self, *, limit: int = 10, window_seconds: int = 900) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        stamp = now if now is not None else time.monotonic()
        with self._lock:
            recent = [item for item in self._hits.get(key, []) if stamp - item < self.window_seconds]
            if len(recent) >= self.limit:
                self._hits[key] = recent
                return False
            recent.append(stamp)
            self._hits[key] = recent
            return True


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if not _EMAIL.fullmatch(email) or len(email) > 254:
        raise CivicAuthError("email non valida")
    return email


def sanitize_profile(value: object, *, display_name: str = "", since: str | None = None) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    name = str(display_name or "").strip()[:40]
    favorites: list[dict[str, str]] = []
    for item in data.get("favorites") or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        if not item_id.isdigit():
            continue
        favorites.append({"id": item_id, "name": str(item.get("name") or "")[:200]})
        if len(favorites) >= MAX_FAVORITES:
            break
    parties: list[dict[str, Any]] = []
    for item in data.get("parties") or []:
        if not isinstance(item, dict):
            continue
        try:
            party_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        parties.append(
            {
                "id": party_id,
                "name": str(item.get("name") or "")[:200],
                "abbreviation": (str(item["abbreviation"])[:20] if item.get("abbreviation") else None),
                "logo_url": item.get("logo_url") if isinstance(item.get("logo_url"), str) else None,
            }
        )
        if len(parties) >= MAX_PARTIES:
            break
    saved: list[dict[str, str]] = []
    for item in data.get("saved") or []:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url.startswith("./?post="):
            continue
        saved.append({"url": url[:300], "title": str(item.get("title") or "")[:200]})
        if len(saved) >= MAX_SAVED:
            break
    incoming_member = data.get("member") if isinstance(data.get("member"), dict) else {}
    member_since = since or incoming_member.get("since") or date.today().isoformat()
    member_name = name or str(incoming_member.get("name") or "").strip()[:40]
    return {
        "zone": _zone(data.get("zone")),
        "favorites": favorites,
        "saved": saved,
        "parties": parties,
        "member": {"name": member_name, "since": str(member_since)[:10]} if member_name else None,
    }


def _zone(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not value:
        return None
    try:
        region_id = int(value["region_id"]) if value.get("region_id") is not None else None
    except (TypeError, ValueError):
        region_id = None
    if region_id is None:
        return None
    province = value.get("province")
    municipality_id = value.get("municipality_id")
    try:
        municipality = int(municipality_id) if municipality_id not in (None, "") else None
    except (TypeError, ValueError):
        municipality = None
    return {
        "region_id": region_id,
        "region_name": str(value.get("region_name") or "")[:120],
        "province": str(province).upper()[:2] if province else None,
        "province_name": str(value.get("province_name") or "")[:120] if province else None,
        "municipality_id": municipality,
        "municipality_name": str(value.get("municipality_name") or "")[:120] if municipality else None,
    }


def account_payload(account: CivicAccount) -> dict[str, Any]:
    profile = sanitize_profile(
        account.profile_json,
        display_name=account.display_name,
        since=account.created_at.date().isoformat() if account.created_at else None,
    )
    if account.display_name and profile.get("member"):
        profile["member"]["name"] = account.display_name
    return {
        "email": account.email,
        "display_name": account.display_name,
        "profile": profile,
    }


class CivicAccountService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def register(self, *, email: str, password: str, display_name: str = "") -> tuple[int, dict[str, Any]]:
        normalized = normalize_email(email)
        _require_password(password)
        hashed = _HASHER.hash(password)
        name = display_name.strip()[:40]
        account = CivicAccount(
            email=normalized,
            password_hash=hashed,
            display_name=name,
            profile_json=sanitize_profile({}, display_name=name),
        )
        try:
            with self.session_factory.begin() as session:
                session.add(account)
                session.flush()
                return account.id, account_payload(account)
        except IntegrityError as error:
            raise CivicAuthConflict() from error

    def login(self, *, email: str, password: str) -> tuple[int, dict[str, Any]]:
        try:
            normalized = normalize_email(email)
        except CivicAuthError as error:
            _waste_verify(password)
            raise CivicAuthRejected() from error
        with self.session_factory() as session:
            account = session.scalar(select(CivicAccount).where(CivicAccount.email == normalized))
            if account is None:
                _waste_verify(password)
                raise CivicAuthRejected()
            if not _verify(account.password_hash, password):
                raise CivicAuthRejected()
            if _HASHER.check_needs_rehash(account.password_hash):
                account.password_hash = _HASHER.hash(password)
                account.updated_at = utc_now()
                session.commit()
            return account.id, account_payload(account)

    def get(self, account_id: int) -> dict[str, Any]:
        with self.session_factory() as session:
            account = session.get(CivicAccount, account_id)
            if account is None:
                raise CivicAuthNotFound()
            return account_payload(account)

    def update_profile(self, account_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory.begin() as session:
            account = session.get(CivicAccount, account_id)
            if account is None:
                raise CivicAuthNotFound()
            name = str(payload.get("display_name") or "").strip()[:40]
            if not name:
                member = payload.get("member") if isinstance(payload.get("member"), dict) else {}
                name = str(member.get("name") or account.display_name or "").strip()[:40]
            if name:
                account.display_name = name
            since = account.created_at.date().isoformat() if account.created_at else None
            account.profile_json = sanitize_profile(payload, display_name=account.display_name, since=since)
            account.updated_at = utc_now()
            session.flush()
            return account_payload(account)


def _require_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise CivicAuthError(f"la password deve avere almeno {MIN_PASSWORD_LENGTH} caratteri")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise CivicAuthError("la password è troppo lunga")


def _verify(stored: str, password: str) -> bool:
    try:
        return _HASHER.verify(stored, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _waste_verify(password: str) -> None:
    try:
        _HASHER.verify(_DUMMY_HASH, password)
    except (VerifyMismatchError, InvalidHashError):
        return
