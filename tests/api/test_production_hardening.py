from fastapi.testclient import TestClient

from backend.app.core.config import AppEnvironment, Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine
from backend.app.main import create_app
from scripts.run_web import gunicorn_argv


def _app(tmp_path, **overrides):
    values = {
        "env": AppEnvironment.TEST,
        "database_url": f"sqlite:///{tmp_path / 'prod.db'}",
        "raw_storage_path": tmp_path / "raw",
        "admin_api_key": "test-admin-secret",
        "trusted_hosts": "localhost,127.0.0.1,testserver",
        "cors_origins": "https://verapolitica.it,http://127.0.0.1:8000",
        "enable_demo_ui": False,
        "enable_api_docs": False,
    }
    values.update(overrides)
    settings = Settings(**values)
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return create_app(settings), settings


def test_liveness_and_readiness(tmp_path):
    app, _settings = _app(tmp_path)
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
        compat = client.get("/health")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert compat.status_code == 200
    assert "password" not in live.text.casefold()
    assert "database_url" not in ready.text.casefold()


def test_readiness_fails_when_alembic_revision_behind(tmp_path):
    from alembic import command

    from backend.app.db.schema import alembic_config

    url = f"sqlite:///{tmp_path / 'behind.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")
    settings = Settings(
        database_url=url,
        raw_storage_path=tmp_path / "raw",
        admin_api_key="test-admin-secret",
        trusted_hosts="testserver",
        enable_demo_ui=False,
        enable_api_docs=False,
    )
    with TestClient(create_app(settings)) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json()["ready"] is False


def test_security_headers_and_request_id(tmp_path):
    app, _settings = _app(tmp_path)
    with TestClient(app) as client:
        generated = client.get("/health/live")
        propagated = client.get(
            "/health/live", headers={"X-Request-ID": "client-request-id-1"}
        )
    assert generated.headers["X-Request-ID"]
    assert propagated.headers["X-Request-ID"] == "client-request-id-1"
    assert generated.headers["X-Content-Type-Options"] == "nosniff"
    assert generated.headers["Referrer-Policy"] == "no-referrer"
    assert generated.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in generated.headers["Content-Security-Policy"]
    assert "camera=()" in generated.headers["Permissions-Policy"]


def test_cors_allowlist_and_trusted_host(tmp_path):
    app, _settings = _app(tmp_path)
    with TestClient(app) as client:
        allowed = client.get(
            "/health/live", headers={"Origin": "https://verapolitica.it"}
        )
        denied = client.get(
            "/health/live", headers={"Origin": "https://evil.example"}
        )
        bad_host = client.get("/health/live", headers={"host": "evil.example"})
    assert allowed.headers.get("access-control-allow-origin") == "https://verapolitica.it"
    assert denied.headers.get("access-control-allow-origin") != "https://evil.example"
    assert bad_host.status_code == 400


def test_demo_ui_and_docs_disabled(tmp_path):
    app, _settings = _app(tmp_path)
    with TestClient(app) as client:
        demo = client.get("/demo/")
        docs = client.get("/docs")
        openapi = client.get("/openapi.json")
        public = client.get("/app/")
        admin = client.get("/admin/drafts")
    assert demo.status_code == 404
    assert docs.status_code == 404
    assert openapi.status_code == 404
    assert public.status_code == 200
    assert admin.status_code == 401


def test_generic_500_does_not_leak_secrets(tmp_path):
    app, _settings = _app(tmp_path)

    @app.get("/__boom")
    def boom():
        raise RuntimeError(
            "VERAPOLITICA_ADMIN_API_KEY=super-secret-value postgresql+psycopg://x:y@db/z"
        )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/__boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    blob = str(body).casefold()
    assert "super-secret-value" not in blob
    assert "postgresql+psycopg" not in blob
    assert "traceback" not in blob
    assert body["error"]["request_id"]
    assert response.headers.get("X-Request-ID")


def test_raw_storage_and_web_command_are_configurable(tmp_path):
    settings = Settings(
        raw_storage_path=tmp_path / "raw-store",
        web_host="127.0.0.1",
        web_port=9000,
        web_workers=3,
    )
    argv = gunicorn_argv(settings)
    assert settings.raw_storage_path == tmp_path / "raw-store"
    assert "--workers" in argv
    assert "3" in argv
    assert "127.0.0.1:9000" in argv
    assert "uvicorn.workers.UvicornWorker" in argv
    assert "--reload" not in argv


def test_smoke_test_against_local_app(tmp_path):
    app, _settings = _app(tmp_path)
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
        search = client.get("/search", params={"q": "test", "limit": 1})
        regions = client.get("/regions", params={"offset": 0, "limit": 1})
        glossary = client.get("/glossary", params={"offset": 0, "limit": 1})
        politicians = client.get("/politicians", params={"offset": 0, "limit": 1})
        proposals = client.get("/proposals", params={"offset": 0, "limit": 1})
        referendums = client.get("/referendums", params={"offset": 0, "limit": 1})
    assert live.status_code == 200
    assert ready.status_code == 200
    assert search.status_code == 200
    assert regions.status_code == 200
    assert glossary.status_code == 200
    assert politicians.status_code == 200
    assert proposals.status_code == 200
    assert referendums.status_code == 200


def test_web_process_does_not_start_scheduler(tmp_path):
    app, _settings = _app(tmp_path, schedule_senato_cron="0 3 * * *")
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert not hasattr(app.state, "scheduler")


def test_invalid_request_id_is_replaced(tmp_path):
    app, _settings = _app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/health/live", headers={"X-Request-ID": "short"})
    assert response.headers["X-Request-ID"] != "short"
    assert len(response.headers["X-Request-ID"]) >= 8


def test_docs_can_be_enabled_explicitly(tmp_path):
    app, _settings = _app(tmp_path, enable_api_docs=True)
    with TestClient(app) as client:
        docs = client.get("/docs")
        openapi = client.get("/openapi.json")
    assert docs.status_code == 200
    assert openapi.status_code == 200
    assert "paths" in openapi.json()


def test_docs_csp_allows_swagger_assets_only_on_docs_pages(tmp_path):
    from backend.app.core.config import Settings
    from backend.app.main import create_app

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'docs.db'}",
        raw_storage_path=tmp_path / "raw",
        enable_api_docs=True,
    )
    with TestClient(create_app(settings)) as client:
        docs = client.get("/docs")
        public = client.get("/app/")
    assert docs.status_code == 200
    docs_csp = docs.headers["Content-Security-Policy"]
    assert "https://cdn.jsdelivr.net" in docs_csp
    assert "frame-ancestors 'none'" in docs_csp
    public_csp = public.headers["Content-Security-Policy"]
    assert "cdn.jsdelivr.net" not in public_csp
    assert "script-src 'self';" in public_csp


def test_frontend_assets_are_revalidated(tmp_path):
    from backend.app.core.config import Settings
    from backend.app.main import create_app

    settings = Settings(database_url=f"sqlite:///{tmp_path / 'cache.db'}", raw_storage_path=tmp_path / "raw")
    with TestClient(create_app(settings)) as client:
        script = client.get("/app/app.js")
        health = client.get("/health/live")
    assert script.headers["Cache-Control"] == "no-cache"
    assert "no-cache" not in health.headers.get("Cache-Control", "")
