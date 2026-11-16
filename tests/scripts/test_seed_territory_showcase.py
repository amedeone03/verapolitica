"""Showcase territory seed is idempotent and publishes utile/promesse blocks."""

from datetime import datetime, timezone

from sqlalchemy import select

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    Municipality,
    RawDocument,
    RawDocumentStatus,
    Region,
    Source,
    TerritoryBlock,
    TerritoryBlockStatus,
)
from backend.app.models.territory import TerritoryStatus
from backend.app.services.redazione.service import RedazioneService
from scripts.seed_territory_showcase import ShowcaseBlock, seed


NOW = datetime(2026, 11, 6, 9, tzinfo=timezone.utc)
ISTAT = "https://demo.istat.it/app/?i=POS&l=it&a=2026"


def _factory(tmp_path):
    url = f"sqlite:///{tmp_path / 'showcase.db'}"
    engine = create_db_engine(url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        source = Source(key="istat", name="ISTAT", base_url="https://www.istat.it")
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=NOW,
            source_url="https://www.istat.it/comuni",
            content_type="text/csv",
            storage_key="test/comuni",
            raw_sha256="0" * 64,
            structured_records=[],
            normalized_text="x",
            process_status=RawDocumentStatus.PARSED,
            collector_version="t",
            parser_version="t",
        )
        session.add(document)
        session.flush()
        liguria = Region(
            istat_code="07",
            canonical_name="Liguria",
            status=TerritoryStatus.ACTIVE,
            source_id=source.id,
            raw_document_id=document.id,
            source_url="https://www.istat.it/regioni",
        )
        session.add(liguria)
        session.flush()
        roma = Municipality(
            istat_code="058091",
            region_id=liguria.id,
            canonical_name="Roma",
            province_abbreviation="RM",
            province_name="Roma",
            status=TerritoryStatus.ACTIVE,
            source_id=source.id,
            raw_document_id=document.id,
            source_url="https://www.istat.it/comuni",
        )
        session.add(roma)
        session.commit()
    return factory, RedazioneService(factory, leads=frozenset({"Verificatore"}))


def test_seed_publishes_and_skips_second_run(tmp_path):
    factory, service = _factory(tmp_path)
    items = (
        ShowcaseBlock(
            "region",
            "Liguria",
            "utile",
            {
                "cosa_conta_1": "Sanità e trasporti regionali.",
                "cosa_conta_2": "Atti sul sito istituzionale.",
                "cosa_conta_3": "Consiglio regionale.",
                "poteri": "Competenze regionali costituzionali.",
                "sources": [{"name": "ISTAT", "url": ISTAT}],
            },
        ),
        ShowcaseBlock(
            "municipio",
            "roma-1",
            "utile",
            {
                "cosa_conta_1": "Centro storico.",
                "cosa_conta_2": "Giunta municipale.",
                "cosa_conta_3": "Atti su comune.roma.it.",
                "poteri": "Funzioni delegate.",
                "sources": [{"name": "Roma Capitale", "url": "https://www.comune.roma.it/web/it/municipi.page"}],
            },
        ),
    )
    first = seed(service, factory, author="Amedeo", approver="Verificatore", items=items)
    assert first.published == ["region/Liguria/utile", "municipio/roma-1/utile"]
    assert not first.errors
    second = seed(service, factory, author="Amedeo", approver="Verificatore", items=items)
    assert second.skipped and not second.published
    with factory() as session:
        rows = list(session.scalars(select(TerritoryBlock).where(TerritoryBlock.status == TerritoryBlockStatus.PUBLISHED)))
        assert len(rows) == 2
