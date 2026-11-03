"""Re-attach Camera and Senato parliamentary groups from stored raw bundles.

Group rows live in the SPARQL bundle, not in ``structured_records``. After
Camera/Senato identities exist, run this instead of downloading the sources
again. Memberships match the exact ``PoliticianSourceIdentifier``; unresolved
names stay unresolved.

    python -m scripts.reprocess_parliamentary_groups --dry-run
    python -m scripts.reprocess_parliamentary_groups --apply

Does not invent identities. Does not publish profiles.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import RawDocument, RawDocumentStatus, Source
from backend.app.pipeline.mappers import (
    CameraParliamentaryGroupMapper,
    SenatoParliamentaryGroupMapper,
)
from backend.app.pipeline.parsers import CameraParser, ParserError, SenatoParser
from backend.app.services import ParliamentaryGroupService, ParliamentaryGroupServiceError
from backend.app.storage import LocalRawStorage, StorageError


@dataclass
class SourceReport:
    source_key: str
    raw_document_id: int | None = None
    total_observations: int = 0
    groups_created: int = 0
    memberships_created: int = 0
    memberships_updated: int = 0
    memberships_unchanged: int = 0
    unresolved_references: int = 0
    error: str | None = None


@dataclass
class Report:
    dry_run: bool
    sources: list[SourceReport] = field(default_factory=list)


def _latest_parsed(session: Session, source_key: str) -> RawDocument | None:
    return session.scalar(
        select(RawDocument)
        .join(Source)
        .where(
            Source.key == source_key,
            RawDocument.process_status == RawDocumentStatus.PARSED,
        )
        .order_by(RawDocument.id.desc())
    )


def _mapper(source_key: str, camera_legislature: int | str):
    if source_key == "camera-deputati":
        return CameraParser(), CameraParliamentaryGroupMapper(camera_legislature)
    if source_key == "senato-repubblica":
        return SenatoParser(), SenatoParliamentaryGroupMapper()
    raise ValueError(f"unsupported source {source_key!r}")


def reprocess(
    session_factory: sessionmaker[Session],
    storage: LocalRawStorage,
    *,
    source_keys: tuple[str, ...] = ("camera-deputati", "senato-repubblica"),
    camera_legislature: int | str = 19,
    dry_run: bool = True,
) -> Report:
    report = Report(dry_run=dry_run)
    for source_key in source_keys:
        item = SourceReport(source_key=source_key)
        report.sources.append(item)
        try:
            parser, mapper = _mapper(source_key, camera_legislature)
            with session_factory() as session:
                document = _latest_parsed(session, source_key)
                if document is None:
                    item.error = "nessun documento grezzo analizzato"
                    continue
                item.raw_document_id = document.id
                content = storage.get(document.storage_key)
                document_id = document.id
            parsed = parser.parse(content)
            observations = mapper.map_records(
                parsed.parliamentary_group_records,
                source_key=source_key,
                raw_document_id=document_id,
            )
            item.total_observations = len(observations)
            if dry_run:
                continue
            result = ParliamentaryGroupService(session_factory).sync(observations)
            item.groups_created = result.groups_created
            item.memberships_created = result.memberships_created
            item.memberships_updated = result.memberships_updated
            item.memberships_unchanged = result.memberships_unchanged
            item.unresolved_references = result.unresolved_references
        except (ParserError, StorageError, ParliamentaryGroupServiceError, ValueError) as exc:
            item.error = f"{type(exc).__name__}: {exc}"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--database-url")
    parser.add_argument("--raw-storage-path")
    args = parser.parse_args(argv)
    settings = get_settings()
    runtime = (
        settings.model_copy(update={"database_url": args.database_url})
        if args.database_url
        else settings
    )
    engine = create_db_engine(runtime.database_url)
    try:
        prepare_runtime_schema(engine, runtime)
        factory = create_session_factory(engine)
        storage = LocalRawStorage(
            args.raw_storage_path or settings.raw_storage_path
        )
        report = reprocess(
            factory,
            storage,
            camera_legislature=settings.camera_legislature,
            dry_run=args.dry_run,
        )
    finally:
        engine.dispose()
    print(
        json.dumps(
            asdict(report),
            ensure_ascii=False,
            indent=2,
            default=lambda value: value.isoformat()
            if isinstance(value, datetime)
            else str(value),
        )
    )
    if any(item.error for item in report.sources):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
