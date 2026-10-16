import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.config import AppEnvironment, Settings
from backend.app.main import create_app
from backend.app.models import (
    PledgeAssessment,
    PledgeAssessmentDraft,
    PledgeAssessmentDraftStatus,
    PledgeClassification,
    Politician,
    PoliticianVersion,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalDraft,
    ProposalDraftStatus,
    ProposalType,
)
from backend.app.models.pledge import PledgeAssessmentOrigin
from backend.app.models.politician_profile import PoliticianProceeding, ProfileContentStatus
from backend.app.schemas.pledge import PledgeAssessmentProposal, PledgeClassificationRequest
from backend.app.schemas.politician_profile import PledgeEvidenceReadiness
from backend.app.scoring.types import (
    DUAL_APPROVAL_VERDICTS,
    CommitmentType,
    EvidenceLabel,
    FulfillmentVerdict,
    HolderRole,
    PledgeSpecificity,
)
from backend.app.services.pledge_explanation_service import UNRATED_MESSAGE
from backend.app.services.pledge_service import (
    NewAssessmentDraft,
    PledgeService,
    PledgeValidationError,
)
from backend.app.services.reference_profile_audit import CEO_REFERENCE_WARNING
from scripts.prepare_demo import DemoSafetyError
from scripts.prepare_reference_profile import DEFAULT_FIXTURE, _load_fixture
from scripts.review_reference_pledges import (
    ALREADY_SKIPPED_DUPLICATE,
    APPROVE_PLEDGE,
    BLOCK_SOURCE_ISSUE,
    KEEP_PENDING_NEEDS_REVIEW,
    REJECT_NOT_EXPLICIT_PROMISE,
    decide_pledge_action,
    main as review_main,
    review_reference_pledges,
)
from tests.scripts.test_approve_reference_profile import _prepare
from tests.scripts.test_prepare_reference_profile import EXISTING_PLEDGES, NOW


class _FakePledge:
    def __init__(self, proposal_id: int, title: str, statement: str) -> None:
        self.id = proposal_id
        self.canonical_title = title
        self.exact_statement = statement


def _draft_payload(fixture_pledge: dict, politician_id: int = 206) -> dict:
    return {
        "title": fixture_pledge["title"],
        "exact_statement": fixture_pledge["exact_statement"],
        "introduced_at": fixture_pledge["introduced_at"],
        "official_url": fixture_pledge["declaration_url"],
        "proposal_type": "explicit_promise",
        "proposal_identifier": f"reference-profile:giorgia_meloni_v1:pledge:{fixture_pledge['identity_key']}",
        "metadata": {
            "fixture": "giorgia_meloni_v1",
            "suggested_verdict": fixture_pledge.get("suggested_verdict"),
            "_resolved_actors": [{"politician_id": politician_id, "display_name": "Giorgia Meloni"}],
        },
    }


def _published_from_existing() -> list[_FakePledge]:
    return [
        _FakePledge(101 + index, title, title) for index, title in enumerate(EXISTING_PLEDGES)
    ]


def _classify_legacy(session_factory, politician_id: int) -> None:
    service = PledgeService(session_factory)
    with session_factory() as session:
        ids = list(
            session.scalars(
                select(Proposal.id)
                .join(ProposalActor, ProposalActor.proposal_id == Proposal.id)
                .where(
                    ProposalActor.politician_id == politician_id,
                    Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
                    Proposal.published_at.is_not(None),
                )
            )
        )
        autonomia = session.scalar(
            select(Proposal.id).where(
                Proposal.canonical_title.startswith(
                    "Dare seguito al processo virtuoso di autonomia"
                )
            )
        )
    for proposal_id in ids:
        service.classify(
            proposal_id,
            PledgeClassificationRequest(
                specificity=PledgeSpecificity.HIGH,
                commitment_type=CommitmentType.ACTION,
                holder_role=HolderRole.GOVERNMENT_COALITION,
                cap_topic_code="20" if proposal_id == autonomia else "1",
                mandate_start=date(2022, 10, 22),
                mandate_end=date(2027, 10, 12),
                note="Automatic demo classification; editorial review pending",
            ),
            classified_by="demo-setup",
        )


