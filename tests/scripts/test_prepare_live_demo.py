from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from scripts.prepare_live_demo import prepare


def test_prepare_live_demo_refuses_same_author_and_approver(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    try:
        prepare(
            factory,
            author="Amedeo",
            approver="Amedeo",
            party_approver="Direzione",
            portraits_path=None,
            raw_storage=tmp_path / "raw",
        )
    except ValueError as error:
        assert "diverso" in str(error)
    else:
        raise AssertionError("expected author and approver to differ")
    engine.dispose()


def test_prepare_live_demo_runs_without_resetting_when_the_archive_is_empty(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    report = prepare(
        factory,
        author="Amedeo",
        approver="Verificatore",
        party_approver="Direzione",
        portraits_path=tmp_path / "portraits.json",
        raw_storage=tmp_path / "raw",
        get=lambda url: b'{"results":{"bindings":[]}}',
    )
    assert report.meloni["errors"]
    assert report.parties["unmatched"]
    engine.dispose()
