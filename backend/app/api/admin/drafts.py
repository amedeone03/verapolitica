from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from backend.app.api.deps import (
    get_admin_principal,
    get_db_session,
    get_session_factory,
)
from backend.app.models import (
    Evidence,
    Politician,
    PoliticianVersion,
    ProfileDraft,
    ProfileDraftKind,
    ProfileDraftStatus,
    RawDocument,
    Source,
)
from backend.app.schemas import (
    AdminPrincipal,
    DraftDetailResponse,
    DraftListItem,
    DraftListResponse,
    EvidenceResponse,
    FinalReviewResponse,
    PoliticianSummary,
    PoliticianVersionContext,
    PoliticianVersionProfile,
    ProfileDiff,
    RawDocumentSourceResponse,
    ReviewDecisionResult,
    ReviewNoteRequest,
    ReviewStartedResult,
)
from backend.app.services import (
    DraftNotFoundError,
    PublishService,
    ReviewService,
)


router = APIRouter(prefix="/drafts", tags=["admin-drafts"])


@router.get("", response_model=DraftListResponse)
def list_drafts(
    session: Annotated[Session, Depends(get_db_session)],
    draft_status: Annotated[
        ProfileDraftStatus | None,
        Query(alias="status"),
    ] = None,
    kind: ProfileDraftKind | None = None,
    politician_id: Annotated[int | None, Query(gt=0)] = None,
    source_key: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DraftListResponse:
    if (
        created_after is not None
        and created_before is not None
        and created_after > created_before
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="created_after must not be later than created_before",
        )

    filters = []
    if draft_status is not None:
        filters.append(ProfileDraft.status == draft_status)
    if kind is not None:
        filters.append(ProfileDraft.kind == kind)
    if politician_id is not None:
        filters.append(ProfileDraft.politician_id == politician_id)
    if created_after is not None:
        filters.append(ProfileDraft.created_at >= created_after)
    if created_before is not None:
        filters.append(ProfileDraft.created_at <= created_before)

    query = select(ProfileDraft).options(
        selectinload(ProfileDraft.politician),
        selectinload(ProfileDraft.review),
    )
    count_query = select(func.count(ProfileDraft.id))
    if source_key is not None:
        source_filter = Source.key == source_key
        query = query.join(RawDocument).join(Source).where(source_filter)
        count_query = (
            count_query.select_from(ProfileDraft)
            .join(RawDocument)
            .join(Source)
            .where(source_filter)
        )
    else:
        count_query = count_query.select_from(ProfileDraft)
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)

    active_first = case(
        (
            ProfileDraft.status.in_(
                (ProfileDraftStatus.PENDING, ProfileDraftStatus.IN_REVIEW)
            ),
            0,
        ),
        else_=1,
    )
    drafts = list(
        session.scalars(
            query.order_by(
                active_first,
                ProfileDraft.created_at.desc(),
                ProfileDraft.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
    )
    evidence_counts = _evidence_counts(session, [draft.id for draft in drafts])
    return DraftListResponse(
        items=tuple(
            DraftListItem(
                id=draft.id,
                politician_id=draft.politician_id,
                politician_name=(
                    f"{draft.politician.canonical_given_name} "
                    f"{draft.politician.canonical_family_name}"
                ).strip(),
                kind=draft.kind,
                status=draft.status,
                baseline_version_id=draft.baseline_version_id,
                created_at=draft.created_at,
                updated_at=draft.updated_at,
                evidence_count=evidence_counts.get(draft.id, 0),
                change_count=_change_count(draft.diff_data),
                supersedes_id=draft.supersedes_id,
                final_review_decision=(
                    draft.review.decision if draft.review is not None else None
                ),
            )
            for draft in drafts
        ),
        total=session.scalar(count_query) or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/{draft_id}", response_model=DraftDetailResponse)
def get_draft(
    draft_id: int,
    session: Annotated[Session, Depends(get_db_session)],
) -> DraftDetailResponse:
    draft = session.scalar(
        select(ProfileDraft)
        .where(ProfileDraft.id == draft_id)
        .options(
            selectinload(ProfileDraft.politician).selectinload(
                Politician.current_version
            ),
            selectinload(ProfileDraft.baseline_version),
            selectinload(ProfileDraft.raw_document).selectinload(RawDocument.source),
            selectinload(ProfileDraft.evidence),
            selectinload(ProfileDraft.review),
            selectinload(ProfileDraft.supersedes),
        )
    )
    if draft is None:
        raise DraftNotFoundError(f"ProfileDraft {draft_id} does not exist")

    politician = draft.politician
    document = draft.raw_document
    superseded_by_ids = tuple(
        session.scalars(
            select(ProfileDraft.id)
            .where(ProfileDraft.supersedes_id == draft.id)
            .order_by(ProfileDraft.id)
        )
    )
    return DraftDetailResponse(
        id=draft.id,
        politician=PoliticianSummary(
            id=politician.id,
            given_name=politician.canonical_given_name,
            family_name=politician.canonical_family_name,
            birth_date=politician.birth_date,
            current_version_id=politician.current_version_id,
        ),
        kind=draft.kind,
        status=draft.status,
        profile_schema_version=draft.profile_schema_version,
        baseline_version_id=draft.baseline_version_id,
        raw_document_id=draft.raw_document_id,
        supersedes_id=draft.supersedes_id,
        superseded_draft_ids=_superseded_chain_ids(draft),
        superseded_by_draft_ids=superseded_by_ids,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        proposed_profile=PoliticianVersionProfile.model_validate(
            draft.proposed_profile_data
        ),
        diff=ProfileDiff.model_validate(draft.diff_data),
        evidence=tuple(
            EvidenceResponse(
                id=item.id,
                field_path=item.field_path,
                raw_document_id=item.raw_document_id,
                source_url=item.source_url,
                source_record_identifier=item.source_record_identifier,
                source_field_name=item.source_field_name,
                source_value=item.source_value,
                extraction_method=item.extraction_method,
                created_at=item.created_at,
            )
            for item in draft.evidence
        ),
        source_document=RawDocumentSourceResponse(
            id=document.id,
            source_key=document.source.key,
            source_name=document.source.name,
            source_url=document.source_url,
            retrieved_at=document.retrieved_at,
            raw_sha256=document.raw_sha256,
            normalized_sha256=document.normalized_sha256,
            collector_version=document.collector_version,
            parser_version=document.parser_version,
        ),
        baseline_version=_version_context(draft.baseline_version),
        current_version=_version_context(politician.current_version),
        final_review=(
            FinalReviewResponse(
                id=draft.review.id,
                reviewer=draft.review.reviewer,
                decision=draft.review.decision,
                note=draft.review.note,
                created_at=draft.review.created_at,
            )
            if draft.review is not None
            else None
        ),
    )


@router.post(
    "/{draft_id}/start-review",
    response_model=ReviewStartedResult,
)
def start_review(
    draft_id: int,
    session_factory: Annotated[
        sessionmaker[Session],
        Depends(get_session_factory),
    ],
) -> ReviewStartedResult:
    return ReviewService(session_factory).start_review(draft_id)


@router.post(
    "/{draft_id}/approve",
    response_model=ReviewDecisionResult,
)
def approve_draft(
    draft_id: int,
    session_factory: Annotated[
        sessionmaker[Session],
        Depends(get_session_factory),
    ],
    principal: Annotated[AdminPrincipal, Depends(get_admin_principal)],
    payload: Annotated[ReviewNoteRequest, Body()] = ReviewNoteRequest(),
) -> ReviewDecisionResult:
    return PublishService(session_factory).approve(
        draft_id,
        reviewer=principal.reviewer_identity,
        note=payload.note,
    )


@router.post(
    "/{draft_id}/reject",
    response_model=ReviewDecisionResult,
)
def reject_draft(
    draft_id: int,
    session_factory: Annotated[
        sessionmaker[Session],
        Depends(get_session_factory),
    ],
    principal: Annotated[AdminPrincipal, Depends(get_admin_principal)],
    payload: Annotated[ReviewNoteRequest, Body()] = ReviewNoteRequest(),
) -> ReviewDecisionResult:
    return ReviewService(session_factory).reject(
        draft_id,
        reviewer=principal.reviewer_identity,
        note=payload.note,
    )


def _evidence_counts(session: Session, draft_ids: list[int]) -> dict[int, int]:
    if not draft_ids:
        return {}
    return {
        draft_id: count
        for draft_id, count in session.execute(
            select(Evidence.draft_id, func.count(Evidence.id))
            .where(Evidence.draft_id.in_(draft_ids))
            .group_by(Evidence.draft_id)
        )
    }


def _change_count(diff_data: dict) -> int:
    changes = diff_data.get("changes")
    return len(changes) if isinstance(changes, list) else 0


def _version_context(
    version: PoliticianVersion | None,
) -> PoliticianVersionContext | None:
    if version is None:
        return None
    return PoliticianVersionContext(
        id=version.id,
        version_number=version.version_number,
        profile_schema_version=version.profile_schema_version,
        profile_data=PoliticianVersionProfile.model_validate(version.profile_data),
        created_at=version.created_at,
        published_at=version.published_at,
    )


def _superseded_chain_ids(draft: ProfileDraft) -> tuple[int, ...]:
    identifiers = []
    seen = set()
    current = draft.supersedes
    while current is not None and current.id not in seen:
        identifiers.append(current.id)
        seen.add(current.id)
        current = current.supersedes
    return tuple(identifiers)
