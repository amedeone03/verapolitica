from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from backend.app.db.base import Base
from backend.app.db.schema import alembic_config, current_revision, head_revision
from tests.db.conftest import migrate_sqlite

NEW_TABLES = {"proposal_tags", "editorial_posts", "legislatures", "historical_parliament_mandates"}


def test_archive_revision_matches_models_and_seeds_legislatures(tmp_path):
    url, engine, _factory = migrate_sqlite(tmp_path)
    try:
        assert current_revision(engine) == head_revision(url)
        assert NEW_TABLES <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            rows = connection.execute(
                text("select number, start_date, end_date from legislatures order by number")
            ).all()
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert [row[0] for row in rows] == list(range(20))
        assert str(rows[12][1]) == "1994-04-15" and rows[-1][2] is None
        drift = [item for item in diff if any(name in repr(item) for name in NEW_TABLES)]
        assert drift == []

        cfg = alembic_config(url)
        command.downgrade(cfg, "f3c9a7d14e52")
        assert not NEW_TABLES & set(inspect(engine).get_table_names())
        command.upgrade(cfg, "head")
        assert NEW_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
