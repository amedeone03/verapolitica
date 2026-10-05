import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import DocumentChunk, RawDocument, RawDocumentStatus
from backend.app.pipeline.document_chunking import chunk_document
from backend.app.pipeline.document_extraction import (
    DocumentExtractionError,
    extract_document,
)
from backend.app.storage import RawStorage


class OfficialDocumentPipelineError(RuntimeError):
    def __init__(self, message: str, *, raw_document_id: int | None = None) -> None:
        super().__init__(message)
        self.raw_document_id = raw_document_id


@dataclass(frozen=True, slots=True)
class OfficialDocumentIngestionResult:
    raw_document_id: int
    raw_sha256: str
    normalized_sha256: str
    chunk_count: int
    parser_version: str
    warnings: tuple[str, ...]


class OfficialDocumentPipeline:
    collector_version = "operator_official_document_v1"

    def __init__(
        self,
        session_factory: Callable[[], Session],
        storage: RawStorage,
        *,
        max_document_bytes: int,
        max_chunk_chars: int,
        max_chunks: int,
    ) -> None:
        self.session_factory = session_factory
        self.storage = storage
        self.max_document_bytes = max_document_bytes
        self.max_chunk_chars = max_chunk_chars
        self.max_chunks = max_chunks

    def ingest(
        self,
        *,
        source_id: int,
        source_key: str,
        source_url: str,
        content_type: str,
        content: bytes,
        retrieved_at: datetime | None = None,
    ) -> OfficialDocumentIngestionResult:
        observed_at = retrieved_at or datetime.now(timezone.utc)
        raw_digest = sha256(content).hexdigest()
        storage_key = self.storage.put(source_key, raw_digest, content)
        with self.session_factory() as session:
            document = RawDocument(
                source_id=source_id,
                retrieved_at=observed_at,
                source_url=source_url,
                content_type=content_type,
                storage_key=storage_key,
                raw_sha256=raw_digest,
                process_status=RawDocumentStatus.COLLECTED,
                collector_version=self.collector_version,
                parser_version="pending_official_text_extraction",
            )
            session.add(document)
            session.commit()
            raw_document_id = document.id

        try:
            if len(content) > self.max_document_bytes:
                raise DocumentExtractionError(
                    f"document exceeds {self.max_document_bytes} configured bytes"
                )
            extracted = extract_document(content, content_type)
            chunks = chunk_document(
                extracted,
                max_chunk_chars=self.max_chunk_chars,
                max_chunks=self.max_chunks,
            )
            if not chunks:
                raise DocumentExtractionError("document produced no extractable chunks")
        except Exception as exc:
            with self.session_factory() as session:
                document = session.get(RawDocument, raw_document_id)
                if document is not None:
                    document.process_status = RawDocumentStatus.FAILED
                    document.error_message = str(exc)
                    session.commit()
            raise OfficialDocumentPipelineError(
                str(exc), raw_document_id=raw_document_id
            ) from exc

        canonical = json.dumps(
            {
                "format": extracted.format,
                "pages": [
                    {
                        "page_number": page.page_number,
                        "text": page.text,
                        "char_start": page.char_start,
                        "char_end": page.char_end,
                    }
                    for page in extracted.pages
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        normalized_digest = sha256(canonical.encode("utf-8")).hexdigest()
        with self.session_factory() as session:
            previous_digest = session.scalar(
                select(RawDocument.normalized_sha256)
                .where(
                    RawDocument.source_id == source_id,
                    RawDocument.id != raw_document_id,
                    RawDocument.process_status == RawDocumentStatus.PARSED,
                )
                .order_by(RawDocument.retrieved_at.desc(), RawDocument.id.desc())
                .limit(1)
            )
            document = session.get(RawDocument, raw_document_id)
            if document is None:
                raise OfficialDocumentPipelineError(
                    "RawDocument disappeared before extracted text persistence",
                    raw_document_id=raw_document_id,
                )
            document.normalized_sha256 = normalized_digest
            document.normalized_text = extracted.text
            document.structured_records = [
                {
                    "format": extracted.format,
                    "page_count": len(extracted.pages),
                    "warnings": list(extracted.warnings),
                }
            ]
            document.parser_version = extracted.parser_version
            document.process_status = RawDocumentStatus.PARSED
            document.change_detected = (
                previous_digest is None or previous_digest != normalized_digest
            )
            document.error_message = None
            session.add_all(
                DocumentChunk(
                    raw_document_id=raw_document_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    chunk_hash=chunk.chunk_hash,
                )
                for chunk in chunks
            )
            session.commit()
        return OfficialDocumentIngestionResult(
            raw_document_id=raw_document_id,
            raw_sha256=raw_digest,
            normalized_sha256=normalized_digest,
            chunk_count=len(chunks),
            parser_version=extracted.parser_version,
            warnings=extracted.warnings,
        )
