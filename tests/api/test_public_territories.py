from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import (
    Politician,
    PoliticianVersion,
    RawDocument,
    RawDocumentStatus,
    Source,
    TerritorialOffice,
)
from backend.app.schemas import (
    MunicipalityObservation,
    PoliticianVersionProfile,
    RegionObservation,
    TerritorialMandateObservation,
)
from backend.app.services import (
    TerritorialMandateService,
    TerritoryService,
    normalize_person_name,
)


def public_territory_client(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'territories.db'}"
    settings = Settings(
        database_url=database_url,
        raw_storage_path=tmp_path / "raw",
        admin_api_key="test-admin-secret",
        admin_reviewer_identity="api-editor",
    )
    engine = create_db_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    observed_at = datetime(2026, 2, 21, tzinfo=timezone.utc)
    with factory() as session:
        source = Source(
            key="istat-territories",
            name="ISTAT territorial classifications",
            base_url="https://www.istat.it",
        )
        office_source = Source(
            key="dait-current-mayors",
            name="DAIT current mayors",
            base_url="https://dait.interno.gov.it",
        )
        session.add_all((source, office_source))
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=observed_at,
            source_url="https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.xlsx",
            content_type="application/xlsx",
            storage_key="istat/fixture.xlsx",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="fixture",
            parser_version="fixture",
        )
        office_document = RawDocument(
            source_id=office_source.id,
            retrieved_at=observed_at,
            source_url="https://dait.interno.gov.it/documenti/sindaciincarica.csv",
            content_type="text/csv",
            storage_key="dait/fixture.csv",
            raw_sha256="c" * 64,
            normalized_sha256="d" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="fixture",
            parser_version="fixture",
        )
        session.add_all((document, office_document))
        session.commit()
        document_id = document.id
        office_document_id = office_document.id

    TerritoryService(factory).sync(
        (
            RegionObservation(
                source_key="istat-territories",
                raw_document_id=document_id,
                istat_code="03",
                canonical_name="Lombardia",
                source_url="https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.xlsx",
            ),
            RegionObservation(
                source_key="istat-territories",
                raw_document_id=document_id,
                istat_code="12",
                canonical_name="Lazio",
                source_url="https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.xlsx",
            ),
        ),
        (
            MunicipalityObservation(
                source_key="istat-territories",
                raw_document_id=document_id,
                istat_code="015146",
                region_istat_code="03",
                canonical_name="Milano",
                province_abbreviation="MI",
                province_name="Milano",
                source_url="https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.xlsx",
            ),
            MunicipalityObservation(
                source_key="istat-territories",
                raw_document_id=document_id,
                istat_code="015003",
                region_istat_code="03",
                canonical_name="Abbiategrasso",
                province_abbreviation="MI",
                province_name="Milano",
                source_url="https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.xlsx",
            ),
            MunicipalityObservation(
                source_key="istat-territories",
                raw_document_id=document_id,
                istat_code="058091",
                region_istat_code="12",
                canonical_name="Roma",
                province_abbreviation="RM",
                province_name="Roma",
                source_url="https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.xlsx",
            ),
        ),
    )
    with factory() as session:
        politician = Politician(
            canonical_given_name="Maria",
            canonical_family_name="Rossi",
            normalized_name=normalize_person_name("Maria", "Rossi"),
            birth_date=date(1970, 1, 2),
        )
        session.add(politician)
        session.flush()
        version = PoliticianVersion(
            politician_id=politician.id,
            version_number=1,
            profile_schema_version=1,
            profile_data=PoliticianVersionProfile(
                given_name="Maria",
                family_name="Rossi",
                birth_date=date(1970, 1, 2),
                mandates=(),
            ).model_dump(mode="json"),
            published_at=observed_at,
        )
        session.add(version)
        session.flush()
        politician.current_version_id = version.id
        session.commit()
        politician_id = politician.id

    TerritorialMandateService(factory).sync(
        (
            TerritorialMandateObservation(
                source_key="dait-current-mayors",
                raw_document_id=office_document_id,
                office=TerritorialOffice.MAYOR,
                municipality_istat_code="015146",
                given_name="Maria",
                family_name="Rossi",
                birth_date=date(1970, 1, 2),
                source_identifier="record-1",
                start_date=date(2021, 10, 4),
                end_date=date(2024, 6, 9),
                source_url="https://dait.interno.gov.it/documenti/sindaciincarica.csv",
            ),
            TerritorialMandateObservation(
                source_key="dait-current-mayors",
                raw_document_id=office_document_id,
                office=TerritorialOffice.MAYOR,
                municipality_istat_code="015146",
                given_name="Maria",
                family_name="Rossi",
                birth_date=date(1970, 1, 2),
                source_identifier="record-2",
                start_date=date(2024, 6, 10),
                source_url="https://dait.interno.gov.it/documenti/sindaciincarica.csv",
            ),
        )
    )
    return TestClient(create_app(settings)), politician_id


def test_public_region_and_municipality_api_paginates_and_hides_internal_ids(tmp_path):
    client, politician_id = public_territory_client(tmp_path)
    with client:
        regions = client.get("/regions?offset=0&limit=1")
        municipalities = client.get("/municipalities?limit=1")
        lombardia_filter = client.get("/municipalities?region=1")
        missing = client.get("/regions/99")
        region = client.get("/regions/1")
        municipality = client.get("/municipalities/1")
        politician = client.get(f"/politicians/{politician_id}")

    assert regions.status_code == 200
    payload = regions.json()
    assert payload["total"] == 2
    assert payload["limit"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["name"] == "Lazio"
    assert payload["items"][0]["current_president"] is None
    assert "identity_key" not in str(payload)
    assert municipalities.json()["total"] == 3
    assert len(municipalities.json()["items"]) == 1
    assert lombardia_filter.json()["total"] == 2
    assert missing.status_code == 404
    assert region.json()["municipality_count"] == 2
    assert municipality.json()["current_mayor"]["politician_id"] == politician_id
    offices = politician.json()["territorial_offices"]
    assert [item["end_date"] for item in offices] == [None, "2024-06-09"]
    assert [item["start_date"] for item in offices] == ["2024-06-10", "2021-10-04"]
    assert offices[0]["office"] == "mayor"
    assert offices[0]["municipality"] == "Milano"
    assert "raw_document" not in politician.text
