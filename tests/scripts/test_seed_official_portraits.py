from datetime import date, datetime, timezone

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import Politician, PoliticianVersion
from backend.app.services import normalize_person_name
from scripts.seed_official_portraits import seed


def test_official_portraits_use_governo_image_url_only(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'portraits.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with factory() as session:
        minister = Politician(
            canonical_given_name="Giorgia",
            canonical_family_name="Meloni",
            normalized_name=normalize_person_name("Giorgia", "Meloni"),
            birth_date=date(1977, 1, 15),
        )
        deputy = Politician(
            canonical_given_name="Mario",
            canonical_family_name="Rossi",
            normalized_name=normalize_person_name("Mario", "Rossi"),
            birth_date=date(1970, 1, 1),
        )
        session.add_all((minister, deputy))
        session.flush()
        minister_version = PoliticianVersion(
            politician_id=minister.id,
            version_number=1,
            profile_schema_version=1,
            profile_data={
                "given_name": "Giorgia",
                "family_name": "Meloni",
                "image_url": "https://www.governo.it/meloni.jpg",
                "official_homepage_url": "https://www.governo.it/it/presidente",
                "mandates": [
                    {
                        "institution": "Presidenza del Consiglio",
                        "office": "Presidente del Consiglio",
                        "legislature": "Governo Meloni",
                        "mandate_type": "Presidente del Consiglio dei Ministri",
                        "start_date": "2022-10-21",
                    }
                ],
            },
            published_at=now,
        )
        deputy_version = PoliticianVersion(
            politician_id=deputy.id,
            version_number=1,
            profile_schema_version=1,
            profile_data={
                "given_name": "Mario",
                "family_name": "Rossi",
                "image_url": "https://documenti.camera.it/rossi.jpg",
                "mandates": [
                    {
                        "institution": "Camera dei Deputati",
                        "office": "deputy",
                        "legislature": "19",
                        "mandate_type": "elezione",
                        "start_date": "2022-10-13",
                    }
                ],
            },
            published_at=now,
        )
        session.add_all((minister_version, deputy_version))
        session.flush()
        minister.current_version_id = minister_version.id
        deputy.current_version_id = deputy_version.id
        session.commit()
        minister_id = minister.id

    path = tmp_path / "portraits.json"
    report = seed(factory, path)
    assert report.official == 1
    assert report.commons == 0
    assert str(minister_id) in path.read_text(encoding="utf-8")
    assert "rossi.jpg" not in path.read_text(encoding="utf-8")
    engine.dispose()
