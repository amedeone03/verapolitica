import json
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import (
    AIExtractionRun,
    IdentityResolutionCase,
    IdentityResolutionStatus,
    Municipality,
    PledgeClassification,
    Politician,
    PoliticianSourceIdentifier,
    Proposal,
    ProposalDraft,
    Region,
    Source,
)
from backend.app.pipeline.collectors import GovernoCollector
from backend.app.pipeline.collectors.base import CollectedDocument
from scripts.prepare_demo import DEFAULT_FIXTURE
from scripts.prepare_unified_demo import (
    OFFLINE_PROGRAMME_HTML,
    prepare_unified_demo,
)
from scripts.reset_unified_demo import reset_unified_demo
from scripts.run_ai_extraction import run
from scripts.unified_demo import UnifiedDemoPaths, seed_sqlite_from_ceo
from tests.scripts.test_ceo_ai_demo_extraction import FAKE, HTML
from tests.scripts.test_prepare_real_demo import FIXTURE as GOVERNO_FIXTURE


class FixtureGovernoCollector:
    def collect(self) -> CollectedDocument:
        return CollectedDocument(
            content=GOVERNO_FIXTURE.read_bytes(),
            source_url="https://www.governo.it/it/ministri-e-sottosegretari",
            content_type=GovernoCollector.response_media_type,
            retrieved_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
            collector_version="fixture",
        )


def fetch(_url):
    return OFFLINE_PROGRAMME_HTML.encode("utf-8"), "text/html"


def _istat_xlsx(path: Path) -> Path:
    rows = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures" / "territorial" / "istat_rows.json").read_text()
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Official ISTAT fixture"])
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


def _senato_with_identities(path: Path) -> Path:
    data = json.loads(DEFAULT_FIXTURE.read_text())
    extra = [
        {
            "senatorUri": {"type": "uri", "value": "https://dati.senato.it/senatore/demo-003"},
            "firstName": {"type": "literal", "value": "Mario"},
            "lastName": {"type": "literal", "value": "Rossi"},
            "gender": {"type": "literal", "value": "male"},
            "birthDate": {"type": "literal", "value": "1970-01-01"},
            "birthCity": {"type": "literal", "value": "Roma"},
            "birthProvince": {"type": "literal", "value": "Roma"},
            "birthCountry": {"type": "literal", "value": "Italia"},
            "profession": {"type": "literal", "value": "Giurista"},
            "homepage": {"type": "uri", "value": "https://www.senato.it/demo/mario-rossi"},
            "mandateUri": {"type": "uri", "value": "https://dati.senato.it/mandato/demo-003-19"},
            "mandateType": {"type": "literal", "value": "elettivo"},
            "mandateStart": {"type": "literal", "value": "2022-10-13"},
            "legislature": {"type": "literal", "value": "19"},
            "electionRegion": {"type": "literal", "value": "Lazio"},
        },
        {
            "senatorUri": {"type": "uri", "value": "https://dati.senato.it/senatore/demo-004"},
            "firstName": {"type": "literal", "value": "Carlo"},
            "lastName": {"type": "literal", "value": "Verdi"},
            "gender": {"type": "literal", "value": "male"},
            "birthDate": {"type": "literal", "value": "1960-06-06"},
            "birthCity": {"type": "literal", "value": "Napoli"},
            "birthProvince": {"type": "literal", "value": "Napoli"},
            "birthCountry": {"type": "literal", "value": "Italia"},
            "homepage": {"type": "uri", "value": "https://www.senato.it/demo/carlo-verdi"},
            "mandateUri": {"type": "uri", "value": "https://dati.senato.it/mandato/demo-004-19"},
            "mandateType": {"type": "literal", "value": "elettivo"},
            "mandateStart": {"type": "literal", "value": "2022-10-13"},
            "legislature": {"type": "literal", "value": "19"},
            "electionRegion": {"type": "literal", "value": "Campania"},
        },
    ]
    data["results"]["bindings"].extend(extra)
    path.write_text(json.dumps(data), "utf-8")
    return path


