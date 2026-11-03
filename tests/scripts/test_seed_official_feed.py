from datetime import datetime, timezone

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    EditorialPost,
    EditorialPostStatus,
    Politician,
    PoliticianVersion,
    RawDocument,
    RawDocumentStatus,
    Region,
    Source,
)
from backend.app.services.matching_service import normalize_person_name
from backend.app.models.territory import TerritoryStatus
from backend.app.services.redazione.service import RedazioneService
from scripts.seed_official_feed import CARDS, seed
from sqlalchemy import func, select


def test_official_feed_cards_use_only_institutional_pages_and_are_idempotent(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'feed.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    service = RedazioneService(factory, clock=lambda: datetime(2026, 11, 3, tzinfo=timezone.utc))

    first = seed(service, factory, author="Sincronizzazione fonti ufficiali", approver="Verificatore")
    national = [card for card in CARDS if card.scope == "national"]
    assert first.published == [card.title for card in national]
    assert any("Lazio" in line for line in first.skipped)
    assert first.errors == []
    with factory() as session:
        posts = list(session.scalars(select(EditorialPost)))
        assert len(posts) == 4
        assert {post.status for post in posts} == {EditorialPostStatus.PUBLISHED}
        urls = {item["url"] for post in posts for item in post.citations}
        assert urls == {card.source_url for card in national}
        assert all((post.blocks or {}).get("card", {}).get("category") == "pubblicazione" for post in posts)

    again = seed(service, factory, author="Sincronizzazione fonti ufficiali", approver="Verificatore")
    assert again.published == []
    assert len(again.skipped) == 5
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(EditorialPost)) == 4
    engine.dispose()


def test_lazio_official_card_uses_the_istat_region(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'lazio.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with factory() as session:
        source = Source(key="istat-territories", name="ISTAT", base_url="https://www.istat.it")
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=now,
            source_url="https://www.istat.it",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            storage_key="istat/fixture.bin",
            raw_sha256="a" * 64,
            process_status=RawDocumentStatus.PARSED,
            collector_version="istat_v1",
            parser_version="istat_v1",
        )
        session.add(document)
        session.flush()
        session.add(
            Region(
                istat_code="12",
                canonical_name="Lazio",
                status=TerritoryStatus.ACTIVE,
                source_id=source.id,
                raw_document_id=document.id,
                source_url="https://www.istat.it",
            )
        )
        session.commit()
    service = RedazioneService(factory, clock=lambda: now)
    lazio = next(card for card in CARDS if card.region_name == "Lazio")
    report = seed(service, factory, author="Amedeo", approver="Verificatore", cards=(lazio,))
    assert report.published == [lazio.title]
    with factory() as session:
        post = session.scalar(select(EditorialPost))
        assert post is not None
        assert post.scope.value == "region"
        assert post.region_id is not None
    engine.dispose()


def test_meloni_curriculum_card_is_tagged_when_she_is_published(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'follow.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with factory() as session:
        politician = Politician(
            canonical_given_name="Giorgia",
            canonical_family_name="Meloni",
            normalized_name=normalize_person_name("Giorgia", "Meloni"),
            birth_date=datetime(1977, 1, 15).date(),
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
        politician_id = politician.id
    service = RedazioneService(factory, clock=lambda: now)
    card = next(item for item in CARDS if "curriculum" in item.source_url)
    report = seed(service, factory, author="Amedeo", approver="Verificatore", cards=(card,))
    assert report.published == [card.title]
    with factory() as session:
        post = session.scalar(select(EditorialPost))
        assert politician_id in (post.blocks or {}).get("politician_ids", [])
    engine.dispose()
