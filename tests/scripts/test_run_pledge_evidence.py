from argparse import Namespace
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import PledgeAssessment, Source  # noqa: F401
from scripts.prepare_demo import DemoSafetyError
from scripts.run_pledge_evidence import run
from scripts.unified_demo import UnifiedDemoPaths, assert_settings_are_unified
from tests.services.pledge_seed import seed
from tests.services.test_pledge_service import classification
from backend.app.services.pledge_service import PledgeService


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "fixtures"
    / "pledge_evidence"
    / "legge_86_2024_autonomia.html"
)


def test_cli_ingests_official_file_and_does_not_publish(tmp_path):
    database = tmp_path / "pledge-evidence.db"
    settings = Settings(
        database_url=f"sqlite:///{database}",
        raw_storage_path=tmp_path / "raw",
    )
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    data = seed(factory)
    PledgeService(factory).classify(data.pledge_id, classification(), classified_by="ed")
    engine.dispose()

    summary = run(
        Namespace(
            proposal_id=data.pledge_id,
            all_unrated=False,
            dry_run=False,
            conservative_judge=True,
            use_llm=False,
            ingest_url="https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg",
            ingest_file=FIXTURE,
            source_name="Gazzetta Ufficiale",
            source_key="gazzetta-ufficiale",
            published_at="2024-06-26",
        ),
        settings=settings,
    )
    assert summary["published"] is False
    engine = create_db_engine(settings.database_url)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(PledgeAssessment)) == 0
    finally:
        engine.dispose()


def test_cli_refuses_news_url(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'news.db'}",
        raw_storage_path=tmp_path / "raw",
    )
    with pytest.raises(ValueError, match="non-official"):
        run(
            Namespace(
                proposal_id=1,
                all_unrated=False,
                dry_run=True,
                conservative_judge=False,
                use_llm=False,
                ingest_url="https://www.corriere.it/politica/autonomia",
                ingest_file=FIXTURE,
                source_name="News",
                source_key="news",
                published_at=None,
            ),
            settings=settings,
        )


def test_unified_wrapper_refuses_ceo_and_demo_paths(tmp_path):
    workspace = tmp_path / "repo"
    (workspace / "data" / "unified_demo").mkdir(parents=True)
    paths = UnifiedDemoPaths.for_workspace(workspace)
    with pytest.raises(DemoSafetyError):
        assert_settings_are_unified(
            f"sqlite:///{workspace / 'data' / 'ceo_demo' / 'verapolitica.db'}",
            paths.raw_storage,
            workspace,
        )
    with pytest.raises(DemoSafetyError):
        assert_settings_are_unified(
            f"sqlite:///{workspace / 'data' / 'demo' / 'verapolitica.db'}",
            paths.raw_storage,
            workspace,
        )