def _pending_giustizia_draft(session_factory, ids: dict) -> int:
    with session_factory() as session:
        giustizia = session.scalar(
            select(Proposal.id).where(
                Proposal.canonical_title.startswith(
                    "Rivedremo anche la riforma dell’ordinamento giudiziario"
                )
            )
        )
    service = PledgeService(session_factory, clock=lambda: NOW)
    draft, created = service.propose(
        NewAssessmentDraft(
            proposal_id=giustizia,
            proposal=PledgeAssessmentProposal(
                verdict=FulfillmentVerdict.IN_PROGRESS,
                evidence_label=EvidenceLabel.SUPPORTS,
                rationale="Official act language names the same policy instrument as the commitment.",
                quoted_excerpt=EXISTING_PLEDGES[3],
                raw_document_id=ids["document_id"],
                effective_at=date(2024, 1, 15),
            ),
            origin=PledgeAssessmentOrigin.EDITOR,
            created_by="demo-editor",
        )
    )
    assert created is True
    return draft.id


def _unrelated_classification(session_factory) -> int:
    with session_factory() as session:
        politician = Politician(
            canonical_given_name="Mario",
            canonical_family_name="Rossi",
            normalized_name="mario rossi",
            birth_date=date(1970, 1, 1),
        )
        session.add(politician)
        session.flush()
        version = PoliticianVersion(
            politician_id=politician.id,
            version_number=1,
            profile_schema_version=1,
            profile_data={"given_name": "Mario", "family_name": "Rossi", "mandates": []},
            published_at=NOW,
        )
        session.add(version)
        session.flush()
        politician.current_version = version
        proposal = Proposal(
            canonical_title="Una promessa non Meloni",
            exact_statement="Presenterò una legge non correlata.",
            proposal_type=ProposalType.EXPLICIT_PROMISE,
            introduced_at=date(2022, 10, 25),
            published_at=NOW,
        )
        session.add(proposal)
        session.flush()
        session.add(
            ProposalActor(
                proposal_id=proposal.id,
                actor_type="politician",
                role=ProposalActorRole.COMMITMENT_OWNER,
                politician_id=politician.id,
                display_name="Mario Rossi",
                identity_key=f"pol-{proposal.id}",
            )
        )
        session.add(
            PledgeClassification(
                proposal_id=proposal.id,
                specificity=PledgeSpecificity.HIGH,
                commitment_type=CommitmentType.ACTION,
                holder_role=HolderRole.GOVERNMENT_COALITION,
                cap_topic_code="1",
                mandate_start=date(2022, 10, 22),
                mandate_end=date(2027, 10, 12),
                classified_by="other-editor",
            )
        )
        session.commit()
        return proposal.id


def test_decision_table_for_sixteen_reference_items():
    fixture = _load_fixture(DEFAULT_FIXTURE)
    published = _published_from_existing()
    actions = {}
    approved_titles: set[str] = set()
    for pledge in fixture["pledges"]:
        payload = _draft_payload(pledge)
        if pledge["number"] in {9, 14}:
            payload = None
        decision = decide_pledge_action(
            pledge,
            draft_payload=payload,
            published=published,
            already_approved_titles=approved_titles,
        )
        actions[pledge["number"]] = decision["recommended_action"]
        if decision["recommended_action"] == APPROVE_PLEDGE:
            approved_titles.add(decision["title"])
            approved_titles.add(decision["promise_text"])
    assert actions[9] == ALREADY_SKIPPED_DUPLICATE
    assert actions[14] == ALREADY_SKIPPED_DUPLICATE
    assert actions[10] == BLOCK_SOURCE_ISSUE
    assert actions[16] == KEEP_PENDING_NEEDS_REVIEW
    assert {actions[number] for number in (1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 13, 15)} == {
        APPROVE_PLEDGE
    }
    assert actions[4] == APPROVE_PLEDGE
    assert actions[6] == APPROVE_PLEDGE


