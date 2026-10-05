from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app.ai import ExtractionProviderError, FakeExtractionProvider
from backend.app.models import (
    AIExtractionCandidate,
    AIExtractionCandidateStatus,
    AIExtractionRun,
    AIExtractionRunStatus,
    Politician,
    PoliticianSourceIdentifier,
    Proposal,
    ProposalDraft,
    Source,
)
from backend.app.pipeline.official_document_pipeline import OfficialDocumentPipeline
from backend.app.schemas import (
    ExtractedPoliticalClaim,
    ObservedActorType,
    PoliticalClaimExtraction,
    StructuredExtractionResult,
)
from backend.app.services import (
    ActorIdentityHint,
    ProposalExtractionProviderFailure,
    ProposalExtractionService,
)


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "fixtures"
    / "ai"
    / "synthetic_official_programme.html"
)
SOURCE_URL = "https://official.example/programme.html"
PROMISE = "The Civic Example Party commits to build 100 new clinics by 2030."
PROPOSAL = "The programme proposes a national housing transparency register."


def _claim(
    *,
    statement: str = PROPOSAL,
    claim_type: str = "proposal",
    title: str = "Create a national housing transparency register",
    topic: str = "housing",
    actor_mentions=(),
    evidence_text: str | None = None,
    abstention_reason: str | None = None,
):
    if abstention_reason:
        return {"abstention_reason": abstention_reason}
    return {
        "claim_type": claim_type,
        "exact_statement": statement,
        "normalized_title": title,
        "summary": None,
        "topic": topic,
        "actor_mentions": list(actor_mentions),
        "announced_at": None,
        "target_date": "2030-12-31" if claim_type == "explicit_promise" else None,
        "evidence": [
            {
                "chunk_index": 0,
                "page": None,
                "supporting_text": evidence_text or statement,
            }
        ],
        "confidence": "high",
        "abstention_reason": None,
    }


def _provider(*claims, model_name="fake-extraction-v1"):
    return FakeExtractionProvider(
        StructuredExtractionResult.model_validate(
            {
                "output": {"candidates": list(claims)},
                "usage": {
                    "request_count": 1,
                    "input_tokens": 100,
                    "output_tokens": 25,
                },
            }
        ),
        model_name=model_name,
    )


def _document(session_factory, raw_storage) -> int:
    with session_factory() as session:
        source = Source(
            key="official-example",
            name="Synthetic official source",
            base_url="https://official.example",
        )
        session.add(source)
        session.commit()
        source_id = source.id
    return OfficialDocumentPipeline(
        session_factory,
        raw_storage,
        max_document_bytes=100_000,
        max_chunk_chars=10_000,
        max_chunks=5,
    ).ingest(
        source_id=source_id,
        source_key="official-example",
        source_url=SOURCE_URL,
        content_type="text/html",
        content=FIXTURE.read_bytes(),
    ).raw_document_id


def _service(session_factory, provider, *, prompt_version="proposal_extraction_v1"):
    return ProposalExtractionService(
        session_factory,
        provider,
        max_chunks_per_run=5,
        max_evidence_excerpt_chars=600,
        prompt_version=prompt_version,
    )


def test_extraction_schema_enforces_promise_owner_and_controlled_topic():
    with pytest.raises(ValidationError, match="commitment-owner"):
        ExtractedPoliticalClaim.model_validate(
            _claim(statement=PROMISE, claim_type="explicit_promise")
        )
    payload = _claim()
    payload["topic"] = "uncontrolled-topic"
    with pytest.raises(ValidationError):
        ExtractedPoliticalClaim.model_validate(payload)


def test_clear_proposal_creates_internal_draft_with_audit_metadata(
    session_factory, raw_storage
):
    document_id = _document(session_factory, raw_storage)
    result = _service(session_factory, _provider(_claim())).extract(document_id)

    assert result.accepted_count == 1
    assert len(result.draft_ids) == 1
    with session_factory() as session:
        run = session.get(AIExtractionRun, result.run_id)
        proposal = session.scalar(select(Proposal))
        assert run.status is AIExtractionRunStatus.COMPLETED
        assert run.prompt_version == "proposal_extraction_v1"
        assert run.input_tokens == 100
        assert proposal.published_at is None


def test_explicit_promise_preserves_statement_and_actor_remains_unresolved(
    session_factory, raw_storage
):
    document_id = _document(session_factory, raw_storage)
    claim = _claim(
        statement=PROMISE,
        claim_type="explicit_promise",
        title="Build 100 clinics by 2030",
        topic="healthcare",
        actor_mentions=[
            {"name": "The Civic Example Party", "role": "commitment_owner"}
        ],
    )
    result = _service(session_factory, _provider(claim)).extract(document_id)

    with session_factory() as session:
        draft = session.get(ProposalDraft, result.draft_ids[0])
        assert draft.proposed_data["exact_statement"] == PROMISE
        assert draft.proposed_data["proposal_type"] == "explicit_promise"
        assert draft.proposed_data["metadata"]["_unresolved_actors"] == [
            "The Civic Example Party"
        ]


