from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.deps import get_admin_principal, get_session_factory
from backend.app.models.politician_profile import (
    ProfileContentKind,
    ProfileContentStatus,
)
from backend.app.schemas import AdminPrincipal, ReviewNoteRequest
from backend.app.schemas.politician_profile import (
    AdminProfileContentDetail,
    AdminProfileContentList,
    EditorialPreviewResponse,
    SourceCompleteness,
)
from backend.app.services.politician_profile_service import (
    PoliticianProfileConflictError,
    PoliticianProfileNotFoundError,
    PoliticianProfileService,
    PoliticianProfileValidationError,
)


router = APIRouter(prefix="/profile-content", tags=["admin-profile-content"])


def _service(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> PoliticianProfileService:
    return PoliticianProfileService(session_factory)


Service = Annotated[PoliticianProfileService, Depends(_service)]
Principal = Annotated[AdminPrincipal, Depends(get_admin_principal)]


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except PoliticianProfileNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PoliticianProfileValidationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except PoliticianProfileConflictError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error


@router.get("", response_model=AdminProfileContentList)
def list_profile_content(
    service: Service,
    kind: ProfileContentKind | None = None,
    content_status: Annotated[
        ProfileContentStatus | None, Query(alias="status")
    ] = None,
    politician_id: Annotated[int | None, Query(gt=0)] = None,
    source_completeness: SourceCompleteness | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminProfileContentList:
    return service.list_admin(
        kind=kind,
        status=content_status,
        politician_id=politician_id,
        source_completeness=source_completeness,
        offset=offset,
        limit=limit,
    )


@router.get("/{kind}/{content_id}", response_model=AdminProfileContentDetail)
def get_profile_content(
    kind: ProfileContentKind,
    content_id: Annotated[int, Path(gt=0)],
    service: Service,
) -> AdminProfileContentDetail:
    with _errors():
        return service.get_admin(kind, content_id)


@router.post("/{kind}/{content_id}/approve", response_model=AdminProfileContentDetail)
def approve_profile_content(
    kind: ProfileContentKind,
    content_id: Annotated[int, Path(gt=0)],
    service: Service,
    principal: Principal,
    payload: Annotated[ReviewNoteRequest, Body()] = ReviewNoteRequest(),
) -> AdminProfileContentDetail:
    with _errors():
        return service.approve(
            kind, content_id, reviewer=principal.reviewer_identity, note=payload.note
        )


@router.post("/{kind}/{content_id}/reject", response_model=AdminProfileContentDetail)
def reject_profile_content(
    kind: ProfileContentKind,
    content_id: Annotated[int, Path(gt=0)],
    service: Service,
    principal: Principal,
    payload: Annotated[ReviewNoteRequest, Body()] = ReviewNoteRequest(),
) -> AdminProfileContentDetail:
    with _errors():
        return service.reject(
            kind, content_id, reviewer=principal.reviewer_identity, note=payload.note
        )


politicians_router = APIRouter(prefix="/politicians", tags=["admin-profile-preview"])


@politicians_router.get(
    "/{politician_id}/editorial-preview",
    response_model=EditorialPreviewResponse,
)
def editorial_preview(
    politician_id: Annotated[int, Path(gt=0)],
    service: Service,
) -> EditorialPreviewResponse:
    with _errors():
        return service.editorial_preview(politician_id)


@politicians_router.get("/{politician_id}/reference-readiness")
def reference_readiness(
    politician_id: Annotated[int, Path(gt=0)],
    service: Service,
) -> dict:
    with _errors():
        return service.reference_readiness(politician_id)
