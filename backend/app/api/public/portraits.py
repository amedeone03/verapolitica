import json
import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from backend.app.api.deps import get_api_settings
from backend.app.core.config import Settings


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
    candidate = directory / name
    return candidate if candidate.is_file() else None


@router.get("/portraits", response_model=dict[str, PortraitCredit])
def list_portraits(
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> dict[str, PortraitCredit]:
    """Credited portraits keyed by politician id. Empty when no dataset is configured.

    When the image was stored locally the URL points at this API, so viewers do
    not request third-party hosts.
    """

    raw, directory = _load(settings)
    result: dict[str, PortraitCredit] = {}
    for key, value in raw.items():
        if not str(key).isdigit() or not isinstance(value, dict):
            continue
        local = _local_file(value, directory)
        url = f"/portraits/{key}/image" if local else str(value.get("url", ""))
        if not (local or url.startswith("https://")):
            continue
        try:
            result[str(key)] = PortraitCredit.model_validate({**value, "url": url})
        except ValueError:
            continue
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
