from alembic import command
from sqlalchemy import inspect

from backend.app.db.base import Base
from backend.app.db.schema import (
    alembic_config,
    current_revision,
    head_revision,
)
from backend.app.models import Source  # noqa: F401 — register metadata

from tests.db.conftest import EXPECTED_TABLES, constraint_names, migrate_sqlite


def test_alembic_upgrade_creates_current_schema(tmp_path):
    url, engine, _factory = migrate_sqlite(tmp_path)
    try:
        tables = set(inspect(engine).get_table_names())
        assert EXPECTED_TABLES <= tables
        assert "alembic_version" in tables
        assert current_revision(engine) == head_revision(url)
        assert current_revision(engine) is not None
        names = constraint_names(engine, "ingestion_job_runs")
        assert "uq_ingestion_job_runs_running_name" in names
        politician_ids = constraint_names(engine, "politician_source_identifiers")
        assert "uq_politician_source_identifiers_source_value" in politician_ids
        municipality_checks = constraint_names(engine, "municipalities")
        assert "ck_municipalities_istat_code" in municipality_checks
        proposal_ids = constraint_names(engine, "proposal_source_identifiers")
        assert "uq_proposal_source_identity" in proposal_ids
    finally:
        engine.dispose()


def test_alembic_downgrade_and_reupgrade(tmp_path):
    url, engine, _factory = migrate_sqlite(tmp_path)
    cfg = alembic_config(url)
    try:
        command.downgrade(cfg, "-1")
        assert current_revision(engine) is None
        assert "politicians" not in inspect(engine).get_table_names()
        command.upgrade(cfg, "head")
        assert current_revision(engine) == head_revision(url)
        assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migrated_schema_matches_sqlalchemy_metadata(tmp_path):
    _url, engine, _factory = migrate_sqlite(tmp_path)
    try:
        migrated = set(inspect(engine).get_table_names()) - {"alembic_version"}
        modeled = set(Base.metadata.tables)
        assert modeled == migrated
    finally:
        engine.dispose()
