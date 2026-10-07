from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.deps import get_admin_principal, get_session_factory
from backend.app.models import PledgeAssessmentDraftStatus, PledgeAssessmentOrigin
from backend.app.schemas import AdminPrincipal
from backend.app.schemas.pledge import (
    AuditCodingRequest,
    AuditQualityReport,
    AuditSampleRequest,
    AuditSampleResponse,
    BiasAuditResponse,
    PledgeApprovalRequest,
    PledgeAssessmentDraftResponse,
    PledgeAssessmentProposal,
    PledgeAssessmentResponse,
    PledgeClassificationRequest,
    PledgeClassificationResponse,
    PledgeRejectionRequest,
)
from backend.app.services.pledge_service import (
    NewAssessmentDraft,
    PledgeConflictError,
    PledgeNotFoundError,
    PledgeService,
    PledgeValidationError,
)


router = APIRouter(prefix="/pledges", tags=["admin-pledges"])


class ApprovalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    draft: PledgeAssessmentDraftResponse
    published: PledgeAssessmentResponse | None


def _service(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> PledgeService:
    return PledgeService(session_factory)


Service = Annotated[PledgeService, Depends(_service)]
Principal = Annotated[AdminPrincipal, Depends(get_admin_principal)]


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except PledgeNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PledgeValidationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except PledgeConflictError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error


@router.put("/{proposal_id}/classification", response_model=PledgeClassificationResponse)
def classify_pledge(
    proposal_id: Annotated[int, Path(gt=0)],
    payload: PledgeClassificationRequest,
    service: Service,
    principal: Principal,
) -> PledgeClassificationResponse:
    with _errors():
        return service.classify(
            proposal_id, payload, classified_by=principal.reviewer_identity
        )


@router.post(
    "/{proposal_id}/assessment-drafts",
    response_model=PledgeAssessmentDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
def propose_assessment(
    proposal_id: Annotated[int, Path(gt=0)],
    payload: PledgeAssessmentProposal,
    service: Service,
    principal: Principal,
) -> PledgeAssessmentDraftResponse:
    with _errors():
        draft, _created = service.propose(
            NewAssessmentDraft(
                proposal_id=proposal_id,
                proposal=payload,
                origin=PledgeAssessmentOrigin.EDITOR,
                created_by=principal.reviewer_identity,
            )
        )
        return draft


@router.get("/assessment-drafts", response_model=list[PledgeAssessmentDraftResponse])
def list_assessment_drafts(
    service: Service,
    draft_status: Annotated[
        PledgeAssessmentDraftStatus | None, Query(alias="status")
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[PledgeAssessmentDraftResponse]:
    return service.list_drafts(status=draft_status, offset=offset, limit=limit)


def _reviewer(principal: AdminPrincipal, declared: str | None) -> str:
    # The admin API has one shared credential. A declared name is recorded as an
    # attestation next to that credential; real four-eyes control needs per-user
    # authentication (see docs/scoring-methodology.md).
    if declared is None:
        return principal.reviewer_identity
    return f"{principal.reviewer_identity}/{declared.strip()}"


class ReviewerApprovalRequest(PledgeApprovalRequest):
    reviewer: str | None = None


@router.post("/assessment-drafts/{draft_id}/approve", response_model=ApprovalResult)
def approve_assessment(
    draft_id: Annotated[int, Path(gt=0)],
    service: Service,
    principal: Principal,
    payload: Annotated[ReviewerApprovalRequest, Body()] = ReviewerApprovalRequest(),
) -> ApprovalResult:
    with _errors():
        draft, published = service.approve(
            draft_id, reviewer=_reviewer(principal, payload.reviewer), note=payload.note
        )
        return ApprovalResult(draft=draft, published=published)


@router.post(
    "/assessment-drafts/{draft_id}/reject", response_model=PledgeAssessmentDraftResponse
)
def reject_assessment(
    draft_id: Annotated[int, Path(gt=0)],
    payload: PledgeRejectionRequest,
    service: Service,
    principal: Principal,
) -> PledgeAssessmentDraftResponse:
    with _errors():
        return service.reject(
            draft_id, reviewer=principal.reviewer_identity, note=payload.note
        )


@router.post(
    "/audit-samples", response_model=AuditSampleResponse, status_code=status.HTTP_201_CREATED
)
def draw_audit_sample(
    payload: AuditSampleRequest, service: Service, principal: Principal
) -> AuditSampleResponse:
    with _errors():
        return service.draw_audit_sample(
            sample_key=payload.sample_key,
            size=payload.size,
            seed=payload.seed,
            created_by=principal.reviewer_identity,
        )


@router.get("/audit-samples/{sample_key}", response_model=AuditSampleResponse)
def get_audit_sample(sample_key: str, service: Service) -> AuditSampleResponse:
    with _errors():
        return service.get_audit_sample(sample_key)


@router.post(
    "/audit-samples/{sample_key}/codings/{assessment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def record_audit_coding(
    sample_key: str,
    assessment_id: Annotated[int, Path(gt=0)],
    payload: AuditCodingRequest,
    service: Service,
    principal: Principal,
) -> None:
    with _errors():
        service.record_audit_coding(
            sample_key,
            assessment_id,
            coder=_reviewer(principal, payload.coder),
            verdict=payload.verdict,
            note=payload.note,
        )


@router.get("/audit-samples/{sample_key}/quality", response_model=AuditQualityReport)
def audit_quality(sample_key: str, service: Service) -> AuditQualityReport:
    with _errors():
        return service.audit_quality(sample_key)


@router.get("/bias-audit", response_model=BiasAuditResponse)
def bias_audit(
    service: Service,
    min_per_group: Annotated[int, Query(ge=2, le=1000)] = 5,
    flag_threshold: Annotated[float, Query(gt=0, le=1)] = 0.15,
) -> BiasAuditResponse:
    return service.bias_audit(min_per_group=min_per_group, flag_threshold=flag_threshold)
