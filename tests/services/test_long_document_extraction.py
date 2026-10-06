from sqlalchemy import func, select

from backend.app.ai import FakeExtractionProvider
from backend.app.models import (
    AIExtractionCandidate,
    AIExtractionCandidateStatus,
    AIExtractionRun,
    DocumentChunk,
    Proposal,
    Source,
)
from backend.app.pipeline.chunk_selection import select_relevant_chunks
from backend.app.pipeline.official_document_pipeline import OfficialDocumentPipeline
from backend.app.schemas import StructuredExtractionResult
from backend.app.services import ProposalExtractionService
from backend.app.services.official_extraction_runner import live_extraction_provider
from backend.app.core.config import Settings


TITLE = "Disegno di legge per il reddito energetico"
ACTOR = "Sen. Verdi"
ARTICLE = (
    "Articolo 1. Si impegna a stanziare 10 milioni di euro il 12/01/2026. "
    f"Presentato da {ACTOR}."
)


def _long_html() -> bytes:
    blocks = [
        "<html><body>",
        f"<h1>{TITLE}</h1>",
        "<p>Atto Senato. Dati generali. Presentato da Governo. Relatori. Assegnazione.</p>",
    ]
    filler = "testo descrittivo senza impegni e senza date. " * 12
    for index in range(70):
        blocks.append(f"<p>Sezione di riempimento {index}. {filler}</p>")
    blocks.append(f"<p>{ARTICLE}</p>")
    blocks.append("</body></html>")
    return "".join(blocks).encode("utf-8")


def _ingest(session_factory, raw_storage) -> int:
    with session_factory() as session:
        source = Source(
            key="senato-ddl-long",
            name="Senato della Repubblica",
            base_url="https://www.senato.it",
        )
        session.add(source)
        session.commit()
        source_id = source.id
    return OfficialDocumentPipeline(
        session_factory,
        raw_storage,
        max_document_bytes=200_000,
        max_chunk_chars=220,
        max_chunks=400,
    ).ingest(
        source_id=source_id,
        source_key="senato-ddl-long",
        source_url="https://www.senato.it/leg/19/BGT/Schede/Ddliter/2047.htm",
        content_type="text/html",
        content=_long_html(),
    ).raw_document_id


def _claim(*, chunk_index: int, page: int | None, excerpt: str, abstain: bool = False):
    if abstain:
        return {"abstention_reason": "insufficient_evidence"}
    return {
        "claim_type": "proposal",
        "exact_statement": TITLE,
        "normalized_title": TITLE,
        "summary": ARTICLE,
        "topic": "environment",
        "actor_mentions": [{"name": ACTOR, "role": "proposer"}],
        "announced_at": "2026-01-12",
        "target_date": None,
        "evidence": [
            {
                "chunk_index": chunk_index,
                "page": page,
                "supporting_text": excerpt,
            },
            {
                "chunk_index": chunk_index,
                "page": page,
                "supporting_text": ACTOR,
            },
        ],
        "confidence": "medium",
        "abstention_reason": None,
    }


def test_live_provider_uses_ollama_without_api_key():
    provider = live_extraction_provider(
        Settings(llm_provider="ollama", llm_model="qwen2.5:7b")
    )
    assert provider.provider_name == "ollama"
    assert provider.model_name == "qwen2.5:7b"
    assert provider._num_ctx == 8192
    assert provider._structured_format == "json"


