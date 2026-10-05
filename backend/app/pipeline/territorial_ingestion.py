from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import RawDocument, RawDocumentStatus
from backend.app.pipeline.collectors.base import Collector
from backend.app.pipeline.parsers.base import ParsedDocument, Parser, ParserError
from backend.app.schemas import SourceDocumentProvenance
from backend.app.storage.base import RawStorage


@dataclass(frozen=True, slots=True)
class TerritorialRawResult:
    raw_document_id: int
    change_detected: bool
    storage_key: str
    parsed: ParsedDocument
    provenance: SourceDocumentProvenance


class TerritorialRawPipeline:
    """Persist raw provenance and parsing output, leaving domain writes to services."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        storage: RawStorage,
        collector: Collector,
        parser: Parser,
    ) -> None:
        self.session_factory = session_factory
        self.storage = storage
        self.collector = collector
        self.parser = parser

    def run(self, *, source_id: int, source_key: str) -> TerritorialRawResult:
        collected = self.collector.collect()
        raw_digest = sha256(collected.content).hexdigest()
        storage_key = self.storage.put(source_key, raw_digest, collected.content)
        with self.session_factory() as session:
            document = RawDocument(
                source_id=source_id,
                retrieved_at=collected.retrieved_at,
                source_url=collected.source_url,
                content_type=collected.content_type,
                storage_key=storage_key,
                raw_sha256=raw_digest,
                process_status=RawDocumentStatus.COLLECTED,
                collector_version=collected.collector_version,
                parser_version=self.parser.version,
            )
            session.add(document)
            session.commit()
            session.refresh(document)
            document_id = document.id
        try:
            parsed = self.parser.parse(collected.content)
        except ParserError as exc:
            with self.session_factory() as session:
                document = session.get(RawDocument, document_id)
                if document is not None:
                    document.process_status = RawDocumentStatus.FAILED
                    document.error_message = str(exc)
                    session.commit()
            raise
        normalized_digest = sha256(parsed.canonical_json.encode("utf-8")).hexdigest()
        with self.session_factory() as session:
            previous = session.scalar(
                select(RawDocument.normalized_sha256)
                .where(
                    RawDocument.source_id == source_id,
                    RawDocument.id != document_id,
                    RawDocument.process_status == RawDocumentStatus.PARSED,
                )
                .order_by(RawDocument.retrieved_at.desc(), RawDocument.id.desc())
                .limit(1)
            )
            changed = previous is None or previous != normalized_digest
            document = session.get(RawDocument, document_id)
            if document is None:
                raise RuntimeError("RawDocument disappeared before parsed persistence")
            document.structured_records = parsed.structured_records
            document.normalized_text = parsed.normalized_text
            document.normalized_sha256 = normalized_digest
            document.process_status = RawDocumentStatus.PARSED
            document.change_detected = changed
            document.parser_version = parsed.parser_version
            session.commit()
        provenance = SourceDocumentProvenance(
            source_key=source_key,
            raw_document_id=document_id,
            source_url=collected.source_url,
            retrieved_at=collected.retrieved_at,
            raw_sha256=raw_digest,
            normalized_sha256=normalized_digest,
            collector_version=collected.collector_version,
            parser_version=parsed.parser_version,
        )
        return TerritorialRawResult(
            raw_document_id=document_id,
            change_detected=changed,
            storage_key=storage_key,
            parsed=parsed,
            provenance=provenance,
        )
