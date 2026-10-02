import json
from datetime import date, datetime, timezone

from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    Politician,
    PoliticianVersion,
    ProfileDraft,
    ProfileDraftKind,
    ProfileDraftStatus,
    RawDocument,
    RawDocumentStatus,
    Review,
    Source,
)
from backend.app.services import normalize_person_name
from scripts import review_profile_draft


def profile_data(name: str) -> dict:
    return {
        "given_name": name,
        "family_name": "Rossi",
        "birth_date": "1970-01-02",
        "birth_place": None,
        "gender": None,
        "profession": None,
        "image_url": None,
        "official_homepage_url": None,
        "mandates": [],
    }


def setup_database(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'review-cli.db'}",
        raw_storage_path=tmp_path / "raw",
    )
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        source = Source(
            key="senato-repubblica",
            name="Senato della Repubblica",
            base_url="https://dati.senato.it",
        )
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
            source_url="https://dati.senato.it/sparql",
            content_type="application/json",
            storage_key="senato/review-cli.json",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="senato_collector_v1",
            parser_version="senato_parser_v1",
        )
        session.add(document)
        session.flush()

        draft_ids = []
        for name in ("Maria", "Luca"):
            politician = Politician(
                canonical_given_name=name,
                canonical_family_name="Rossi",
                normalized_name=normalize_person_name(name, "Rossi"),
                birth_date=date(1970, 1, 2),
            )
            session.add(politician)
            session.flush()
            draft = ProfileDraft(
                politician_id=politician.id,
                raw_document_id=document.id,
                kind=ProfileDraftKind.INITIAL,
                status=ProfileDraftStatus.PENDING,
                proposed_profile_data=profile_data(name),
                diff_data={"status": "initial", "changes": []},
            )
            session.add(draft)
            session.flush()
            draft_ids.append(draft.id)
        session.commit()
    engine.dispose()
    return settings, tuple(draft_ids)


def database_counts(settings):
    engine = create_db_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        result = (
            session.scalar(select(func.count()).select_from(PoliticianVersion)),
            session.scalar(select(func.count()).select_from(Review)),
        )
    engine.dispose()
    return result


def test_cli_approval_prints_publication_json_and_blocks_second_attempt(
    tmp_path, monkeypatch, capsys
):
    settings, (draft_id, _) = setup_database(tmp_path)
    monkeypatch.setattr(review_profile_draft, "get_settings", lambda: settings)

    first_exit = review_profile_draft.main(
        [
            "--draft-id",
            str(draft_id),
            "--approve",
            "--reviewer",
            "demo-editor",
        ]
    )
    first = json.loads(capsys.readouterr().out)

    assert first_exit == 0
    assert first["decision"] == "approved"
    assert first["created_version_id"] == first["current_version_id"]
    assert first["version_number"] == 1
    assert first["final_draft_status"] == "approved"

    second_exit = review_profile_draft.main(
        [
            "--draft-id",
            str(draft_id),
            "--approve",
            "--reviewer",
            "demo-editor",
        ]
    )
    second = json.loads(capsys.readouterr().err)

    assert second_exit == 2
    assert second["error_type"] == "DraftNotReviewableError"
    assert "approved" in second["error"]
    assert database_counts(settings) == (1, 1)


def test_cli_rejection_prints_json_and_creates_no_version(
    tmp_path, monkeypatch, capsys
):
    settings, (_, draft_id) = setup_database(tmp_path)
    monkeypatch.setattr(review_profile_draft, "get_settings", lambda: settings)

    exit_code = review_profile_draft.main(
        [
            "--draft-id",
            str(draft_id),
            "--reject",
            "--reviewer",
            "demo-editor",
            "--note",
            "Evidence requires clarification",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["decision"] == "rejected"
    assert payload["created_version_id"] is None
    assert payload["version_number"] is None
    assert payload["final_draft_status"] == "rejected"
    assert database_counts(settings) == (0, 1)
