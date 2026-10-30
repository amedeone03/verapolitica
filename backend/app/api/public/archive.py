from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.deps import get_session_factory
from backend.app.models import Chamber
from backend.app.schemas.archive import (
    PublicEraList,
    PublicHistoricalMandateList,
    PublicLegislatureDetail,
    PublicProvinceList,
    PublicTerritoryHistory,
)
from backend.app.services.archive_service import ArchiveNotFoundError, ArchiveService


router = APIRouter(prefix="/archive", tags=["archive"])
Factory = Annotated[sessionmaker[Session], Depends(get_session_factory)]


def _not_found(error: ArchiveNotFoundError) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, str(error))


@router.get("/legislatures", response_model=PublicEraList)
def list_legislatures(factory: Factory) -> PublicEraList:
    """Legislatures since 1946 grouped by era (a journalistic convention)."""

    return ArchiveService(factory).eras()


@router.get("/legislatures/{number}", response_model=PublicLegislatureDetail)
def get_legislature(number: Annotated[int, Path(ge=0, le=99)], factory: Factory) -> PublicLegislatureDetail:
    try:
        return ArchiveService(factory).legislature(number)
    except ArchiveNotFoundError as error:
        raise _not_found(error) from None


@router.get("/parliamentarians", response_model=PublicHistoricalMandateList)
def list_parliamentarians(
    factory: Factory,
    legislature: Annotated[int | None, Query(ge=0, le=99)] = None,
    chamber: Chamber | None = None,
    q: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PublicHistoricalMandateList:
    """Official parliamentary mandates since 1948, from the Chambers' open data."""

    return ArchiveService(factory).mandates(
        legislature=legislature, chamber=chamber, query=q, offset=offset, limit=limit
    )


@router.get("/provinces", response_model=PublicProvinceList)
def list_provinces(
    factory: Factory, region: Annotated[int | None, Query(gt=0)] = None
) -> PublicProvinceList:
    return ArchiveService(factory).provinces(region_id=region)


@router.get("/provinces/{abbreviation}", response_model=PublicTerritoryHistory)
def get_province_history(
    abbreviation: Annotated[str, Path(pattern=r"^[A-Z]{2}$")], factory: Factory
) -> PublicTerritoryHistory:
    try:
        return ArchiveService(factory).province_history(abbreviation)
    except ArchiveNotFoundError as error:
        raise _not_found(error) from None


@router.get("/regions/{region_id}", response_model=PublicTerritoryHistory)
def get_region_history(region_id: Annotated[int, Path(gt=0)], factory: Factory) -> PublicTerritoryHistory:
    try:
        return ArchiveService(factory).region_history(region_id)
    except ArchiveNotFoundError as error:
        raise _not_found(error) from None
