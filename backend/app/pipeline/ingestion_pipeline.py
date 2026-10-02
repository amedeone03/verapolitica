from dataclasses import dataclass
from hashlib import sha256
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.raw_document import RawDocument, RawDocumentStatus
from backend.app.pipeline.collectors.base import Collector
from backend.app.pipeline.mappers.base import CandidateProfileMapper
from backend.app.pipeline.parsers.base import Parser, ParserError
from backend.app.schemas import CandidateProfile, SourceDocumentProvenance
from backend.app.storage.base import RawStorage


@dataclass(frozen=True, slots=True)
class IngestionResult:
    raw_document_id: int
    process_status: RawDocumentStatus
    change_detected: bool | None
    raw_sha256: str
    normalized_sha256: str | None
    storage_key: str
    collector_version: str
    parser_version: str
    candidate_profiles: tuple[CandidateProfile, ...]


class IngestionPipeline:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        storage: RawStorage,
        collector: Collector,
        parser: Parser,
        profile_mapper: CandidateProfileMapper | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.storage = storage
        self.collector = collector
        self.parser = parser
        self.profile_mapper = profile_mapper

    def run(self, *, source_id: int, source_key: str) -> IngestionResult:
        collected = self.collector.collect()
        raw_digest = sha256(collected.content).hexdigest()
        storage_key = self.storage.put(source_key, raw_digest, collected.content)

        with self.session_factory() as session:
            raw_document = RawDocument(
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
            session.add(raw_document)
            session.commit()
            session.refresh(raw_document)
            raw_document_id = raw_document.id

        try:
            parsed = self.parser.parse(collected.content)
        except ParserError as exc:
            with self.session_factory() as session:
                failed_document = session.get(RawDocument, raw_document_id)
                if failed_document is None:
                    raise RuntimeError("RawDocument disappeared during parsing") from exc
                failed_document.process_status = RawDocumentStatus.FAILED
                failed_document.error_message = str(exc)
                session.commit()
            raise

        normalized_digest = sha256(parsed.canonical_json.encode("utf-8")).hexdigest()

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
            changed = previous_digest is None or previous_digest != normalized_digest

            parsed_document = session.get(RawDocument, raw_document_id)
            if parsed_document is None:
                raise RuntimeError("RawDocument disappeared before persistence")
            parsed_document.structured_records = parsed.structured_records
            parsed_document.normalized_text = parsed.normalized_text
            parsed_document.normalized_sha256 = normalized_digest
            parsed_document.process_status = RawDocumentStatus.PARSED
            parsed_document.change_detected = changed
            parsed_document.parser_version = parsed.parser_version
            parsed_document.error_message = None
            session.commit()

        candidate_profiles: tuple[CandidateProfile, ...] = ()
        if changed and self.profile_mapper is not None:
            provenance = SourceDocumentProvenance(
                source_key=source_key,
                raw_document_id=raw_document_id,
                source_url=collected.source_url,
                retrieved_at=collected.retrieved_at,
                raw_sha256=raw_digest,
                normalized_sha256=normalized_digest,
                collector_version=collected.collector_version,
                parser_version=parsed.parser_version,
            )
            candidate_profiles = self.profile_mapper.map_records(
                parsed.structured_records,
                document=provenance,
            )

        return IngestionResult(
            raw_document_id=raw_document_id,
            process_status=RawDocumentStatus.PARSED,
            change_detected=changed,
            raw_sha256=raw_digest,
            normalized_sha256=normalized_digest,
            storage_key=storage_key,
            collector_version=collected.collector_version,
            parser_version=parsed.parser_version,
            candidate_profiles=candidate_profiles,
        )
