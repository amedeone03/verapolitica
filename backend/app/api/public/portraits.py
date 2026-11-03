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
from backend.app.models import Politician, PoliticianVersion
from backend.app.services.official_images import official_https_image_url


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


def _from_published_profiles(session: Session) -> dict[str, PortraitCredit]:
    """Official Camera/Senato/Governo photos already stored on published schede."""

    result: dict[str, PortraitCredit] = {}
    rows = session.execute(
        select(Politician, PoliticianVersion)
        .join(PoliticianVersion, PoliticianVersion.id == Politician.current_version_id)
        .where(PoliticianVersion.published_at.is_not(None))
    )
    for politician, version in rows:
        profile = version.profile_data if isinstance(version.profile_data, dict) else {}
        url = official_https_image_url(profile.get("image_url"))
        if url is None:
            continue
        source = official_https_image_url(profile.get("official_homepage_url")) or url
        result[str(politician.id)] = PortraitCredit(
            url=url,
            credit="Fonte ufficiale",
            license="Ritratto istituzionale ufficiale",
            source_url=source,
            origin="Fonte ufficiale",
        )
    return result


@router.get("/portraits", response_model=dict[str, PortraitCredit])
def list_portraits(
    settings: Annotated[Settings, Depends(get_api_settings)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, PortraitCredit]:
    """Credited portraits keyed by politician id.

    Local files from ``VERAPOLITICA_PORTRAITS_PATH`` win. Missing ids fall back
    to the official ``image_url`` already stored on the published scheda.
    """

    raw, directory = _load(settings)
    result: dict[str, PortraitCredit] = {}
    for key, value in raw.items():
        if not str(key).isdigit() or not isinstance(value, dict):
            continue
        local = _local_file(value, directory)
        stored = official_https_image_url(value.get("url")) or ""
        url = f"/portraits/{key}/image" if local else stored
        if not (local or url.startswith("https://")):
            continue
        try:
            result[str(key)] = PortraitCredit.model_validate({**value, "url": url})
        except ValueError:
            continue
    for key, credit in _from_published_profiles(session).items():
        result.setdefault(key, credit)
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
