from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db_session
from backend.app.schemas import PublicMunicipality, PublicMunicipalityList
from backend.app.services import PublicTerritoryQueryService


router = APIRouter(prefix="/municipalities", tags=["municipalities"])


@router.get("", response_model=PublicMunicipalityList)
def list_municipalities(
    session: Annotated[Session, Depends(get_db_session)],
    region: Annotated[int | None, Query(gt=0)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PublicMunicipalityList:
    return PublicTerritoryQueryService(session).list_municipalities(
        offset=offset,
        limit=limit,
        region_id=region,
    )


@router.get("/{municipality_id}", response_model=PublicMunicipality)
def get_municipality(
    municipality_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PublicMunicipality:
    municipality = PublicTerritoryQueryService(session).get_municipality(
        municipality_id
    )
    if municipality is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="municipality not found",
        )
    return municipality
