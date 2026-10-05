from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db_session
from backend.app.schemas import PublicRegion, PublicRegionList
from backend.app.services import PublicTerritoryQueryService


router = APIRouter(prefix="/regions", tags=["regions"])


@router.get("", response_model=PublicRegionList)
def list_regions(
    session: Annotated[Session, Depends(get_db_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PublicRegionList:
    return PublicTerritoryQueryService(session).list_regions(
        offset=offset, limit=limit
    )


@router.get("/{region_id}", response_model=PublicRegion)
def get_region(
    region_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PublicRegion:
    region = PublicTerritoryQueryService(session).get_region(region_id)
    if region is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="region not found",
        )
    return region
