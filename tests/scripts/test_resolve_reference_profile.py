from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.config import AppEnvironment, Settings
from backend.app.main import create_app
from backend.app.models import PledgeAssessment, ProposalDraft, ProposalDraftStatus
from backend.app.models.politician_profile import (
    PoliticianBiography,
    PoliticianCareerEntry,
    PoliticianProceeding,
    ProfileContentKind,
    ProfileContentStatus,
    ProfileSourceKind,
)
from backend.app.schemas.politician_profile import (
    BiographyDraftInput,
    CareerEntryDraftInput,
    ProfileSourceInput,
)
from backend.app.scoring.types import DUAL_APPROVAL_VERDICTS, FulfillmentVerdict
from backend.app.services.politician_profile_service import (
    PoliticianProfileService,
    PoliticianProfileValidationError,
)
from backend.app.services.reference_profile_audit import (
    CEO_REFERENCE_WARNING,
    SourceCompleteness,
    audit_from_factory,
)
from scripts.attach_profile_source import attach_profile_source
from scripts.prepare_demo import DemoSafetyError
from scripts.prepare_reference_profile import prepare_reference_profile
from scripts.resolve_reference_profile import (
    PRECISE_PDF_DATE,
    main as resolve_main,
    resolve_reference_profile,
)
from tests.scripts.test_prepare_reference_profile import (
    _classify_and_assess_autonomia,
    _seed_meloni,
)


OLD_BIO = (
    "Giorgia Meloni, diplomata in lingue e giornalista professionista, inizia "
    "l’attività politica nel 1992. Presidente del partito dal 2014, guida il "
    "governo italiano dal 22 ottobre 2022."
)


