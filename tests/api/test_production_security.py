from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.app.api.errors import _safe_validation_details
from backend.app.core.config import AppEnvironment, Settings
from backend.app.core.middleware import request_body_limit
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine
from backend.app.main import create_app


def _app(tmp_path, **overrides):
    values = {
        "env": AppEnvironment.TEST,
        "database_url": f"sqlite:///{tmp_path / 'sec.db'}",
        "raw_storage_path": tmp_path / "raw",
        "admin_api_key": "test-admin-secret",
        "trusted_hosts": "localhost,127.0.0.1,testserver",
        "cors_origins": "https://verapolitica.it,http://127.0.0.1:8000",
        "enable_demo_ui": False,
        "enable_api_docs": False,
        "max_request_body_bytes": 65_536,
    }
    values.update(overrides)
    settings = Settings(**values)
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return create_app(settings), settings


def test_admin_requires_bearer_and_rejects_alternate_channels(tmp_path):
    app, _settings = _app(tmp_path)
    with TestClient(app) as client:
        missing = client.get("/admin/drafts")
        invalid = client.get(
            "/admin/drafts", headers={"Authorization": "Bearer wrong-key"}
        )
        query = client.get("/admin/drafts", params={"api_key": "test-admin-secret"})
        header = client.get("/admin/drafts", headers={"X-Admin-Key": "test-admin-secret"})
        body = client.post(
            "/admin/jobs/senato/run",
            json={"admin_api_key": "test-admin-secret"},
        )
        ok = client.get(
            "/admin/drafts",
            headers={"Authorization": "Bearer test-admin-secret"},
        )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert query.status_code == 401
    assert header.status_code == 401
    assert body.status_code == 401
    assert ok.status_code == 200
    blob = missing.text + invalid.text + ok.text
    assert "test-admin-secret" not in blob
    assert "wrong-key" not in blob


def test_production_defaults_keep_demo_and_docs_off():
    settings = Settings(
        env=AppEnvironment.PRODUCTION,
        database_url="postgresql+psycopg://verapolitica:x@localhost:5432/verapolitica",
        admin_api_key="a-sufficiently-long-admin-token",
        cors_origins="https://verapolitica.it",
        trusted_hosts="verapolitica.it",
        public_base_url="https://verapolitica.it",
        raw_storage_path="/var/lib/verapolitica/raw",
    )
    assert settings.is_production
    assert settings.demo_ui_enabled is False
    assert settings.api_docs_enabled is False


def test_demo_and_upload_routes_absent_when_disabled(tmp_path):
    app, _settings = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/demo/").status_code == 404
        assert client.get("/demo/ai-upload").status_code == 404
        assert client.post("/demo/ai-upload/ingest").status_code == 404
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/app/").status_code == 200


def test_static_and_portrait_path_traversal_rejected(tmp_path):
    portraits = tmp_path / "portraits.json"
    portraits.write_text(
        json.dumps(
            {
                "1": {
                    "file": "../secret.txt",
                    "url": "https://example.com/x.jpg",
                    "credit": "x",
                    "license": "CC0",
                    "source_url": "https://example.com",
                    "origin": "test",
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "secret.txt").write_text("should-not-be-served", encoding="utf-8")
    app, _settings = _app(tmp_path, portraits_path=portraits)
    with TestClient(app) as client:
        listing = client.get("/portraits")
        image = client.get("/portraits/1/image")
        escaped = client.get("/app/../../backend/app/core/config.py")
        encoded = client.get("/app/%2e%2e/%2e%2e/.env")
    assert listing.status_code == 200
    listed = listing.json().get("1", {})
    assert listed.get("url") != "/portraits/1/image"
    assert image.status_code == 404
    assert "should-not-be-served" not in image.text
    assert escaped.status_code in {404, 400}
    assert encoded.status_code in {404, 400}
    assert "database_url" not in escaped.text


def test_oversized_body_rejected(tmp_path):
    app, _settings = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/admin/drafts",
            headers={"Authorization": "Bearer test-admin-secret"},
            content=b"x" * 70_000,
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert "test-admin-secret" not in response.text


def test_demo_upload_limit_is_not_the_public_json_cap():
    settings = Settings(
        env=AppEnvironment.DEVELOPMENT,
        enable_demo_ui=True,
        max_request_body_bytes=65_536,
        ai_max_document_bytes=1_000_000,
    )
    assert request_body_limit(settings, "/admin/drafts") == 65_536
    assert request_body_limit(settings, "/demo/ai-upload/ingest") == 1_000_000 + 65_536


def test_production_validation_details_omit_submitted_input():
    errors = [
        {
            "type": "extra_forbidden",
            "loc": ["body", "admin_api_key"],
            "msg": "Extra inputs are not permitted",
            "input": "super-secret-value",
            "ctx": {"error": "x"},
        }
    ]
    details = _safe_validation_details(errors, production=True)
    blob = json.dumps(details)
    assert "super-secret-value" not in blob
    assert "input" not in details[0]
    assert "ctx" not in details[0]
    development = _safe_validation_details(errors, production=False)
    assert development[0]["input"] == "super-secret-value"


def test_settings_json_does_not_expose_admin_key():
    settings = Settings(
        admin_api_key="test-admin-secret",
        llm_api_key="llm-secret-value",
    )
    dumped = settings.model_dump(mode="json")
    assert dumped["admin_api_key"] != "test-admin-secret"
    assert dumped["llm_api_key"] != "llm-secret-value"
    assert "test-admin-secret" not in json.dumps(dumped)
    assert "llm-secret-value" not in json.dumps(dumped)


def test_cors_does_not_allow_write_methods_from_browser(tmp_path):
    app, _settings = _app(tmp_path)
    with TestClient(app) as client:
        preflight = client.options(
            "/admin/drafts",
            headers={
                "Origin": "https://verapolitica.it",
                "Access-Control-Request-Method": "POST",
            },
        )
        allowed_get = client.options(
            "/politicians",
            headers={
                "Origin": "https://verapolitica.it",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert preflight.headers.get("access-control-allow-methods", "") == "" or (
        "POST" not in preflight.headers.get("access-control-allow-methods", "")
    )
    assert "GET" in allowed_get.headers.get("access-control-allow-methods", "GET")
