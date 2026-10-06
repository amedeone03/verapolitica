from argparse import Namespace
from pathlib import Path

from sqlalchemy import func, select
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import (
    AIExtractionRun,
    Proposal,
    ProposalDraft,
    ProposalSourceIdentifier,
)
from backend.app.pipeline.document_extraction import extract_html
from scripts.reset_ceo_ai_demo import reset_ceo_ai_demo
from scripts.run_ai_extraction import run


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "ai"
HTML = FIXTURE_ROOT / "ceo_ddl_60476.html"
FAKE = FIXTURE_ROOT / "ceo_ddl_60476_fake_response.json"
TITLE = (
    "Disposizioni per l'accesso alle cure palliative e alla terapia del dolore "
    "nei luoghi di vita e di cura"
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'ceo-ai.db'}",
        raw_storage_path=tmp_path / "raw",
        enable_demo_ui=True,
        admin_reviewer_identity="ceo-editor",
    )


def _args(settings: Settings) -> Namespace:
    return Namespace(
        file=HTML,
        source_url="https://dati.senato.it/ddl/60476.html",
        source_key="senato-ddl",
        source_name="Senato della Repubblica — Disegni di legge",
        fake_response=FAKE,
        force=False,
    )


def test_ceo_fake_response_is_grounded_in_official_html():
    text = extract_html(HTML.read_bytes()).text
    assert TITLE in text
    assert "Sen. De Poli Antonio" in text
    assert "2026-09-18" in text


def test_fake_cli_creates_unpublished_simulated_draft(tmp_path):
    settings = _settings(tmp_path)
    summary = run(_args(settings), settings=settings)

    assert summary["accepted_count"] == 1
    assert summary["publication"].startswith("none")
    assert summary["chunk_count"] == 1
    draft_id = summary["proposal_draft_ids"][0]
    engine = create_db_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            draft = session.get(ProposalDraft, draft_id)
            proposal = session.get(Proposal, draft.proposal_id)
            run_row = session.scalar(select(AIExtractionRun))
            identifier = session.scalar(select(ProposalSourceIdentifier))
            assert proposal.published_at is None
            assert draft.proposed_data["title"] == TITLE
            assert draft.proposed_data["proposal_type"] == "proposal"
            assert draft.proposed_data["metadata"]["_unresolved_actors"]
            assert draft.proposed_data["metadata"]["_resolved_actors"] == []
            assert run_row.provider == "fake"
            assert run_row.model == "simulated-ceo-demo"
            assert run_row.input_tokens == 0
            assert identifier.official_identifier.startswith(
                "urn:verapolitica:official-claim:"
            )
            assert session.scalar(select(func.count()).select_from(Proposal)) == 1
    finally:
        engine.dispose()

    with TestClient(create_app(settings)) as client:
        page = client.get(f"/demo/ai-draft/{draft_id}")
        assert page.status_code == 200
        assert "Simulated AI extraction — CEO demo" in page.text
        assert "cure palliative" in page.text
        assert "Sen. De Poli Antonio" in page.text
        assert "fake" in page.text
        assert "simulated-ceo-demo" in page.text
        assert "Evidence from official source" in page.text
        assert "healthcare" in page.text
        public = client.get("/proposals")
        assert public.json()["total"] == 0


def test_demo_ai_draft_route_is_local_only(tmp_path):
    hidden = Settings(
        database_url=f"sqlite:///{tmp_path / 'hidden.db'}",
        raw_storage_path=tmp_path / "raw",
        enable_demo_ui=False,
    )
    with TestClient(create_app(hidden)) as client:
        assert client.get("/demo/ai-draft/1").status_code == 404


def test_reset_dry_run_lists_operator_artifacts_without_deleting(tmp_path):
    settings = _settings(tmp_path)
    run(_args(settings), settings=settings)
    preview = reset_ceo_ai_demo(settings=settings, dry_run=True)
    assert preview["dry_run"] is True
    assert preview["proposals"] == 1
    assert preview["proposal_ids"]
    assert preview["proposal_draft_ids"]
    assert preview["raw_document_ids"]
    assert preview["ai_extraction_run_ids"]
    assert "SPARQL" in preview["preserved"]
    engine = create_db_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Proposal)) == 1
            assert session.scalar(select(func.count()).select_from(AIExtractionRun)) == 1
    finally:
        engine.dispose()


def test_reset_removes_only_simulated_extraction(tmp_path):
    settings = _settings(tmp_path)
    run(_args(settings), settings=settings)
    result = reset_ceo_ai_demo(settings=settings, dry_run=False)
    assert result["proposals"] == 1
    engine = create_db_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Proposal)) == 0
            assert session.scalar(select(func.count()).select_from(AIExtractionRun)) == 0
    finally:
        engine.dispose()
