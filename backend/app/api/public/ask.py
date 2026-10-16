from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.deps import get_api_settings, get_session_factory
from backend.app.core.config import Settings
from backend.app.schemas.ask import AskRequest, AskResponse
from backend.app.services.ask_verapolitica_service import AskVeraPoliticaService


router = APIRouter(tags=["ask"])


@router.post("/ask", response_model=AskResponse)
def ask_verapolitica(
    payload: AskRequest,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> AskResponse:
    """Read-only question answering over published VeraPolitica data."""

    return AskVeraPoliticaService(session_factory, settings).ask(payload.question)
