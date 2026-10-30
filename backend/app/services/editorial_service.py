"""Newsroom posts: draft, review by someone else, publish, never edit.

The admin API still has one shared credential, so author and reviewer names are
attestations recorded next to it (``<credential>/<name>``), exactly like pledge
approvals. Per-user accounts are needed for real four-eyes control.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    EditorialPost,
    EditorialPostStatus,
    FeedScope,
    Municipality,
    Region,
)
from backend.app.schemas.feed import (
    EditorialPostList,
    EditorialPostRequest,
    EditorialPostResponse,
    FeedSource,
)


class EditorialError(RuntimeError):
    pass


class EditorialNotFoundError(EditorialError):
    pass


class EditorialValidationError(EditorialError):
    pass


class EditorialConflictError(EditorialError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def post_response(post: EditorialPost) -> EditorialPostResponse:
    return EditorialPostResponse(
        id=post.id,
        title=post.title,
        body=post.body,
        scope=post.scope,
        region_id=post.region_id,
        province_abbreviation=post.province_abbreviation,
        municipality_id=post.municipality_id,
        citations=tuple(FeedSource(title=item["title"], url=item["url"]) for item in post.citations),
        corrects_id=post.corrects_id,
        status=post.status,
        created_by=post.created_by,
        reviewed_by=post.reviewed_by,
        review_note=post.review_note,
        published_at=post.published_at,
        created_at=post.created_at,
    )


class EditorialService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    @staticmethod
    def _territory(session: Session, payload: EditorialPostRequest) -> tuple[int | None, str | None, int | None]:
        """Return (region_id, province, municipality_id), filled upwards for filtering."""

        if payload.scope is FeedScope.NATIONAL:
            return None, None, None
        if payload.scope is FeedScope.REGION:
            if session.get(Region, payload.region_id) is None:
                raise EditorialValidationError("region not found")
            return payload.region_id, None, None
        if payload.scope is FeedScope.PROVINCE:
            region_id = session.scalar(
                select(Municipality.region_id)
                .where(Municipality.province_abbreviation == payload.province_abbreviation)
                .limit(1)
            )
            if region_id is None:
                raise EditorialValidationError("province not found")
            return region_id, payload.province_abbreviation, None
        municipality = session.get(Municipality, payload.municipality_id)
        if municipality is None:
            raise EditorialValidationError("municipality not found")
        return municipality.region_id, municipality.province_abbreviation, municipality.id

    def create(self, payload: EditorialPostRequest, *, author: str) -> EditorialPostResponse:
        with self.session_factory.begin() as session:
            region_id, province, municipality_id = self._territory(session, payload)
            if payload.corrects_id is not None:
                corrected = session.get(EditorialPost, payload.corrects_id)
                if corrected is None or corrected.status is not EditorialPostStatus.PUBLISHED:
                    raise EditorialValidationError("a correction must point at a published post")
            post = EditorialPost(
                title=payload.title.strip(),
                body=payload.body.strip(),
                scope=payload.scope,
                region_id=region_id,
                province_abbreviation=province,
                municipality_id=municipality_id,
                citations=[
                    {"title": item.title.strip(), "url": str(item.url)} for item in payload.citations
                ],
                corrects_id=payload.corrects_id,
                status=EditorialPostStatus.PENDING,
                created_by=author,
                created_at=self.clock(),
            )
            session.add(post)
            session.flush()
            return post_response(post)

    def list(
        self, *, status: EditorialPostStatus | None = None, offset: int = 0, limit: int = 50
    ) -> EditorialPostList:
        with self.session_factory() as session:
            query = select(EditorialPost)
            count = select(func.count(EditorialPost.id))
            if status is not None:
                query = query.where(EditorialPost.status == status)
                count = count.where(EditorialPost.status == status)
            rows = session.scalars(
                query.order_by(EditorialPost.created_at.desc(), EditorialPost.id.desc())
                .offset(offset)
                .limit(limit)
            )
            return EditorialPostList(
                items=tuple(post_response(row) for row in rows),
                total=session.scalar(count) or 0,
            )

    def _pending(self, session: Session, post_id: int) -> EditorialPost:
        post = session.scalar(
            select(EditorialPost).where(EditorialPost.id == post_id).with_for_update()
        )
        if post is None:
            raise EditorialNotFoundError("editorial post not found")
        if post.status is not EditorialPostStatus.PENDING:
            raise EditorialConflictError(f"post is {post.status.value}")
        return post

    def publish(self, post_id: int, *, reviewer: str, note: str | None = None) -> EditorialPostResponse:
        with self.session_factory.begin() as session:
            post = self._pending(session, post_id)
            if post.created_by == reviewer:
                raise EditorialConflictError("the author cannot publish their own post")
            now = self.clock()
            post.status = EditorialPostStatus.PUBLISHED
            post.reviewed_by = reviewer
            post.review_note = note
            post.published_at = now
            post.updated_at = now
            session.flush()
            return post_response(post)

    def reject(self, post_id: int, *, reviewer: str, note: str) -> EditorialPostResponse:
        with self.session_factory.begin() as session:
            post = self._pending(session, post_id)
            post.status = EditorialPostStatus.REJECTED
            post.reviewed_by = reviewer
            post.review_note = note
            post.updated_at = self.clock()
            session.flush()
            return post_response(post)