def test_explicit_promise_and_duplicate_guards():
    published = _published_from_existing()
    vague = {
        "number": 99,
        "identity_key": "valori",
        "title": "Crediamo nella famiglia e nella nazione",
        "exact_statement": "La famiglia è un valore fondamentale.",
        "introduced_at": "2022-10-25",
        "declaration_url": "https://www.senato.it/show-doc?id=1",
        "origin_label": "retorica",
        "match_phrases": ["famiglia"],
    }
    decision = decide_pledge_action(
        vague, draft_payload=_draft_payload(vague), published=published
    )
    assert decision["recommended_action"] == REJECT_NOT_EXPLICIT_PROMISE
    assert decision["explicit_promise"] is False

    naval = {
        "number": 9,
        "identity_key": "blocco-navale",
        "title": "Realizzare un blocco navale europeo",
        "exact_statement": "Realizzare un blocco navale europeo",
        "introduced_at": "2022-08-01",
        "declaration_url": "https://www.rainews.it/video/example",
        "origin_label": "video",
        "match_phrases": ["blocco navale"],
    }
    skipped = decide_pledge_action(naval, draft_payload=None, published=published)
    assert skipped["recommended_action"] == ALREADY_SKIPPED_DUPLICATE
    duplicate_draft = decide_pledge_action(
        naval, draft_payload=_draft_payload(naval), published=published
    )
    assert duplicate_draft["recommended_action"] == "REJECT_DUPLICATE"


def test_dry_run_makes_no_db_changes(session_factory):
    ids, assessment_id = _prepare(session_factory)
    _classify_legacy(session_factory, ids["politician_id"])
    pending_id = _pending_giustizia_draft(session_factory, ids)
    unrelated_id = _unrelated_classification(session_factory)
    with session_factory() as session:
        before_drafts = [
            (row.id, row.status.value) for row in session.scalars(select(ProposalDraft))
        ]
        before_classifications = [
            (row.proposal_id, row.mandate_start.isoformat())
            for row in session.scalars(select(PledgeClassification))
        ]
    report = review_reference_pledges(
        "giorgia-meloni",
        session_factory=session_factory,
        dry_run=True,
        allow_non_unified=True,
    )
    assert report["dry_run"] is True
    assert len(report["approved"]) == 12
    assert {item["pdf_number"] for item in report["kept_pending"]} == {10, 16}
    assert {item["pdf_number"] for item in report["duplicate"]} == {9, 14}
    with session_factory() as session:
        after_drafts = [
            (row.id, row.status.value) for row in session.scalars(select(ProposalDraft))
        ]
        after_classifications = [
            (row.proposal_id, row.mandate_start.isoformat())
            for row in session.scalars(select(PledgeClassification))
        ]
        assessment = session.get(PledgeAssessment, assessment_id)
        pending = session.get(PledgeAssessmentDraft, pending_id)
        unrelated = session.scalar(
            select(PledgeClassification).where(
                PledgeClassification.proposal_id == unrelated_id
            )
        )
        assert after_drafts == before_drafts
        assert after_classifications == before_classifications
        assert assessment.verdict is FulfillmentVerdict.IN_PROGRESS
        assert pending.status is PledgeAssessmentDraftStatus.PENDING
        assert unrelated.mandate_start == date(2022, 10, 22)


