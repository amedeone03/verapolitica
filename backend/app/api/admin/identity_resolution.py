from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from pydantic import TypeAdapter
from sqlalchemy import case as sql_case
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from backend.app.api.deps import (
    get_admin_principal,
    get_db_session,
    get_session_factory,
)
from backend.app.models import (
    IdentityResolutionCase,
    IdentityResolutionStatus,
    Source,
)
from backend.app.schemas import (
    AdminPrincipal,
    CandidateProfile,
    IdentityResolutionDecisionResult,
    IdentityResolutionDetailResponse,
    IdentityResolutionListItem,
    IdentityResolutionListResponse,
    IdentityResolutionNoteRequest,
    IdentityResolutionSourceResponse,
    IdentitySourceIdentifierResponse,
    MatchingResult,
    PoliticianSummary,
    PossiblePoliticianMatchResponse,
    ResolveExistingIdentityRequest,
)
from backend.app.services import (
    IdentityResolutionCaseNotFoundError,
    IdentityResolutionService,
)


router = APIRouter(
    prefix="/identity-resolution",
    tags=["admin-identity-resolution"],
)
_MATCHING_RESULT_ADAPTER = TypeAdapter(MatchingResult)


@router.get("", response_model=IdentityResolutionListResponse)
def list_identity_resolution_cases(
    session: Annotated[Session, Depends(get_db_session)],
    case_status: Annotated[
        IdentityResolutionStatus | None,
        Query(alias="status"),
    ] = None,
    source_key: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> IdentityResolutionListResponse:
    filters = []
    if case_status is not None:
        filters.append(IdentityResolutionCase.status == case_status)
    if source_key is not None:
        filters.append(Source.key == source_key)
    query = (
        select(IdentityResolutionCase)
        .join(Source)
        .options(selectinload(IdentityResolutionCase.source))
    )
    count_query = (
        select(func.count(IdentityResolutionCase.id))
        .select_from(IdentityResolutionCase)
        .join(Source)
    )
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    pending_first = sql_case(
        (IdentityResolutionCase.status == IdentityResolutionStatus.PENDING, 0),
        else_=1,
    )
    cases = list(
        session.scalars(
            query.order_by(
                pending_first,
                IdentityResolutionCase.created_at.desc(),
                IdentityResolutionCase.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
    )
    return IdentityResolutionListResponse(
        items=tuple(_list_item(item) for item in cases),
        total=session.scalar(count_query) or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/{case_id}", response_model=IdentityResolutionDetailResponse)
def get_identity_resolution_case(
    case_id: int,
    session: Annotated[Session, Depends(get_db_session)],
    session_factory: Annotated[
        sessionmaker[Session],
        Depends(get_session_factory),
    ],
) -> IdentityResolutionDetailResponse:
    item = session.scalar(
        select(IdentityResolutionCase)
        .where(IdentityResolutionCase.id == case_id)
        .options(selectinload(IdentityResolutionCase.source))
    )
    if item is None:
        raise IdentityResolutionCaseNotFoundError(
            f"IdentityResolutionCase {case_id} does not exist"
        )
    candidate = CandidateProfile.model_validate(item.candidate_snapshot)
    possible_matches = IdentityResolutionService(session_factory).possible_matches(
        case_id
    )
    return IdentityResolutionDetailResponse(
        id=item.id,
        status=item.status,
        candidate_display_name=item.candidate_display_name,
        candidate_snapshot=candidate,
        matching_result=_MATCHING_RESULT_ADAPTER.validate_python(
            item.matching_result_data
        ),
        source=_source_response(item.source),
        raw_document_id=item.raw_document_id,
        source_identifier=item.source_identifier,
        official_source_url=_official_source_url(candidate),
        possible_matches=tuple(
            PossiblePoliticianMatchResponse(
                politician=PoliticianSummary(
                    id=match.politician_id,
                    given_name=match.given_name,
                    family_name=match.family_name,
                    birth_date=match.birth_date,
                    current_version_id=match.current_version_id,
                ),
                signals=match.signals,
                source_identifiers=tuple(
                    IdentitySourceIdentifierResponse(
                        authority=identifier.authority,
                        value=identifier.value,
                    )
                    for identifier in match.source_identifiers
                ),
            )
            for match in possible_matches
        ),
        created_at=item.created_at,
        updated_at=item.updated_at,
        resolved_at=item.resolved_at,
        resolved_politician_id=item.resolved_politician_id,
        reviewer_identity=item.reviewer_identity,
        resolution_note=item.resolution_note,
    )


@router.post(
    "/{case_id}/resolve-existing",
    response_model=IdentityResolutionDecisionResult,
)
def resolve_identity_to_existing(
    case_id: int,
    payload: Annotated[ResolveExistingIdentityRequest, Body()],
    session_factory: Annotated[
        sessionmaker[Session],
        Depends(get_session_factory),
    ],
    principal: Annotated[AdminPrincipal, Depends(get_admin_principal)],
) -> IdentityResolutionDecisionResult:
    return IdentityResolutionService(session_factory).resolve_to_existing(
        case_id,
        payload.politician_id,
        reviewer_identity=principal.reviewer_identity,
        note=payload.note,
    )


@router.post(
    "/{case_id}/resolve-new",
    response_model=IdentityResolutionDecisionResult,
)
def resolve_identity_as_new(
    case_id: int,
    session_factory: Annotated[
        sessionmaker[Session],
        Depends(get_session_factory),
    ],
    principal: Annotated[AdminPrincipal, Depends(get_admin_principal)],
    payload: Annotated[
        IdentityResolutionNoteRequest,
        Body(),
    ] = IdentityResolutionNoteRequest(),
) -> IdentityResolutionDecisionResult:
    return IdentityResolutionService(session_factory).resolve_as_new(
        case_id,
        reviewer_identity=principal.reviewer_identity,
        note=payload.note,
    )


@router.post(
    "/{case_id}/ignore",
    response_model=IdentityResolutionDecisionResult,
)
def ignore_identity_resolution_case(
    case_id: int,
    session_factory: Annotated[
        sessionmaker[Session],
        Depends(get_session_factory),
    ],
    principal: Annotated[AdminPrincipal, Depends(get_admin_principal)],
    payload: Annotated[
        IdentityResolutionNoteRequest,
        Body(),
    ] = IdentityResolutionNoteRequest(),
) -> IdentityResolutionDecisionResult:
    return IdentityResolutionService(session_factory).ignore(
        case_id,
        reviewer_identity=principal.reviewer_identity,
        note=payload.note,
    )


def _list_item(item: IdentityResolutionCase) -> IdentityResolutionListItem:
    candidate = CandidateProfile.model_validate(item.candidate_snapshot)
    mandate = candidate.profile.mandates[0] if candidate.profile.mandates else None
    return IdentityResolutionListItem(
        id=item.id,
        status=item.status,
        candidate_display_name=item.candidate_display_name,
        source=_source_response(item.source),
        source_identifier=item.source_identifier,
        official_source_url=_official_source_url(candidate),
        current_role=mandate.mandate_type if mandate is not None else None,
        birth_date=candidate.identity.birth_date,
        created_at=item.created_at,
        updated_at=item.updated_at,
        resolved_at=item.resolved_at,
        resolved_politician_id=item.resolved_politician_id,
    )


def _source_response(source: Source) -> IdentityResolutionSourceResponse:
    return IdentityResolutionSourceResponse(
        id=source.id,
        key=source.key,
        name=source.name,
    )


def _official_source_url(candidate: CandidateProfile) -> str:
    return str(
        candidate.profile.official_homepage_url
        or candidate.provenance.document.source_url
    )
