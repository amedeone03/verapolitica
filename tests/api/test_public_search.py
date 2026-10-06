from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import (
    Municipality,
    ParliamentaryGroup,
    PoliticalParty,
    Politician,
    PoliticianVersion,
    Proposal,
    ProposalType,
    RawDocument,
    RawDocumentStatus,
    Region,
    Source,
    TerritoryStatus,
)
from backend.app.schemas import PoliticalMandate, PoliticianVersionProfile
from backend.app.services import normalize_person_name


def _client(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'search-api.db'}"
    settings = Settings(
        database_url=database_url,
        raw_storage_path=tmp_path / "raw",
        admin_api_key="test-admin-secret",
    )
    engine = create_db_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        source = Source(key="search", name="Search", base_url="https://example.test")
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
            source_url="https://example.test/search",
            content_type="application/json",
            storage_key="search.json",
            raw_sha256="1" * 64,
            normalized_sha256="2" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="v1",
            parser_version="v1",
        )
        session.add(document)
        session.flush()
        politician = Politician(
            canonical_given_name="Anna",
            canonical_family_name="Rossi",
            normalized_name=normalize_person_name("Anna", "Rossi"),
            birth_date=date(1970, 1, 2),
        )
        session.add(politician)
        session.flush()
        version = PoliticianVersion(
            politician_id=politician.id,
            version_number=1,
            profile_schema_version=1,
            profile_data=PoliticianVersionProfile(
                given_name="Anna",
                family_name="Rossi",
                birth_date=date(1970, 1, 2),
                mandates=(
                    PoliticalMandate(
                        institution="Senato della Repubblica",
                        office="senator",
                        legislature="19",
                        mandate_type="elettivo",
                        start_date=date(2022, 10, 13),
                    ),
                ),
            ).model_dump(mode="json"),
            published_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
        )
        session.add(version)
        session.flush()
        politician.current_version_id = version.id
        region = Region(
            istat_code="03",
            canonical_name="Lombardia",
            status=TerritoryStatus.ACTIVE,
            source_id=source.id,
            raw_document_id=document.id,
            source_url="https://example.test/istat",
        )
        session.add(region)
        session.flush()
        session.add(
            Municipality(
                istat_code="015146",
                region_id=region.id,
                canonical_name="Milano",
                province_abbreviation="MI",
                province_name="Milano",
                status=TerritoryStatus.ACTIVE,
                source_id=source.id,
                raw_document_id=document.id,
                source_url="https://example.test/istat",
            )
        )
        session.add(
            Proposal(
                canonical_title="Synthetic housing transparency proposal",
                proposal_type=ProposalType.LEGISLATIVE_PROPOSAL,
                published_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
            )
        )
        session.add(
            ParliamentaryGroup(
                canonical_name="Fratelli d'Italia",
                abbreviation="FdI",
                institution="Senato della Repubblica",
                legislature="19",
            )
        )
        session.add(
            PoliticalParty(canonical_name="Demo Civic Alliance", abbreviation="DCA-SYN")
        )
        session.commit()
    engine.dispose()
    return TestClient(create_app(settings))


def test_public_search_api_and_filters(tmp_path):
    with _client(tmp_path) as client:
        anna = client.get("/search", params={"q": "Anna"})
        milano = client.get("/search", params={"q": "Milano", "type": "municipality"})
        group = client.get("/parliamentary-groups/1")
        party = client.get("/political-parties/1")
        empty = client.get("/search", params={"q": "   "})
        long_query = client.get("/search", params={"q": "x" * 201})
        bad_type = client.get("/search", params={"q": "Anna", "type": "draft"})
        bad_limit = client.get("/search", params={"q": "Anna", "limit": 200})

    assert anna.status_code == 200
    assert anna.json()["items"][0]["entity_type"] == "politician"
    assert anna.json()["items"][0]["url"] == "/app/?politician=1"
    assert milano.status_code == 200
    assert milano.json()["items"][0]["title"] == "Milano"
    assert group.status_code == 200
    assert group.json()["name"] == "Fratelli d'Italia"
    assert party.json()["name"] == "Demo Civic Alliance"
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "invalid_search_query"
    assert long_query.status_code == 422
    assert bad_type.status_code == 422
    assert bad_limit.status_code == 422


def test_search_does_not_expose_internal_tables(tmp_path):
    with _client(tmp_path) as client:
        payload = client.get("/search", params={"q": "Anna"}).json()
    blob = str(payload).casefold()
    assert "identity_resolution" not in blob
    assert "reviewer" not in blob
    assert "raw_document" not in blob
    assert "admin" not in blob
