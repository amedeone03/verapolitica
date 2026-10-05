import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import func, select

from backend.app.models import (
    Municipality,
    RawDocument,
    RawDocumentStatus,
    Region,
    Source,
)
from backend.app.pipeline.mappers import DaitMayorMapper, IstatTerritoryMapper
from backend.app.pipeline.parsers import DaitMayorParser, IstatTerritoryParser
from backend.app.schemas import SourceDocumentProvenance
from backend.app.services import TerritoryService


FIXTURES = Path(__file__).parents[1] / "fixtures" / "territorial"


def istat_xlsx_bytes() -> bytes:
    rows = json.loads((FIXTURES / "istat_rows.json").read_text())
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Elenco dei comuni italiani"])
    sheet.append([])
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def add_document(session_factory, key: str, content_type: str) -> tuple[Source, int]:
    with session_factory() as session:
        source = Source(key=key, name=key, base_url="https://example.test")
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=datetime.now(timezone.utc),
            source_url="https://example.test/data",
            content_type=content_type,
            storage_key=f"{key}/fixture",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="fixture",
            parser_version="fixture",
        )
        session.add(document)
        session.commit()
        session.refresh(source)
        session.refresh(document)
        return source, document.id


def test_istat_xlsx_parser_and_flexible_header_mapper_are_read_only(session_factory):
    parsed = IstatTerritoryParser().parse(istat_xlsx_bytes())
    source, document_id = add_document(
        session_factory,
        "istat-territories",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    before = 0
    regions, municipalities = IstatTerritoryMapper().map_records(
        parsed.structured_records,
        source_key=source.key,
        raw_document_id=document_id,
        source_url="https://example.test/istat.xlsx",
    )
    with session_factory() as session:
        after = session.scalar(select(func.count()).select_from(Municipality))
    assert before == after == 0
    assert [(item.istat_code, item.canonical_name) for item in regions] == [
        ("03", "Lombardia"),
        ("12", "Lazio"),
    ]
    assert municipalities[0].istat_code == "015146"
    assert municipalities[1].province_abbreviation == "RM"


def test_dait_parser_maps_only_exact_three_part_territory_and_exposes_unresolved(
    session_factory,
):
    istat_source, istat_document_id = add_document(
        session_factory, "istat-territories", "application/xlsx"
    )
    parsed_istat = IstatTerritoryParser().parse(istat_xlsx_bytes())
    regions, municipalities = IstatTerritoryMapper().map_records(
        parsed_istat.structured_records,
        source_key=istat_source.key,
        raw_document_id=istat_document_id,
        source_url="https://example.test/istat.xlsx",
    )
    TerritoryService(session_factory).sync(regions, municipalities)
    dait_source, dait_document_id = add_document(
        session_factory, "dait-current-mayors", "text/csv"
    )
    csv_bytes = (FIXTURES / "dait_mayors.csv").read_bytes()
    parsed = DaitMayorParser().parse(csv_bytes)
    provenance = SourceDocumentProvenance(
        source_key=dait_source.key,
        raw_document_id=dait_document_id,
        source_url="https://example.test/dait.csv",
        retrieved_at=datetime.now(timezone.utc),
        raw_sha256="c" * 64,
        normalized_sha256="d" * 64,
        collector_version="fixture",
        parser_version=parsed.parser_version,
    )
    mapped = DaitMayorMapper(session_factory).map_records(
        parsed.structured_records, document=provenance
    )
    assert len(mapped.candidates) == len(mapped.mandates) == 2
    assert {item.municipality_istat_code for item in mapped.mandates} == {
        "015146",
        "058091",
    }
    assert mapped.candidates[0].identity.birth_date.isoformat() == "1970-01-02"
    assert mapped.candidates[1].identity.birth_date is None
    assert len(mapped.unresolved_rows) == 1
    assert mapped.unresolved_rows[0].reason == "territory_not_found"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Region)) == 2
        assert session.scalar(select(func.count()).select_from(Municipality)) == 2
