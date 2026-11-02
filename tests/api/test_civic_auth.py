"""Citizen email/password accounts are separate from redazione and admin."""

from fastapi.testclient import TestClient

from backend.app.core.config import AppEnvironment, Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine
from backend.app.main import create_app
from backend.app.services.civic_account_service import AttemptLimiter


MEMBERS = "Anna Redattrice=tok-anna-redattrice;Bruno Verificatore=tok-bruno-verificatore"
PASSWORD = "long-enough-password"


def _app(tmp_path, **overrides):
    values = {
        "env": AppEnvironment.TEST,
        "database_url": f"sqlite:///{tmp_path / 'civic.db'}",
        "raw_storage_path": tmp_path / "raw",
        "admin_api_key": "test-admin-secret",
        "redazione_members": MEMBERS,
        "session_secret": "civic-test-session-secret-32chars",
        "trusted_hosts": "localhost,127.0.0.1,testserver",
        "cors_origins": "http://testserver",
        "enable_demo_ui": False,
        "enable_api_docs": False,
    }
    values.update(overrides)
    settings = Settings(**values)
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return create_app(settings)


def _cookie_header(response) -> str:
    return response.headers.get("set-cookie") or ""


def test_register_login_me_logout_and_profile(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/auth/register",
            json={"email": "Lettrice@example.com", "password": PASSWORD},
        )
        assert created.status_code == 200, created.text
        assert created.json()["email"] == "lettrice@example.com"
        cookie = _cookie_header(created)
        assert "vp_civic=" in cookie
        assert "httponly" in cookie.casefold()
        assert "samesite=lax" in cookie.casefold()

        me = client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "lettrice@example.com"

        saved = client.put(
            "/auth/profile",
            json={
                "display_name": "Giulia",
                "favorites": [{"id": "206", "name": "Giorgia Meloni"}],
                "parties": [],
                "saved": [],
                "zone": None,
            },
        )
        assert saved.status_code == 200
        assert saved.json()["display_name"] == "Giulia"
        assert saved.json()["profile"]["member"]["name"] == "Giulia"
        assert saved.json()["profile"]["favorites"][0]["id"] == "206"

        client.post("/auth/logout")
        assert client.get("/auth/me").status_code == 401

        login = client.post(
            "/auth/login",
            json={"email": "lettrice@example.com", "password": PASSWORD},
        )
        assert login.status_code == 200
        assert login.json()["display_name"] == "Giulia"
        assert client.get("/auth/me").json()["profile"]["favorites"][0]["id"] == "206"


def test_login_does_not_reveal_whether_email_exists(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        missing = client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": PASSWORD},
        )
        client.post("/auth/register", json={"email": "giulia@example.com", "password": PASSWORD})
        client.post("/auth/logout")
        wrong = client.post(
            "/auth/login",
            json={"email": "giulia@example.com", "password": "wrong-password-1"},
        )
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json()["error"]["message"] == wrong.json()["error"]["message"]
    assert "giulia" not in missing.text.casefold()


def test_duplicate_email_is_conflict(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        first = client.post(
            "/auth/register", json={"email": "giulia@example.com", "password": PASSWORD}
        )
        second = client.post(
            "/auth/register", json={"email": "GIULIA@example.com", "password": PASSWORD}
        )
    assert first.status_code == 200
    assert second.status_code == 409
    assert "già registrata" in second.json()["error"]["message"]


def test_civic_cookie_does_not_open_redazione_or_admin(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        client.post("/auth/register", json={"email": "giulia@example.com", "password": PASSWORD})
        redazione = client.get("/redazione/api/me")
        admin = client.get("/admin/drafts")
        desk = client.get("/redazione/api/accesso")
    assert redazione.status_code == 401
    assert admin.status_code == 401
    assert desk.status_code == 200
    assert desk.json()["configured"] is True


def test_short_password_rejected(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/auth/register", json={"email": "giulia@example.com", "password": "short"}
        )
    assert response.status_code in {400, 422}


def test_register_login_rate_limit(tmp_path):
    app = _app(tmp_path)
    app.state.civic_limiter = AttemptLimiter(limit=3, window_seconds=60)
    with TestClient(app) as client:
        codes = [
            client.post(
                "/auth/login",
                json={"email": "rate@example.com", "password": PASSWORD},
            ).status_code
            for _ in range(4)
        ]
    assert codes[:3] == [401, 401, 401]
    assert codes[3] == 429
