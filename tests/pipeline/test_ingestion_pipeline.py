import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.app.models import RawDocument, RawDocumentStatus
from backend.app.pipeline.collectors import CollectedDocument
from backend.app.pipeline.ingestion_pipeline import IngestionPipeline
from backend.app.pipeline.mappers import (
    CandidateMappingError,
    SenatoCandidateProfileMapper,
)
from backend.app.pipeline.parsers import ParserError, SenatoParser


def sparql_binding(
    senator_id: str,
    first_name: str,
    last_name: str,
    *,
    profession: str,
) -> dict:
    return {
        "senatorUri": {"type": "uri", "value": f"https://dati.senato.it/senatore/{senator_id}"},
        "firstName": {"type": "literal", "value": first_name},
        "lastName": {"type": "literal", "value": last_name},
        "gender": {"type": "literal", "value": "female" if first_name == "ANNA" else "male"},
        "birthDate": {"type": "literal", "value": "1970-01-02"},
        "birthCity": {"type": "literal", "value": "Roma"},
        "birthProvince": {"type": "literal", "value": "Roma"},
        "birthCountry": {"type": "literal", "value": "Italia"},
        "profession": {"type": "literal", "value": profession},
        "photoUrl": {"type": "uri", "value": f"https://www.senato.it/photo/{senator_id}.jpg"},
        "homepage": {"type": "uri", "value": f"https://www.senato.it/senatore/{senator_id}"},
        "mandateUri": {"type": "uri", "value": f"https://dati.senato.it/mandato/{senator_id}-19"},
        "mandateType": {"type": "literal", "value": "elettivo"},
        "mandateStart": {"type": "literal", "value": "2022-10-13"},
        "legislature": {"type": "literal", "value": "19"},
        "electionRegion": {"type": "literal", "value": "Lazio"},
    }


def response_payload(*, profession: str = "Avvocato") -> dict:
    return {
        "head": {"vars": ["senatorUri", "firstName", "lastName"]},
        "results": {
            "bindings": [
                sparql_binding("2", "LUCA", "BIANCHI", profession="Docente"),
                sparql_binding("1", "ANNA", "ROSSI", profession=profession),
            ]
        },
    }


def encode_payload(payload: dict, *, pretty: bool = False) -> bytes:
    if pretty:
        return json.dumps(payload, ensure_ascii=False, indent=4).encode()
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


class SequenceCollector:
    version = "senato_collector_v1"

    def __init__(self, documents: list[bytes]) -> None:
        self.documents = iter(documents)
        self.call_count = 0

    def collect(self) -> CollectedDocument:
        content = next(self.documents)
        retrieved_at = datetime(2026, 10, 2, tzinfo=timezone.utc) + timedelta(
            seconds=self.call_count
        )
        self.call_count += 1
        return CollectedDocument(
            content=content,
            source_url="https://dati.senato.it/sparql",
            content_type="application/sparql-results+json",
            retrieved_at=retrieved_at,
            collector_version=self.version,
        )


def build_pipeline(
    session_factory,
    raw_storage,
    documents: list[bytes],
    *,
    with_profile_mapper: bool = True,
):
    return IngestionPipeline(
        session_factory=session_factory,
        storage=raw_storage,
        collector=SequenceCollector(documents),
        parser=SenatoParser(),
        profile_mapper=(
            SenatoCandidateProfileMapper() if with_profile_mapper else None
        ),
    )


def all_documents(session_factory) -> list[RawDocument]:
    with session_factory() as session:
        return list(session.scalars(select(RawDocument).order_by(RawDocument.id)))


def test_first_ingestion_is_changed(session_factory, source, raw_storage):
    content = encode_payload(response_payload())
    pipeline = build_pipeline(session_factory, raw_storage, [content])

    result = pipeline.run(source_id=source.id, source_key=source.key)

    assert result.process_status is RawDocumentStatus.PARSED
    assert result.change_detected is True
    assert result.normalized_sha256 is not None
    assert result.collector_version == "senato_collector_v1"
    assert result.parser_version == "senato_parser_v1"
    assert len(result.candidate_profiles) == 2
    document = all_documents(session_factory)[0]
    assert document.structured_records is not None
    assert document.structured_records[0]["senator_uri"].endswith("/1")
    assert raw_storage.get(result.storage_key) == content


