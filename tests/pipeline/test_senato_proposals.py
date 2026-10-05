import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from backend.app.models import RawDocument, RawDocumentStatus, Source
from backend.app.pipeline.collectors import SenatoProposalCollector
from backend.app.pipeline.mappers import ProposalMappingError, SenatoProposalMapper
from backend.app.pipeline.parsers import ParserError, SenatoProposalParser
from backend.app.pipeline.proposal_pipeline import ProposalIngestionPipeline


FIXTURES = Path("data/fixtures/proposals")


def test_senato_proposal_collector_uses_structured_official_query():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=json.loads((FIXTURES / "senato_proposals.json").read_text()))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        document = SenatoProposalCollector(
            "https://dati.senato.it/sparql",
            19,
            record_limit=25,
            client=client,
        ).collect()

    query = requests[0].url.params["query"]
    assert "osr:Ddl" in query
    assert "osr:statoDdl" in query
    assert "osr:senatore" in query
    assert "LIMIT 25" in query
    assert requests[0].headers["user-agent"].startswith("VeraPolitica/")
    assert document.collector_version == "senato_proposal_collector_v1"


def test_parser_groups_actor_rows_and_mapper_preserves_status_and_provenance():
    parsed = SenatoProposalParser().parse(
        (FIXTURES / "senato_proposals.json").read_bytes()
    )
    assert len(parsed.structured_records) == 1
    record = parsed.structured_records[0]
    assert record["official_id"] == "synthetic-100"
    assert len(record["actors"]) == 2
    assert json.loads(parsed.canonical_json) == parsed.structured_records

    observation = SenatoProposalMapper().map_records(
        parsed.structured_records,
        source_key="senato-ddl",
        raw_document_id=1,
        observed_at=datetime(2026, 2, 4, tzinfo=timezone.utc),
    )[0]
    assert observation.proposal_type.value == "legislative_proposal"
    assert observation.normalized_status.value == "introduced"
    assert observation.source_status_label == "da assegn. a commis."
    assert observation.actors[0].source_identifier.endswith("synthetic-anna")
    assert {item.source_field for item in observation.evidence} >= {
        "osr:titolo",
        "osr:statoDdl",
        "osr:senatore",
    }


def test_unknown_source_status_is_rejected_instead_of_guessed():
    parsed = SenatoProposalParser().parse(
        (FIXTURES / "senato_proposals.json").read_bytes()
    )
    parsed.structured_records[0]["source_status_label"] = "unknown new label"
    with pytest.raises(ProposalMappingError, match="unknown new label"):
        SenatoProposalMapper().map_records(
            parsed.structured_records,
            source_key="senato-ddl",
            raw_document_id=1,
            observed_at=datetime.now(timezone.utc),
        )


def test_proposal_pipeline_changed_only_and_parser_failure(
    session_factory, raw_storage
):
    with session_factory() as session:
        source = Source(
            key="senato-ddl",
            name="Senato DDL",
            base_url="https://dati.senato.it",
        )
        session.add(source)
        session.commit()
        source_id = source.id

    contents = [
        (FIXTURES / "senato_proposals.json").read_bytes(),
        (FIXTURES / "senato_proposals.json").read_bytes(),
        (FIXTURES / "senato_proposals_updated.json").read_bytes(),
    ]

    class Collector:
        version = "fixture_proposal_collector_v1"

        def collect(self):
            from backend.app.pipeline.collectors import CollectedDocument

            return CollectedDocument(
                content=contents.pop(0),
                source_url="https://dati.senato.it/sparql",
                content_type="application/json",
                retrieved_at=datetime.now(timezone.utc),
                collector_version=self.version,
            )

    pipeline = ProposalIngestionPipeline(
        session_factory,
        raw_storage,
        Collector(),
        SenatoProposalParser(),
        SenatoProposalMapper(),
    )
    first = pipeline.run(source_id=source_id, source_key="senato-ddl")
    replay = pipeline.run(source_id=source_id, source_key="senato-ddl")
    updated = pipeline.run(source_id=source_id, source_key="senato-ddl")

    assert first.change_detected is True and len(first.observations) == 1
    assert replay.change_detected is False and replay.observations == ()
    assert updated.change_detected is True
    assert updated.observations[0].normalized_status.value == "under_review"

    contents.append(b"not-json")
    with pytest.raises(ParserError):
        pipeline.run(source_id=source_id, source_key="senato-ddl")
    with session_factory() as session:
        failed = session.scalar(
            select(RawDocument)
            .where(RawDocument.source_id == source_id)
            .order_by(RawDocument.id.desc())
        )
        assert failed.process_status is RawDocumentStatus.FAILED
        assert failed.storage_key
