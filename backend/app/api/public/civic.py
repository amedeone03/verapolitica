from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db_session
from backend.app.models.civic import GeographicScopeType, ReferendumStatus
from backend.app.schemas.civic import (
    PublicGlossaryList,
    PublicGlossaryTerm,
    PublicReferendum,
    PublicReferendumList,
    PublicVotingGuide,
    PublicVotingGuideList,
)
from backend.app.services.public_civic_service import PublicCivicQueryService


referendums_router = APIRouter(prefix="/referendums", tags=["referendums"])
voting_guides_router = APIRouter(prefix="/voting-guides", tags=["voting-guides"])
glossary_router = APIRouter(prefix="/glossary", tags=["glossary"])


@referendums_router.get("", response_model=PublicReferendumList)
def list_referendums(
    session: Annotated[Session, Depends(get_db_session)],
    referendum_status: Annotated[ReferendumStatus | None, Query(alias="status")] = None,
    scope: GeographicScopeType | None = None,
    upcoming: bool = False,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PublicReferendumList:
    return PublicCivicQueryService(session).list_referendums(
        offset=offset,
        limit=limit,
        status=referendum_status,
        scope=scope,
        upcoming=upcoming,
    )


@referendums_router.get("/{referendum_id}", response_model=PublicReferendum)
def get_referendum(
    referendum_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PublicReferendum:
    record = PublicCivicQueryService(session).get_referendum(referendum_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="published referendum not found",
        )
    return record


@voting_guides_router.get("", response_model=PublicVotingGuideList)
def list_voting_guides(
    session: Annotated[Session, Depends(get_db_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PublicVotingGuideList:
    return PublicCivicQueryService(session).list_voting_guides(
        offset=offset, limit=limit
    )


@voting_guides_router.get("/{guide_id}", response_model=PublicVotingGuide)
def get_voting_guide(
    guide_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PublicVotingGuide:
    record = PublicCivicQueryService(session).get_voting_guide(guide_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="published voting guide not found",
        )
    return record


@glossary_router.get("", response_model=PublicGlossaryList)
def list_glossary(
    session: Annotated[Session, Depends(get_db_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PublicGlossaryList:
    return PublicCivicQueryService(session).list_glossary(offset=offset, limit=limit)


@glossary_router.get("/{slug}", response_model=PublicGlossaryTerm)
def get_glossary_term(
    slug: Annotated[str, Path(min_length=1, max_length=200)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PublicGlossaryTerm:
    record = PublicCivicQueryService(session).get_glossary_term(slug)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="published glossary term not found",
        )
    return record
