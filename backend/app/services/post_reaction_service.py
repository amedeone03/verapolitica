"""Reactions of registered readers on published redazione posts.

One reaction per reader per post (heart, angry, party, tears). Counts are
public; who reacted is never returned, only the caller's own reaction.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import EditorialPost, EditorialPostStatus
from backend.app.models.civic_account import POST_REACTIONS, CivicAccount, CivicPostReaction
from backend.app.services.civic_account_service import CivicAuthError, CivicAuthNotFound

MAX_POSTS_PER_REQUEST = 50


class ReactionNotFound(CivicAuthError):
    def __init__(self) -> None:
        super().__init__("post non pubblicato", status_code=404)


def empty_summary() -> dict[str, Any]:
    return {"counts": {code: 0 for code in POST_REACTIONS}, "total": 0, "mine": None}


class PostReactionService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def summaries(self, post_ids: Iterable[int], account_id: int | None = None) -> dict[int, dict[str, Any]]:
        ids = sorted({int(post_id) for post_id in post_ids})[:MAX_POSTS_PER_REQUEST]
        if not ids:
            return {}
        with self.session_factory() as session:
            return self._summaries(session, ids, account_id)

    def react(self, account_id: int, post_id: int, reaction: str | None) -> dict[str, Any]:
        if reaction is not None and reaction not in POST_REACTIONS:
            raise CivicAuthError("reazione non valida")
        with self.session_factory.begin() as session:
            if session.get(CivicAccount, account_id) is None:
                raise CivicAuthNotFound()
            post = session.get(EditorialPost, post_id)
            if post is None or post.status is not EditorialPostStatus.PUBLISHED:
                raise ReactionNotFound()
            row = session.scalar(
                select(CivicPostReaction).where(
                    CivicPostReaction.account_id == account_id,
                    CivicPostReaction.post_id == post_id,
                )
            )
            if reaction is None:
                if row is not None:
                    session.delete(row)
            elif row is None:
                session.add(CivicPostReaction(account_id=account_id, post_id=post_id, reaction=reaction))
            else:
                row.reaction = reaction
            session.flush()
            return self._summaries(session, [post_id], account_id)[post_id]

    def _summaries(self, session: Session, ids: list[int], account_id: int | None) -> dict[int, dict[str, Any]]:
        published = set(
            session.scalars(
                select(EditorialPost.id).where(
                    EditorialPost.id.in_(ids),
                    EditorialPost.status == EditorialPostStatus.PUBLISHED,
                )
            )
        )
        result = {post_id: empty_summary() for post_id in ids if post_id in published}
        if not result:
            return {}
        rows = session.execute(
            select(CivicPostReaction.post_id, CivicPostReaction.reaction, func.count())
            .where(CivicPostReaction.post_id.in_(result))
            .group_by(CivicPostReaction.post_id, CivicPostReaction.reaction)
        )
        for post_id, reaction, count in rows:
            if reaction in POST_REACTIONS:
                result[post_id]["counts"][reaction] = int(count)
                result[post_id]["total"] += int(count)
        if account_id is not None:
            mine = session.execute(
                select(CivicPostReaction.post_id, CivicPostReaction.reaction).where(
                    CivicPostReaction.account_id == account_id,
                    CivicPostReaction.post_id.in_(result),
                )
            )
            for post_id, reaction in mine:
                result[post_id]["mine"] = reaction
        return result
