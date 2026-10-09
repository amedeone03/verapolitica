from datetime import datetime, timezone

from sqlalchemy import func, select

from backend.app.models import (
    DocumentChunk,
    PledgeAssessment,
    PledgeAssessmentDraft,
    PledgeEvidenceCandidate,
    Proposal,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.scoring.conservative_evidence_judge import ConservativeOfficialActJudge
from backend.app.scoring.types import EvidenceLabel, FulfillmentVerdict
from backend.app.services.pledge_evidence_service import PledgeEvidenceService
from backend.app.services.pledge_service import PledgeService
from tests.services.pledge_seed import seed
from tests.services.test_pledge_service import classification


LAW = (
    "LEGGE 26 giugno 2024, n. 86. Disposizioni per l'attuazione dell'autonomia "
    "differenziata delle Regioni a statuto ordinario. Promulga la seguente legge."
)
NEWS = "Il governo avrebbe mantenuto la promessa sull'autonomia differenziata, secondo i giornali."
TOPIC_ONLY = "Il Ministero della giustizia pubblica il calendario delle commissioni per marzo."


def _add_document(session, *, url, text, key="gazzetta-ufficiale", published="2024-06-26"):
    source = session.scalar(select(Source).where(Source.key == key))
    if source is None:
        source = Source(key=key, name="Gazzetta Ufficiale", base_url="https://www.gazzettaufficiale.it")
        session.add(source)
        session.flush()
    document = RawDocument(
        source_id=source.id,
        retrieved_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        source_url=url,
        content_type="text/html",
        storage_key=f"{key}.html",
        raw_sha256="e" * 64,
        normalized_sha256="f" * 64,
        structured_records=[{"official_published_at": published}] if published else [],
        normalized_text=text,
        process_status=RawDocumentStatus.PARSED,
        change_detected=True,
        collector_version="test",
        parser_version="test",
    )
    session.add(document)
    session.flush()
    chunk = DocumentChunk(
        raw_document_id=document.id, chunk_index=0, text=text, chunk_hash="g" * 64
    )
    session.add(chunk)
    session.flush()
    return document.id, chunk.id


def test_unofficial_and_topic_only_documents_do_not_create_drafts(session_factory):
    data = seed(session_factory)
    service = PledgeService(session_factory)
    service.classify(
        data.pledge_id,
        classification(cap_topic_code="20"),
        classified_by="ed",
    )
    with session_factory() as session:
        proposal = session.get(Proposal, data.pledge_id)
        proposal.canonical_title = "Autonomia differenziata"
        proposal.exact_statement = (
            "intendiamo dare seguito al processo virtuoso di autonomia differenziata"
        )
        _add_document(
            session,
            url="https://www.corriere.it/politica/autonomia",
            text="Il governo avrebbe mantenuto la promessa sull'autonomia differenziata.",
            key="corriere",
        )
        session.commit()
    report = PledgeEvidenceService(
        session_factory, judge=ConservativeOfficialActJudge()
    ).run(proposal_ids=[data.pledge_id])
    assert report.drafts_created == 0
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PledgeAssessmentDraft)) == 0
        assert session.scalar(select(func.count()).select_from(PledgeAssessment)) == 0


def test_official_act_creates_pending_draft_without_publishing(session_factory):
    data = seed(session_factory)
    pledges = PledgeService(session_factory)
    pledges.classify(
        data.pledge_id,
        classification(
            cap_topic_code="20",
        ),
        classified_by="ed",
    )
    with session_factory() as session:
        proposal = session.get(Proposal, data.pledge_id)
        proposal.canonical_title = "Autonomia differenziata"
        proposal.exact_statement = (
            "intendiamo dare seguito al processo virtuoso di autonomia differenziata"
        )
        _add_document(
            session,
            url="https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg",
            text=LAW,
        )
        session.commit()
    before = pledges.scorecard_for_politician(data.politician_id)
    assert all(item.latest_assessment is None for item in before.pledges)
    report = PledgeEvidenceService(
        session_factory, judge=ConservativeOfficialActJudge()
    ).run(proposal_ids=[data.pledge_id])
    assert report.drafts_created == 1
    assert report.candidates_stored == 1
    (draft,) = pledges.list_drafts()
    assert draft.status == "pending"
    assert draft.proposed_verdict is FulfillmentVerdict.IN_PROGRESS
    assert draft.evidence_label is EvidenceLabel.SUPPORTS
    assert "autonomia differenziata" in draft.quoted_excerpt
    after = pledges.scorecard_for_politician(data.politician_id)
    assert after.pledges[0].verdict is FulfillmentVerdict.NOT_YET_RATED
    assert after.pledges[0].latest_assessment is None
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PledgeAssessment)) == 0
        candidate = session.scalar(select(PledgeEvidenceCandidate))
        assert candidate.status.value == "drafted"


def test_same_topic_unrelated_official_document_abstains(session_factory):
    data = seed(session_factory)
    PledgeService(session_factory).classify(
        data.pledge_id, classification(cap_topic_code="12"), classified_by="ed"
    )
    with session_factory() as session:
        proposal = session.get(Proposal, data.pledge_id)
        proposal.canonical_title = "Riforma dell'ordinamento giudiziario"
        proposal.exact_statement = (
            "rivedremo anche la riforma dell'ordinamento giudiziario per le logiche correntizie"
        )
        _add_document(
            session,
            url="https://www.giustizia.it/calendario",
            text=TOPIC_ONLY,
            key="ministero-giustizia",
            published="2024-03-01",
        )
        session.commit()
    report = PledgeEvidenceService(
        session_factory, judge=ConservativeOfficialActJudge()
    ).run(proposal_ids=[data.pledge_id])
    assert report.drafts_created == 0
    assert report.no_candidate_abstentions == 1


def test_invalid_excerpt_creates_no_draft(session_factory):
    data = seed(session_factory)
    PledgeService(session_factory).classify(data.pledge_id, classification(), classified_by="ed")

    class BadJudge:
        name = "bad"
        version = "t"

        def judge(self, *, pledge_text, commitment_type, passage_text):
            del pledge_text, commitment_type, passage_text
            from backend.app.scoring.evidence_matching import EvidenceJudgment

            return EvidenceJudgment(
                EvidenceLabel.SUPPORTS,
                FulfillmentVerdict.IN_PROGRESS,
                "testo che non esiste nel documento ufficiale",
                "inventato",
            )
    report = PledgeEvidenceService(session_factory, judge=BadJudge()).run(
        proposal_ids=[data.pledge_id]
    )
    assert report.drafts_created == 0
    assert report.rejections.get("excerpt_not_found_in_source", 0) >= 1
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PledgeAssessmentDraft)) == 0


def test_approved_assessment_updates_scorecard_pending_does_not(session_factory):
    data = seed(session_factory)
    service = PledgeService(session_factory)
    service.classify(data.pledge_id, classification(), classified_by="ed")
    from tests.services.test_pledge_service import editor_draft

    draft, _ = editor_draft(
        service, data, data.pledge_id, FulfillmentVerdict.KEPT, EvidenceLabel.SUPPORTS
    )
    pending = service.scorecard_for_politician(data.politician_id)
    assert pending.pledges[0].verdict is FulfillmentVerdict.NOT_YET_RATED
    service.approve(draft.id, reviewer="rev")
    published = service.scorecard_for_politician(data.politician_id)
    assert published.pledges[0].verdict is FulfillmentVerdict.KEPT
    assert published.pledges[0].latest_assessment is not None
    assert published.methodology_version == "pledge-score/v1"