def _prepare(workspace: Path, **overrides):
    workspace.mkdir(parents=True, exist_ok=True)
    values = {
        "workspace_root": workspace,
        "offline": True,
        "rebuild": True,
        "governo_collector": FixtureGovernoCollector(),
        "fetch": fetch,
        "portrait_lookup": None,
        "istat_fixture": _istat_xlsx(workspace / "istat.xlsx"),
    }
    values.update(overrides)
    return prepare_unified_demo(**values)


def test_unified_prepare_does_not_touch_ceo_or_synthetic_demo(tmp_path):
    workspace = tmp_path / "workspace"
    ceo = workspace / "data" / "ceo_demo"
    synthetic = workspace / "data" / "demo"
    ceo.mkdir(parents=True)
    synthetic.mkdir(parents=True)
    ceo_marker = ceo / "keep.txt"
    demo_marker = synthetic / "keep.txt"
    ceo_db = ceo / "verapolitica.db"
    ceo_marker.write_text("ceo", "utf-8")
    demo_marker.write_text("demo", "utf-8")
    ceo_db.write_bytes(b"not-a-real-db")

    report = _prepare(workspace)
    paths = UnifiedDemoPaths.for_workspace(workspace)
    assert paths.database.is_file()
    assert ceo_marker.read_text("utf-8") == "ceo"
    assert demo_marker.read_text("utf-8") == "demo"
    assert ceo_db.read_bytes() == b"not-a-real-db"
    assert "ceo_demo" not in report.database_path
    assert "/data/demo/" not in report.database_path


def test_unified_prepare_is_idempotent_and_links_deterministic_identities(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    senato = _senato_with_identities(workspace / "senato.json")
    first = _prepare(workspace, senato_fixture=senato)
    second = _prepare(workspace, rebuild=False, senato_fixture=senato)
    assert first.counts["politicians"] == second.counts["politicians"]
    assert first.counts["pledge_classifications"] == second.counts["pledge_classifications"]
    assert first.counts["municipalities"] == second.counts["municipalities"]
    assert first.counts["duplicate_canonical_people"] == 0
    assert "Mario Rossi" in first.identities_linked
    assert "Carlo Verdi" in first.identities_left_unresolved

    engine = create_db_engine(f"sqlite:///{first.database_path}")
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            mario = list(
                session.scalars(
                    select(Politician).where(
                        Politician.canonical_given_name == "Mario",
                        Politician.canonical_family_name == "Rossi",
                    )
                )
            )
            assert len(mario) == 1
            authorities = set(
                session.scalars(
                    select(Source.key)
                    .join(PoliticianSourceIdentifier, PoliticianSourceIdentifier.source_id == Source.id)
                    .where(PoliticianSourceIdentifier.politician_id == mario[0].id)
                )
            )
            assert "senato-repubblica" in authorities
            assert "governo-italiano" in authorities
            pending = list(
                session.scalars(
                    select(IdentityResolutionCase).where(
                        IdentityResolutionCase.status == IdentityResolutionStatus.PENDING
                    )
                )
            )
            assert pending
            sources = {item.key for item in session.scalars(select(Source))}
            assert {"senato-repubblica", "governo-italiano", "istat-territories"} <= sources
    finally:
        engine.dispose()


def test_reset_removes_ai_drafts_and_preserves_baseline(tmp_path):
    workspace = tmp_path / "workspace"
    ceo = workspace / "data" / "ceo_demo"
    ceo.mkdir(parents=True)
    ceo_marker = ceo / "keep.txt"
    ceo_marker.write_text("ceo", "utf-8")
    report = _prepare(workspace)
    paths = UnifiedDemoPaths.for_workspace(workspace)
    paths.portraits_json.write_text("{}", "utf-8")
    (paths.portraits_dir / "abc.bin").write_bytes(b"x")

    settings = Settings(
        database_url=f"sqlite:///{paths.database}",
        raw_storage_path=paths.raw_storage,
        demo_upload_path=paths.uploads,
        portraits_path=paths.portraits_json,
        enable_demo_ui=True,
        admin_reviewer_identity="unified-demo-editor",
    )
    run(
        Namespace(
            file=HTML,
            source_url="https://dati.senato.it/ddl/60476.html",
            source_key="senato-ddl",
            source_name="Senato della Repubblica — Disegni di legge",
            fake_response=FAKE,
            force=False,
        ),
        settings=settings,
    )
    engine = create_db_engine(settings.database_url)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(AIExtractionRun)) == 1
            drafts_before = session.scalar(select(func.count()).select_from(ProposalDraft))
            pledges_before = session.scalar(select(func.count()).select_from(PledgeClassification))
            municipalities_before = session.scalar(select(func.count()).select_from(Municipality))
            assert drafts_before >= 1
    finally:
        engine.dispose()

    dry = reset_unified_demo(workspace_root=workspace, settings=settings, dry_run=True)
    assert dry["dry_run"] is True
    assert dry["ai_extraction_runs"] >= 1

    applied = reset_unified_demo(workspace_root=workspace, settings=settings, dry_run=False)
    assert applied["dry_run"] is False
    assert applied["ai_extraction_runs"] >= 1
    assert ceo_marker.read_text("utf-8") == "ceo"
    assert paths.portraits_json.is_file()
    assert (paths.portraits_dir / "abc.bin").is_file()

    engine = create_db_engine(settings.database_url)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(AIExtractionRun)) == 0
            assert session.scalar(select(func.count()).select_from(PledgeClassification)) == pledges_before
            assert session.scalar(select(func.count()).select_from(Municipality)) == municipalities_before
            assert session.scalar(select(func.count()).select_from(Region)) >= 1
            published = session.scalar(
                select(func.count()).select_from(Proposal).where(Proposal.published_at.is_not(None))
            )
            assert published >= pledges_before
    finally:
        engine.dispose()


