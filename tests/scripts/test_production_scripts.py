import json

import pytest

from backend.app.core.config import AppEnvironment, Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine
from scripts.prepare_demo import DemoSafetyError, prepare_demo
from scripts.release_check import main as release_check_main
from scripts.run_web import gunicorn_argv
from scripts.smoke_test import READ_ONLY_PATHS, parse_args


def test_prepare_demo_refuses_production(monkeypatch, tmp_path):
    monkeypatch.setenv("VERAPOLITICA_ENV", "production")
    with pytest.raises(DemoSafetyError, match="production"):
        prepare_demo(workspace_root=tmp_path / "workspace")


def test_release_check_passes_isolated_sqlite(tmp_path, monkeypatch, capsys):
    database = tmp_path / "release.db"
    settings = Settings(
        env=AppEnvironment.TEST,
        database_url=f"sqlite:///{database}",
        raw_storage_path=tmp_path / "raw",
        admin_api_key="test-admin-secret",
    )
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    monkeypatch.setattr("scripts.release_check.get_settings", lambda: settings)
    assert release_check_main() == 0
    captured = capsys.readouterr().out
    report = json.loads(captured)
    assert report["ok"] is True
    assert "postgresql+psycopg://" not in captured
    assert "password" not in captured.casefold()


def test_smoke_test_is_read_only():
    args = parse_args(["--base-url", "http://127.0.0.1:8000"])
    assert args.base_url == "http://127.0.0.1:8000"
    assert all(path.startswith("/") for path in READ_ONLY_PATHS)
    assert all("/admin" not in path for path in READ_ONLY_PATHS)
    assert "/health/live" in READ_ONLY_PATHS


def test_gunicorn_command_is_production_safe():
    argv = gunicorn_argv(
        Settings(web_host="0.0.0.0", web_port=8000, web_workers=2)
    )
    assert argv[0] == "gunicorn"
    assert "--reload" not in argv
    assert "uvicorn.workers.UvicornWorker" in argv
