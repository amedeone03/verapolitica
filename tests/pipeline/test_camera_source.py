import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from backend.app.models import RawDocument, RawDocumentStatus, Source
from backend.app.pipeline.collectors import CameraCollector, CollectedDocument
from backend.app.pipeline.ingestion_pipeline import IngestionPipeline
from backend.app.pipeline.mappers import CameraCandidateProfileMapper
from backend.app.pipeline.parsers import CameraParser, ParserError
from backend.app.schemas import Gender, SourceDocumentProvenance


FIXTURE_PATH = Path("data/fixtures/camera/camera_deputies.json")


def fixture_content() -> bytes:
    return FIXTURE_PATH.read_bytes()


def camera_source(session_factory) -> Source:
    with session_factory() as session:
        source = Source(
            key="camera-deputati",
            name="Camera dei Deputati",
            base_url="https://dati.camera.it",
        )
        session.add(source)
        session.commit()
        session.refresh(source)
        return source


class SequenceCollector:
    version = "camera_collector_v1"

    def __init__(self, documents: list[bytes]) -> None:
        self.documents = iter(documents)
        self.count = 0

    def collect(self) -> CollectedDocument:
        content = next(self.documents)
        retrieved_at = datetime(2026, 10, 3, tzinfo=timezone.utc) + timedelta(
            seconds=self.count
        )
        self.count += 1
        return CollectedDocument(
            content=content,
            source_url="https://dati.camera.it/sparql",
            content_type="application/sparql-results+json",
            retrieved_at=retrieved_at,
            collector_version=self.version,
        )


def pipeline(session_factory, raw_storage, documents):
    return IngestionPipeline(
        session_factory=session_factory,
        storage=raw_storage,
        collector=SequenceCollector(documents),
        parser=CameraParser(),
        profile_mapper=CameraCandidateProfileMapper(),
    )


def test_collector_uses_current_legislature_and_official_sparql_contract():
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        assert request.method == "GET"
        assert request.headers["accept"] == "application/sparql-results+json"
        assert "repubblica_19" in query
        assert "FILTER NOT EXISTS" in query
        assert "?personUri a foaf:Person" in query
        return httpx.Response(200, json={"results": {"bindings": []}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        document = CameraCollector(
            "https://dati.camera.it/sparql", 19, client=client
        ).collect()

    assert document.collector_version == "camera_collector_v1"
    assert document.source_url == "https://dati.camera.it/sparql"


def test_parser_normalizes_dates_strings_and_record_order():
    parsed = CameraParser().parse(fixture_content())

    assert parsed.parser_version == "camera_parser_v1"
    assert len(parsed.structured_records) == 2
    assert parsed.structured_records[0]["deputy_uri"].endswith("d100_19")
    assert parsed.structured_records[0]["birth_date"] == "1970-01-02"
    assert parsed.structured_records[0]["mandate_start"] == "2022-10-13"
    assert json.loads(parsed.canonical_json) == parsed.structured_records


def test_parser_rejects_invalid_date_with_record_context():
    payload = json.loads(fixture_content())
    payload["results"]["bindings"][0]["birthDate"]["value"] = "19650231"

    with pytest.raises(ParserError, match="record 0.*birth_date"):
        CameraParser().parse(json.dumps(payload).encode())


def test_mapper_produces_source_independent_profile_and_provenance():
    record = CameraParser().parse(fixture_content()).structured_records[0]
    document = SourceDocumentProvenance(
        source_key="camera-deputati",
        raw_document_id=42,
        source_url="https://dati.camera.it/sparql",
        retrieved_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
        raw_sha256="a" * 64,
        normalized_sha256="b" * 64,
        collector_version="camera_collector_v1",
        parser_version="camera_parser_v1",
    )

    candidate = CameraCandidateProfileMapper().map_records(
        (record,), document=document
    )[0]

    assert candidate.identity.given_name == "MARIA"
    assert candidate.identity.birth_date == date(1970, 1, 2)
    assert candidate.identity.source_identifiers[0].authority == "camera-deputati"
    assert candidate.profile.gender is Gender.FEMALE
    assert candidate.profile.mandates[0].institution == "Camera dei Deputati"
    assert candidate.profile.mandates[0].office == "deputy"
    birth_evidence = next(
        field
        for field in candidate.provenance.fields
        if field.target_path == "identity.birth_date"
    )
    assert "/persona.rdf/" in birth_evidence.source_record_id
    assert birth_evidence.source_field == "birthDate"


def test_camera_normalized_change_detection_and_changed_only_mapping(
    session_factory, raw_storage
):
    source = camera_source(session_factory)
    original = fixture_content()
    payload = json.loads(original)
    payload["results"]["bindings"].reverse()
    formatting_only = json.dumps(payload, indent=4).encode()
    payload["results"]["bindings"][0]["profession"]["value"] = "Magistrata"
    meaningful = json.dumps(payload).encode()
    ingestion = pipeline(
        session_factory, raw_storage, [original, formatting_only, meaningful]
    )

    first = ingestion.run(source_id=source.id, source_key=source.key)
    second = ingestion.run(source_id=source.id, source_key=source.key)
    third = ingestion.run(source_id=source.id, source_key=source.key)

    assert first.change_detected is True
    assert len(first.candidate_profiles) == 2
    assert second.raw_sha256 != first.raw_sha256
    assert second.normalized_sha256 == first.normalized_sha256
    assert second.change_detected is False
    assert second.candidate_profiles == ()
    assert third.normalized_sha256 != second.normalized_sha256
    assert third.change_detected is True
    assert len(third.candidate_profiles) == 2


def test_camera_parser_failure_preserves_raw_document(
    session_factory, raw_storage
):
    source = camera_source(session_factory)
    ingestion = pipeline(session_factory, raw_storage, [b'{"results": {}}'])

    with pytest.raises(ParserError, match="results.bindings"):
        ingestion.run(source_id=source.id, source_key=source.key)

    with session_factory() as session:
        document = session.query(RawDocument).one()
        assert document.process_status is RawDocumentStatus.FAILED
        assert document.normalized_sha256 is None
