import pytest

from backend.app.core.config import AppEnvironment
from backend.app.services.reference_profile_audit import (
    audit_from_factory,
    format_audit_text,
    format_report_text,
)
from scripts.audit_reference_profile import main as audit_main
from scripts.prepare_demo import DemoSafetyError
from scripts.prepare_reference_profile import prepare_reference_profile
from scripts.report_reference_profile import main as report_main
from tests.scripts.test_prepare_reference_profile import (
    _classify_and_assess_autonomia,
    _seed_meloni,
)


def test_audit_and_report_are_read_only(session_factory):
    ids = _seed_meloni(session_factory)
    _classify_and_assess_autonomia(session_factory, ids)
    prepare_reference_profile(
        session_factory=session_factory, dry_run=False, allow_non_unified=True
    )
    first = audit_from_factory(session_factory, "giorgia-meloni")
    second = audit_from_factory(session_factory, "giorgia-meloni")
    assert first.to_dict()["politician_id"] == ids["politician_id"]
    assert [item.status for item in first.profile_items] == [
        item.status for item in second.profile_items
    ]
    text = format_audit_text(first)
    assert "CONTENT TYPE" in text
    assert "MISSING_SOURCE_URL" in text
    assert "READY_FOR_EDITORIAL_REVIEW" in text
    report = format_report_text(first)
    assert "Biography:" in report
    assert "14 pending drafts" in report or "pending drafts" in report
    assert first.readiness.pledges["reference_duplicates_skipped"] == 2
    assert first.readiness.assessments["new_drafts"] == 0
    assert first.readiness.proceedings["missing_sources"] == 4
    assert first.readiness.proceedings["review_ready"] == 0


def test_operator_commands_refuse_production(monkeypatch):
    monkeypatch.setattr(
        "scripts.audit_reference_profile.configured_environment",
        lambda: AppEnvironment.PRODUCTION,
    )
    monkeypatch.setattr(
        "scripts.report_reference_profile.configured_environment",
        lambda: AppEnvironment.PRODUCTION,
    )
    with pytest.raises(DemoSafetyError, match="production"):
        audit_main(["giorgia-meloni"])
    with pytest.raises(DemoSafetyError, match="production"):
        report_main(["giorgia-meloni"])
