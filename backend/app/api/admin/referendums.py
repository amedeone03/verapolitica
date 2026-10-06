from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from backend.app.api.deps import (
    get_admin_principal,
    get_db_session,
    get_session_factory,
)
from backend.app.models.civic import (
    Referendum,
    ReferendumDraft,
    ReferendumDraftKind,
    ReferendumDraftStatus,
    ReferendumEvidence,
)
from backend.app.schemas import AdminPrincipal, ReviewNoteRequest
from backend.app.schemas.civic import (
    ReferendumDraftDetailResponse,
    ReferendumDraftListItem,
    ReferendumDraftListResponse,
    ReferendumEvidenceResponse,
    ReferendumFinalReviewResponse,
    ReferendumObservation,
    ReferendumReviewResult,
    ReferendumReviewStarted,
)
from backend.app.services.referendum_review_service import (
    ReferendumDraftNotFoundError,
    ReferendumReviewService,
)


router = APIRouter(prefix="/referendums/drafts", tags=["admin-referendum-drafts"])


@router.get("", response_model=ReferendumDraftListResponse)
def list_referendum_drafts(
    session: Annotated[Session, Depends(get_db_session)],
    draft_status: Annotated[
        ReferendumDraftStatus | None, Query(alias="status")
    ] = None,
    kind: ReferendumDraftKind | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ReferendumDraftListResponse:
    filters = []
    if draft_status is not None:
        filters.append(ReferendumDraft.status == draft_status)
    if kind is not None:
        filters.append(ReferendumDraft.kind == kind)
    query = select(ReferendumDraft, Referendum).join(Referendum)
    count_query = select(func.count(ReferendumDraft.id))
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    active_first = case(
        (
            ReferendumDraft.status.in_(
                (ReferendumDraftStatus.PENDING, ReferendumDraftStatus.IN_REVIEW)
            ),
            0,
        ),
        else_=1,
    )
    rows = session.execute(
        query.order_by(
            active_first, ReferendumDraft.created_at.desc(), ReferendumDraft.id.desc()
        )
        .offset(offset)
        .limit(limit)
    ).all()
    evidence_counts = (
        {
            draft_id: count
            for draft_id, count in session.execute(
                select(ReferendumEvidence.draft_id, func.count(ReferendumEvidence.id))
                .where(ReferendumEvidence.draft_id.in_([draft.id for draft, _ in rows]))
                .group_by(ReferendumEvidence.draft_id)
            ).all()
        }
        if rows
        else {}
    )
    items = []
    for draft, referendum in rows:
        observation = ReferendumObservation.model_validate(draft.proposed_data)
        items.append(
            ReferendumDraftListItem(
                id=draft.id,
                referendum_id=referendum.id,
                title=observation.title,
                referendum_type=observation.referendum_type,
                kind=draft.kind,
                status=draft.status,
                vote_date=observation.vote_date,
                created_at=draft.created_at,
                evidence_count=evidence_counts.get(draft.id, 0),
            )
        )
    return ReferendumDraftListResponse(
        items=tuple(items),
        total=session.scalar(count_query) or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/{draft_id}", response_model=ReferendumDraftDetailResponse)
def get_referendum_draft(
    draft_id: int,
    session: Annotated[Session, Depends(get_db_session)],
) -> ReferendumDraftDetailResponse:
    draft = session.scalar(
        select(ReferendumDraft)
        .where(ReferendumDraft.id == draft_id)
        .options(
            selectinload(ReferendumDraft.evidence).selectinload(
                ReferendumEvidence.source
            ),
            selectinload(ReferendumDraft.review),
        )
    )
    if draft is None:
        raise ReferendumDraftNotFoundError(
            f"ReferendumDraft {draft_id} does not exist"
        )
    return ReferendumDraftDetailResponse(
        id=draft.id,
        referendum_id=draft.referendum_id,
        kind=draft.kind,
        status=draft.status,
        supersedes_id=draft.supersedes_id,
        proposed=ReferendumObservation.model_validate(draft.proposed_data),
        evidence=tuple(
            ReferendumEvidenceResponse(
                id=item.id,
                field_path=item.field_path,
                source_name=item.source.name,
                source_url=item.source_url,
                source_field=item.source_field,
                source_value=item.source_value,
                observed_at=item.observed_at,
            )
            for item in draft.evidence
        ),
        final_review=(
            ReferendumFinalReviewResponse(
                id=draft.review.id,
                reviewer=draft.review.reviewer,
                decision=draft.review.decision,
                note=draft.review.note,
                created_at=draft.review.created_at,
            )
            if draft.review
            else None
        ),
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


@router.post("/{draft_id}/start-review", response_model=ReferendumReviewStarted)
def start_referendum_review(
    draft_id: int,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> ReferendumReviewStarted:
    return ReferendumReviewService(session_factory).start_review(draft_id)


@router.post("/{draft_id}/approve", response_model=ReferendumReviewResult)
def approve_referendum_draft(
    draft_id: int,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    principal: Annotated[AdminPrincipal, Depends(get_admin_principal)],
    payload: Annotated[ReviewNoteRequest, Body()] = ReviewNoteRequest(),
) -> ReferendumReviewResult:
    return ReferendumReviewService(session_factory).approve(
        draft_id, reviewer=principal.reviewer_identity, note=payload.note
    )


@router.post("/{draft_id}/reject", response_model=ReferendumReviewResult)
def reject_referendum_draft(
    draft_id: int,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    principal: Annotated[AdminPrincipal, Depends(get_admin_principal)],
    payload: Annotated[ReviewNoteRequest, Body()] = ReviewNoteRequest(),
) -> ReferendumReviewResult:
    return ReferendumReviewService(session_factory).reject(
        draft_id, reviewer=principal.reviewer_identity, note=payload.note
    )
