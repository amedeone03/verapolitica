from sqlalchemy import Boolean, DateTime, JSON, inspect

from backend.app.db.base import Base
from backend.app.models import IngestionJobRun, Municipality, Source  # noqa: F401

from tests.db.conftest import migrate_sqlite


def test_portable_column_types_are_postgres_compatible(tmp_path):
    _url, engine, _factory = migrate_sqlite(tmp_path)
    try:
        inspector = inspect(engine)
        job_columns = {column["name"]: column for column in inspector.get_columns("ingestion_job_runs")}
        assert job_columns["error_message"]["nullable"] is True
        assert job_columns["metadata"]["nullable"] is False
        source_columns = {column["name"]: column for column in inspector.get_columns("sources")}
        assert source_columns["is_enabled"]["nullable"] is False
        region_columns = {column["name"]: column for column in inspector.get_columns("regions")}
        assert region_columns["istat_code"]["nullable"] is False
    finally:
        engine.dispose()

    metadata_column = IngestionJobRun.__table__.c["metadata"]
    assert isinstance(metadata_column.type, JSON)
    assert metadata_column.name == "metadata"
    started = IngestionJobRun.__table__.c.started_at
    assert isinstance(started.type, DateTime)
    assert started.type.timezone is True
    enabled = Source.__table__.c.is_enabled
    assert isinstance(enabled.type, Boolean)
    istat = Municipality.__table__.c.istat_code
    assert istat.type.length == 6
    for table in Base.metadata.tables.values():
        for column in table.columns:
            enum_type = getattr(column.type, "native_enum", None)
            if enum_type is False or enum_type is True:
                assert enum_type is False
