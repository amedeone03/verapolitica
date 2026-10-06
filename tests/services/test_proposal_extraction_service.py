import json
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
        assert run.provider_response["chunk_selection"]["full_document_coverage"] is True
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
        first_run = session.get(AIExtractionRun, first.run_id)
        fingerprint = first_run.provider_response["inference_fingerprint"]
        assert fingerprint["sha256"] == first_run.completed_idempotency_key
        assert fingerprint["prompt_content_sha256"]
        assert "raw_document_id" not in fingerprint
        assert session.scalar(select(func.count()).select_from(AIExtractionRun)) == 2
        assert session.scalar(select(func.count()).select_from(ProposalDraft)) == 1
        statuses = set(session.scalars(select(AIExtractionCandidate.status)))
        assert AIExtractionCandidateStatus.DUPLICATE in statuses


def test_prompt_text_model_budget_and_force_rerun_create_new_runs(
    session_factory, raw_storage, monkeypatch
):
    from backend.app.services import proposal_extraction_service as pes

    document_id = _document(session_factory, raw_storage)
    original_prompt = pes.load_proposal_extraction_prompt
    first = _service(session_factory, _provider(_claim())).extract(document_id)
    reused = _service(session_factory, _provider(_claim())).extract(document_id)

    monkeypatch.setattr(
        pes, "load_proposal_extraction_prompt", lambda: "CHANGED PROMPT TEXT FOR FINGERPRINT"
    )
    prompt_changed = _service(session_factory, _provider(_claim())).extract(document_id)
    monkeypatch.setattr(pes, "load_proposal_extraction_prompt", original_prompt)

    model_changed = _service(
        session_factory, _provider(_claim(), model_name="fake-extraction-v2")
    ).extract(document_id)
    budget_provider = _provider(_claim())
    budget_provider._num_ctx = 4096
    ctx_changed = ProposalExtractionService(
        session_factory,
        budget_provider,
        max_chunks_per_run=5,
        max_evidence_excerpt_chars=600,
    ).extract(document_id)
    token_changed = ProposalExtractionService(
        session_factory,
        _provider(_claim()),
        max_chunks_per_run=5,
        max_evidence_excerpt_chars=600,
        max_document_tokens=2_000,
    ).extract(document_id)
    forced = _service(session_factory, _provider(_claim())).extract(
        document_id, force_rerun=True
    )
    after_force = _service(session_factory, _provider(_claim())).extract(document_id)

    assert reused.run_id == first.run_id
    assert reused.reused_completed_run is True
    assert prompt_changed.run_id != first.run_id
    assert model_changed.run_id not in {first.run_id, prompt_changed.run_id}
    assert ctx_changed.run_id not in {
        first.run_id,
        prompt_changed.run_id,
        model_changed.run_id,
    }
    assert token_changed.run_id not in {
        first.run_id,
        prompt_changed.run_id,
        model_changed.run_id,
        ctx_changed.run_id,
    }
    assert forced.run_id != first.run_id
    assert forced.reused_completed_run is False
    assert after_force.run_id == forced.run_id
    assert after_force.reused_completed_run is True
    with session_factory() as session:
        runs = tuple(session.scalars(select(AIExtractionRun).order_by(AIExtractionRun.id)))
        assert len(runs) == 6
        original = session.get(AIExtractionRun, first.run_id)
        latest = session.get(AIExtractionRun, forced.run_id)
        assert original.status is AIExtractionRunStatus.COMPLETED
        assert original.completed_idempotency_key is None
        assert original.provider_response["superseded_by_run_id"] == forced.run_id
        assert latest.completed_idempotency_key == latest.idempotency_key
        assert latest.provider_response["force_rerun"] is True
        assert session.scalar(select(func.count()).select_from(ProposalDraft)) == 1
        proposal = session.scalar(select(Proposal))
        assert proposal.published_at is None


PAGE5_HTML = """
<html><body>
<h1>Conversione in legge, con modificazioni, del decreto-legge 7 agosto 2026, n. 144</h1>
<p>Dati generali. Iniziativa Governativa. Governo Meloni-I.</p>
<p>Presentazione Senato della Repubblica. Non ancora pubblicato. scadenza il 6 ottobre 2026.</p>
<p>annunciato nella seduta n. 459 del 29 settembre 2026</p>
<p>Il Governo si impegna a completare la digitalizzazione entro il 31 dicembre 2027.</p>
</body></html>
"""
PAGE5_TITLE = (
    "Conversione in legge, con modificazioni, del decreto-legge 7 agosto 2026, n. 144"
)
PAGE5_ANNOUNCEMENT = "annunciato nella seduta n. 459 del 29 settembre 2026"
PAGE5_SCADENZA = "scadenza il 6 ottobre 2026"
PAGE5_COMMITMENT = (
    "Il Governo si impegna a completare la digitalizzazione entro il 31 dicembre 2027"
)


def _page5_document(session_factory, raw_storage) -> int:
    with session_factory() as session:
        source = Source(
            key="senato-ddl-page5",
            name="Senato della Repubblica",
            base_url="https://www.senato.it",
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
        source_key="senato-ddl-page5",
        source_url="https://www.senato.it/leg/19/BGT/Schede/Ddliter/2047.htm",
        content_type="text/html",
        content=PAGE5_HTML.encode("utf-8"),
    ).raw_document_id


