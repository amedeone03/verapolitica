from pathlib import Path

from sqlalchemy import select

from backend.app.ai import FakeExtractionProvider
from backend.app.models import (
    AIExtractionCandidate,
    AIExtractionCandidateStatus,
    Proposal,
    ProposalDraft,
    Source,
)
from backend.app.pipeline.official_document_pipeline import OfficialDocumentPipeline
from backend.app.pipeline.prompts import load_proposal_extraction_prompt
from backend.app.schemas import StructuredExtractionResult
from backend.app.services import ProposalExtractionService


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "ai"
BILL_HTML = FIXTURE_ROOT / "parliamentary_bill_snippet.html"
METADATA_HTML = FIXTURE_ROOT / "parliamentary_metadata_only.html"
TITLE = (
    "Misure urgenti per la funzionalità della pubblica amministrazione, "
    "presentato dal Presidente del Consiglio dei ministri."
)
INITIATIVE = "Iniziativa Governativa"
SOURCE_URL = "https://www.senato.it/leg/19/BGT/Schede/Ddliter/snippet.htm"


def _ingest(session_factory, raw_storage, path: Path) -> int:
    with session_factory() as session:
        source = Source(
            key="senato-ddl-snippet",
            name="Senato della Repubblica",
            base_url="https://www.senato.it",
        )
        session.add(source)
        session.commit()
        source_id = source.id
    return OfficialDocumentPipeline(
        session_factory,
        raw_storage,
        max_document_bytes=50_000,
        max_chunk_chars=4_000,
        max_chunks=8,
    ).ingest(
        source_id=source_id,
        source_key="senato-ddl-snippet",
        source_url=SOURCE_URL,
        content_type="text/html",
        content=path.read_bytes(),
    ).raw_document_id


def _claim(
    *,
    statement: str = TITLE,
    evidence_text: str | None = None,
    actor_mentions=None,
    abstention_reason: str | None = None,
):
    if abstention_reason:
        return {"abstention_reason": abstention_reason}
    actors = actor_mentions if actor_mentions is not None else [
        {"name": INITIATIVE, "role": "government"}
    ]
    evidence = [
        {
            "chunk_index": 0,
            "page": None,
            "supporting_text": evidence_text or statement,
        }
    ]
    if actors:
        evidence.append(
            {
                "chunk_index": 0,
                "page": None,
                "supporting_text": actors[0]["name"],
            }
        )
    return {
        "claim_type": "proposal",
        "exact_statement": statement,
        "normalized_title": statement.rstrip("."),
        "summary": "Disegno di legge di iniziativa governativa.",
        "topic": "public_administration",
        "actor_mentions": actors,
        "announced_at": None,
        "target_date": None,
        "evidence": evidence,
        "confidence": "high",
        "abstention_reason": None,
    }


def _provider(*claims):
    return FakeExtractionProvider(
        StructuredExtractionResult.model_validate({"output": {"candidates": list(claims)}})
    )


def _service(session_factory, provider):
    return ProposalExtractionService(
        session_factory,
        provider,
        max_chunks_per_run=8,
        max_evidence_excerpt_chars=600,
    )


def test_prompt_treats_official_bills_as_proposals_without_colloquial_wording():
    compact = " ".join(load_proposal_extraction_prompt().split())
    assert "DISEGNO DI LEGGE" in compact
    assert "Iniziativa Governativa" in compact
    assert "proponiamo" in compact
    assert "does not make the bill cease to be a proposal" in compact
    assert "included in the cited supporting excerpts" in compact


def test_parliamentary_bill_title_qualifies_as_proposal(session_factory, raw_storage):
    document_id = _ingest(session_factory, raw_storage, BILL_HTML)
    result = _service(session_factory, _provider(_claim())).extract(document_id)
    assert result.accepted_count == 1
    with session_factory() as session:
        draft = session.get(ProposalDraft, result.draft_ids[0])
        proposal = session.get(Proposal, draft.proposal_id)
        assert draft.proposed_data["exact_statement"] == TITLE
        assert draft.proposed_data["proposal_type"] == "proposal"
        assert proposal.published_at is None


def test_approved_status_does_not_prevent_grounded_proposal(
    session_factory, raw_storage
):
    document_id = _ingest(session_factory, raw_storage, BILL_HTML)
    result = _service(session_factory, _provider(_claim())).extract(document_id)
    assert result.accepted_count == 1
    with session_factory() as session:
        from backend.app.models import DocumentChunk

        text = session.scalar(
            select(DocumentChunk.text).where(
                DocumentChunk.raw_document_id == document_id
            )
        )
        assert "approvato definitivamente" in text
        draft = session.get(ProposalDraft, result.draft_ids[0])
        assert draft.proposed_data["exact_statement"] == TITLE


def test_government_initiative_actor_is_unresolved(session_factory, raw_storage):
    document_id = _ingest(session_factory, raw_storage, BILL_HTML)
    result = _service(session_factory, _provider(_claim())).extract(document_id)
    with session_factory() as session:
        draft = session.get(ProposalDraft, result.draft_ids[0])
        assert draft.proposed_data["metadata"]["_unresolved_actors"] == [INITIATIVE]
        assert draft.proposed_data["metadata"]["_resolved_actors"] == []
        actors = draft.proposed_data["actors"]
        assert actors[0]["role"] == "government"
        assert actors[0]["display_name"] == INITIATIVE


def test_parliamentary_claim_requires_exact_evidence(session_factory, raw_storage):
    document_id = _ingest(session_factory, raw_storage, BILL_HTML)
    result = _service(
        session_factory,
        _provider(
            _claim(
                statement="The government will create a new secret ministry.",
                evidence_text="The government will create a new secret ministry.",
                actor_mentions=[],
            )
        ),
    ).extract(document_id)
    assert result.accepted_count == 0
    assert result.rejected_count == 1
    assert result.draft_ids == ()
    with session_factory() as session:
        candidate = session.scalar(select(AIExtractionCandidate))
        assert candidate.status is AIExtractionCandidateStatus.REJECTED
        assert "does not occur in chunk" in candidate.validation_message
        assert session.scalar(select(Proposal)) is None


def test_unsupported_parliamentary_metadata_still_abstains(
    session_factory, raw_storage
):
    document_id = _ingest(session_factory, raw_storage, METADATA_HTML)
    result = _service(session_factory, _provider()).extract(document_id)
    assert result.accepted_count == 0
    assert result.candidate_count == 0
    assert result.draft_ids == ()
    with session_factory() as session:
        assert session.scalar(select(Proposal)) is None
        from backend.app.models import DocumentChunk

        text = session.scalar(
            select(DocumentChunk.text).where(
                DocumentChunk.raw_document_id == document_id
            )
        )
        assert TITLE not in text
        assert INITIATIVE not in text
