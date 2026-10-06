from alembic import command
from sqlalchemy import inspect

from backend.app.db.schema import alembic_config, current_revision, head_revision
from tests.db.conftest import migrate_sqlite


def test_search_revision_upgrade_downgrade_reupgrade(tmp_path):
    url, engine, _factory = migrate_sqlite(tmp_path)
    cfg = alembic_config(url)
    try:
        assert current_revision(engine) == head_revision(url)
        columns = {column["name"] for column in inspect(engine).get_columns("municipalities")}
        assert "search_primary" in columns
        assert "search_document" in columns
        command.downgrade(cfg, "1864a1eb302a")
        assert current_revision(engine) == "1864a1eb302a"
        columns = {column["name"] for column in inspect(engine).get_columns("municipalities")}
        assert "search_primary" not in columns
        command.upgrade(cfg, "head")
        assert current_revision(engine) == "b7c4e2a91f10"
        columns = {column["name"] for column in inspect(engine).get_columns("proposals")}
        assert "search_primary" in columns
    finally:
        engine.dispose()
