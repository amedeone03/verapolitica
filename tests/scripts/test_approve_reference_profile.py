import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.config import AppEnvironment, Settings
from backend.app.main import create_app
from backend.app.models import PledgeAssessment, ProposalDraft, ProposalDraftStatus
from backend.app.models.politician_profile import (
    PoliticianBiography,
    PoliticianCareerEntry,
    PoliticianPosition,
    PoliticianProceeding,
    ProfileContentStatus,
)
from backend.app.scoring.types import DUAL_APPROVAL_VERDICTS, FulfillmentVerdict
from backend.app.services.reference_profile_audit import CEO_REFERENCE_WARNING
from scripts.approve_reference_profile import (
    approve_reference_profile,
    main as approve_main,
)
from scripts.prepare_demo import DemoSafetyError
from scripts.prepare_reference_profile import prepare_reference_profile
from tests.scripts.test_prepare_reference_profile import (
    _classify_and_assess_autonomia,
    _seed_meloni,
)


def _prepare(session_factory):
    ids = _seed_meloni(session_factory)
    assessment_id = _classify_and_assess_autonomia(session_factory, ids)
    prepare_reference_profile(
        session_factory=session_factory, dry_run=False, allow_non_unified=True
    )
    return ids, assessment_id


def _status_snapshot(session_factory, politician_id: int) -> dict[str, tuple[str, ...]]:
    with session_factory() as session:
        return {
            "biography": tuple(
                row.status.value
                for row in session.scalars(
                    select(PoliticianBiography).where(
                        PoliticianBiography.politician_id == politician_id
                    )
                )
            ),
            "career": tuple(
                (row.identity_key, row.status.value)
                for row in session.scalars(
                    select(PoliticianCareerEntry).where(
                        PoliticianCareerEntry.politician_id == politician_id
                    )
                )
            ),
            "positions": tuple(
                row.status.value
                for row in session.scalars(
                    select(PoliticianPosition).where(
                        PoliticianPosition.politician_id == politician_id
                    )
                )
            ),
            "proceedings": tuple(
                row.status.value
                for row in session.scalars(
                    select(PoliticianProceeding).where(
                        PoliticianProceeding.politician_id == politician_id
                    )
                )
            ),
            "pledge_drafts": tuple(
                row.status.value for row in session.scalars(select(ProposalDraft))
            ),
            "assessments": tuple(
                (row.id, row.verdict.value)
                for row in session.scalars(select(PledgeAssessment))
            ),
        }


def test_dry_run_makes_no_db_changes(session_factory):
    ids, _assessment_id = _prepare(session_factory)
    before = _status_snapshot(session_factory, ids["politician_id"])
    report = approve_reference_profile(
        "giorgia-meloni",
        session_factory=session_factory,
        dry_run=True,
        allow_non_unified=True,
    )
    after = _status_snapshot(session_factory, ids["politician_id"])
    assert report["dry_run"] is True
    assert len(report["approved"]) == 16
    assert {item["kind"] for item in report["approved"]} == {
        "biography",
        "career_entry",
        "position",
    }
    assert after == before


def test_apply_publishes_only_review_ready_profile_content(session_factory, tmp_path):
    ids, assessment_id = _prepare(session_factory)
    first = approve_reference_profile(
        "giorgia-meloni",
        session_factory=session_factory,
        dry_run=False,
        allow_non_unified=True,
    )
    assert first["dry_run"] is False
    assert len([item for item in first["approved"] if item["kind"] == "biography"]) == 1
    assert len([item for item in first["approved"] if item["kind"] == "career_entry"]) == 10
    assert len([item for item in first["approved"] if item["kind"] == "position"]) == 5
    blocked_keys = {item["identity_key"] for item in first["blocked"]}
    assert "presidente-consiglio-2022" in blocked_keys
    assert {item["kind"] for item in first["blocked"]} >= {"career_entry", "proceeding"}
    assert all(item["kind"] != "proceeding" or item["action"] == "blocked" for item in first["blocked"])
    counts = first["counts"]
    assert counts["biography"] == {"published": 1, "pending": 0}
    assert counts["career"] == {"published": 10, "pending": 1}
    assert counts["positions"] == {"published": 5, "pending": 0}
    assert counts["proceedings"] == {"published": 0, "pending": 4}

    with session_factory() as session:
        pdc = session.scalar(
            select(PoliticianCareerEntry).where(
                PoliticianCareerEntry.politician_id == ids["politician_id"],
                PoliticianCareerEntry.identity_key == "presidente-consiglio-2022",
            )
        )
        assert pdc.status is ProfileContentStatus.PENDING
        assert pdc.start_date.isoformat() == "2022-10-22"
        drafts = list(session.scalars(select(ProposalDraft)))
        assert drafts and all(row.status is ProposalDraftStatus.PENDING for row in drafts)
        assessment = session.get(PledgeAssessment, assessment_id)
        assert assessment.verdict is FulfillmentVerdict.IN_PROGRESS
        assert assessment.rationale.startswith("Official act language")

    second = approve_reference_profile(
        "giorgia-meloni",
        session_factory=session_factory,
        dry_run=False,
        allow_non_unified=True,
    )
    assert second["approved"] == []
    assert len(second["already_published"]) == 16
    assert second["counts"] == first["counts"]

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        raw_storage_path=tmp_path / "raw",
        admin_api_key="profile-admin",
        admin_reviewer_identity="desk-one",
    )
    with TestClient(create_app(settings)) as client:
        public = client.get(f"/politicians/{ids['politician_id']}").json()
        blob = str(public)
        assert public["biography"]["body"]
        assert "Giorgia Meloni" in public["biography"]["body"]
        assert len(public["career_entries"]) == 10
        assert all(item["start_date"] != "2022-10-22" for item in public["career_entries"])
        assert public["profile"]["mandates"][0]["start_date"] == "2022-10-21"
        assert len(public["positions"]) == 5
        assert public["proceedings"] == []
        assert CEO_REFERENCE_WARNING not in blob
        assert "reference-profile-operator" not in blob
        assert "reviewed_by" not in blob
        titles = {item["title"] for item in public.get("proposals") or []}
        assert "Abolire e sostituire il Reddito di cittadinanza" not in titles
        keys = [
            f"{item['role'].casefold()}|{str(item['start_date'])[:4]}"
            for item in public["career_entries"]
        ]
        mandate = public["profile"]["mandates"][0]
        mandate_role = (
            mandate.get("mandate_type") or mandate.get("office") or ""
        ).casefold()
        keys.append(f"{mandate_role}|{str(mandate['start_date'])[:4]}")
        assert len(keys) == len(set(keys))
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


def test_operator_command_refuses_production(monkeypatch):
    monkeypatch.setattr(
        "scripts.approve_reference_profile.configured_environment",
        lambda: AppEnvironment.PRODUCTION,
    )
    with pytest.raises(DemoSafetyError, match="production"):
        approve_reference_profile(
            "giorgia-meloni", dry_run=True, allow_non_unified=True
        )
    assert approve_main(["giorgia-meloni", "--dry-run"]) == 1
