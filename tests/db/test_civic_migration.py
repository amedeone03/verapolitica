from alembic import command
from sqlalchemy import inspect

from backend.app.db.schema import alembic_config, current_revision, head_revision
from tests.db.conftest import migrate_sqlite


def test_civic_revision_upgrade_downgrade_reupgrade(tmp_path):
    url, engine, _factory = migrate_sqlite(tmp_path)
    cfg = alembic_config(url)
    try:
        assert current_revision(engine) == head_revision(url)
        tables = set(inspect(engine).get_table_names())
        assert "referendums" in tables
        assert "voting_guides" in tables
        assert "glossary_terms" in tables
        assert "notification_reminder_candidates" in tables
        command.downgrade(cfg, "b7c4e2a91f10")
        assert current_revision(engine) == "b7c4e2a91f10"
        tables = set(inspect(engine).get_table_names())
        assert "referendums" not in tables
        command.upgrade(cfg, "head")
        assert current_revision(engine) == head_revision(url)
        columns = {column["name"] for column in inspect(engine).get_columns("referendums")}
        assert "official_question" in columns
        assert "search_primary" in columns
    finally:
        engine.dispose()
