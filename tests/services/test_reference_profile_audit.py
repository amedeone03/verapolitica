import json
from datetime import date

from backend.app.models.politician_profile import (
    PoliticianCareerEntry,
    ProfileContentKind,
    ProfileContentStatus,
)
from backend.app.schemas.politician_profile import (
    CareerEntryDraftInput,
    ProfileSourceInput,
    SourceCompleteness,
)
from backend.app.schemas.politician_profile import ProfileSourceKind
from backend.app.scoring.types import DUAL_APPROVAL_VERDICTS, FulfillmentVerdict
from backend.app.services.politician_profile_service import PoliticianProfileService
from backend.app.services.reference_profile_audit import (
    CEO_REFERENCE_WARNING,
    DEFAULT_FIXTURE,
    SourceAuditRow,
    audit_from_factory,
    classify_profile_item,
    is_complete_source_url,
)
from scripts.prepare_reference_profile import prepare_reference_profile
from tests.scripts.test_prepare_reference_profile import (
    _classify_and_assess_autonomia,
    _seed_meloni,
)


def test_incomplete_url_is_not_treated_as_complete():
    assert is_complete_source_url(None) is False
    assert is_complete_source_url("") is False
    assert is_complete_source_url("camera.it/deputati") is False
    assert is_complete_source_url("https://presidenza.governo.it/curriculum.pdf") is True


def test_biography_ready_when_one_url_exists_and_secondaries_are_flagged():
    result = classify_profile_item(
        kind=ProfileContentKind.BIOGRAPHY,
        identity_key="primary",
        title="Biografia",
        sources=[
            SourceAuditRow(
                name="Presidenza del Consiglio — Curriculum ufficiale",
                url="https://presidenza.governo.it/curriculum.pdf",
                kind="official",
                complete=True,
            ),
            SourceAuditRow(
                name="Camera dei Deputati — Profilo parlamentare",
                url=None,
                kind="official",
                complete=False,
            ),
            SourceAuditRow(
                name="Treccani — Biografia di Giorgia Meloni",
                url=None,
                kind="institutional",
                complete=False,
            ),
        ],
        body="Testo.",
    )
    assert result.status == SourceCompleteness.READY_FOR_EDITORIAL_REVIEW.value
    assert "Camera dei Deputati" in " ".join(result.flags)
    assert "Treccani" in " ".join(result.flags)


def test_proceeding_without_url_is_missing_source_url():
    result = classify_profile_item(
        kind=ProfileContentKind.PROCEEDING,
        identity_key="caso-almasri-2025",
        title="Caso Almasri (2025)",
        sources=[SourceAuditRow(name="ANSA", url=None, kind="news", complete=False)],
        summary="Iscrizione, poi archiviazione.",
        proceeding_types=["judicial_proceeding"],
    )
    assert result.status == SourceCompleteness.MISSING_SOURCE_URL.value
    assert "do not invent" in result.blocker


def test_position_requires_date_and_url():
    missing_date = classify_profile_item(
        kind=ProfileContentKind.POSITION,
        identity_key="immigrazione",
        title="Immigrazione",
        sources=[
            SourceAuditRow(
                name="Corriere",
                url="https://roma.corriere.it/example",
                kind="news",
                complete=True,
            )
        ],
        position_statement="Posizione.",
        verifiable_statement="Atto.",
        statement_date=None,
    )
    assert missing_date.status == SourceCompleteness.NEEDS_FACT_CHECK.value
    ready = classify_profile_item(
        kind=ProfileContentKind.POSITION,
        identity_key="immigrazione",
        title="Immigrazione",
        sources=[
            SourceAuditRow(
                name="Corriere",
                url="https://roma.corriere.it/example",
                kind="news",
                complete=True,
            )
        ],
        position_statement="Posizione.",
        verifiable_statement="Atto.",
        statement_date=date(2026, 5, 16),
    )
    assert ready.status == SourceCompleteness.READY_FOR_EDITORIAL_REVIEW.value


