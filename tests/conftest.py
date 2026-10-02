from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import Source  # noqa: F401 - registers all model metadata
from backend.app.storage import LocalRawStorage


@pytest.fixture
def session_factory(tmp_path) -> Iterator[sessionmaker[Session]]:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    yield factory
    engine.dispose()


@pytest.fixture
def source(session_factory) -> Source:
    with session_factory() as session:
        source = Source(
            key="senato-repubblica",
            name="Senato della Repubblica",
            base_url="https://dati.senato.it",
        )
        session.add(source)
        session.commit()
        session.refresh(source)
        return source


@pytest.fixture
def raw_storage(tmp_path) -> LocalRawStorage:
    return LocalRawStorage(tmp_path / "raw")
