"""Reactions on published posts: counts are public, reacting needs an account."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.config import AppEnvironment, Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine
from backend.app.main import create_app
from backend.app.models import EditorialPost, EditorialPostStatus, FeedScope


PASSWORD = "long-enough-password"


def _app(tmp_path):
    settings = Settings(
        env=AppEnvironment.TEST,
        database_url=f"sqlite:///{tmp_path / 'reactions.db'}",
        raw_storage_path=tmp_path / "raw",
        admin_api_key="test-admin-secret",
        redazione_members="Anna Redattrice=tok-anna-redattrice;Bruno Verificatore=tok-bruno-verificatore",
        session_secret="civic-test-session-secret-32chars",
        trusted_hosts="localhost,127.0.0.1,testserver",
        cors_origins="http://testserver",
        enable_demo_ui=False,
        enable_api_docs=False,
    )
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for title, state in (("Pubblicata", EditorialPostStatus.PUBLISHED), ("In attesa", EditorialPostStatus.PENDING)):
            session.add(EditorialPost(
                title=title, body="Testo.", scope=FeedScope.NATIONAL, citations=[],
                status=state, created_by="Anna Redattrice",
                published_at=datetime(2026, 11, 5, tzinfo=timezone.utc) if state is EditorialPostStatus.PUBLISHED else None,
            ))
        session.commit()
    engine.dispose()
    return create_app(settings)


def _register(client, email):
    response = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


def test_guest_sees_counts_but_cannot_react(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        listed = client.get("/reactions?posts=1,2")
        assert listed.status_code == 200
        assert listed.headers["cache-control"] == "private, no-store"
        items = listed.json()["items"]
        # Only published posts are counted; the pending one is not even listed.
        assert [item["post_id"] for item in items] == [1]
        assert items[0]["total"] == 0 and items[0]["mine"] is None
        assert set(items[0]["counts"]) == {"heart", "angry", "party", "tears"}
        assert client.put("/reactions/1", json={"reaction": "heart"}).status_code == 401


def test_one_reaction_per_reader_can_change_and_be_removed(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        _register(client, "giulia@example.com")
        first = client.put("/reactions/1", json={"reaction": "heart"}).json()
        assert first["mine"] == "heart" and first["counts"]["heart"] == 1 and first["total"] == 1
        changed = client.put("/reactions/1", json={"reaction": "party"}).json()
        assert changed["mine"] == "party" and changed["counts"]["heart"] == 0 and changed["total"] == 1

        client.post("/auth/logout")
        _register(client, "marco@example.com")
        other = client.put("/reactions/1", json={"reaction": "tears"}).json()
        assert other["total"] == 2 and other["mine"] == "tears"
        listed = client.get("/reactions?posts=1").json()["items"][0]
        assert listed["counts"] == {"heart": 0, "angry": 0, "party": 1, "tears": 1}
        # Who reacted is never returned.
        assert "giulia" not in client.get("/reactions?posts=1").text

        removed = client.put("/reactions/1", json={"reaction": None}).json()
        assert removed["mine"] is None and removed["total"] == 1


def test_unknown_reaction_and_unpublished_post_are_refused(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        _register(client, "giulia@example.com")
        assert client.put("/reactions/1", json={"reaction": "like"}).status_code == 400
        assert client.put("/reactions/2", json={"reaction": "heart"}).status_code == 404
        assert client.put("/reactions/999", json={"reaction": "heart"}).status_code == 404
        assert client.get("/reactions?posts=a,b").status_code == 422


def test_shared_posts_are_kept_in_the_profile(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        _register(client, "giulia@example.com")
        saved = client.put("/auth/profile", json={
            "display_name": "Giulia",
            "saved": [{"url": "./?post=1", "title": "Pubblicata"}],
            "shared": [
                {"url": "./?post=1", "title": "Pubblicata", "at": "2026-11-06"},
                {"url": "./?post=1", "title": "Doppione"},
                {"url": "https://example.com/?post=1", "title": "Esterno"},
                {"url": "./?post=1&x=<script>", "title": "Iniezione"},
            ],
        })
        assert saved.status_code == 200
        profile = saved.json()["profile"]
        assert profile["saved"] == [{"url": "./?post=1", "title": "Pubblicata"}]
        assert profile["shared"] == [{"url": "./?post=1", "title": "Pubblicata", "at": "2026-11-06"}]
