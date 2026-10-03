import argparse
import json
import sys
from dataclasses import dataclass

from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import Source
from backend.app.pipeline.collectors import CameraCollector, CollectorError, SenatoCollector
from backend.app.pipeline.ingestion_pipeline import IngestionPipeline
from backend.app.pipeline.mappers import (
    CameraCandidateProfileMapper,
    CandidateMappingError,
    SenatoCandidateProfileMapper,
)
from backend.app.pipeline.parsers import CameraParser, ParserError, SenatoParser
from backend.app.storage import LocalRawStorage, StorageError

@dataclass(frozen=True)
class SourceSpec:
    key: str
    name: str
    base_url: str


SOURCE_SPECS = {
    "senato": SourceSpec(
        key="senato-repubblica",
        name="Senato della Repubblica",
        base_url="https://dati.senato.it",
    ),
    "camera": SourceSpec(
        key="camera-deputati",
        name="Camera dei Deputati",
        base_url="https://dati.camera.it",
    ),
}


def get_or_create_source(session_factory, spec: SourceSpec) -> Source:
    with session_factory() as session:
        source = session.scalar(select(Source).where(Source.key == spec.key))
        if source is None:
            source = Source(
                key=spec.key,
                name=spec.name,
                base_url=spec.base_url,
            )
            session.add(source)
            session.commit()
            session.refresh(source)
        return source


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest an official political source")
    parser.add_argument(
        "--source",
        choices=tuple(SOURCE_SPECS),
        default="senato",
        help="official source to ingest (default: senato)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    spec = SOURCE_SPECS[args.source]
    source = get_or_create_source(session_factory, spec)

    if args.source == "camera":
        collector = CameraCollector(
            endpoint=settings.camera_sparql_endpoint,
            legislature=settings.camera_legislature,
            timeout_seconds=settings.camera_request_timeout_seconds,
        )
        parser = CameraParser()
        mapper = CameraCandidateProfileMapper()
    else:
        collector = SenatoCollector(
            endpoint=settings.senato_sparql_endpoint,
            legislature=settings.senato_legislature,
            timeout_seconds=settings.senato_request_timeout_seconds,
        )
        parser = SenatoParser()
        mapper = SenatoCandidateProfileMapper()

    pipeline = IngestionPipeline(
        session_factory=session_factory,
        storage=LocalRawStorage(settings.raw_storage_path),
        collector=collector,
        parser=parser,
        profile_mapper=mapper,
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
                "source": args.source,
                "source_key": source.key,
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
