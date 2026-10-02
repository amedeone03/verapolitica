from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db_session
from backend.app.schemas import PublicPolitician, PublicPoliticianList
from backend.app.services import PublicPoliticianQueryService


router = APIRouter(prefix="/politicians", tags=["politicians"])


@router.get("", response_model=PublicPoliticianList)
def list_politicians(
    session: Annotated[Session, Depends(get_db_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PublicPoliticianList:
    return PublicPoliticianQueryService(session).list(offset=offset, limit=limit)


@router.get("/{politician_id}", response_model=PublicPolitician)
def get_politician(
    politician_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PublicPolitician:
    politician = PublicPoliticianQueryService(session).get(politician_id)
    if politician is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="published politician not found",
        )
    return politician