def _prepare_conflict(session_factory):
    ids = _seed_meloni(session_factory)
    assessment_id = _classify_and_assess_autonomia(session_factory, ids)
    service = PoliticianProfileService(session_factory)
    bio_id, _ = service.upsert_biography(
        ids["politician_id"],
        BiographyDraftInput(
            identity_key="primary",
            body=OLD_BIO,
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
    service.approve(ProfileContentKind.BIOGRAPHY, bio_id, reviewer="desk")
    service.upsert_career_entry(
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
    prepare_reference_profile(
        session_factory=session_factory, dry_run=False, allow_non_unified=True
    )
    return ids, assessment_id


def test_dry_run_makes_no_db_changes(session_factory):
    ids, assessment_id = _prepare_conflict(session_factory)
    with session_factory() as session:
        bio = session.scalar(
            select(PoliticianBiography).where(
                PoliticianBiography.politician_id == ids["politician_id"],
                PoliticianBiography.status == ProfileContentStatus.PUBLISHED,
            )
        )
        pdc = session.scalar(
            select(PoliticianCareerEntry).where(
                PoliticianCareerEntry.identity_key == "presidente-consiglio-2022"
            )
        )
        proceedings = [
            row.status
            for row in session.scalars(
                select(PoliticianProceeding).where(
                    PoliticianProceeding.politician_id == ids["politician_id"]
                )
            )
        ]
        drafts = [row.status for row in session.scalars(select(ProposalDraft))]
        assessment = session.get(PledgeAssessment, assessment_id)
        before = (bio.body, pdc.status, tuple(proceedings), tuple(drafts), assessment.verdict)
    report = resolve_reference_profile(
        "giorgia-meloni",
        session_factory=session_factory,
        dry_run=True,
        allow_non_unified=True,
    )
    assert report["dry_run"] is True
    assert report["biography"]["action"] == "would_revise"
    assert report["pdc_career"]["action"] == "would_reject"
    assert report["approved_proceedings"] == []
    with session_factory() as session:
        bio = session.scalar(
            select(PoliticianBiography).where(
                PoliticianBiography.politician_id == ids["politician_id"],
                PoliticianBiography.status == ProfileContentStatus.PUBLISHED,
            )
        )
        pdc = session.scalar(
            select(PoliticianCareerEntry).where(
                PoliticianCareerEntry.identity_key == "presidente-consiglio-2022"
            )
        )
        proceedings = [
            row.status
            for row in session.scalars(
                select(PoliticianProceeding).where(
                    PoliticianProceeding.politician_id == ids["politician_id"]
                )
            )
        ]
        drafts = [row.status for row in session.scalars(select(ProposalDraft))]
        assessment = session.get(PledgeAssessment, assessment_id)
        after = (bio.body, pdc.status, tuple(proceedings), tuple(drafts), assessment.verdict)
    assert after == before
    assert PRECISE_PDF_DATE in bio.body


def test_apply_revises_biography_rejects_pdc_and_leaves_proceedings_pending(
    session_factory, tmp_path
):
    ids, assessment_id = _prepare_conflict(session_factory)
    first = resolve_reference_profile(
        "giorgia-meloni",
        session_factory=session_factory,
        dry_run=False,
        allow_non_unified=True,
    )
    assert first["biography"]["action"] == "revised_and_published"
    assert first["pdc_career"]["action"] == "rejected"
    assert first["approved_proceedings"] == []
    assert first["counts"]["biography"]["published"] == 1
    assert first["counts"]["biography"]["superseded"] == 1
    assert first["counts"]["career"]["rejected"] == 1
    assert first["counts"]["proceedings"] == {
        "pending": 4,
        "published": 0,
        "rejected": 0,
        "superseded": 0,
    }
    with session_factory() as session:
        published = PoliticianProfileService.published_biography(
            session, ids["politician_id"]
        )
        assert PRECISE_PDF_DATE not in published.body
        assert "dall’ottobre 2022" in published.body
        pdc = session.scalar(
            select(PoliticianCareerEntry).where(
                PoliticianCareerEntry.identity_key == "presidente-consiglio-2022"
            )
        )
        assert pdc.status is ProfileContentStatus.REJECTED
        assert pdc.start_date == date(2022, 10, 22)
        proceedings = list(
            session.scalars(
                select(PoliticianProceeding).where(
                    PoliticianProceeding.politician_id == ids["politician_id"]
                )
            )
        )
        assert len(proceedings) == 4
        assert all(row.status is ProfileContentStatus.PENDING for row in proceedings)
        almasri = next(row for row in proceedings if "Almasri" in row.title)
        assert almasri.proceeding_types == ["judicial_proceeding"]
        assert almasri.outcome.value == "archived"
        drafts = list(session.scalars(select(ProposalDraft)))
        assert drafts and all(row.status is ProposalDraftStatus.PENDING for row in drafts)
        assessment = session.get(PledgeAssessment, assessment_id)
        assert assessment.verdict is FulfillmentVerdict.IN_PROGRESS

    audit = audit_from_factory(session_factory, "giorgia-meloni")
    proceeding_items = [
        item for item in audit.profile_items if item.content_type == "proceeding"
    ]
    assert proceeding_items
    assert all(
        item.source_completeness == SourceCompleteness.MISSING_SOURCE_URL.value
        for item in proceeding_items
    )

    second = resolve_reference_profile(
        "giorgia-meloni",
        session_factory=session_factory,
        dry_run=False,
        allow_non_unified=True,
    )
    assert second["biography"]["action"] == "already_consistent"
    assert second["pdc_career"]["action"] == "already_rejected"
    assert second["approved_proceedings"] == []

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        raw_storage_path=tmp_path / "raw",
        admin_api_key="profile-admin",
        admin_reviewer_identity="desk-one",
    )
    with TestClient(create_app(settings)) as client:
        public = client.get(f"/politicians/{ids['politician_id']}").json()
        blob = str(public)
        assert PRECISE_PDF_DATE not in public["biography"]["body"]
        assert "dall’ottobre 2022" in public["biography"]["body"]
        assert public["profile"]["mandates"][0]["start_date"] == "2022-10-21"
        assert all(item["start_date"] != "2022-10-22" for item in public["career_entries"])
        assert public["proceedings"] == []
        assert CEO_REFERENCE_WARNING not in blob
        assert "Caso Almasri" not in blob
        titles = {item["title"] for item in public.get("proposals") or []}
        assert "Abolire e sostituire il Reddito di cittadinanza" not in titles
        scorecard = client.get(f"/politicians/{ids['politician_id']}/scorecard").json()
        assert scorecard["methodology_version"] == "pledge-score/v1"
        assert scorecard["tracked_pledges"] == 1
        assert scorecard["pledges"][0]["verdict"] == "in_progress"
        assert scorecard["pledges"][0]["latest_assessment"]["id"] == assessment_id
        explanation = client.get(f"/proposals/{ids['autonomia_id']}/explanation")
        assert explanation.status_code == 200
        spec = client.get("/openapi.json").json()["paths"]
        assert "/ask" in spec
        assert any(path.endswith("/explanation") for path in spec)
        assert FulfillmentVerdict.BROKEN in DUAL_APPROVAL_VERDICTS
        assert len(DUAL_APPROVAL_VERDICTS) == 1


def test_attach_source_dry_run_and_invalid_url(session_factory):
    ids, _assessment_id = _prepare_conflict(session_factory)
    service = PoliticianProfileService(session_factory)
    with session_factory() as session:
        proceeding = session.scalar(
            select(PoliticianProceeding).where(
                PoliticianProceeding.politician_id == ids["politician_id"],
                PoliticianProceeding.identity_key == "caso-almasri-2025",
            )
        )
        proceeding_id = proceeding.id
    detail = service.get_admin(ProfileContentKind.PROCEEDING, proceeding_id)
    source_id = detail.source_ids[0]
    dry = attach_profile_source(
        "proceeding",
        proceeding_id,
        source_id,
        "https://www.ansa.it/sito/notizie/example.html",
        session_factory=session_factory,
        dry_run=True,
        allow_non_unified=True,
    )
    assert dry["action"] == "would_attach"
    with session_factory() as session:
        row = session.get(PoliticianProceeding, proceeding_id)
        assert row.status is ProfileContentStatus.PENDING
    with pytest.raises(PoliticianProfileValidationError):
        attach_profile_source(
            "proceeding",
            proceeding_id,
            source_id,
            "ansa-without-scheme",
            session_factory=session_factory,
            dry_run=False,
            allow_non_unified=True,
        )
    applied = attach_profile_source(
        "proceeding",
        proceeding_id,
        source_id,
        "https://www.ansa.it/sito/notizie/example.html",
        session_factory=session_factory,
        dry_run=False,
        allow_non_unified=True,
    )
    assert applied["auto_published"] is False
    assert applied["status"] == ProfileContentStatus.PENDING.value
    ready = resolve_reference_profile(
        "giorgia-meloni",
        session_factory=session_factory,
        dry_run=True,
        allow_non_unified=True,
    )
    proceeding_ready = [
        item
        for item in ready["approved_proceedings"]
        if item["identity_key"] == "caso-almasri-2025"
    ]
    assert proceeding_ready
    blocked = [
        item
        for item in ready["audit_proceedings"]
        if item["identity_key"] != "caso-almasri-2025"
    ]
    assert blocked
    assert all(
        item["source_completeness"] == SourceCompleteness.MISSING_SOURCE_URL.value
        for item in blocked
    )


def test_operator_command_refuses_production(monkeypatch):
    monkeypatch.setattr(
        "scripts.resolve_reference_profile.configured_environment",
        lambda: AppEnvironment.PRODUCTION,
    )
    with pytest.raises(DemoSafetyError, match="production"):
        resolve_reference_profile(
            "giorgia-meloni", dry_run=True, allow_non_unified=True
        )
    assert resolve_main(["giorgia-meloni", "--dry-run"]) == 1