def test_apply_approves_classifies_and_reconciles(session_factory):
    ids, assessment_id = _prepare(session_factory)
    _classify_legacy(session_factory, ids["politician_id"])
    pending_id = _pending_giustizia_draft(session_factory, ids)
    unrelated_id = _unrelated_classification(session_factory)
    with session_factory() as session:
        proceedings_before = [
            (row.id, row.status.value)
            for row in session.scalars(select(PoliticianProceeding))
        ]
        pending_before = session.get(PledgeAssessmentDraft, pending_id)

    first = review_reference_pledges(
        "giorgia-meloni",
        session_factory=session_factory,
        dry_run=False,
        allow_non_unified=True,
    )
    assert first["dry_run"] is False
    assert len(first["approved"]) == 12
    assert first["assessment_drafts_created"] == []
    assert first["proceedings_untouched"] is True
    assert first["assessment_drafts_untouched"] is True
    approved_numbers = {item["pdf_number"] for item in first["approved"]}
    assert approved_numbers == {1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 13, 15}
    assert {item["pdf_number"] for item in first["kept_pending"]} == {10, 16}
    assert len(first["mandate_windows_reconciled"]) == 9
    assert all(item["from"] == "2022-10-22" for item in first["mandate_windows_reconciled"])
    assert all(item["to"] == "2022-10-21" for item in first["mandate_windows_reconciled"])
    assert all(
        item["mandate_end_unchanged"] == "2027-10-12"
        for item in first["mandate_windows_reconciled"]
    )

    with session_factory() as session:
        published = list(
            session.scalars(
                select(Proposal).where(
                    Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
                    Proposal.published_at.is_not(None),
                )
            )
        )
        meloni_published = [
            row
            for row in published
            if any(
                actor.politician_id == ids["politician_id"]
                for actor in session.scalars(
                    select(ProposalActor).where(ProposalActor.proposal_id == row.id)
                )
            )
        ]
        assert len(meloni_published) == 21
        pending_drafts = [
            row
            for row in session.scalars(select(ProposalDraft))
            if row.status is ProposalDraftStatus.PENDING
            and "reference-profile:" in str((row.proposed_data or {}).get("proposal_identifier"))
        ]
        titles = {
            (row.proposed_data or {}).get("title") for row in pending_drafts
        }
        assert titles == {
            "Abolire progressivamente le accise sui carburanti",
            "Rendere strutturale l’esenzione dal bollo auto",
        }
        fornero = session.scalar(
            select(Proposal).where(
                Proposal.canonical_title.startswith("Rivedere la legge Fornero")
            )
        )
        classification = session.scalar(
            select(PledgeClassification).where(
                PledgeClassification.proposal_id == fornero.id
            )
        )
        assert classification.holder_role is HolderRole.OPPOSITION
        assert classification.mandate_start == date(2018, 1, 12)
        assert classification.mandate_end is None
        windows = list(session.scalars(select(PledgeClassification)))
        meloni_gov = [
            row
            for row in windows
            if row.holder_role is HolderRole.GOVERNMENT_COALITION
            and row.proposal_id != unrelated_id
        ]
        assert {row.mandate_start for row in meloni_gov} == {date(2022, 10, 21)}
        assert {row.mandate_end for row in meloni_gov} == {date(2027, 10, 12)}
        unrelated = session.scalar(
            select(PledgeClassification).where(
                PledgeClassification.proposal_id == unrelated_id
            )
        )
        assert unrelated.mandate_start == date(2022, 10, 22)
        assessment = session.get(PledgeAssessment, assessment_id)
        assert assessment.verdict is FulfillmentVerdict.IN_PROGRESS
        assert assessment.rationale.startswith("Official act language")
        pending = session.get(PledgeAssessmentDraft, pending_id)
        assert pending.status is pending_before.status
        assert pending.proposed_verdict is FulfillmentVerdict.IN_PROGRESS
        proceedings = [
            (row.id, row.status.value)
            for row in session.scalars(select(PoliticianProceeding))
        ]
        assert proceedings == proceedings_before
        assert all(row.status is ProfileContentStatus.PENDING for row in session.scalars(select(PoliticianProceeding)))
        new_assessments = list(session.scalars(select(PledgeAssessment)))
        assert [row.id for row in new_assessments] == [assessment_id]

        service = PledgeService(session_factory)
        rdc = session.scalar(
            select(Proposal).where(
                Proposal.canonical_title == "Abolire e sostituire il Reddito di cittadinanza"
            )
        )
        with pytest.raises(PledgeValidationError, match="verbatim"):
            service.propose(
                NewAssessmentDraft(
                    proposal_id=rdc.id,
                    proposal=PledgeAssessmentProposal(
                        verdict=FulfillmentVerdict.KEPT,
                        evidence_label=EvidenceLabel.SUPPORTS,
                        rationale="PDF commentary is not official evidence.",
                        quoted_excerpt="PDF cites D.L. 48/2023 and legge 85/2023.",
                        raw_document_id=ids["document_id"],
                    ),
                    origin=PledgeAssessmentOrigin.EDITOR,
                    created_by="pdf-operator",
                )
            )

    second = review_reference_pledges(
        "giorgia-meloni",
        session_factory=session_factory,
        dry_run=False,
        allow_non_unified=True,
    )
    assert second["approved"] == []
    assert len(second["already_published"]) == 12
    assert second["mandate_windows_reconciled"] == []
    assert second["assessment_drafts_created"] == []
    assert second["published_pledge_count"] == first["published_pledge_count"]