def test_long_document_selects_subset_and_stores_audit_metadata(
    session_factory, raw_storage
):
    document_id = _ingest(session_factory, raw_storage)
    with session_factory() as session:
        chunks = tuple(
            session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.raw_document_id == document_id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
    assert len(chunks) > 16
    selection = select_relevant_chunks(chunks, max_selected=16)
    article_chunk = next(chunk for chunk in chunks if "10 milioni di euro" in chunk.text)
    assert article_chunk.chunk_index in selection.selected_indexes

    provider = FakeExtractionProvider(
        StructuredExtractionResult.model_validate(
            {
                "output": {
                    "candidates": [
                        _claim(
                            chunk_index=article_chunk.chunk_index,
                            page=article_chunk.page_start,
                            excerpt="10 milioni di euro",
                        )
                    ]
                }
            }
        ),
        model_name="qwen2.5:7b",
    )
    result = ProposalExtractionService(
        session_factory,
        provider,
        max_chunks_per_run=40,
        max_evidence_excerpt_chars=600,
        max_selected_chunks=16,
    ).extract(document_id)

    assert result.accepted_count == 1
    assert len(provider.requests[0].chunks) == len(selection.selected_indexes)
    with session_factory() as session:
        run = session.get(AIExtractionRun, result.run_id)
        proposal = session.scalar(select(Proposal))
        assert proposal.published_at is None
        assert run.provider_response["chunk_selection"]["full_document_coverage"] is False
        assert run.input_chunk_count == len(selection.selected_indexes)
        assert article_chunk.chunk_index in run.provider_response["chunk_selection"][
            "selected_chunk_indexes"
        ]


def test_evidence_from_unselected_chunk_is_rejected(session_factory, raw_storage):
    document_id = _ingest(session_factory, raw_storage)
    with session_factory() as session:
        chunks = tuple(
            session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.raw_document_id == document_id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
    selection = select_relevant_chunks(chunks, max_selected=16)
    unselected = next(
        chunk
        for chunk in chunks
        if chunk.chunk_index not in selection.selected_indexes
    )
    provider = FakeExtractionProvider(
        StructuredExtractionResult.model_validate(
            {
                "output": {
                    "candidates": [
                        _claim(
                            chunk_index=unselected.chunk_index,
                            page=unselected.page_start,
                            excerpt=unselected.text[:40].strip(),
                        )
                    ]
                }
            }
        )
    )
    result = ProposalExtractionService(
        session_factory,
        provider,
        max_chunks_per_run=40,
        max_evidence_excerpt_chars=600,
        max_selected_chunks=16,
    ).extract(document_id)
    assert result.rejected_count == 1
    assert result.draft_ids == ()
    with session_factory() as session:
        candidate = session.scalar(select(AIExtractionCandidate))
        assert candidate.status is AIExtractionCandidateStatus.REJECTED
        assert "missing chunk" in candidate.validation_message
        assert session.scalar(select(func.count()).select_from(Proposal)) == 0


def test_evidence_from_omitted_packed_chunk_is_rejected(session_factory, raw_storage):
    document_id = _ingest(session_factory, raw_storage)
    with session_factory() as session:
        chunks = tuple(
            session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.raw_document_id == document_id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
    selection = select_relevant_chunks(
        chunks, max_selected=16, max_document_tokens=80
    )
    assert selection.omitted_indexes
    omitted = next(
        chunk for chunk in chunks if chunk.chunk_index in selection.omitted_indexes
    )
    provider = FakeExtractionProvider(
        StructuredExtractionResult.model_validate(
            {
                "output": {
                    "candidates": [
                        _claim(
                            chunk_index=omitted.chunk_index,
                            page=omitted.page_start,
                            excerpt=omitted.text[:40].strip(),
                        )
                    ]
                }
            }
        )
    )
    result = ProposalExtractionService(
        session_factory,
        provider,
        max_chunks_per_run=40,
        max_evidence_excerpt_chars=600,
        max_selected_chunks=16,
        max_document_tokens=80,
    ).extract(document_id)
    assert result.rejected_count == 1
    assert result.draft_ids == ()
    with session_factory() as session:
        candidate = session.scalar(select(AIExtractionCandidate))
        assert candidate.status is AIExtractionCandidateStatus.REJECTED
        assert "missing chunk" in candidate.validation_message
        run = session.get(AIExtractionRun, result.run_id)
        assert omitted.chunk_index in run.provider_response["chunk_selection"][
            "omitted_chunk_indexes"
        ]
        assert omitted.chunk_index not in run.provider_response["chunk_selection"][
            "sent_chunk_indexes"
        ]


def test_model_abstention_creates_no_public_proposal(session_factory, raw_storage):
    document_id = _ingest(session_factory, raw_storage)
    provider = FakeExtractionProvider(
        StructuredExtractionResult.model_validate(
            {"output": {"candidates": [_claim(chunk_index=0, page=None, excerpt="x", abstain=True)]}}
        )
    )
    result = ProposalExtractionService(
        session_factory,
        provider,
        max_chunks_per_run=40,
        max_evidence_excerpt_chars=600,
        max_selected_chunks=16,
    ).extract(document_id)
    assert result.abstained_count == 1
    assert result.draft_ids == ()
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Proposal)) == 0
