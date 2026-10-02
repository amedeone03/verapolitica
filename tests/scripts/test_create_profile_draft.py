import json
from datetime import date, datetime, timezone

from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    Evidence,
    Politician,
    PoliticianSourceIdentifier,
    ProfileDraft,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.services import normalize_person_name
from scripts import create_profile_draft


def parsed_record() -> dict[str, str | None]:
    return {
        "senator_uri": "https://dati.senato.it/senatore/100",
        "first_name": "Maria",
        "last_name": "Rossi",
        "gender": "F",
        "birth_date": "1970-01-02",
        "birth_city": "Roma",
        "birth_province": "RM",
        "birth_country": "Italia",
        "profession": "Avvocata",
        "photo_url": None,
        "homepage": "https://example.test/profile",
        "mandate_uri": "https://dati.senato.it/mandato/100",
        "mandate_type": "elettivo",
        "mandate_start": "2022-10-13",
        "legislature": "19",
        "election_region": "Lazio",
    }


def setup_database(tmp_path, *, with_politician: bool):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'draft-cli.db'}",
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
            storage_key="senato/test.json",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[parsed_record()],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="senato_collector_v1",
            parser_version="senato_parser_v1",
        )
        session.add(document)
        if with_politician:
            politician = Politician(
                canonical_given_name="Maria",
                canonical_family_name="Rossi",
                normalized_name=normalize_person_name("Maria", "Rossi"),
                birth_date=date(1970, 1, 2),
            )
            politician.source_identifiers.append(
                PoliticianSourceIdentifier(
                    source_id=source.id,
                    value="https://dati.senato.it/senatore/100",
                )
            )
            session.add(politician)
        session.commit()
        document_id = document.id
    engine.dispose()
    return settings, document_id


def counts(settings) -> tuple[int, int]:
    engine = create_db_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        result = (
            session.scalar(select(func.count()).select_from(ProfileDraft)),
            session.scalar(select(func.count()).select_from(Evidence)),
        )
    engine.dispose()
    return result


def test_cli_creates_one_initial_draft_and_prints_json(tmp_path, monkeypatch, capsys):
    settings, document_id = setup_database(tmp_path, with_politician=True)
    monkeypatch.setattr(create_profile_draft, "get_settings", lambda: settings)

    exit_code = create_profile_draft.main(
        [
            "--raw-document-id",
            str(document_id),
            "--candidate-index",
            "0",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "draft_created"
    assert payload["kind"] == "initial"
    assert payload["baseline_version_id"] is None
    assert payload["evidence_count"] > 0
    assert counts(settings) == (1, payload["evidence_count"])


def test_cli_refuses_candidate_without_one_match(tmp_path, monkeypatch, capsys):
    settings, document_id = setup_database(tmp_path, with_politician=False)
    monkeypatch.setattr(create_profile_draft, "get_settings", lambda: settings)

    exit_code = create_profile_draft.main(
        [
            "--raw-document-id",
            str(document_id),
            "--candidate-index",
            "0",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["error_type"] == "CandidateNotMatchedError"
    assert payload["matching_result"]["status"] == "new"
    assert counts(settings) == (0, 0)
