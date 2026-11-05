import json
import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_api_settings, get_db_session
from backend.app.core.config import Settings
from backend.app.models import EditorialSymbol
from backend.app.services import symbols as symbols_module


router = APIRouter(tags=["portraits"])

_FILE_NAME = re.compile(r"^[0-9a-f]{24}\.(jpg|png|webp)$")
_MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


class PortraitCredit(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    credit: str
    license: str
    source_url: str
    origin: str


def _load(settings: Settings) -> tuple[dict[str, dict], Path | None]:
    path = settings.portraits_path
    if path is None or not path.is_file():
        return {}, None
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}, None
    return (raw if isinstance(raw, dict) else {}), path.parent / "portraits"


def _local_file(entry: dict, directory: Path | None) -> Path | None:
    name = entry.get("file")
    if directory is None or not isinstance(name, str) or not _FILE_NAME.fullmatch(name):
        return None
    root = directory.expanduser().resolve()
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


def _approved_by_redazione(session: Session) -> dict[str, PortraitCredit]:
    """Photos uploaded in the redazione console and approved by a second member."""

    rows = session.scalars(select(EditorialSymbol).where(EditorialSymbol.kind == "politician"))
    return {
        row.key: PortraitCredit(
            url=symbols_module.media_url(row.image_id),
            credit=row.credit,
            license=symbols_module.LICENSES.get(row.license, row.license),
            source_url=row.source_url,
            origin="Redazione VeraPolitica",
        )
        for row in rows
        if row.key.isdigit()
    }


@router.get("/portraits", response_model=dict[str, PortraitCredit])
def list_portraits(
    settings: Annotated[Settings, Depends(get_api_settings)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, PortraitCredit]:
    """Credited portraits keyed by politician id, all served by this site.

    A photo approved in the redazione console wins. Otherwise a file already
    stored next to ``VERAPOLITICA_PORTRAITS_PATH`` is used. Nothing is linked
    from Camera, Senato, Governo or any other outside host.
    """

    raw, directory = _load(settings)
    result: dict[str, PortraitCredit] = {}
    for key, value in raw.items():
        if not str(key).isdigit() or not isinstance(value, dict):
            continue
        if _local_file(value, directory) is None:
            continue
        try:
            result[str(key)] = PortraitCredit.model_validate({**value, "url": f"/portraits/{key}/image"})
        except ValueError:
            continue
    result.update(_approved_by_redazione(session))
    return result


@router.get("/portraits/{politician_id}/image")
def get_portrait_image(
    politician_id: Annotated[int, PathParam(gt=0)],
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> FileResponse:
    raw, directory = _load(settings)
    entry = raw.get(str(politician_id))
    local = _local_file(entry, directory) if isinstance(entry, dict) else None
    if local is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "portrait not found")
    return FileResponse(
        local,
        media_type=_MEDIA_TYPES[local.suffix.lstrip(".")],
        headers={"Cache-Control": "public, max-age=86400"},
    )
