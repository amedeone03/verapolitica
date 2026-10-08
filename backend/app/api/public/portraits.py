import json
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from backend.app.api.deps import get_api_settings
from backend.app.core.config import Settings


router = APIRouter(tags=["portraits"])


class PortraitCredit(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    credit: str
    license: str
    source_url: str
    origin: str


@router.get("/portraits", response_model=dict[str, PortraitCredit])
def list_portraits(
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> dict[str, PortraitCredit]:
    """Credited portraits keyed by politician id. Empty when no dataset is configured."""

    path = settings.portraits_path
    if path is None or not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    result: dict[str, PortraitCredit] = {}
    for key, value in raw.items() if isinstance(raw, dict) else ():
        if not str(key).isdigit() or not isinstance(value, dict):
            continue
        if not str(value.get("url", "")).startswith("https://"):
            continue
        try:
            result[str(key)] = PortraitCredit.model_validate(value)
        except ValueError:
            continue
    return result
