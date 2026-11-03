from datetime import date, datetime, timezone

from sqlalchemy import select

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    PoliticalParty,
    PoliticalPartyAffiliation,
    Politician,
    PoliticianSourceIdentifier,
    PoliticianVersion,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.services import normalize_person_name
from scripts.seed_party_affiliations import seed


def _publish(factory, given, family, *, party_name, identifier):
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with factory() as session:
        source = session.scalar(select(Source).where(Source.key == "governo-italiano"))
        if source is None:
            source = Source(
                key="governo-italiano",
                name="Governo Italiano",
                base_url="https://www.governo.it",
            )
            session.add(source)
            session.flush()
            session.add(
                RawDocument(
                    source_id=source.id,
                    retrieved_at=now,
                    source_url="https://www.governo.it/it/ministri-e-sottosegretari",
                    content_type="application/json",
                    storage_key="governo/parties.json",
                    raw_sha256="a" * 64,
                    normalized_sha256="b" * 64,
                    structured_records=[],
                    process_status=RawDocumentStatus.PARSED,
                    change_detected=True,
                    collector_version="t",
                    parser_version="t",
                )
            )
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
            profile_data={"given_name": given, "family_name": family, "mandates": []},
            published_at=now,
        )
        session.add(version)
        session.flush()
        politician.current_version_id = version.id
        session.add(
            PoliticianSourceIdentifier(
                politician_id=politician.id,
                source_id=source.id,
                value=identifier,
            )
        )
        if session.scalar(select(PoliticalParty).where(PoliticalParty.canonical_name == party_name)) is None:
            session.add(
                PoliticalParty(
                    canonical_name=party_name,
                    abbreviation=party_name[:3],
                    official_website_url=f"https://www.example.org/{party_name.replace(' ', '-').lower()}",
                )
            )
        session.commit()
        return politician.id


def test_affiliations_land_on_published_schede(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'parties.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    _publish(
        factory,
        "Giorgia",
        "Meloni",
        party_name="Fratelli d'Italia",
        identifier="https://www.governo.it/it/presidente",
    )

    first = seed(factory)
    again = seed(factory)

    assert first.created == ["Giorgia Meloni → Fratelli d'Italia"]
    assert first.errors == []
    assert any("già presente" in item for item in again.skipped)
    with factory() as session:
        row = session.scalar(select(PoliticalPartyAffiliation))
        assert row is not None
        assert row.source_url == "https://www.governo.it/it/presidente"
    engine.dispose()


def test_affiliations_match_camera_civil_name_for_schlein(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'schlein.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    _publish(
        factory,
        "Elena Ethel",
        "Schlein",
        party_name="Partito Democratico",
        identifier="https://www.camera.it/leg19/29?shadow_deputato=307427",
    )

    report = seed(factory)

    assert "Elly Schlein → Partito Democratico" in report.created
    assert report.errors == []
    engine.dispose()


def test_affiliations_skip_when_the_catalog_party_is_missing(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    report = seed(factory)
    assert report.created == []
    assert any("scheda pubblica assente" in item for item in report.skipped)
    engine.dispose()
