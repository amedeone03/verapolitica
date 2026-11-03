from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import Politician, PoliticianVersion
from backend.app.services import normalize_person_name


def _person(session, given, family, office, *, start="2022-10-13"):
    politician = Politician(
        canonical_given_name=given,
        canonical_family_name=family,
        normalized_name=normalize_person_name(given, family),
        birth_date=date(1970, 1, 1),
    )
    session.add(politician)
    session.flush()
    version = PoliticianVersion(
        politician_id=politician.id,
        version_number=1,
        profile_schema_version=1,
        profile_data={
            "given_name": given,
            "family_name": family,
            "mandates": [
                {
                    "institution": "Governo Italiano" if office != "deputy" else "Camera dei Deputati",
                    "office": office,
                    "legislature": "19",
                    "mandate_type": office,
                    "start_date": start,
                    "end_date": None,
                    "election_area": None,
                }
            ],
        },
        published_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
    )
    session.add(version)
    session.flush()
    politician.current_version_id = version.id
    return politician.id


def test_list_role_governo_returns_cabinet_even_when_a_later_deputy_seat_exists(tmp_path):
    url = f"sqlite:///{tmp_path / 'gov.db'}"
    engine = create_db_engine(url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        deputy_id = _person(session, "Anna", "Bianchi", "deputy")
        minister_id = _person(session, "Guido", "Crosetto", "Ministro")
        both = Politician(
            canonical_given_name="Giorgia",
            canonical_family_name="Meloni",
            normalized_name=normalize_person_name("Giorgia", "Meloni"),
            birth_date=date(1977, 1, 15),
        )
        session.add(both)
        session.flush()
        version = PoliticianVersion(
            politician_id=both.id,
            version_number=1,
            profile_schema_version=1,
            profile_data={
                "given_name": "Giorgia",
                "family_name": "Meloni",
                "mandates": [
                    {
                        "institution": "Camera dei Deputati",
                        "office": "deputy",
                        "legislature": "19",
                        "mandate_type": "elezione",
                        "start_date": "2024-03-01",
                        "end_date": None,
                        "election_area": None,
                    },
                    {
                        "institution": "Presidenza del Consiglio",
                        "office": "Presidente del Consiglio",
                        "legislature": "Governo Meloni",
                        "mandate_type": "Presidente del Consiglio dei Ministri",
                        "start_date": "2022-10-21",
                        "end_date": None,
                        "election_area": None,
                    },
                ],
            },
            published_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
        )
        session.add(version)
        session.flush()
        both.current_version_id = version.id
        session.commit()
        both_id = both.id
    engine.dispose()

    settings = Settings(database_url=url, raw_storage_path=tmp_path / "raw")
    with TestClient(create_app(settings)) as client:
        all_people = client.get("/politicians?limit=100")
        cabinet = client.get("/politicians?role=governo&limit=100")
        bad = client.get("/politicians?role=senato")
    assert all_people.status_code == 200
    assert {item["id"] for item in all_people.json()["items"]} == {deputy_id, minister_id, both_id}
    assert cabinet.status_code == 200
    assert {item["id"] for item in cabinet.json()["items"]} == {minister_id, both_id}
    assert bad.status_code == 422
