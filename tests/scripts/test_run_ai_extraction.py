from argparse import Namespace
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import AIExtractionRun, Proposal, ProposalDraft
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
        force=False,
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


def test_operator_cli_force_creates_new_run_without_publishing(tmp_path):
    database = tmp_path / "ai-cli-force.db"
    settings = Settings(
        database_url=f"sqlite:///{database}",
        raw_storage_path=tmp_path / "raw",
        enable_demo_ui=True,
    )
    args = Namespace(
        file=FIXTURE_ROOT / "synthetic_official_programme.html",
        source_url="https://official.example/programme.html",
        source_key="official-cli-force",
        source_name="Synthetic CLI source",
        fake_response=FIXTURE_ROOT / "synthetic_fake_response.json",
        force=False,
    )
    first = run(args, settings=settings)
    repeated = run(args, settings=settings)
    args.force = True
    forced = run(args, settings=settings)

    assert first["accepted_count"] == 1
    assert repeated["reused_completed_run"] is True
    assert repeated["extraction_run_id"] == first["extraction_run_id"]
    assert forced["reused_completed_run"] is False
    assert forced["extraction_run_id"] != first["extraction_run_id"]
    engine = create_db_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(AIExtractionRun)) == 2
            assert session.scalar(select(func.count()).select_from(ProposalDraft)) == 1
            proposal = session.scalar(select(Proposal))
            assert proposal.published_at is None
    finally:
        engine.dispose()


def test_operator_cli_force_rejected_when_demo_ui_disabled(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'ai-cli-hidden.db'}",
        raw_storage_path=tmp_path / "raw",
        enable_demo_ui=False,
    )
    args = Namespace(
        file=FIXTURE_ROOT / "synthetic_official_programme.html",
        source_url="https://official.example/programme.html",
        source_key="official-cli-hidden",
        source_name="Synthetic CLI source",
        fake_response=FIXTURE_ROOT / "synthetic_fake_response.json",
        force=True,
    )
    with pytest.raises(ValueError, match="local/demo-only"):
        run(args, settings=settings)
