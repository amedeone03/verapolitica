from argparse import Namespace
from pathlib import Path

from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import Proposal, ProposalDraft
from scripts.run_ai_extraction import run


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2] / "data" / "fixtures" / "ai"
)


def test_operator_cli_fake_provider_creates_draft_only(tmp_path):
    database = tmp_path / "ai-cli.db"
    settings = Settings(
        database_url=f"sqlite:///{database}",
        raw_storage_path=tmp_path / "raw",
    )
    args = Namespace(
        file=FIXTURE_ROOT / "synthetic_official_programme.html",
        source_url="https://official.example/programme.html",
        source_key="official-cli-test",
        source_name="Synthetic CLI source",
        fake_response=FIXTURE_ROOT / "synthetic_fake_response.json",
    )

    summary = run(args, settings=settings)

    assert summary["accepted_count"] == 1
    assert summary["publication"].startswith("none")
    engine = create_db_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(ProposalDraft)) == 1
            proposal = session.scalar(select(Proposal))
            assert proposal.published_at is None
    finally:
        engine.dispose()
