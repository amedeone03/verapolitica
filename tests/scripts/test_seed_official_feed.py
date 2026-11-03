from datetime import datetime, timezone

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import EditorialPost, EditorialPostStatus
from backend.app.services.redazione.service import RedazioneService
from scripts.seed_official_feed import CARDS, seed
from sqlalchemy import func, select


def test_official_feed_cards_use_only_institutional_pages_and_are_idempotent(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'feed.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    service = RedazioneService(factory, clock=lambda: datetime(2026, 11, 3, tzinfo=timezone.utc))

    first = seed(service, factory, author="Sincronizzazione fonti ufficiali", approver="Verificatore")
    assert first.published == [card.title for card in CARDS]
    assert first.errors == []
    with factory() as session:
        posts = list(session.scalars(select(EditorialPost)))
        assert len(posts) == 3
        assert {post.status for post in posts} == {EditorialPostStatus.PUBLISHED}
        urls = {item["url"] for post in posts for item in post.citations}
        assert urls == {card.source_url for card in CARDS}
        assert all((post.blocks or {}).get("card", {}).get("category") == "pubblicazione" for post in posts)

    again = seed(service, factory, author="Sincronizzazione fonti ufficiali", approver="Verificatore")
    assert again.published == []
    assert len(again.skipped) == 3
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(EditorialPost)) == 3
    engine.dispose()