def test_public_scorecard_ask_and_spiegami(session_factory, tmp_path):
    ids, assessment_id = _prepare(session_factory)
    _classify_legacy(session_factory, ids["politician_id"])
    _pending_giustizia_draft(session_factory, ids)
    review_reference_pledges(
        "giorgia-meloni",
        session_factory=session_factory,
        dry_run=False,
        allow_non_unified=True,
    )
    settings = Settings(
        env=AppEnvironment.TEST,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        raw_storage_path=tmp_path / "raw",
        admin_api_key="profile-admin",
        trusted_hosts="localhost,127.0.0.1,testserver",
        enable_demo_ui=False,
    )
    with TestClient(create_app(settings)) as client:
        scorecard = client.get(f"/politicians/{ids['politician_id']}/scorecard").json()
        assert scorecard["methodology_version"] == "pledge-score/v1"
        assert scorecard["tracked_pledges"] == 21
        verdicts = {item["verdict"] for item in scorecard["pledges"]}
        assert "in_progress" in verdicts
        assert "not_yet_rated" in verdicts
        assert "kept" not in verdicts
        assert "broken" not in verdicts
        autonomia = next(
            item
            for item in scorecard["pledges"]
            if "autonomia" in item["title"].casefold()
        )
        assert autonomia["verdict"] == "in_progress"
        assert autonomia["latest_assessment"]["id"] == assessment_id
        unrated = [item for item in scorecard["pledges"] if item["verdict"] == "not_yet_rated"]
        assert len(unrated) == 20
        assert all(item["latest_assessment"] is None for item in unrated)
        rdc = next(item for item in unrated if "Reddito di cittadinanza" in item["title"])
        assert rdc["declaration_source_url"]
        assert rdc["introduced_at"] == "2022-10-25"
        blob = json.dumps(scorecard)
        assert "giorgia_meloni_v1" not in blob
        assert "suggested_verdict" not in blob
        assert "reference-profile" not in blob
        assert "PDF" not in blob
        for stratum in scorecard["strata"]:
            assert stratum["rate"] is None
            assert stratum["closed_pledges"] == 0
        roles = {stratum["role"] for stratum in scorecard["strata"]}
        assert roles == {"government_coalition", "opposition"}

        public = client.get(f"/politicians/{ids['politician_id']}").json()
        public_blob = json.dumps(public)
        assert CEO_REFERENCE_WARNING not in public_blob
        assert "reference-profile-operator" not in public_blob
        assert "reviewed_by" not in public_blob
        titles = {item["title"] for item in public["proposals"]}
        assert "Abolire e sostituire il Reddito di cittadinanza" in titles
        assert "Abolire progressivamente le accise sui carburanti" not in titles
        assert public["proceedings"] == []
        assert public["profile"]["mandates"][0]["start_date"] == "2022-10-21"

        rdc_id = rdc["proposal_id"]
        explanation = client.get(f"/proposals/{rdc_id}/explanation").json()
        assert explanation["verdict"] == "not_yet_rated"
        assert explanation["public_verdict_label"] == "Non ancora valutata"
        assert explanation["explanation"] == UNRATED_MESSAGE
        assert explanation["generated_by_ai"] is False
        assert "Mantenuta" not in explanation["explanation"]

        asked = client.post(
            "/ask",
            json={"question": "Quali promesse di Giorgia Meloni non sono ancora valutate?"},
        )
        assert asked.status_code == 200
        body = asked.json()
        assert body["intent"] in {"politician_pledges", "pledges_by_verdict"}
        result_titles = " ".join(item["title"] for item in body["results"])
        assert "Reddito di cittadinanza" in result_titles
        assert all(item["verdict"] != "kept" for item in body["results"])
        assert "suggested_verdict" not in json.dumps(body)

    assert FulfillmentVerdict.BROKEN in DUAL_APPROVAL_VERDICTS
    assert len(DUAL_APPROVAL_VERDICTS) == 1


