from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select

from backend.app.ai import (
    FakeExtractionProvider,
    OllamaStructuredExtractionProvider,
    OpenAIExtractionProvider,
)
from backend.app.core.config import Settings
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import DocumentChunk, RawDocument, Source
from backend.app.pipeline.chunk_selection import select_relevant_chunks
from backend.app.pipeline.official_document_pipeline import OfficialDocumentPipeline
from backend.app.schemas import StructuredExtractionResult
from backend.app.services.proposal_extraction_service import ProposalExtractionService
from backend.app.storage import LocalRawStorage


def source_details(source_url: str, source_key: str | None) -> tuple[str, str]:
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("--source-url must be an absolute HTTPS official URL")
    base_url = f"https://{parsed.hostname}"
    if source_key is None:
        host_key = re.sub(r"[^a-z0-9]+", "-", parsed.hostname.lower()).strip("-")
        source_key = f"official-{host_key}"[:100]
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", source_key):
        raise ValueError("--source-key must use lowercase letters, digits, '_' or '-'")
    return source_key, base_url


def content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix == ".pdf":
        return "application/pdf"
    raise ValueError("only .html, .htm, and text-based .pdf files are supported")


def fake_extraction_provider(fake_response: Path) -> FakeExtractionProvider:
    payload = json.loads(fake_response.read_text(encoding="utf-8"))
    if "output" not in payload:
        payload = {
            "output": payload,
            "usage": {"request_count": 1, "input_tokens": 0, "output_tokens": 0},
        }
    return FakeExtractionProvider(
        StructuredExtractionResult.model_validate(payload),
        model_name="simulated-ceo-demo",
    )


