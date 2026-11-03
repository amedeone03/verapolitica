from datetime import date, datetime, timezone

from sqlalchemy import select

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    Politician,
    PoliticianSourceIdentifier,
    PoliticianVersion,
    Proposal,
    Source,
)
from backend.app.models.politician_profile import PoliticianBiography, PoliticianCareerEntry, ProfileContentStatus
from backend.app.services import normalize_person_name
from backend.app.services.redazione.service import RedazioneService
from scripts.seed_opposition_showcase import seed


def _publish(factory, given, family, identifier):
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with factory() as session:
        source = session.scalar(select(Source).where(Source.key == "camera-deputati"))
        if source is None:
            source = Source(key="camera-deputati", name="Camera", base_url="https://www.camera.it")
            session.add(source)
            session.flush()
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
        session.commit()
        return politician.id


def test_opposition_showcase_uses_only_complete_fixture_urls(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'opp.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    schlein_id = _publish(factory, "Elly", "Schlein", "deputato:schlein")
    conte_id = _publish(factory, "Giuseppe", "Conte", "deputato:conte")
    service = RedazioneService(factory, clock=lambda: datetime(2026, 11, 3, tzinfo=timezone.utc))

    first = seed(service, factory, author="Amedeo", approver="Verificatore")
    assert first.errors == []
    assert first.schlein.politician_id == schlein_id
    assert first.conte.politician_id == conte_id
    assert "incarico A.C. 1741" in first.schlein.published
    assert "promessa sanità A.C. 1741" in first.schlein.published
    assert "chi è" in first.conte.published
    assert "incarico Conte I" in first.conte.published

    with factory() as session:
        career = session.scalar(
            select(PoliticianCareerEntry).where(
                PoliticianCareerEntry.politician_id == schlein_id,
                PoliticianCareerEntry.status == ProfileContentStatus.PUBLISHED,
            )
        )
        bio = session.scalar(
            select(PoliticianBiography).where(
                PoliticianBiography.politician_id == conte_id,
                PoliticianBiography.status == ProfileContentStatus.PUBLISHED,
            )
        )
        promise = session.scalar(
            select(Proposal).where(Proposal.canonical_title == "Finanziamento della sanità pubblica")
        )
        assert career is not None and "A.C. 1741" in career.role
        assert bio is not None and "Giuseppe Conte" in bio.body
        assert promise is not None and promise.published_at is not None

    again = seed(service, factory, author="Amedeo", approver="Verificatore")
    assert again.schlein.published == []
    assert again.conte.published == []
    engine.dispose()
