from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_api_settings, get_db_session
from backend.app.core.config import Settings
from backend.app.models import EditorialImage
from backend.app.schemas.feed import FeedFilter, FeedItem, FeedPage
from backend.app.services.feed_service import FeedService, FeedValidationError


router = APIRouter(prefix="/feed", tags=["feed"])


@router.get("", response_model=FeedPage)
def get_feed(
    session: Annotated[Session, Depends(get_db_session)],
    scope: FeedFilter = FeedFilter.ALL,
    region: Annotated[int | None, Query(gt=0)] = None,
    province: Annotated[str | None, Query(pattern=r"^[A-Z]{2}$")] = None,
    municipality: Annotated[int | None, Query(gt=0)] = None,
    offset: Annotated[int, Query(ge=0, le=500)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    redazione: bool = False,
) -> FeedPage:
    """Verified facts, newest first. The zone is the reader's own territory."""

    service = FeedService(session)
    try:
        zone = service.resolve_zone(
            region_id=region, province=province, municipality_id=municipality
        )
    except FeedValidationError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return service.page(feed_filter=scope, zone=zone, offset=offset, limit=limit, redazione_only=redazione)


@router.get("/posts/{post_id}", response_model=FeedItem)
def get_post(
    post_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> FeedItem:
    item = FeedService(session, public_names=frozenset(settings.redazione_member_tokens.values())).post(post_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "published post not found")
    return item


media_router = APIRouter(tags=["media"])


@media_router.get("/media/{image_id}", include_in_schema=False)
def media(
    image_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_db_session)],
) -> Response:
    """Images uploaded by the redazione for feed cards (round portraits)."""

    image = session.get(EditorialImage, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "image not found")
    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"},
    )
