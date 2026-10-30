from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.deps import get_admin_principal, get_session_factory
from backend.app.models import EditorialPostStatus
from backend.app.schemas import AdminPrincipal
from backend.app.schemas.feed import (
    EditorialPostList,
    EditorialPostRequest,
    EditorialPostResponse,
    EditorialReviewRequest,
)
from backend.app.services.editorial_service import (
    EditorialConflictError,
    EditorialNotFoundError,
    EditorialService,
    EditorialValidationError,
)


router = APIRouter(prefix="/editorial/posts", tags=["admin-editorial"])
Principal = Annotated[AdminPrincipal, Depends(get_admin_principal)]


def _service(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> EditorialService:
    return EditorialService(session_factory)


Service = Annotated[EditorialService, Depends(_service)]


def _attested(principal: AdminPrincipal, declared: str | None) -> str:
    # One shared admin credential: a declared name is an attestation recorded
    # next to it, not an authenticated identity (see docs/civic-features.md).
    if declared is None:
        return principal.reviewer_identity
    return f"{principal.reviewer_identity}/{declared.strip()}"


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except EditorialNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except EditorialValidationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except EditorialConflictError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error


@router.post("", response_model=EditorialPostResponse, status_code=status.HTTP_201_CREATED)
def create_post(payload: EditorialPostRequest, service: Service, principal: Principal) -> EditorialPostResponse:
    with _errors():
        return service.create(payload, author=_attested(principal, payload.author))


@router.get("", response_model=EditorialPostList)
def list_posts(
    service: Service,
    post_status: Annotated[EditorialPostStatus | None, Query(alias="status")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> EditorialPostList:
    return service.list(status=post_status, offset=offset, limit=limit)


@router.post("/{post_id}/publish", response_model=EditorialPostResponse)
def publish_post(
    post_id: Annotated[int, Path(gt=0)],
    payload: EditorialReviewRequest,
    service: Service,
    principal: Principal,
) -> EditorialPostResponse:
    with _errors():
        return service.publish(
            post_id, reviewer=_attested(principal, payload.reviewer), note=payload.note
        )


@router.post("/{post_id}/reject", response_model=EditorialPostResponse)
def reject_post(
    post_id: Annotated[int, Path(gt=0)],
    payload: EditorialReviewRequest,
    service: Service,
    principal: Principal,
) -> EditorialPostResponse:
    if not payload.note:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "a rejection needs a note")
    with _errors():
        return service.reject(
            post_id, reviewer=_attested(principal, payload.reviewer), note=payload.note
        )
