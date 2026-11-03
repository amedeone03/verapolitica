from datetime import date, datetime, timezone

from sqlalchemy import select

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import EditorialPost, Politician, PoliticianVersion
from backend.app.services import normalize_person_name
from backend.app.services.redazione.service import RedazioneService
from backend.app.services.redazione.style import has_errors, news_findings
from scripts.seed_official_notizia import BLOCKS, TITLE, seed


def _publish_meloni(factory):
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with factory() as session:
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
            profile_data={"given_name": "Giorgia", "family_name": "Meloni", "mandates": []},
            published_at=now,
        )
        session.add(version)
        session.flush()
        politician.current_version_id = version.id
        session.commit()
        return politician.id


def test_notizia_payload_has_no_blocking_findings():
    findings = news_findings(
        {
            "title": TITLE,
            "blocks": BLOCKS,
            "sources": [
                {"name": "Senato", "url": "https://www.senato.it/show-doc?id=1361012&leg=19&tipodoc=Resaula", "area": "istituzionale"},
                {"name": "Sky", "url": "https://tg24.sky.it/politica/2025/10/18/manovra-meloni", "area": "centrodestra"},
                {"name": "Il Fatto", "url": "https://www.ilfattoquotidiano.it/2024/01/29/ius-soli-giuseppe-conte-a-che-tempo-che-fa-non-sono-favorevole-serve-lo-ius-scholae-e-lo-ius-culturae/7425636/", "area": "centrosinistra"},
            ],
            "card": {"category": "notizia"},
        }
    )
    assert not has_errors(findings)


def test_notizia_publishes_once_with_three_archived_urls(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'news.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    _publish_meloni(factory)
    service = RedazioneService(factory, clock=lambda: datetime(2026, 11, 3, tzinfo=timezone.utc))

    first = seed(service, factory, author="Amedeo", approver="Verificatore")
    again = seed(service, factory, author="Amedeo", approver="Verificatore")

    assert first.published == [TITLE]
    assert first.errors == []
    assert again.skipped
    with factory() as session:
        post = session.scalar(select(EditorialPost))
        assert post is not None
        assert post.published_at is not None
        urls = {item["url"] for item in (post.blocks or {}).get("fonti") or post.citations or []}
        assert "https://www.senato.it/show-doc?id=1361012&leg=19&tipodoc=Resaula" in urls
        assert "https://tg24.sky.it/politica/2025/10/18/manovra-meloni" in urls
    engine.dispose()