def test_exact_duplicate_is_unchanged_and_reuses_storage(
    session_factory, source, raw_storage
):
    content = encode_payload(response_payload())
    pipeline = build_pipeline(session_factory, raw_storage, [content, content])

    first = pipeline.run(source_id=source.id, source_key=source.key)
    second = pipeline.run(source_id=source.id, source_key=source.key)

    assert second.change_detected is False
    assert second.raw_sha256 == first.raw_sha256
    assert second.normalized_sha256 == first.normalized_sha256
    assert second.storage_key == first.storage_key
    assert len(first.candidate_profiles) == 2
    assert second.candidate_profiles == ()
    assert len(all_documents(session_factory)) == 2


def test_formatting_only_change_is_unchanged(session_factory, source, raw_storage):
    original_payload = response_payload()
    reformatted_payload = {
        "results": {
            "bindings": list(reversed(original_payload["results"]["bindings"]))
        },
        "head": original_payload["head"],
    }
    original = encode_payload(original_payload)
    reformatted = encode_payload(reformatted_payload, pretty=True)
    pipeline = build_pipeline(session_factory, raw_storage, [original, reformatted])

    first = pipeline.run(source_id=source.id, source_key=source.key)
    second = pipeline.run(source_id=source.id, source_key=source.key)

    assert second.raw_sha256 != first.raw_sha256
    assert second.normalized_sha256 == first.normalized_sha256
    assert second.change_detected is False
    assert second.candidate_profiles == ()


def test_meaningful_change_is_detected(session_factory, source, raw_storage):
    original = encode_payload(response_payload(profession="Avvocato"))
    changed = encode_payload(response_payload(profession="Magistrato"))
    pipeline = build_pipeline(session_factory, raw_storage, [original, changed])

    first = pipeline.run(source_id=source.id, source_key=source.key)
    second = pipeline.run(source_id=source.id, source_key=source.key)

    assert second.raw_sha256 != first.raw_sha256
    assert second.normalized_sha256 != first.normalized_sha256
    assert second.change_detected is True
    assert len(second.candidate_profiles) == 2


def test_parser_failure_preserves_raw_document(
    session_factory, source, raw_storage
):
    invalid_content = b'{"results":{"not_bindings":[]}}'
    pipeline = build_pipeline(session_factory, raw_storage, [invalid_content])

    with pytest.raises(ParserError, match="results.bindings"):
        pipeline.run(source_id=source.id, source_key=source.key)

    document = all_documents(session_factory)[0]
    assert document.process_status is RawDocumentStatus.FAILED
    assert document.normalized_sha256 is None
    assert document.change_detected is None
    assert document.error_message is not None
    assert document.collector_version == "senato_collector_v1"
    assert document.parser_version == "senato_parser_v1"
    assert raw_storage.get(document.storage_key) == invalid_content


def test_mapping_failure_preserves_parsed_raw_document(
    session_factory, source, raw_storage
):
    payload = response_payload()
    payload["results"]["bindings"][0]["gender"]["value"] = "unsupported"
    content = encode_payload(payload)
    pipeline = build_pipeline(session_factory, raw_storage, [content])

    with pytest.raises(CandidateMappingError, match="unsupported gender value") as error:
        pipeline.run(source_id=source.id, source_key=source.key)

    assert "senatore/2" in str(error.value)
    document = all_documents(session_factory)[0]
    assert document.process_status is RawDocumentStatus.PARSED
    assert document.change_detected is True
    assert document.normalized_sha256 is not None
    assert document.structured_records is not None
    assert raw_storage.get(document.storage_key) == content
