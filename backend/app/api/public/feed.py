from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db_session
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
) -> FeedPage:
    """Verified facts, newest first. The zone is the reader's own territory."""

    service = FeedService(session)
    try:
        zone = service.resolve_zone(
            region_id=region, province=province, municipality_id=municipality
        )
    except FeedValidationError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return service.page(feed_filter=scope, zone=zone, offset=offset, limit=limit)


@router.get("/posts/{post_id}", response_model=FeedItem)
def get_post(
    post_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_db_session)],
) -> FeedItem:
    item = FeedService(session).post(post_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "published post not found")
    return item
