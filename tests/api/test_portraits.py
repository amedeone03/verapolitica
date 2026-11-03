from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import Politician, PoliticianVersion
from backend.app.services import normalize_person_name


def test_portraits_include_published_official_https_photos(tmp_path):
    database = tmp_path / "portraits.db"
    engine = create_db_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with factory() as session:
        person = Politician(
            canonical_given_name="GIUSEPPE",
            canonical_family_name="CONTE",
            normalized_name=normalize_person_name("Giuseppe", "Conte"),
            birth_date=date(1964, 8, 8),
        )
        session.add(person)
        session.flush()
        version = PoliticianVersion(
            politician_id=person.id,
            version_number=1,
            profile_schema_version=1,
            profile_data={
                "given_name": "GIUSEPPE",
                "family_name": "CONTE",
                "image_url": "http://www.senato.it/leg/19/BGT/Schede/Attsen/conte.jpg",
            },
            published_at=now,
        )
        session.add(version)
        session.flush()
        person.current_version_id = version.id
        session.commit()
        politician_id = str(person.id)
    engine.dispose()

    settings = Settings(database_url=f"sqlite:///{database}")
    with TestClient(create_app(settings)) as client:
        body = client.get("/portraits").json()

    assert politician_id in body
    assert body[politician_id]["url"] == "https://www.senato.it/leg/19/BGT/Schede/Attsen/conte.jpg"
    assert body[politician_id]["origin"] == "Fonte ufficiale"
