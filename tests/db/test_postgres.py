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


def test_postgres_search_exact_and_conservative_typo():
    from datetime import date, datetime, timezone

    from backend.app.models import Politician, PoliticianVersion
    from backend.app.schemas import PoliticalMandate, PoliticianVersionProfile
    from backend.app.services import SearchService, normalize_person_name
    from backend.app.schemas.search import SearchEntityType

    url = postgres_url()
    cfg = alembic_config(url)
    engine = create_db_engine(url)
    factory = create_session_factory(engine)
    try:
        command.upgrade(cfg, "head")
        with factory() as session:
            with session.begin():
                politician = Politician(
                    canonical_given_name="Giorgia",
                    canonical_family_name="Meloni",
                    normalized_name=normalize_person_name("Giorgia", "Meloni"),
                    birth_date=date(1977, 1, 15),
                )
                session.add(politician)
                session.flush()
                version = PoliticianVersion(
                    politician_id=politician.id,
                    version_number=1,
                    profile_schema_version=1,
                    profile_data=PoliticianVersionProfile(
                        given_name="Giorgia",
                        family_name="Meloni",
                        birth_date=date(1977, 1, 15),
                        mandates=(
                            PoliticalMandate(
                                institution="Presidenza del Consiglio",
                                office="president of the council",
                                legislature="19",
                                mandate_type="governo",
                                start_date=date(2022, 10, 22),
                            ),
                        ),
                    ).model_dump(mode="json"),
                    published_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
                )
                session.add(version)
                session.flush()
                politician.current_version_id = version.id
        with factory() as session:
            service = SearchService(session)
            exact = service.search("Giorgia Meloni", entity_type=SearchEntityType.POLITICIAN)
            typo = service.search("Giorga Meloni", entity_type=SearchEntityType.POLITICIAN)
            assert exact.items[0].title == "Giorgia Meloni"
            assert typo.total >= 1
            assert typo.items[0].title == "Giorgia Meloni"
    finally:
        engine.dispose()
