from datetime import date, datetime, timezone

from sqlalchemy import select

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    Politician,
    PoliticianSourceIdentifier,
    PoliticianVersion,
    Proposal,
    ProposalActor,
    Source,
)
from backend.app.models.politician_profile import PoliticianBiography, PoliticianCareerEntry, ProfileContentStatus
from backend.app.services import normalize_person_name
from backend.app.services.redazione.service import RedazioneService
from scripts.seed_meloni_showcase import seed


def _publish_meloni(factory) -> int:
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with factory() as session:
        source = Source(key="governo-italiano", name="Governo Italiano", base_url="https://www.governo.it")
        session.add(source)
        session.flush()
        politician = Politician(
            canonical_given_name="Giorgia",
            canonical_family_name="Meloni",
            normalized_name=normalize_person_name("Giorgia", "Meloni"),
            birth_date=date(1977, 1, 15),
        )
        session.add(politician)
        session.flush()
        version = PoliticianVersion(
            politician_id=politician.id,
            version_number=1,
            profile_schema_version=1,
            profile_data={
                "given_name": "Giorgia",
                "family_name": "Meloni",
                "mandates": [
                    {
                        "institution": "Presidenza del Consiglio dei Ministri",
                        "office": "presidente del consiglio",
                        "legislature": "Governo Meloni",
                        "mandate_type": "Presidente del Consiglio dei Ministri",
                        "start_date": "2022-10-21",
                        "end_date": None,
                        "election_area": None,
                    }
                ],
            },
            published_at=now,
        )
        session.add(version)
        session.flush()
        politician.current_version_id = version.id
        session.add(
            PoliticianSourceIdentifier(
                politician_id=politician.id,
                source_id=source.id,
                value="https://www.governo.it/it/presidente",
            )
        )
        session.commit()
        return politician.id


def test_meloni_showcase_publishes_bio_career_and_one_promise(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'meloni.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    politician_id = _publish_meloni(factory)
    service = RedazioneService(factory, clock=lambda: datetime(2026, 11, 3, tzinfo=timezone.utc))

    first = seed(service, factory, author="Amedeo", approver="Verificatore")
    assert first.politician_id == politician_id
    assert first.errors == []
    assert "chi è" in first.published
    assert "incarico 2008–2011" in first.published
    assert "promessa reddito di cittadinanza" in first.published

    with factory() as session:
        bio = session.scalar(
            select(PoliticianBiography).where(
                PoliticianBiography.politician_id == politician_id,
                PoliticianBiography.status == ProfileContentStatus.PUBLISHED,
            )
        )
        career = session.scalar(
            select(PoliticianCareerEntry).where(
                PoliticianCareerEntry.politician_id == politician_id,
                PoliticianCareerEntry.identity_key == "ministra-gioventu-2008",
                PoliticianCareerEntry.status == ProfileContentStatus.PUBLISHED,
            )
        )
        promise = session.scalar(select(Proposal).join(ProposalActor))
        assert bio is not None and "ottobre 2022" in bio.body
        assert career is not None and career.institution == "Governo Berlusconi IV"
        assert promise is not None
        assert promise.published_at is not None
        assert "Reddito di cittadinanza" in promise.canonical_title

    again = seed(service, factory, author="Amedeo", approver="Verificatore")
    assert again.published == []
    assert len(again.skipped) == 3
    engine.dispose()


def test_meloni_showcase_refuses_same_author_and_approver(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'same.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    service = RedazioneService(factory)
    try:
        seed(service, factory, author="Amedeo", approver="Amedeo")
    except ValueError as error:
        assert "diverso" in str(error)
    else:
        raise AssertionError("expected author and approver to differ")
    engine.dispose()
