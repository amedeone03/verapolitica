from datetime import datetime, timezone

from sqlalchemy import select

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models.pledge import PledgeAssessment
from backend.app.services.redazione.service import RedazioneService
from scripts.seed_meloni_showcase import seed as seed_meloni
from scripts.seed_rdc_verdict import EXCERPT, seed
from tests.scripts.test_seed_meloni_showcase import _publish_meloni


def test_rdc_verdict_uses_the_gazzetta_excerpt(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'rdc.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    _publish_meloni(factory)
    service = RedazioneService(factory, clock=lambda: datetime(2026, 11, 3, tzinfo=timezone.utc))
    seed_meloni(service, factory, author="Amedeo", approver="Verificatore")

    first = seed(service, factory, author="Amedeo", approver="Verificatore")
    again = seed(service, factory, author="Amedeo", approver="Verificatore")

    assert first.errors == []
    assert "stato mantenuta" in first.published[0]
    assert again.skipped
    with factory() as session:
        row = session.scalar(select(PledgeAssessment))
        assert row is not None
        assert row.verdict.value == "kept"
        assert row.quoted_excerpt == EXCERPT
        assert "gazzettaufficiale.it" in row.source_url
    engine.dispose()
