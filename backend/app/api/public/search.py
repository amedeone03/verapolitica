from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db_session
from backend.app.schemas.search import PublicSearchResultList, SearchEntityType
from backend.app.services.search_service import MAX_QUERY_LENGTH, SearchService


router = APIRouter(tags=["search"])


@router.get("/search", response_model=PublicSearchResultList)
def search(
    session: Annotated[Session, Depends(get_db_session)],
    q: Annotated[str, Query(max_length=MAX_QUERY_LENGTH)],
    entity_type: Annotated[SearchEntityType | None, Query(alias="type")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> PublicSearchResultList:
    return SearchService(session).search(
        q, entity_type=entity_type, offset=offset, limit=limit
    )
