import json
from pathlib import Path

import pytest

from sqlalchemy import select

from backend.app.core.config import AppEnvironment
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models.politician_profile import (
    PoliticianProceeding,
    PoliticianProfileSource,
    ProfileContentKind,
    ProfileContentStatus,
)
from backend.app.services.reference_profile_audit import DEFAULT_FIXTURE, resolve_politician
from scripts.audit_meloni_pdf_completeness import (
    BLOCKED,
    BLOCKED_SOURCE,
    MATCHES_PUBLISHED,
    MISSING,
    NEEDS_MANUAL_REVIEW,
    PENDING,
    PUBLISHED,
    SUPERSEDE_DUPLICATE,
    audit_completeness,
    format_report,
    main as audit_main,
)
from scripts.prepare_demo import DemoSafetyError


UNIFIED_DB = (
    Path(__file__).resolve().parents[2] / "data" / "unified_demo" / "verapolitica.db"
)


def test_operator_command_refuses_production(monkeypatch):
    monkeypatch.setattr(
        "scripts.audit_meloni_pdf_completeness.configured_environment",
        lambda: AppEnvironment.PRODUCTION,
    )
    with pytest.raises(DemoSafetyError, match="production"):
        audit_main([])


@pytest.mark.skipif(not UNIFIED_DB.exists(), reason="unified demo database is not present")
def test_completeness_audit_is_read_only_and_covers_pdf_sections():
    before = (UNIFIED_DB.stat().st_mtime_ns, UNIFIED_DB.stat().st_size)
    engine = create_db_engine(f"sqlite:///{UNIFIED_DB}")
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            politician = resolve_politician(session, "giorgia-meloni")
            first = audit_completeness(session, politician)
            second = audit_completeness(session, politician)
            proceedings = list(
                session.scalars(
                    select(PoliticianProceeding).where(
                        PoliticianProceeding.politician_id == politician.id
                    )
                )
            )
            proceeding_sources = {
                row.id: list(
                    session.scalars(
                        select(PoliticianProfileSource).where(
                            PoliticianProfileSource.content_kind
                            == ProfileContentKind.PROCEEDING,
                            PoliticianProfileSource.content_id == row.id,
                        )
                    )
                )
                for row in proceedings
            }
    finally:
        engine.dispose()
    after = (UNIFIED_DB.stat().st_mtime_ns, UNIFIED_DB.stat().st_size)

    assert before == after
    assert first.politician_id == 206
    assert first.pdc_date_discrepancy is True
    assert first.canonical_pdc_start == "2022-10-21"
    assert [row.status for row in first.identity] == [row.status for row in second.identity]
    assert all(row.status != MISSING for row in first.identity)
    assert all(row.status == PUBLISHED for row in first.identity)
    assert any("2022-10-21" in row.notes for row in first.identity)

    assert first.biography[0].status == PUBLISHED
    career_roles = [row.item for row in first.career]
    assert any("Consigliera della Provincia di Roma" in item for item in career_roles)
    assert any("Presidente del Consiglio" in item for item in career_roles)
    published_career = [row for row in first.career if row.status == PUBLISHED]
    assert len(published_career) >= 10
    assert any(row.action == SUPERSEDE_DUPLICATE for row in first.career)

    assert len(first.positions) == 5
    assert all(row.status == PUBLISHED and row.action == MATCHES_PUBLISHED for row in first.positions)

    promise_rows = [row for row in first.promises if row.item.startswith("#")]
    assert len(promise_rows) == 16
    published = [row for row in promise_rows if row.status == PUBLISHED]
    blocked = [row for row in promise_rows if row.status == BLOCKED]
    assert len(published) == 14
    assert len(blocked) == 2
    assert any("#10" in row.item and row.action == BLOCKED_SOURCE for row in blocked)
    assert any("#16" in row.item and row.action == NEEDS_MANUAL_REVIEW for row in blocked)
    assert all(row.status == PENDING and row.action == BLOCKED_SOURCE for row in first.proceedings)
    assert len(first.proceedings) == 4
    assert not any(row.status == PUBLISHED for row in first.proceedings)
    assert len(proceedings) == 4
    assert {row.status for row in proceedings} == {ProfileContentStatus.PENDING}
    assert all(row.summary and row.title for row in proceedings)
    assert any("favoreggiamento" in (row.summary or "") for row in proceedings)
    assert any("94 vittime" in (row.summary or "") for row in proceedings)
    assert any("Edi Rama" in (row.summary or "") for row in proceedings)
    assert any("Fanpage" in (row.summary or "") for row in proceedings)
    assert all(proceeding_sources[row.id] for row in proceedings)
    assert all(
        source.url is None or source.incomplete
        for sources in proceeding_sources.values()
        for source in sources
    )

    fixture = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    for item in fixture["pledges"]:
        assert any(item["title"] in row.item for row in first.promises)
    for item in fixture["proceedings"]:
        assert any(item["title"] == row.item for row in first.proceedings)

    text = format_report(first)
    assert "IDENTITY" in text
    assert "BIOGRAPHY" in text
    assert "CAREER" in text
    assert "POSITIONS" in text
    assert "PROMISES" in text
    assert "PROCEEDINGS" in text
    assert "SOURCES" in text
