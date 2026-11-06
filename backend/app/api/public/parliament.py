"""Parliament at a glance: seats by group in the Camera and the Senato."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db_session
from backend.app.services.parliament_composition import CHAMBERS, composition


router = APIRouter(prefix="/parliament", tags=["parliament"])


@router.get("/composition")
def get_composition(session: Annotated[Session, Depends(get_db_session)], response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=300"
    return {chamber: composition(session, chamber) for chamber in CHAMBERS}
