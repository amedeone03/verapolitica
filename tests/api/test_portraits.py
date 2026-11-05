import base64
import json
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import Politician, PoliticianVersion
from backend.app.services import normalize_person_name
from backend.app.services.redazione.service import RedazioneConflict, RedazioneService, RedazioneValidation

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _person(factory, given: str, family: str, image_url: str | None = None) -> str:
    with factory() as session:
        person = Politician(
            canonical_given_name=given,
            canonical_family_name=family,
            normalized_name=normalize_person_name(given, family),
            birth_date=date(1964, 8, 8),
        )
        session.add(person)
        session.flush()
        profile = {"given_name": given, "family_name": family}
        if image_url:
            profile["image_url"] = image_url
        version = PoliticianVersion(
            politician_id=person.id, version_number=1, profile_schema_version=1,
            profile_data=profile, published_at=NOW,
        )
        session.add(version)
        session.flush()
        person.current_version_id = version.id
        session.commit()
        return str(person.id)


@pytest.fixture
def setup(tmp_path):
    database = tmp_path / "portraits.db"
    engine = create_db_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    yield database, factory, tmp_path
    engine.dispose()


def _propose_photo(service: RedazioneService, key: str, *, member: str = "Anna") -> int:
    image = service.upload_image({"data": base64.b64encode(JPEG).decode(), "credit": "Mario Bianchi"}, member=member)
    proposal = service.propose_symbol(
        {
            "kind": "politician", "key": key, "image_id": image["id"], "credit": "Mario Bianchi",
            "license": "cc-by-sa", "source_url": "https://commons.wikimedia.org/wiki/File:Esempio.jpg",
        },
        member=member,
    )
    return proposal["id"]


def test_photos_on_the_scheda_from_senato_are_never_shown(setup):
    database, factory, _ = setup
    conte = _person(factory, "GIUSEPPE", "CONTE", "http://www.senato.it/leg/19/BGT/Schede/Attsen/conte.jpg")
    with TestClient(create_app(Settings(database_url=f"sqlite:///{database}"))) as client:
        assert client.get("/portraits").json() == {}
        hits = client.get("/search", params={"q": "conte"}).json()["items"]
    person = next(item for item in hits if item["metadata"].get("id") == int(conte))
    assert "image_url" not in person["metadata"]


def test_existing_stored_photos_stay_and_outside_links_are_dropped(setup):
    database, factory, tmp_path = setup
    kept = _person(factory, "Giorgia", "Meloni")
    linked = _person(factory, "Elly", "Schlein")
    folder = tmp_path / "portraits"
    folder.mkdir()
    (folder / "054117f1fafd9e9177e7a44c.jpg").write_bytes(JPEG)
    portraits = tmp_path / "portraits.json"
    portraits.write_text(json.dumps({
        kept: {"url": "https://www.governo.it/meloni.jpg", "credit": "Governo Italiano", "license": "Ritratto",
               "source_url": "https://www.governo.it/", "origin": "Governo Italiano", "file": "054117f1fafd9e9177e7a44c.jpg"},
        linked: {"url": "https://www.camera.it/schlein.jpg", "credit": "Camera", "license": "Ritratto",
                 "source_url": "https://www.camera.it/", "origin": "Camera"},
    }), "utf-8")
    settings = Settings(database_url=f"sqlite:///{database}", portraits_path=portraits)
    with TestClient(create_app(settings)) as client:
        body = client.get("/portraits").json()
        assert body[kept]["url"] == f"/portraits/{kept}/image"
        assert client.get(body[kept]["url"]).content == JPEG
    assert linked not in body


def test_the_redazione_uploads_a_photo_and_a_second_member_approves_it(setup):
    database, factory, _ = setup
    person = _person(factory, "Giuseppe", "Conte")
    service = RedazioneService(factory)
    request_id = _propose_photo(service, person)
    with pytest.raises(RedazioneConflict):
        service.approve("change", request_id, member="Anna")
    with TestClient(create_app(Settings(database_url=f"sqlite:///{database}"))) as client:
        assert client.get("/portraits").json() == {}

    service.approve("change", request_id, member="Luca")
    with TestClient(create_app(Settings(database_url=f"sqlite:///{database}"))) as client:
        photo = client.get("/portraits").json()[person]
        assert photo["url"].startswith("/media/")
        assert photo["license"] == "CC BY-SA"
        assert photo["origin"] == "Redazione VeraPolitica"
        assert client.get(photo["url"]).content == JPEG
    listed = next(item for item in service.symbols()["politician"] if item["key"] == person)
    assert listed["symbol"]["approved_by"] == "Luca"


def test_a_photo_cannot_claim_the_coat_of_arms_licence(setup):
    _, factory, _ = setup
    person = _person(factory, "Giuseppe", "Conte")
    service = RedazioneService(factory)
    image = service.upload_image({"data": base64.b64encode(JPEG).decode()}, member="Anna")
    with pytest.raises(RedazioneValidation):
        service.propose_symbol(
            {"kind": "politician", "key": person, "image_id": image["id"], "credit": "Camera",
             "license": "istituzionale", "source_url": "https://example.org/foto"},
            member="Anna",
        )
