from typing import Annotated

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db_session
from backend.app.models import ParliamentaryGroup, PoliticalParty, PoliticalPartyAffiliation
from backend.app.schemas.search import (
    PublicParliamentaryGroup,
    PublicPartyMember,
    PublicPoliticalPartyDetail,
    PublicPoliticalPartyList,
    PublicPoliticalPartySummary,
)
from backend.app.services import symbols
from backend.app.services.party_scorecard_service import published_names


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


def _is_current(row: PoliticalPartyAffiliation, today: date) -> bool:
    return row.end_date is None or row.end_date >= today


def _members(
    session: Session, party_ids: list[int]
) -> dict[int, list[tuple[PoliticalPartyAffiliation, str]]]:
    if not party_ids:
        return {}
    rows = list(
        session.scalars(
            select(PoliticalPartyAffiliation)
            .where(PoliticalPartyAffiliation.political_party_id.in_(party_ids))
            .order_by(PoliticalPartyAffiliation.id)
        )
    )
    # Only published politicians are named on public pages.
    names = published_names(session, {row.politician_id for row in rows})
    members: dict[int, list[tuple[PoliticalPartyAffiliation, str]]] = {}
    for row in rows:
        if row.politician_id in names:
            members.setdefault(row.political_party_id, []).append((row, names[row.politician_id]))
    return members


def _member(row: PoliticalPartyAffiliation, name: str) -> PublicPartyMember:
    return PublicPartyMember(
        politician_id=row.politician_id,
        name=name,
        start_date=row.start_date.isoformat() if row.start_date else None,
        end_date=row.end_date.isoformat() if row.end_date else None,
        source_url=row.source_url,
    )


@parties_router.get("", response_model=PublicPoliticalPartyList)
def list_political_parties(
    session: Annotated[Session, Depends(get_db_session)],
    all_parties: Annotated[bool, Query(alias="all")] = False,
) -> PublicPoliticalPartyList:
    """Parties with at least one published member, most current members first.

    ``all=true`` lists every party in the redazione's list, members or not
    (the sign-up asks readers which parties they want to follow).
    """

    parties = list(session.scalars(select(PoliticalParty).order_by(PoliticalParty.canonical_name)))
    members = _members(session, [party.id for party in parties])
    logos = symbols.logo_urls(session, "party")
    today = date.today()
    items = []
    for party in parties:
        rows = members.get(party.id, [])
        if not rows and not all_parties:
            continue
        current = {row.politician_id for row, _ in rows if _is_current(row, today)}
        items.append(
            PublicPoliticalPartySummary(
                id=party.id,
                name=party.canonical_name,
                abbreviation=party.abbreviation,
                logo_url=logos.get(str(party.id)),
                current_member_count=len(current),
            )
        )
    items.sort(key=lambda item: (-item.current_member_count, item.name.casefold()))
    return PublicPoliticalPartyList(items=tuple(items), total=len(items))


@parties_router.get("/{party_id}", response_model=PublicPoliticalPartyDetail)
def get_political_party(
    party_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PublicPoliticalPartyDetail:
    party = session.scalar(select(PoliticalParty).where(PoliticalParty.id == party_id))
    if party is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="political party not found",
        )
    today = date.today()
    current: dict[int, PublicPartyMember] = {}
    former: dict[int, PublicPartyMember] = {}
    for row, name in _members(session, [party.id]).get(party.id, []):
        target = current if _is_current(row, today) else former
        target.setdefault(row.politician_id, _member(row, name))
    former = {key: value for key, value in former.items() if key not in current}
    order = lambda member: member.name.casefold()  # noqa: E731
    return PublicPoliticalPartyDetail(
        id=party.id,
        name=party.canonical_name,
        abbreviation=party.abbreviation,
        logo_url=symbols.logo_urls(session, "party").get(str(party.id)),
        current_members=tuple(sorted(current.values(), key=order)),
        former_members=tuple(sorted(former.values(), key=order)),
    )
