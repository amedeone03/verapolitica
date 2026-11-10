"""Draft city/region timelines in Archivio (Verona and the attached Word drafts)."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.models import Municipality, RawDocument, RawDocumentStatus, Region, Source

NOW = datetime(2026, 11, 6, 9, tzinfo=timezone.utc)


def test_verona_timeline_is_a_draft_and_links_the_live_comune(tmp_path):
    url = f"sqlite:///{tmp_path / 'timelines.db'}"
    settings = Settings(database_url=url, raw_storage_path=tmp_path / "raw", admin_api_key="test-admin-secret")
    client = TestClient(create_app(settings))
    with client:
        factory = client.app.state.session_factory
        with factory() as session:
            source = Source(key="istat", name="ISTAT", base_url="https://www.istat.it")
            session.add(source)
            session.flush()
            document = RawDocument(
                source_id=source.id, retrieved_at=NOW, source_url="https://www.istat.it/comuni",
                content_type="text/csv", storage_key="test/comuni", raw_sha256="1" * 64,
                structured_records=[], normalized_text="x", process_status=RawDocumentStatus.PARSED,
                collector_version="t", parser_version="t",
            )
            session.add(document)
            session.flush()
            veneto = Region(
                istat_code="05", canonical_name="Veneto", source_id=source.id,
                raw_document_id=document.id, source_url="https://www.istat.it/regioni",
            )
            session.add(veneto)
            session.flush()
            town = Municipality(
                istat_code="023091", region_id=veneto.id, canonical_name="Verona",
                province_abbreviation="VR", province_name="Verona", source_id=source.id,
                raw_document_id=document.id, source_url="https://www.istat.it/comuni",
            )
            session.add(town)
            session.flush()
            verona_id, veneto_id = town.id, veneto.id
            session.commit()

        listing = client.get("/archive/timelines").json()
        assert "non verificate" in listing["disclaimer"].casefold()
        by_name = {item["name"]: item for item in listing["items"]}
        assert by_name["Verona"]["kind"] == "city"
        assert by_name["Verona"]["draft"] is True
        assert by_name["Verona"]["municipality_id"] == verona_id
        assert by_name["Verona"]["province_abbreviation"] == "VR"
        assert by_name["Veneto"]["kind"] == "region"
        assert by_name["Veneto"]["region_id"] == veneto_id
        cities = client.get("/archive/timelines?kind=city").json()
        assert "Verona" in [item["name"] for item in cities["items"]]
        assert all(item["kind"] == "city" for item in cities["items"])
        detail = client.get("/archive/timelines/verona").json()
        assert detail["mayor"] == "Damiano Tommasi"
        assert detail["municipality_id"] == verona_id
        assert any("Tommasi" in event["body"] for event in detail["events"])
        assert "non verificata" in detail["disclaimer"].casefold()
        assert client.get("/archive/timelines/narnia").status_code == 404
