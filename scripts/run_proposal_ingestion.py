import json
import sys

from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import Source
from backend.app.pipeline.collectors import CollectorError, SenatoProposalCollector
from backend.app.pipeline.mappers import ProposalMappingError, SenatoProposalMapper
from backend.app.pipeline.parsers import ParserError, SenatoProposalParser
from backend.app.pipeline.proposal_pipeline import ProposalIngestionPipeline
from backend.app.services import ProposalService, ProposalServiceError
from backend.app.storage import LocalRawStorage, StorageError


SOURCE_KEY = "senato-ddl"
SOURCE_NAME = "Senato della Repubblica — Disegni di legge"
SOURCE_BASE_URL = "https://dati.senato.it"


def get_or_create_source(session_factory) -> Source:
    with session_factory() as session:
        source = session.scalar(select(Source).where(Source.key == SOURCE_KEY))
        if source is None:
            source = Source(
                key=SOURCE_KEY,
                name=SOURCE_NAME,
                base_url=SOURCE_BASE_URL,
            )
            session.add(source)
            session.commit()
            session.refresh(source)
        return source


def main() -> int:
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    prepare_runtime_schema(engine, settings)
    session_factory = create_session_factory(engine)
    source = get_or_create_source(session_factory)
    try:
        ingestion = ProposalIngestionPipeline(
            session_factory=session_factory,
            storage=LocalRawStorage(settings.raw_storage_path),
            collector=SenatoProposalCollector(
                endpoint=settings.senato_sparql_endpoint,
                legislature=settings.senato_legislature,
                record_limit=settings.senato_proposal_record_limit,
                timeout_seconds=settings.senato_request_timeout_seconds,
            ),
            parser=SenatoProposalParser(),
            mapper=SenatoProposalMapper(),
        ).run(source_id=source.id, source_key=source.key)
        sync = ProposalService(session_factory).sync(ingestion.observations)
    except (
        CollectorError,
        ParserError,
        ProposalMappingError,
        ProposalServiceError,
        StorageError,
    ) as exc:
        print(f"Proposal ingestion failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(
        json.dumps(
            {
                "source": "senato",
                "source_key": source.key,
                "raw_document_id": ingestion.raw_document_id,
                "process_status": ingestion.process_status.value,
                "change_detected": ingestion.change_detected,
                "normalized_sha256": ingestion.normalized_sha256,
                "proposal_observation_count": len(ingestion.observations),
                "sync": sync.model_dump(mode="json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
