from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db_session
from backend.app.models import ParliamentaryGroup, PoliticalParty
from backend.app.schemas.search import PublicParliamentaryGroup, PublicPoliticalParty


groups_router = APIRouter(prefix="/parliamentary-groups", tags=["parliamentary-groups"])
parties_router = APIRouter(prefix="/political-parties", tags=["political-parties"])


@groups_router.get("/{group_id}", response_model=PublicParliamentaryGroup)
def get_parliamentary_group(
    group_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PublicParliamentaryGroup:
    group = session.scalar(select(ParliamentaryGroup).where(ParliamentaryGroup.id == group_id))
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="parliamentary group not found",
        )
    return PublicParliamentaryGroup(
        id=group.id,
        name=group.canonical_name,
        abbreviation=group.abbreviation,
        institution=group.institution,
        legislature=group.legislature,
    )


@parties_router.get("/{party_id}", response_model=PublicPoliticalParty)
def get_political_party(
    party_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PublicPoliticalParty:
    party = session.scalar(select(PoliticalParty).where(PoliticalParty.id == party_id))
    if party is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="political party not found",
        )
    return PublicPoliticalParty(
        id=party.id,
        name=party.canonical_name,
        abbreviation=party.abbreviation,
    )
