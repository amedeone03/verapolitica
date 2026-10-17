from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.config import AppEnvironment, Settings
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models.politician_profile import (
    PoliticianProceeding,
    PoliticianProfileSource,
    ProfileContentKind,
    ProfileContentStatus,
)
from scripts.prepare_demo import DemoSafetyError
from scripts.resolve_meloni_proceedings import (
    PLANS,
    main as resolve_main,
    resolve_meloni_proceedings,
)


UNIFIED_DB = (
    Path(__file__).resolve().parents[2] / "data" / "unified_demo" / "verapolitica.db"
)
PUBLIC_LEAKS = (
    "reviewed_by",
    "review_note",
    "reference-profile-editor",
    "ceo_reference_warning",
    "ANTEPRIMA EDITORIALE",
)
EXPECTED_URLS = {
    spec.url
    for plan in PLANS
    for spec in plan.sources
}


def test_operator_refuses_production(monkeypatch):
    monkeypatch.setattr(
        "scripts.resolve_meloni_proceedings.configured_environment",
        lambda: AppEnvironment.PRODUCTION,
    )
    with pytest.raises(DemoSafetyError, match="production"):
        resolve_meloni_proceedings(dry_run=True, allow_non_unified=True)
    assert resolve_main(["--dry-run"]) == 1


@pytest.mark.skipif(not UNIFIED_DB.exists(), reason="unified demo database is not present")
def test_apply_is_idempotent_and_publishes_supported_proceedings():
    first = resolve_meloni_proceedings(dry_run=False)
    second = resolve_meloni_proceedings(dry_run=False)
    assert set(first["published"] + first["already_published"]) == {
        plan.identity_key for plan in PLANS
    }
    assert second["created_sources"] == 0
    assert second["published"] == []
    assert set(second["already_published"]) == {plan.identity_key for plan in PLANS}

    engine = create_db_engine(f"sqlite:///{UNIFIED_DB}")
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            rows = list(
                session.scalars(
                    select(PoliticianProceeding).where(
                        PoliticianProceeding.politician_id == 206
                    )
                )
            )
            assert {row.identity_key: row.status for row in rows} == {
                plan.identity_key: ProfileContentStatus.PUBLISHED for plan in PLANS
            }
            sources = list(
                session.scalars(
                    select(PoliticianProfileSource).where(
                        PoliticianProfileSource.content_kind
                        == ProfileContentKind.PROCEEDING,
                        PoliticianProfileSource.content_id.in_([row.id for row in rows]),
                    )
                )
            )
            urls = [row.url for row in sources]
            assert set(EXPECTED_URLS) <= set(urls)
            assert Counter(urls) == Counter(set(urls))
            assert all(row.url and not row.incomplete for row in sources)
            cutro = next(row for row in rows if row.identity_key == "naufragio-cutro-2023")
            albania = next(
                row for row in rows if row.identity_key == "accordo-italia-albania-2023"
            )
            assert "judicial_proceeding" not in cutro.proceeding_types
            assert "judicial_proceeding" not in albania.proceeding_types
            assert "procedimento penale personale" in cutro.summary
            assert "non costituiscono procedimenti penali personali" in albania.summary
            assert "non comportano automaticamente responsabilità personali" in next(
                row.summary for row in rows if row.identity_key == "gioventu-nazionale-2024"
            )
            almasri = next(row for row in rows if row.identity_key == "caso-almasri-2025")
            assert almasri.proceeding_types == ["judicial_proceeding"]
            assert "insufficienti gli elementi" not in (almasri.outcome_summary or "")
    finally:
        engine.dispose()


@pytest.mark.skipif(not UNIFIED_DB.exists(), reason="unified demo database is not present")
def test_public_profile_shows_published_proceedings_without_editorial_leaks():
    with TestClient(
        create_app(
            Settings(
                env=AppEnvironment.DEVELOPMENT,
                database_url=f"sqlite:///{UNIFIED_DB}",
                raw_storage_path=UNIFIED_DB.parent / "raw",
                admin_api_key="local-presentation-admin-key",
                trusted_hosts="localhost,127.0.0.1,testserver",
                enable_demo_ui=False,
            )
        )
    ) as client:
        person = client.get("/politicians/206").json()
        scorecard = client.get("/politicians/206/scorecard").json()

    titles = {item["title"] for item in person["proceedings"]}
    assert titles == {
        "Caso Almasri (2025)",
        "Naufragio di Cutro (2023)",
        "Accordo Italia–Albania sui migranti (2023–2026)",
        "Rapporti con il passato fascista e inchiesta su Gioventù Nazionale (2024)",
    }
    assert len(person["proceedings"]) == 4
    blob = str(person) + str(scorecard)
    for leak in PUBLIC_LEAKS:
        assert leak not in blob
    for item in person["proceedings"]:
        assert item["summary"]
        assert item["sources"]
        assert all(source.get("url") for source in item["sources"])
        assert "url=null" not in str(item)
    by_title = {item["title"]: item for item in person["proceedings"]}
    assert "judicial_proceeding" in by_title["Caso Almasri (2025)"]["proceeding_types"]
    assert "judicial_proceeding" not in by_title["Naufragio di Cutro (2023)"]["proceeding_types"]
    assert (
        "judicial_proceeding"
        not in by_title["Accordo Italia–Albania sui migranti (2023–2026)"]["proceeding_types"]
    )
    assert "procedimento penale personale" in by_title["Naufragio di Cutro (2023)"]["summary"]
    assert (
        "procedimenti penali personali"
        in by_title["Accordo Italia–Albania sui migranti (2023–2026)"]["summary"]
    )