def _page5_claim(
    *,
    announced_at: str | None = "2026-09-29",
    target_date: str | None = None,
    extra_evidence: str = PAGE5_ANNOUNCEMENT,
):
    return {
        "claim_type": "proposal",
        "exact_statement": PAGE5_TITLE,
        "normalized_title": PAGE5_TITLE,
        "summary": "Conversione in legge del decreto-legge 144/2026.",
        "topic": "public_administration",
        "actor_mentions": [{"name": "Governo", "role": "government"}],
        "announced_at": announced_at,
        "target_date": target_date,
        "evidence": [
            {
                "chunk_index": 0,
                "page": None,
                "supporting_text": PAGE5_TITLE,
            },
            {
                "chunk_index": 0,
                "page": None,
                "supporting_text": "Governo Meloni-I",
            },
            {
                "chunk_index": 0,
                "page": None,
                "supporting_text": extra_evidence,
            },
            {
                "chunk_index": 0,
                "page": None,
                "supporting_text": PAGE5_ANNOUNCEMENT,
            },
        ],
        "confidence": "high",
        "abstention_reason": None,
    }


def test_parliamentary_announcement_date_is_accepted(session_factory, raw_storage):
    document_id = _page5_document(session_factory, raw_storage)
    result = _service(
        session_factory, _provider(_page5_claim())
    ).extract(document_id)
    assert result.accepted_count == 1
    with session_factory() as session:
        draft = session.get(ProposalDraft, result.draft_ids[0])
        assert draft.proposed_data["introduced_at"] == "2026-09-29"
        assert draft.proposed_data["metadata"]["target_date"] is None
        assert session.scalar(select(Proposal)).published_at is None


def test_scadenza_target_date_is_rejected_without_creating_a_draft(
    session_factory, raw_storage
):
    document_id = _page5_document(session_factory, raw_storage)
    result = _service(
        session_factory,
        _provider(_page5_claim(target_date="2026-10-06", extra_evidence=PAGE5_SCADENZA)),
    ).extract(document_id)
    assert result.accepted_count == 0
    assert result.rejected_count == 1
    assert result.draft_ids == ()
    with session_factory() as session:
        candidate = session.scalar(select(AIExtractionCandidate))
        assert candidate.status is AIExtractionCandidateStatus.REJECTED
        assert "procedural_deadline_not_proposal_target" in candidate.validation_message
        assert candidate.model_output["target_date"] == "2026-10-06"
        assert session.scalar(select(func.count()).select_from(Proposal)) == 0
        assert session.scalar(select(func.count()).select_from(ProposalDraft)) == 0


def test_commitment_deadline_target_date_is_accepted(session_factory, raw_storage):
    document_id = _page5_document(session_factory, raw_storage)
    result = _service(
        session_factory,
        _provider(
            _page5_claim(target_date="2027-12-31", extra_evidence=PAGE5_COMMITMENT)
        ),
    ).extract(document_id)
    assert result.accepted_count == 1
    with session_factory() as session:
        draft = session.get(ProposalDraft, result.draft_ids[0])
        assert draft.proposed_data["metadata"]["target_date"] == "2027-12-31"


def test_second_semantic_failure_creates_no_draft_and_no_third_provider_request(
    session_factory, raw_storage
):
    import httpx

    from backend.app.ai import OllamaStructuredExtractionProvider

    document_id = _page5_document(session_factory, raw_storage)
    calls = []
    payload = {
        "output": {
            "candidates": [
                _page5_claim(target_date="2026-10-06", extra_evidence=PAGE5_SCADENZA)
            ]
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        del request
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps(payload["output"])}},
        )

    provider = OllamaStructuredExtractionProvider(
        model_name="qwen3:8b",
        base_url="http://127.0.0.1:11434",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = _service(session_factory, provider).extract(document_id)
    assert len(calls) == 2
    assert result.accepted_count == 0
    assert result.rejected_count == 1
    assert result.draft_ids == ()
    with session_factory() as session:
        run = session.get(AIExtractionRun, result.run_id)
        assert run.request_count == 2
        attempts = run.provider_response["ollama_diagnostics"]["attempts"]
        assert [item["validation_status"] for item in attempts] == [
            "semantic_invalid",
            "semantic_invalid",
        ]
        assert session.scalar(select(func.count()).select_from(ProposalDraft)) == 0
        public = session.scalar(select(Proposal))
        assert public is None or public.published_at is None


def test_repaired_null_target_date_creates_unpublished_draft(
    session_factory, raw_storage
):
    import httpx

    from backend.app.ai import OllamaStructuredExtractionProvider

    document_id = _page5_document(session_factory, raw_storage)
    first = _page5_claim(target_date="2026-10-06", extra_evidence=PAGE5_SCADENZA)
    second = _page5_claim(target_date=None, extra_evidence=PAGE5_SCADENZA)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        body = first if len(calls) == 1 else second
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps({"candidates": [body]})}},
        )

    provider = OllamaStructuredExtractionProvider(
        model_name="qwen3:8b",
        base_url="http://127.0.0.1:11434",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = _service(session_factory, provider).extract(document_id)
    assert len(calls) == 2
    assert result.accepted_count == 1
    with session_factory() as session:
        draft = session.get(ProposalDraft, result.draft_ids[0])
        assert draft.proposed_data["metadata"]["target_date"] is None
        assert draft.proposed_data["introduced_at"] == "2026-09-29"
        assert session.scalar(select(Proposal)).published_at is None
        run = session.get(AIExtractionRun, result.run_id)
        diagnostics = run.provider_response["ollama_diagnostics"]
        assert diagnostics["attempt_count"] == 2
        assert diagnostics["attempts"][1]["repaired_fields"] == ["target_date"]
