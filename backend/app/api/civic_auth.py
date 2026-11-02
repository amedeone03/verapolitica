"""Citizen account HTTP API (``/auth``).

Email + password, HttpOnly cookie. A civic session is not a redazione or admin
credential.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.deps import get_api_settings, get_session_factory
from backend.app.core.config import Settings
from backend.app.services.civic_account_service import (
    AttemptLimiter,
    CivicAccountService,
    CivicAuthError,
    CivicAuthNotFound,
)


router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE_NAME = "vp_civic"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class CredentialsBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().casefold()
        if not _EMAIL.fullmatch(email):
            raise ValueError("email non valida")
        return email


class ProfileBody(BaseModel):
    display_name: str | None = Field(default=None, max_length=40)
    member: dict[str, Any] | None = None
    zone: dict[str, Any] | None = None
    favorites: list[dict[str, Any]] | None = None
    parties: list[dict[str, Any]] | None = None
    saved: list[dict[str, Any]] | None = None


def get_limiter(request: Request) -> AttemptLimiter:
    limiter = getattr(request.app.state, "civic_limiter", None)
    if limiter is None:
        limiter = AttemptLimiter()
        request.app.state.civic_limiter = limiter
    return limiter


def get_civic_service(
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> CivicAccountService:
    return CivicAccountService(factory)


def _cookie_secure(settings: Settings) -> bool:
    return settings.is_production or settings.public_base_url.strip().lower().startswith("https://")


def _signer(settings: Settings) -> TimestampSigner:
    key = settings.session_signing_key
    if not key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "session secret non configurato")
    return TimestampSigner(key)


def _set_session(response: Response, settings: Settings, account_id: int) -> None:
    token = _signer(settings).sign(str(account_id)).decode("ascii")
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(settings),
        path="/",
    )


def _clear_session(response: Response, settings: Settings) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", samesite="lax", secure=_cookie_secure(settings))


def _account_id_from_cookie(request: Request, settings: Settings) -> int:
    raw = request.cookies.get(COOKIE_NAME, "")
    if not raw:
        raise CivicAuthNotFound()
    try:
        payload = _signer(settings).unsign(raw, max_age=COOKIE_MAX_AGE)
        return int(payload)
    except (BadSignature, SignatureExpired, ValueError, TypeError) as error:
        raise CivicAuthNotFound() from error


def _run(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except CivicAuthError as error:
        raise HTTPException(error.status_code, str(error)) from error


def _client_key(request: Request, action: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{action}:{host}"


def _rate_limit(limiter: AttemptLimiter, request: Request, action: str) -> None:
    if not limiter.allow(_client_key(request, action)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "troppi tentativi, riprova più tardi",
            headers={"Retry-After": "60"},
        )


@router.post("/register")
def register(
    body: CredentialsBody,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_api_settings)],
    service: Annotated[CivicAccountService, Depends(get_civic_service)],
    limiter: Annotated[AttemptLimiter, Depends(get_limiter)],
) -> dict[str, Any]:
    _rate_limit(limiter, request, "register")
    account_id, payload = _run(service.register, email=body.email, password=body.password)
    _set_session(response, settings, account_id)
    return payload


@router.post("/login")
def login(
    body: CredentialsBody,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_api_settings)],
    service: Annotated[CivicAccountService, Depends(get_civic_service)],
    limiter: Annotated[AttemptLimiter, Depends(get_limiter)],
) -> dict[str, Any]:
    _rate_limit(limiter, request, "login")
    account_id, payload = _run(service.login, email=body.email, password=body.password)
    _set_session(response, settings, account_id)
    return payload


@router.post("/logout")
def logout(
    response: Response,
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> dict[str, bool]:
    _clear_session(response, settings)
    return {"ok": True}


@router.get("/me")
def me(
    request: Request,
    settings: Annotated[Settings, Depends(get_api_settings)],
    service: Annotated[CivicAccountService, Depends(get_civic_service)],
) -> dict[str, Any]:
    account_id = _run(_account_id_from_cookie, request, settings)
    return _run(service.get, account_id)


@router.put("/profile")
def update_profile(
    body: ProfileBody,
    request: Request,
    settings: Annotated[Settings, Depends(get_api_settings)],
    service: Annotated[CivicAccountService, Depends(get_civic_service)],
) -> dict[str, Any]:
    account_id = _run(_account_id_from_cookie, request, settings)
    return _run(service.update_profile, account_id, body.model_dump())
