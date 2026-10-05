from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from backend.app.api.deps import (
    get_admin_principal,
    get_db_session,
    get_session_factory,
)
from backend.app.models import (
    Proposal,
    ProposalDraft,
    ProposalDraftKind,
    ProposalDraftStatus,
    ProposalEvidence,
)
from backend.app.schemas import (
    AdminPrincipal,
    ProposalDraftDetailResponse,
    ProposalDraftListItem,
    ProposalDraftListResponse,
    ProposalEvidenceResponse,
    ProposalFinalReviewResponse,
    ProposalObservation,
    ProposalReviewResult,
    ProposalReviewStarted,
    ReviewNoteRequest,
)
from backend.app.services import ProposalDraftNotFoundError, ProposalReviewService


router = APIRouter(prefix="/proposals/drafts", tags=["admin-proposal-drafts"])


@router.get("", response_model=ProposalDraftListResponse)
def list_proposal_drafts(
    session: Annotated[Session, Depends(get_db_session)],
    draft_status: Annotated[
        ProposalDraftStatus | None, Query(alias="status")
    ] = None,
    kind: ProposalDraftKind | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ProposalDraftListResponse:
    filters = []
    if draft_status is not None:
        filters.append(ProposalDraft.status == draft_status)
    if kind is not None:
        filters.append(ProposalDraft.kind == kind)
    query = select(ProposalDraft, Proposal).join(Proposal)
    count_query = select(func.count(ProposalDraft.id))
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    active_first = case(
        (
            ProposalDraft.status.in_(
                (ProposalDraftStatus.PENDING, ProposalDraftStatus.IN_REVIEW)
            ),
            0,
        ),
        else_=1,
    )
    rows = session.execute(
        query.order_by(active_first, ProposalDraft.created_at.desc(), ProposalDraft.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    evidence_counts = {
        draft_id: count
        for draft_id, count in session.execute(
            select(ProposalEvidence.draft_id, func.count(ProposalEvidence.id))
            .where(ProposalEvidence.draft_id.in_([draft.id for draft, _ in rows]))
            .group_by(ProposalEvidence.draft_id)
        )
    } if rows else {}
    items = []
    for draft, proposal in rows:
        observation = ProposalObservation.model_validate(draft.proposed_data)
        unresolved = observation.metadata.get("_unresolved_actors", [])
        items.append(
            ProposalDraftListItem(
                id=draft.id,
                proposal_id=proposal.id,
                title=observation.title,
                proposal_type=observation.proposal_type,
                kind=draft.kind,
                status=draft.status,
                normalized_status=observation.normalized_status,
                source_status_label=observation.source_status_label,
                created_at=draft.created_at,
                evidence_count=evidence_counts.get(draft.id, 0),
                unresolved_actor_count=len(unresolved) if isinstance(unresolved, list) else 0,
            )
        )
    return ProposalDraftListResponse(
        items=tuple(items),
        total=session.scalar(count_query) or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/{draft_id}", response_model=ProposalDraftDetailResponse)
def get_proposal_draft(
    draft_id: int,
    session: Annotated[Session, Depends(get_db_session)],
) -> ProposalDraftDetailResponse:
    draft = session.scalar(
        select(ProposalDraft)
        .where(ProposalDraft.id == draft_id)
        .options(
            selectinload(ProposalDraft.evidence).selectinload(ProposalEvidence.source),
            selectinload(ProposalDraft.review),
        )
    )
    if draft is None:
        raise ProposalDraftNotFoundError(f"ProposalDraft {draft_id} does not exist")
    return ProposalDraftDetailResponse(
        id=draft.id,
        proposal_id=draft.proposal_id,
        kind=draft.kind,
        status=draft.status,
        baseline_status_event_id=draft.baseline_status_event_id,
        supersedes_id=draft.supersedes_id,
        proposed=ProposalObservation.model_validate(draft.proposed_data),
        evidence=tuple(
            ProposalEvidenceResponse(
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
            ProposalFinalReviewResponse(
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


@router.post("/{draft_id}/start-review", response_model=ProposalReviewStarted)
def start_proposal_review(
    draft_id: int,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> ProposalReviewStarted:
    return ProposalReviewService(session_factory).start_review(draft_id)


@router.post("/{draft_id}/approve", response_model=ProposalReviewResult)
def approve_proposal_draft(
    draft_id: int,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    principal: Annotated[AdminPrincipal, Depends(get_admin_principal)],
    payload: Annotated[ReviewNoteRequest, Body()] = ReviewNoteRequest(),
) -> ProposalReviewResult:
    return ProposalReviewService(session_factory).approve(
        draft_id, reviewer=principal.reviewer_identity, note=payload.note
    )


@router.post("/{draft_id}/reject", response_model=ProposalReviewResult)
def reject_proposal_draft(
    draft_id: int,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    principal: Annotated[AdminPrincipal, Depends(get_admin_principal)],
    payload: Annotated[ReviewNoteRequest, Body()] = ReviewNoteRequest(),
) -> ProposalReviewResult:
    return ProposalReviewService(session_factory).reject(
        draft_id, reviewer=principal.reviewer_identity, note=payload.note
    )
