from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.config import AppEnvironment, Settings
from backend.app.db.schema import alembic_config, current_revision, head_revision
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import Source
from backend.app.storage.local import LocalRawStorage
from scripts.backup_ops import (
    archive_directory,
    dump_postgres,
    extract_archive,
    find_pg_binary,
    restore_postgres,
)
from tests.db.conftest import isolated_postgres_database


pytestmark = pytest.mark.postgres


def _production_settings(url: str, raw_path: Path) -> Settings:
    return Settings(
        env=AppEnvironment.PRODUCTION,
        database_url=url,
        admin_api_key="a-sufficiently-long-admin-token",
        cors_origins="https://verapolitica.it",
        trusted_hosts="testserver,verapolitica.it",
        public_base_url="https://verapolitica.it",
        raw_storage_path=raw_path.resolve(),
        log_format="json",
        enable_demo_ui=False,
        enable_api_docs=False,
    )


def test_isolated_postgres_backup_restore_roundtrip(tmp_path):
    if not find_pg_binary("pg_dump") or not find_pg_binary("pg_restore"):
        pytest.skip("pg_dump/pg_restore are not installed")

    raw_source = tmp_path / "raw-source"
    raw_source.mkdir()
    content = b"isolated-backup-raw-document"
    digest = hashlib.sha256(content).hexdigest()
    stored_key = LocalRawStorage(raw_source).put("senato", digest, content)

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    dump_path = backup_dir / "isolated.dump"
    raw_archive = backup_dir / "isolated-raw.tar.gz"
    expected_revision = None

    with isolated_postgres_database("verapolitica_backup_src") as source_url:
        engine = create_db_engine(source_url)
        try:
            command.upgrade(alembic_config(source_url), "head")
            expected_revision = current_revision(engine)
            assert expected_revision == head_revision(source_url)
            factory = create_session_factory(engine)
            with factory() as session:
                with session.begin():
                    session.add(
                        Source(
                            key="backup-roundtrip",
                            name="Backup Roundtrip Source",
                            base_url="https://example.invalid/backup",
                        )
                    )
            dump_postgres(source_url, dump_path)
            archive_directory(raw_source, raw_archive, label="RAW_STORAGE_PATH")
        finally:
            engine.dispose()

    raw_restored = tmp_path / "raw-restored"
    with isolated_postgres_database("verapolitica_backup_dst") as dest_url:
        dest_engine = create_db_engine(dest_url)
        try:
            assert current_revision(dest_engine) is None
            restore_postgres(dest_url, dump_path, confirmed=True, replace_existing=False)
            assert current_revision(dest_engine) == expected_revision
            assert current_revision(dest_engine) == head_revision(dest_url)
            factory = create_session_factory(dest_engine)
            with factory() as session:
                restored = session.scalar(
                    select(Source).where(Source.key == "backup-roundtrip")
                )
                assert restored is not None
                assert restored.name == "Backup Roundtrip Source"
            extract_archive(
                raw_archive,
                raw_restored,
                confirmed=True,
                replace_existing=False,
                label="raw storage",
            )
            assert LocalRawStorage(raw_restored).get(stored_key) == content
            settings = _production_settings(dest_url, raw_restored)
            with TestClient(create_app(settings)) as client:
                live = client.get("/health/live")
                ready = client.get("/health/ready")
            assert live.status_code == 200
            assert ready.status_code == 200
            assert ready.json()["schema_current"] is True
        finally:
            dest_engine.dispose()