def test_broken_still_requires_two_reviewers(session_factory):
    ids, _assessment_id = _prepare(session_factory)
    _classify_legacy(session_factory, ids["politician_id"])
    review_reference_pledges(
        "giorgia-meloni",
        session_factory=session_factory,
        dry_run=False,
        allow_non_unified=True,
    )
    service = PledgeService(session_factory, clock=lambda: NOW)
    with session_factory() as session:
        giustizia = session.scalar(
            select(Proposal.id).where(
                Proposal.canonical_title.startswith(
                    "Rivedremo anche la riforma dell’ordinamento giudiziario"
                )
            )
        )
    draft, _ = service.propose(
        NewAssessmentDraft(
            proposal_id=giustizia,
            proposal=PledgeAssessmentProposal(
                verdict=FulfillmentVerdict.BROKEN,
                evidence_label=EvidenceLabel.REFUTES,
                rationale="The official programme text does not enact the later reform.",
                quoted_excerpt=EXISTING_PLEDGES[3],
                raw_document_id=ids["document_id"],
                effective_at=date(2024, 6, 1),
            ),
            origin=PledgeAssessmentOrigin.EDITOR,
            created_by="editor-a",
        )
    )
    assert draft.approvals_required == 2
    _, published = service.approve(draft.id, reviewer="rev-1")
    assert published is None
    with session_factory() as session:
        row = session.get(PledgeAssessmentDraft, draft.id)
        assert row.status is PledgeAssessmentDraftStatus.AWAITING_SECOND_APPROVAL
        assert session.scalar(
            select(PledgeAssessment).where(PledgeAssessment.proposal_id == giustizia)
        ) is None


def test_operator_command_refuses_production(monkeypatch):
    monkeypatch.setattr(
        "scripts.review_reference_pledges.configured_environment",
        lambda: AppEnvironment.PRODUCTION,
    )
    with pytest.raises(DemoSafetyError, match="production"):
        review_reference_pledges(
            "giorgia-meloni", dry_run=True, allow_non_unified=True
        )
    assert review_main(["giorgia-meloni", "--dry-run"]) == 1


def test_evidence_readiness_labels_exist():
    assert PledgeEvidenceReadiness.ASSESSMENT_EVIDENCE_AVAILABLE.value == (
        "ASSESSMENT_EVIDENCE_AVAILABLE"
    )
    assert PledgeEvidenceReadiness.ASSESSMENT_NEEDS_OFFICIAL_EVIDENCE.value == (
        "ASSESSMENT_NEEDS_OFFICIAL_EVIDENCE"
    )
    assert PledgeEvidenceReadiness.ASSESSMENT_SOURCE_PRESENT_BUT_NO_VERBATIM_EXCERPT.value
    assert PledgeEvidenceReadiness.ASSESSMENT_OTHER_BLOCKER.value