def test_explicit_document_identity_hint_uses_existing_exact_resolution(
    session_factory, raw_storage
):
    document_id = _document(session_factory, raw_storage)
    with session_factory() as session:
        authority = Source(
            key="official-party-register",
            name="Official party register",
            base_url="https://register.example",
        )
        politician = Politician(
            canonical_given_name="Civic",
            canonical_family_name="Example",
            normalized_name="civic example",
        )
        session.add_all((authority, politician))
        session.flush()
        session.add(
            PoliticianSourceIdentifier(
                politician_id=politician.id,
                source_id=authority.id,
                value="https://register.example/person/civic-example",
            )
        )
        session.commit()
        politician_id = politician.id
    claim = _claim(
        statement=PROMISE,
        claim_type="explicit_promise",
        title="Build 100 clinics by 2030",
        topic="healthcare",
        actor_mentions=[
            {"name": "The Civic Example Party", "role": "commitment_owner"}
        ],
    )
    service = ProposalExtractionService(
        session_factory,
        _provider(claim),
        max_chunks_per_run=5,
        max_evidence_excerpt_chars=600,
        actor_identity_hints=(
            ActorIdentityHint(
                display_name="The Civic Example Party",
                actor_type=ObservedActorType.POLITICIAN,
                authority_key="official-party-register",
                source_identifier="https://register.example/person/civic-example",
            ),
        ),
    )
    result = service.extract(document_id)

    with session_factory() as session:
        draft = session.get(ProposalDraft, result.draft_ids[0])
        resolved = draft.proposed_data["metadata"]["_resolved_actors"][0]
        assert resolved["politician_id"] == politician_id
        assert draft.proposed_data["metadata"]["_unresolved_actors"] == []


def test_vague_statement_is_not_promoted_to_promise(session_factory, raw_storage):
    document_id = _document(session_factory, raw_storage)
    vague = _claim(
        statement="We believe healthcare is important.",
        claim_type="explicit_promise",
        title="Value healthcare",
        topic="healthcare",
        actor_mentions=[{"name": "We", "role": "commitment_owner"}],
    )
    result = _service(session_factory, _provider(vague)).extract(document_id)

    assert result.rejected_count == 1
    assert result.draft_ids == ()
    with session_factory() as session:
        candidate = session.scalar(select(AIExtractionCandidate))
        assert "commitment language" in candidate.validation_message


def test_fake_citation_is_rejected_without_creating_proposal(
    session_factory, raw_storage
):
    document_id = _document(session_factory, raw_storage)
    result = _service(
        session_factory,
        _provider(_claim(evidence_text="This sentence is not in the document.")),
    ).extract(document_id)

    assert result.rejected_count == 1
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Proposal)) == 0


def test_abstention_is_a_completed_non_failure(session_factory, raw_storage):
    document_id = _document(session_factory, raw_storage)
    result = _service(
        session_factory,
        _provider(_claim(abstention_reason="incomplete_context")),
    ).extract(document_id)

    assert result.abstained_count == 1
    assert result.draft_ids == ()


def test_malformed_provider_output_and_provider_failure_are_audited(
    session_factory, raw_storage
):
    document_id = _document(session_factory, raw_storage)
    malformed = FakeExtractionProvider({"not_output": True})
    with pytest.raises(ProposalExtractionProviderFailure) as malformed_error:
        _service(session_factory, malformed).extract(document_id)
    failing = FakeExtractionProvider(
        {"output": {"candidates": []}},
        model_name="fake-failure-v1",
        error=ExtractionProviderError("synthetic timeout"),
    )
    with pytest.raises(ProposalExtractionProviderFailure) as provider_error:
        _service(session_factory, failing).extract(document_id)

    with session_factory() as session:
        first = session.get(AIExtractionRun, malformed_error.value.run_id)
        second = session.get(AIExtractionRun, provider_error.value.run_id)
        assert first.status is AIExtractionRunStatus.FAILED
        assert first.provider_response is not None
        assert second.status is AIExtractionRunStatus.FAILED
        assert "synthetic timeout" in second.error_message
        assert session.scalar(select(func.count()).select_from(Proposal)) == 0


def test_duplicate_claim_and_document_idempotency_and_prompt_rerun(
    session_factory, raw_storage
):
    document_id = _document(session_factory, raw_storage)
    provider = _provider(_claim(), _claim())
    service = _service(session_factory, provider)

    first = service.extract(document_id)
    repeated = service.extract(document_id)
    rerun = _service(
        session_factory,
        _provider(_claim()),
        prompt_version="proposal_extraction_v2",
    ).extract(document_id)

    assert first.accepted_count == 1
    assert first.duplicate_count == 1
    assert repeated.run_id == first.run_id
    assert repeated.reused_completed_run is True
    assert rerun.run_id != first.run_id
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AIExtractionRun)) == 2
        assert session.scalar(select(func.count()).select_from(ProposalDraft)) == 1
        statuses = set(session.scalars(select(AIExtractionCandidate.status)))
        assert AIExtractionCandidateStatus.DUPLICATE in statuses
