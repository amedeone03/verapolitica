from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from backend.app.db.base import Base
from backend.app.db.schema import (
    alembic_config,
    current_revision,
    head_revision,
)
from backend.app.models import Source  # noqa: F401 — register metadata

from tests.db.conftest import EXPECTED_TABLES, constraint_names, migrate_sqlite

ALEMBIC_CHAIN = (
    "1864a1eb302a",
    "b7c4e2a91f10",
    "c8d5f3b02a21",
    "d1a7e5b94c30",
    "e2b8f6c03d41",
)


def test_alembic_chain_is_linear_single_head():
    script = ScriptDirectory.from_config(alembic_config())
    assert script.get_heads() == [ALEMBIC_CHAIN[-1]]
    assert script.get_base() == ALEMBIC_CHAIN[0]
    walked = tuple(revision.revision for revision in script.walk_revisions())
    assert walked == tuple(reversed(ALEMBIC_CHAIN))
    for index, revision_id in enumerate(ALEMBIC_CHAIN):
        revision = script.get_revision(revision_id)
        expected_down = ALEMBIC_CHAIN[index - 1] if index else None
        assert revision.down_revision == expected_down


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
        command.downgrade(cfg, "b7c4e2a91f10")
        assert current_revision(engine) == "b7c4e2a91f10"
        assert "pledge_assessments" not in inspect(engine).get_table_names()
        assert "politicians" in inspect(engine).get_table_names()
        assert "referendums" not in inspect(engine).get_table_names()
        municipality_columns = {
            column["name"] for column in inspect(engine).get_columns("municipalities")
        }
        assert "search_primary" in municipality_columns
        command.upgrade(cfg, "head")
        assert current_revision(engine) == head_revision(url)
        assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
        municipality_columns = {
            column["name"] for column in inspect(engine).get_columns("municipalities")
        }
        assert "search_primary" in municipality_columns
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
