import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import func, select

from backend.app.core.config import get_settings
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import Municipality, Source
from backend.app.pipeline.collectors import (
    CollectorError,
    DaitMayorCollector,
    IstatTerritoryCollector,
)
from backend.app.pipeline.mappers import (
    DaitMayorMapper,
    IstatTerritoryMapper,
)
from backend.app.pipeline.parsers import (
    DaitMayorParser,
    IstatTerritoryParser,
    ParserError,
)
from backend.app.pipeline.territorial_ingestion import TerritorialRawPipeline
from backend.app.services import (
    HumanIdentityResolutionCoordinator,
    TerritorialMandateService,
    TerritoryService,
)
from backend.app.storage import LocalRawStorage, StorageError


SOURCE_SPECS = {
    "territories": (
        "istat-territories",
        "ISTAT territorial classifications",
        "https://www.istat.it",
    ),
    "offices": (
        "dait-current-mayors",
        "DAIT current mayors",
        "https://dait.interno.gov.it",
    ),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest official ISTAT territories or DAIT current mayors"
    )
    parser.add_argument("mode", choices=("territories", "offices"))
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--fixture", type=Path, help="offline XLSX/CSV input")
    input_group.add_argument(
        "--live",
        action="store_true",
        help="explicitly download the official live endpoint",
    )
    parser.add_argument("--url", help="override the official endpoint URL")
    parser.add_argument("--database-url")
    parser.add_argument("--raw-storage-path", type=Path)
    parser.add_argument("--timeout-seconds", type=float)
    return parser.parse_args(argv)


def _source(session_factory, mode: str) -> Source:
    key, name, base_url = SOURCE_SPECS[mode]
    with session_factory() as session:
        source = session.scalar(select(Source).where(Source.key == key))
        if source is None:
            source = Source(key=key, name=name, base_url=base_url)
            session.add(source)
            session.commit()
            session.refresh(source)
        return source


def _require_explicit_input(args: argparse.Namespace) -> str | None:
    if args.fixture is None and not args.live and not args.url:
        return (
            "Territorial ingestion requires --fixture for offline use or "
            "--live/--url for an explicit official download"
        )
    if args.mode == "offices" and args.live and args.url is None:
        return None
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_error = _require_explicit_input(args)
    if input_error is not None:
        print(input_error, file=sys.stderr)
        return 1
    settings = get_settings()
    database_url = args.database_url or settings.database_url
    runtime_settings = (
        settings.model_copy(update={"database_url": args.database_url})
        if args.database_url
        else settings
    )
    engine = create_db_engine(database_url)
    prepare_runtime_schema(engine, runtime_settings)
    session_factory = create_session_factory(engine)
    source = _source(session_factory, args.mode)
    storage = LocalRawStorage(args.raw_storage_path or settings.raw_storage_path)
    try:
        if args.mode == "territories":
            official_url = args.url or settings.istat_municipalities_xlsx_url
            collector = IstatTerritoryCollector(
                official_url,
                fixture_path=args.fixture,
                timeout_seconds=(
                    args.timeout_seconds or settings.territorial_request_timeout_seconds
                ),
            )
            mapper = IstatTerritoryMapper()
            raw = TerritorialRawPipeline(
                session_factory, storage, collector, IstatTerritoryParser()
            ).run(source_id=source.id, source_key=source.key)
            regions, municipalities = mapper.map_records(
                raw.parsed.structured_records,
                source_key=source.key,
                raw_document_id=raw.raw_document_id,
                source_url=official_url,
            )
            sync = TerritoryService(session_factory).sync(regions, municipalities)
            summary = {
                "mode": args.mode,
                "input": "fixture" if args.fixture else "live",
                "raw_document_id": raw.raw_document_id,
                "change_detected": raw.change_detected,
                "storage_key": raw.storage_key,
                "regions_mapped": len(regions),
                "municipalities_mapped": len(municipalities),
                "sync": sync.model_dump(mode="json") if sync else None,
            }
        else:
            collector = DaitMayorCollector(
                args.url or settings.dait_current_mayors_csv_url,
                fixture_path=args.fixture,
                timeout_seconds=(
                    args.timeout_seconds or settings.territorial_request_timeout_seconds
                ),
            )
            with session_factory() as session:
                municipality_count = session.scalar(
                    select(func.count()).select_from(Municipality)
                ) or 0
            if municipality_count == 0:
                print(
                    "Office ingestion requires ISTAT territories first. "
                    "Run territories mode before offices.",
                    file=sys.stderr,
                )
                return 1
            raw = TerritorialRawPipeline(
                session_factory, storage, collector, DaitMayorParser()
            ).run(source_id=source.id, source_key=source.key)
            mapped = DaitMayorMapper(session_factory).map_records(
                raw.parsed.structured_records, document=raw.provenance
            )
            identity_results = tuple(
                HumanIdentityResolutionCoordinator(session_factory).process(candidate)
                for candidate in mapped.candidates
            )
            mandate_sync = TerritorialMandateService(session_factory).sync(
                mapped.mandates
            )
            unresolved_reasons: dict[str, int] = {}
            for item in mapped.unresolved_rows:
                unresolved_reasons[item.reason] = unresolved_reasons.get(item.reason, 0) + 1
            summary = {
                "mode": args.mode,
                "input": "fixture" if args.fixture else "live",
                "raw_document_id": raw.raw_document_id,
                "change_detected": raw.change_detected,
                "storage_key": raw.storage_key,
                "candidates_mapped": len(mapped.candidates),
                "mandates_mapped": len(mapped.mandates),
                "identity_cases": sum(
                    item.case is not None for item in identity_results
                ),
                "identity_cases_created": sum(
                    item.case is not None and item.case.created
                    for item in identity_results
                ),
                "unresolved_rows": {
                    "count": len(mapped.unresolved_rows),
                    "reasons": unresolved_reasons,
                    "samples": [asdict(item) for item in mapped.unresolved_rows[:5]],
                },
                "mandate_sync": (
                    None
                    if mandate_sync is None
                    else {
                        **mandate_sync.model_dump(mode="json"),
                        "details": [
                            item.model_dump(mode="json")
                            for item in mandate_sync.details[:5]
                        ],
                    }
                ),
            }
    except (CollectorError, ParserError, StorageError, ValueError, RuntimeError) as exc:
        print(f"Territorial ingestion failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
