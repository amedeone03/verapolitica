"""Territory schede for the public app: the official base plus the published blocks."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.deps import get_session_factory
from backend.app.services.redazione.territory import TerritoryError, TerritorySchede


router = APIRouter(prefix="/territories", tags=["territories"])


@router.get("/regions")
def regions_overview(
    response: Response,
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> dict[str, Any]:
    """The twenty regions with their president and coalition, for Politica."""

    response.headers["Cache-Control"] = "public, max-age=60"
    return TerritorySchede(factory).regions_overview()


@router.get("/{kind}/{key}")
def territory(
    kind: Annotated[str, Path(pattern=r"^(region|province|municipality)$")],
    key: Annotated[str, Path(pattern=r"^[A-Za-z0-9]{1,12}$")],
    response: Response,
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> dict[str, Any]:
    try:
        payload = TerritorySchede(factory).public(kind, key)
    except TerritoryError as error:
        raise HTTPException(error.status_code if error.status_code == 404 else status.HTTP_400_BAD_REQUEST, str(error)) from error
    response.headers["Cache-Control"] = "public, max-age=60"
    return payload
