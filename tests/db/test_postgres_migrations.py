from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from backend.app.core.config import AppEnvironment, Settings
from backend.app.db.schema import (
    alembic_config,
    current_revision,
    head_revision,
    prepare_runtime_schema,
)
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import Source

from tests.db.conftest import (
    EXPECTED_TABLES,
    isolated_postgres_database,
)
from tests.db.test_alembic_migrations import ALEMBIC_CHAIN


pytestmark = pytest.mark.postgres

HEAD = ALEMBIC_CHAIN[-1]
PRIOR = ALEMBIC_CHAIN[-2]
INITIAL = ALEMBIC_CHAIN[0]


def _production_settings(url: str, tmp_path: Path) -> Settings:
    return Settings(
        env=AppEnvironment.PRODUCTION,
        database_url=url,
        admin_api_key="a-sufficiently-long-admin-token",
        cors_origins="https://verapolitica.it",
        trusted_hosts="testserver,verapolitica.it",
        public_base_url="https://verapolitica.it",
        raw_storage_path=(tmp_path / "raw").resolve(),
        log_format="json",
        enable_demo_ui=False,
        enable_api_docs=False,
    )


def test_fresh_empty_postgres_migrates_to_head(tmp_path):
    with isolated_postgres_database("verapolitica_fresh_migrate") as url:
        engine = create_db_engine(url)
        try:
            tables = set(inspect(engine).get_table_names())
            assert not (EXPECTED_TABLES & tables)
            assert "alembic_version" not in tables
            cfg = alembic_config(url)
            command.upgrade(cfg, "head")
            assert current_revision(engine) == HEAD
            assert current_revision(engine) == head_revision(url)
            tables = set(inspect(engine).get_table_names())
            assert EXPECTED_TABLES <= tables
            assert "alembic_version" in tables
            indexes = {index["name"] for index in inspect(engine).get_indexes("politicians")}
            assert "ix_politicians_normalized_name_trgm" in indexes
            factory = create_session_factory(engine)
            with factory() as session:
                with session.begin():
                    session.add(
                        Source(
                            key="senato-repubblica",
                            name="Senato della Repubblica",
                            base_url="https://dati.senato.it",
                        )
                    )
            with factory() as session:
                stored = session.scalar(select(Source).where(Source.key == "senato-repubblica"))
                assert stored is not None
                assert stored.name == "Senato della Repubblica"
            settings = _production_settings(url, tmp_path)
            with TestClient(create_app(settings)) as client:
                live = client.get("/health/live")
                ready = client.get("/health/ready")
                politicians = client.get("/politicians", params={"offset": 0, "limit": 1})
            assert live.status_code == 200
            assert ready.status_code == 200
            assert ready.json()["ready"] is True
            assert ready.json()["schema_current"] is True
            assert ready.json()["schema_revision"] == HEAD
            assert ready.json()["schema_revision"] == "f3c9a7d14e52"
            assert "politician_biographies" in tables
            assert "politician_career_entries" in tables
            assert "politician_positions" in tables
            assert "politician_proceedings" in tables
            assert "politician_profile_sources" in tables
            assert politicians.status_code == 200
        finally:
            engine.dispose()


def test_postgres_upgrade_from_prior_revision_preserves_data(tmp_path):
    with isolated_postgres_database("verapolitica_upgrade_path") as url:
        engine = create_db_engine(url)
        cfg = alembic_config(url)
        try:
            command.upgrade(cfg, INITIAL)
            assert current_revision(engine) == INITIAL
            tables = set(inspect(engine).get_table_names())
            assert "sources" in tables
            assert "politicians" in tables
            assert "pledge_evidence_candidates" not in tables
            assert "referendums" not in tables
            factory = create_session_factory(engine)
            with factory() as session:
                with session.begin():
                    session.add(
                        Source(
                            key="camera-deputati",
                            name="Camera dei Deputati",
                            base_url="https://dati.camera.it",
                        )
                    )
            command.upgrade(cfg, "head")
            assert current_revision(engine) == HEAD
            tables = set(inspect(engine).get_table_names())
            assert EXPECTED_TABLES <= tables
            municipality_columns = {
                column["name"] for column in inspect(engine).get_columns("municipalities")
            }
            assert "search_primary" in municipality_columns
            candidate_indexes = {
                index["name"] for index in inspect(engine).get_indexes("pledge_evidence_candidates")
            }
            assert "ix_pledge_evidence_candidates_status" in candidate_indexes
            with factory() as session:
                stored = session.scalar(select(Source).where(Source.key == "camera-deputati"))
                assert stored is not None
                assert stored.base_url == "https://dati.camera.it"
        finally:
            engine.dispose()


def test_postgres_upgrade_from_previous_head_adds_profile_narratives():
    with isolated_postgres_database("verapolitica_upgrade_head") as url:
        engine = create_db_engine(url)
        cfg = alembic_config(url)
        try:
            command.upgrade(cfg, PRIOR)
            assert current_revision(engine) == PRIOR
            tables = inspect(engine).get_table_names()
            assert "pledge_assessments" in tables
            assert "pledge_evidence_candidates" in tables
            assert "politician_biographies" not in tables
            assert "politician_career_entries" not in tables
            assert "politician_positions" not in tables
            assert "politician_proceedings" not in tables
            assert "politician_profile_sources" not in tables
            command.upgrade(cfg, "head")
            assert current_revision(engine) == HEAD
            assert current_revision(engine) == "f3c9a7d14e52"
            tables = inspect(engine).get_table_names()
            assert "politician_biographies" in tables
            assert "politician_career_entries" in tables
            assert "politician_positions" in tables
            assert "politician_proceedings" in tables
            assert "politician_profile_sources" in tables
        finally:
            engine.dispose()


def test_prepare_runtime_schema_does_not_create_postgres_tables(tmp_path):
    with isolated_postgres_database("verapolitica_no_create_all") as url:
        engine = create_db_engine(url)
        try:
            prepare_runtime_schema(engine, _production_settings(url, tmp_path))
            tables = set(inspect(engine).get_table_names())
            assert "sources" not in tables
            assert "alembic_version" not in tables
            assert current_revision(engine) is None
        finally:
            engine.dispose()


def test_unmigrated_postgres_is_not_ready(tmp_path):
    with isolated_postgres_database("verapolitica_unmigrated") as url:
        settings = _production_settings(url, tmp_path)
        with TestClient(create_app(settings)) as client:
            live = client.get("/health/live")
            ready = client.get("/health/ready")
        assert live.status_code == 200
        assert ready.status_code == 503
        payload = ready.json()
        assert payload["ready"] is False
        assert payload["schema_current"] is False