def test_seed_from_ceo_is_read_only_on_source(tmp_path):
    workspace = tmp_path / "workspace"
    ceo_db = workspace / "data" / "ceo_demo" / "verapolitica.db"
    ceo_db.parent.mkdir(parents=True)
    import sqlite3

    with sqlite3.connect(ceo_db) as connection:
        connection.execute("CREATE TABLE keep (id INTEGER)")
        connection.execute("INSERT INTO keep VALUES (1)")
        connection.commit()
    paths = UnifiedDemoPaths.for_workspace(workspace)
    assert seed_sqlite_from_ceo(paths) is True
    assert ceo_db.is_file()
    with sqlite3.connect(ceo_db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM keep").fetchone()[0] == 1
    assert paths.database.is_file()


def test_unified_public_counts_and_scorecard(tmp_path):
    workspace = tmp_path / "workspace"
    report = _prepare(workspace)
    settings = Settings(
        database_url=f"sqlite:///{report.database_path}",
        raw_storage_path=workspace / "data" / "unified_demo" / "raw",
        portraits_path=workspace / "data" / "unified_demo" / "portraits.json",
        enable_demo_ui=True,
    )
    with TestClient(create_app(settings)) as client:
        people = client.get("/politicians").json()
        names = {f"{item['given_name']} {item['family_name']}" for item in people["items"]}
        assert "Anna Rossi" in names
        assert "Mario Rossi" in names
        assert "Lucia Bianchi" in names
        milano = client.get("/municipalities").json()
        assert any(item["name"] == "Milano" for item in milano["items"])
        methodology = client.get("/methodology/scoring").json()
        assert methodology["version"] == "pledge-score/v1"
        pm = next(item for item in people["items"] if item["family_name"] == "Rossi" and item["given_name"] == "Mario")
        card = client.get(f"/politicians/{pm['id']}/scorecard").json()
        assert card["tracked_pledges"] >= 4
        assert {pledge["verdict"] for pledge in card["pledges"]} == {"not_yet_rated"}
        portraits = client.get("/portraits").json()
        assert portraits == {}
        upload = client.get("/demo/ai-upload")
        assert upload.status_code == 200
        assert "AI-assisted document analysis" in upload.text
