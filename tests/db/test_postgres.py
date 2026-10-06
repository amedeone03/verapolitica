import os

import pytest
from alembic import command
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from backend.app.db.schema import alembic_config, current_revision, head_revision
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import IngestionJobRun, IngestionJobStatus, IngestionJobTrigger

from tests.db.conftest import EXPECTED_TABLES


pytestmark = pytest.mark.postgres


def postgres_url() -> str:
    url = os.environ.get("VERAPOLITICA_POSTGRES_TEST_URL", "").strip()
    if not url:
        pytest.skip("VERAPOLITICA_POSTGRES_TEST_URL is not set")
    return url


def test_postgres_upgrade_and_job_run_roundtrip():
    url = postgres_url()
    cfg = alembic_config(url)
    engine = create_db_engine(url)
    factory = create_session_factory(engine)
    try:
        command.upgrade(cfg, "head")
        tables = set(inspect(engine).get_table_names())
        assert EXPECTED_TABLES <= tables
        assert current_revision(engine) == head_revision(url)
        with factory() as session:
            with session.begin():
                for existing in session.scalars(select(IngestionJobRun)):
                    session.delete(existing)
        with factory() as session:
            with session.begin():
                session.add(
                    IngestionJobRun(
                        job_name="senato",
                        source_key="senato-repubblica",
                        status=IngestionJobStatus.RUNNING,
                        trigger_type=IngestionJobTrigger.CLI,
                        job_metadata={"note": "postgres"},
                    )
                )
        with factory() as session:
            with pytest.raises(IntegrityError):
                with session.begin():
                    session.add(
                        IngestionJobRun(
                            job_name="senato",
                            source_key="senato-repubblica",
                            status=IngestionJobStatus.RUNNING,
                            trigger_type=IngestionJobTrigger.CLI,
                            job_metadata={},
                        )
                    )
        with factory() as session:
            with session.begin():
                for existing in session.scalars(select(IngestionJobRun)):
                    session.delete(existing)
        command.downgrade(cfg, "-1")
        command.upgrade(cfg, "head")
        assert current_revision(engine) == head_revision(url)
    finally:
        engine.dispose()