def live_extraction_provider(settings: Settings):
    provider = (settings.llm_provider or "").strip().casefold()
    if provider == "ollama":
        if not (settings.llm_model or "").strip():
            raise ValueError(
                "Ollama extraction requires VERAPOLITICA_LLM_MODEL"
            )
        return OllamaStructuredExtractionProvider(
            model_name=settings.llm_model,
            base_url=settings.ollama_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
            num_ctx=settings.ollama_num_ctx,
            structured_format=settings.ollama_structured_format,  # type: ignore[arg-type]
        )
    if provider != "openai":
        raise ValueError(
            "live extraction is disabled: configure VERAPOLITICA_LLM_PROVIDER=ollama "
            "or openai, or pass --fake-response"
        )
    if settings.llm_model is None or settings.llm_api_key is None:
        raise ValueError(
            "OpenAI extraction requires VERAPOLITICA_LLM_MODEL and "
            "VERAPOLITICA_LLM_API_KEY"
        )
    return OpenAIExtractionProvider(
        api_key=settings.llm_api_key.get_secret_value(),
        model_name=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def _ensure_source(
    session_factory,
    *,
    source_key: str,
    source_name: str,
    base_url: str,
) -> int:
    with session_factory() as session:
        source = session.scalar(select(Source).where(Source.key == source_key))
        if source is None:
            source = Source(
                key=source_key,
                name=source_name,
                base_url=base_url,
            )
            session.add(source)
            session.commit()
            session.refresh(source)
        elif source.base_url != base_url:
            raise ValueError(
                f"source key {source_key!r} already belongs to {source.base_url}"
            )
        return source.id


def ingest_official_document(
    *,
    settings: Settings,
    content: bytes,
    source_url: str,
    source_name: str,
    content_type: str,
    source_key: str | None = None,
) -> dict:
    source_key, base_url = source_details(source_url, source_key)
    engine = create_db_engine(settings.database_url)
    try:
        prepare_runtime_schema(engine, settings)
        session_factory = create_session_factory(engine)
        source_id = _ensure_source(
            session_factory,
            source_key=source_key,
            source_name=source_name,
            base_url=base_url,
        )
        ingestion = OfficialDocumentPipeline(
            session_factory,
            LocalRawStorage(settings.raw_storage_path),
            max_document_bytes=settings.ai_max_document_bytes,
            max_chunk_chars=settings.ai_max_chunk_chars,
            max_chunks=settings.ai_max_document_chunks,
        ).ingest(
            source_id=source_id,
            source_key=source_key,
            source_url=source_url,
            content_type=content_type,
            content=content,
        )
        page_count = 0
        with session_factory() as session:
            document = session.get(RawDocument, ingestion.raw_document_id)
            if document is not None and document.structured_records:
                first = document.structured_records[0]
                if isinstance(first, dict):
                    page_count = int(first.get("page_count") or 0)
            if page_count == 0:
                pages = [
                    chunk.page_end or chunk.page_start
                    for chunk in session.scalars(
                        select(DocumentChunk).where(
                            DocumentChunk.raw_document_id == ingestion.raw_document_id
                        )
                    )
                    if chunk.page_end or chunk.page_start
                ]
                page_count = max(pages) if pages else 0
        return {
            "raw_document_id": ingestion.raw_document_id,
            "raw_sha256": ingestion.raw_sha256,
            "chunk_count": ingestion.chunk_count,
            "page_count": page_count,
            "warnings": list(ingestion.warnings),
        }
    finally:
        engine.dispose()


def preview_chunk_selection(
    *,
    settings: Settings,
    raw_document_id: int,
) -> dict:
    engine = create_db_engine(settings.database_url)
    try:
        prepare_runtime_schema(engine, settings)
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            chunks = tuple(
                session.scalars(
                    select(DocumentChunk)
                    .where(DocumentChunk.raw_document_id == raw_document_id)
                    .order_by(DocumentChunk.chunk_index)
                )
            )
        if not chunks:
            raise ValueError("document has no extractable sections")
        selection = select_relevant_chunks(
            chunks,
            max_selected=min(
                settings.ai_max_selected_chunks, settings.ai_max_chunks_per_run
            ),
            max_document_tokens=settings.ai_max_document_tokens,
        )
        payload = selection.as_dict()
        payload["coverage_note"] = selection.coverage_note()
        return payload
    finally:
        engine.dispose()


def extract_ingested_document(
    *,
    settings: Settings,
    raw_document_id: int,
    fake_response: Path | None = None,
    provider=None,
) -> dict:
    engine = create_db_engine(settings.database_url)
    try:
        prepare_runtime_schema(engine, settings)
        session_factory = create_session_factory(engine)
        resolved = provider or (
            fake_extraction_provider(fake_response)
            if fake_response is not None
            else live_extraction_provider(settings)
        )
        extraction = ProposalExtractionService(
            session_factory,
            resolved,
            max_chunks_per_run=settings.ai_max_chunks_per_run,
            max_evidence_excerpt_chars=settings.ai_max_evidence_excerpt_chars,
            max_selected_chunks=settings.ai_max_selected_chunks,
            max_document_tokens=settings.ai_max_document_tokens,
        ).extract(raw_document_id)
        return {
            "extraction_run_id": extraction.run_id,
            "reused_completed_run": extraction.reused_completed_run,
            "candidate_count": extraction.candidate_count,
            "accepted_count": extraction.accepted_count,
            "rejected_count": extraction.rejected_count,
            "abstained_count": extraction.abstained_count,
            "duplicate_count": extraction.duplicate_count,
            "proposal_draft_ids": list(extraction.draft_ids),
            "publication": "none — human review and approval are still required",
        }
    finally:
        engine.dispose()


def run_official_extraction(
    *,
    settings: Settings,
    content: bytes,
    source_url: str,
    source_name: str,
    content_type: str,
    source_key: str | None = None,
    fake_response: Path | None = None,
    provider=None,
) -> dict:
    ingestion = ingest_official_document(
        settings=settings,
        content=content,
        source_url=source_url,
        source_name=source_name,
        content_type=content_type,
        source_key=source_key,
    )
    extraction = extract_ingested_document(
        settings=settings,
        raw_document_id=ingestion["raw_document_id"],
        fake_response=fake_response,
        provider=provider,
    )
    return {**ingestion, **extraction}
