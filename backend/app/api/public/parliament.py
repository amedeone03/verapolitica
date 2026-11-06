"""Parliament at a glance: seats by group in the Camera and the Senato."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db_session
from backend.app.services.parliament_composition import CHAMBERS, composition
from backend.app.services.redazione.politics import PoliticsEdits, apply_chamber


router = APIRouter(prefix="/parliament", tags=["parliament"])


@router.get("/composition")
def get_composition(session: Annotated[Session, Depends(get_db_session)], response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=60"
    live = PoliticsEdits(None).published(session)
    return {chamber: apply_chamber(composition(session, chamber), live) for chamber in CHAMBERS}


@router.get("/edits")
def published_edits(session: Annotated[Session, Depends(get_db_session)], response: Response) -> dict[str, Any]:
    """The redazione's live corrections to the Politica page (Governo and notes are applied by the app)."""

    response.headers["Cache-Control"] = "public, max-age=60"
    return {"items": PoliticsEdits(None).published(session)}