def test_pdc_career_conflicts_with_collected_mandate(session_factory):
    ids = _seed_meloni(session_factory, with_pledges=False)
    service = PoliticianProfileService(session_factory)
    content_id, _ = service.upsert_career_entry(
        ids["politician_id"],
        CareerEntryDraftInput(
            identity_key="presidente-consiglio-2022",
            start_date=date(2022, 10, 22),
            start_precision="day",
            is_current=True,
            role="Presidente del Consiglio dei Ministri della Repubblica Italiana",
            institution="Presidenza del Consiglio dei Ministri",
            sources=(
                ProfileSourceInput(
                    name="Presidenza del Consiglio — Curriculum ufficiale",
                    kind=ProfileSourceKind.OFFICIAL,
                    url="https://presidenza.governo.it/curriculum.pdf",
                ),
            ),
            created_by="reference-profile-operator",
        ),
    )
    audit = audit_from_factory(session_factory, "giorgia-meloni")
    pdc = next(item for item in audit.profile_items if item.identity_key == "presidente-consiglio-2022")
    assert pdc.id == content_id
    assert pdc.status == SourceCompleteness.NEEDS_FACT_CHECK.value
    assert "2022-10-21" in pdc.blocker
    with session_factory() as session:
        row = session.get(PoliticianCareerEntry, content_id)
        assert row.start_date == date(2022, 10, 22)
        assert row.status is ProfileContentStatus.PENDING


def test_fixture_apply_audit_does_not_invent_urls_or_assessments(session_factory):
    ids = _seed_meloni(session_factory)
    assessment_id = _classify_and_assess_autonomia(session_factory, ids)
    prepare_reference_profile(
        session_factory=session_factory, dry_run=False, allow_non_unified=True
    )
    audit = audit_from_factory(session_factory, "giorgia-meloni")
    fixture = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    fixture_urls = {
        source.get("url")
        for group in (
            [fixture["biography"]],
            fixture["career_entries"],
            fixture["positions"],
            fixture["proceedings"],
        )
        for item in group
        for source in item.get("sources") or []
        if source.get("url")
    }
    reported_urls = {
        part
        for item in audit.profile_items
        for part in item.source_url.split("; ")
        if part not in {"", "(none)"}
    }
    assert reported_urls <= fixture_urls
    bio = next(item for item in audit.profile_items if item.content_type == "biography")
    assert bio.status == SourceCompleteness.READY_FOR_EDITORIAL_REVIEW.value
    assert bio.publication_status == "pending"
    proceedings = [item for item in audit.profile_items if item.content_type == "proceeding"]
    assert len(proceedings) == 4
    assert {item.status for item in proceedings} == {SourceCompleteness.MISSING_SOURCE_URL.value}
    positions = [item for item in audit.profile_items if item.content_type == "position"]
    assert len(positions) == 5
    assert all(
        item.status == SourceCompleteness.READY_FOR_EDITORIAL_REVIEW.value for item in positions
    )
    skipped = {row.pdf_number for row in audit.pledges if not row.duplicate_safe}
    assert skipped == {9, 14}
    pending_pledges = [row for row in audit.pledges if row.duplicate_safe]
    assert len(pending_pledges) == 14
    assert audit.readiness.assessments["published"] == 1
    assert audit.readiness.assessments["new_drafts"] == 0
    assert all(
        "ASSESSMENT_NEEDS_OFFICIAL_EVIDENCE" in row.evidence_readiness
        for row in pending_pledges
    )
    assert all(row.declaration_url for row in pending_pledges)
    assert audit.readiness.assessments["published"] == 1
    assert assessment_id is not None
    assert FulfillmentVerdict.BROKEN in DUAL_APPROVAL_VERDICTS
    assert CEO_REFERENCE_WARNING.startswith("Contenuto derivato")
