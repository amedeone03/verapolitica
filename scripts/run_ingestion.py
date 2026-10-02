import json
import sys

from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import Source
from backend.app.pipeline.collectors import CollectorError, SenatoCollector
from backend.app.pipeline.ingestion_pipeline import IngestionPipeline
from backend.app.pipeline.mappers import (
    CandidateMappingError,
    SenatoCandidateProfileMapper,
)
from backend.app.pipeline.parsers import ParserError, SenatoParser
from backend.app.storage import LocalRawStorage, StorageError

SOURCE_KEY = "senato-repubblica"
SOURCE_NAME = "Senato della Repubblica"
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
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    source = get_or_create_source(session_factory)

    pipeline = IngestionPipeline(
        session_factory=session_factory,
        storage=LocalRawStorage(settings.raw_storage_path),
        collector=SenatoCollector(
            endpoint=settings.senato_sparql_endpoint,
            legislature=settings.senato_legislature,
            timeout_seconds=settings.senato_request_timeout_seconds,
        ),
        parser=SenatoParser(),
        profile_mapper=SenatoCandidateProfileMapper(),
    )

    try:
        result = pipeline.run(source_id=source.id, source_key=source.key)
    except (CollectorError, ParserError, CandidateMappingError, StorageError) as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(
        json.dumps(
            {
                "raw_document_id": result.raw_document_id,
                "process_status": result.process_status.value,
                "change_detected": result.change_detected,
                "raw_sha256": result.raw_sha256,
                "normalized_sha256": result.normalized_sha256,
                "storage_key": result.storage_key,
                "collector_version": result.collector_version,
                "parser_version": result.parser_version,
                "candidate_profile_count": len(result.candidate_profiles),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
