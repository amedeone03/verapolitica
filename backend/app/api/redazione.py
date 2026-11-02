"""Redazione console API (``/redazione/api``).

Every call is made by a named member of the redazione: each member has their
own token (``VERAPOLITICA_REDAZIONE_MEMBERS``), so the log and the approval
rules know who wrote and who verified. The console UI lives at ``/redazione``.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Security, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.deps import get_api_settings, get_session_factory
from backend.app.core.config import DEMO_REDAZIONE_MEMBERS, Settings
from backend.app.models import CAP_MAJOR_TOPICS
from backend.app.services.redazione import card as card_module
from backend.app.services.redazione import style
from backend.app.services.redazione.service import RedazioneError, RedazioneService


router = APIRouter(prefix="/redazione/api", tags=["redazione"])
_bearer = HTTPBearer(auto_error=False)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def current_member(
    settings: Annotated[Settings, Depends(get_api_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
) -> str:
    members = settings.redazione_member_tokens
    if not members:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "redazione non configurata")
    provided = credentials.credentials if credentials and credentials.scheme.casefold() == "bearer" else ""
    for token, name in members.items():
        if secrets.compare_digest(_digest(provided), _digest(token)):
            return name
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "accesso redazione non valido",
        headers={"WWW-Authenticate": "Bearer"},
    )


Member = Annotated[str, Depends(current_member)]


def get_service(factory: Annotated[sessionmaker[Session], Depends(get_session_factory)]) -> RedazioneService:
    return RedazioneService(factory)


Service = Annotated[RedazioneService, Depends(get_service)]


def _run(call, *args, **kwargs) -> Any:
    try:
        return call(*args, **kwargs)
    except RedazioneError as error:
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": str(error), "findings": error.findings},
        )


@router.get("/accesso")
def access(settings: Annotated[Settings, Depends(get_api_settings)]) -> dict:
    """What the sign-in page shows. Demo members are listed only on local demos."""

    members = settings.redazione_member_tokens
    demo = not settings.is_production and members == DEMO_REDAZIONE_MEMBERS
    return {
        "configured": bool(members),
        "demo_members": [{"name": name, "token": token} for token, name in members.items()] if demo else [],
    }


@router.get("/me")
def me(member: Member, settings: Annotated[Settings, Depends(get_api_settings)]) -> dict:
    return {
        "name": member,
        "members": sorted(set(settings.redazione_member_tokens.values())),
        "demo": not settings.is_production,
    }


@router.get("/panoramica")
def overview(member: Member, service: Service) -> Any:
    return _run(service.overview, member=member)


@router.get("/regole")
def rules(member: Member) -> dict:
    del member
    return {
        "news_blocks": [
            {"key": key, "label": label, "min": low, "max": high} for key, label, low, high in style.NEWS_BLOCKS
        ],
        "news_total": list(style.NEWS_TOTAL_WORDS),
        "source_areas": style.SOURCE_AREAS,
        "loaded_title_words": list(style.LOADED_TITLE_WORDS),
        "judgement_words": list(style.JUDGEMENT_WORDS),
        "unattributed": list(style.UNATTRIBUTED),
        "topics": CAP_MAJOR_TOPICS,
    }


@router.get("/coda")
def queue(member: Member, service: Service) -> Any:
    return _run(service.queue, member=member)


@router.post("/coda/{kind}/{item_id}/approva")
def approve(
    kind: Annotated[str, Path(max_length=20)],
    item_id: Annotated[int, Path(gt=0)],
    member: Member,
    service: Service,
    payload: Annotated[dict, Body()] = {},
) -> Any:
    return _run(
        service.approve,
        kind,
        item_id,
        member=member,
        note=payload.get("note"),
        extra={"classification": payload.get("classification")},
    )


@router.post("/coda/{kind}/{item_id}/rifiuta")
def reject(
    kind: Annotated[str, Path(max_length=20)],
    item_id: Annotated[int, Path(gt=0)],
    member: Member,
    service: Service,
    payload: Annotated[dict, Body()] = {},
) -> Any:
    return _run(service.reject, kind, item_id, member=member, note=payload.get("note") or "")


@router.get("/politici")
def politicians(
    member: Member,
    service: Service,
    q: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> Any:
    del member
    return _run(service.search_politicians, q, limit=limit)


@router.get("/politici/{politician_id}")
def scheda(politician_id: Annotated[int, Path(gt=0)], member: Member, service: Service) -> Any:
    return _run(service.scheda, politician_id, member=member)


@router.post("/politici/{politician_id}/blocchi/{kind}")
def save_block(
    politician_id: Annotated[int, Path(gt=0)],
    kind: Annotated[str, Path(max_length=20)],
    member: Member,
    service: Service,
    payload: Annotated[dict, Body()],
) -> Any:
    return _run(service.save_profile_block, politician_id, kind, payload, member=member)


@router.post("/contenuti/{kind}/{content_id}/ritira")
def withdraw(
    kind: Annotated[str, Path(max_length=20)],
    content_id: Annotated[int, Path(gt=0)],
    member: Member,
    service: Service,
    payload: Annotated[dict, Body()],
) -> Any:
    return _run(service.request_withdrawal, kind, content_id, reason=payload.get("reason") or "", member=member)


@router.post("/politici/{politician_id}/promesse")
def create_promise(
    politician_id: Annotated[int, Path(gt=0)],
    member: Member,
    service: Service,
    payload: Annotated[dict, Body()],
) -> Any:
    return _run(service.create_promise, politician_id, payload, member=member)


@router.post("/promesse/{proposal_id}/stato")
def propose_status(
    proposal_id: Annotated[int, Path(gt=0)],
    member: Member,
    service: Service,
    payload: Annotated[dict, Body()],
) -> Any:
    return _run(service.propose_status, proposal_id, payload, member=member)


@router.post("/promesse/{proposal_id}/classificazione")
def reclassify(
    proposal_id: Annotated[int, Path(gt=0)],
    member: Member,
    service: Service,
    payload: Annotated[dict, Body()],
) -> Any:
    return _run(service.request_reclassification, proposal_id, payload, member=member)


@router.post("/immagini")
def upload_image(member: Member, service: Service, payload: Annotated[dict, Body()]) -> Any:
    return _run(service.upload_image, payload, member=member)


@router.get("/partiti")
def parties(member: Member, service: Service) -> Any:
    del member
    return _run(service.list_parties)


@router.post("/partiti")
def propose_party(member: Member, service: Service, payload: Annotated[dict, Body()]) -> Any:
    return _run(service.propose_party, payload, member=member)


@router.put("/partiti/{party_id}")
def propose_party_edit(party_id: int, member: Member, service: Service, payload: Annotated[dict, Body()]) -> Any:
    return _run(service.propose_party_edit, party_id, payload, member=member)


@router.get("/simboli")
def symbols(member: Member, service: Service) -> Any:
    del member
    return _run(service.symbols)


@router.post("/simboli")
def propose_symbol(member: Member, service: Service, payload: Annotated[dict, Body()]) -> Any:
    return _run(service.propose_symbol, payload, member=member)


@router.get("/card")
def card_options(member: Member) -> dict:
    del member
    return card_module.options()


@router.get("/notizie")
def news_list(member: Member, service: Service) -> Any:
    return _run(service.list_news, member=member)


@router.get("/notizie/{post_id}")
def news_detail(post_id: Annotated[int, Path(gt=0)], member: Member, service: Service) -> Any:
    return _run(service.news, post_id, member=member)


@router.post("/notizie")
def news_create(member: Member, service: Service, payload: Annotated[dict, Body()]) -> Any:
    return _run(service.save_news, payload, member=member)


@router.put("/notizie/{post_id}")
def news_update(
    post_id: Annotated[int, Path(gt=0)], member: Member, service: Service, payload: Annotated[dict, Body()]
) -> Any:
    return _run(service.save_news, payload, member=member, post_id=post_id)


@router.post("/controlla/notizia")
def check_news(member: Member, payload: Annotated[dict, Body()]) -> dict:
    del member
    return {"findings": [item.as_dict() for item in style.news_findings(payload)]}


@router.post("/controlla/{kind}")
def check_block(kind: Annotated[str, Path(max_length=20)], member: Member, payload: Annotated[dict, Body()]) -> dict:
    del member
    if kind == "promise":
        findings = style.promise_findings(payload)
    elif kind == "status":
        findings = style.verdict_findings(payload)
    else:
        findings = style.profile_findings(kind, payload)
    return {"findings": [item.as_dict() for item in findings]}


@router.get("/registro")
def log(
    member: Member,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    politico: Annotated[int | None, Query(gt=0)] = None,
    utente: Annotated[str | None, Query(max_length=200)] = None,
) -> Any:
    del member
    return _run(service.log_entries, limit=limit, offset=offset, politician_id=politico, actor=utente)
