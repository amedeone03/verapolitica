import json
from datetime import datetime, timezone

from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    Politician,
    PoliticianSourceIdentifier,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from scripts import bootstrap_politicians


def parsed_record(identifier: str = "100") -> dict[str, str | None]:
    return {
        "senator_uri": f"https://dati.senato.it/senatore/{identifier}",
        "first_name": "Maria",
        "last_name": "Rossi",
        "gender": "F",
        "birth_date": "1970-01-02",
        "birth_city": "Roma",
        "birth_province": "Roma",
        "birth_country": "Italia",
        "profession": "Avvocata",
        "photo_url": None,
        "homepage": None,
        "mandate_uri": f"https://dati.senato.it/mandato/{identifier}",
        "mandate_type": "elettivo",
        "mandate_start": "2022-10-13",
        "legislature": "19",
        "election_region": "Lazio",
    }


def setup_database(tmp_path, records):
    database_path = tmp_path / "cli.db"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
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
            structured_records=records,
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="senato_collector_v1",
            parser_version="senato_parser_v1",
        )
        session.add(document)
        session.commit()
        document_id = document.id
    engine.dispose()
    return settings, factory, document_id


def database_counts(settings):
    engine = create_db_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        result = (
            session.scalar(select(func.count()).select_from(Politician)),
            session.scalar(
                select(func.count()).select_from(PoliticianSourceIdentifier)
            ),
        )
    engine.dispose()
    return result


def test_cli_dry_run_outputs_detailed_json_without_writes(
    tmp_path, monkeypatch, capsys
):
    settings, _, document_id = setup_database(tmp_path, [parsed_record()])
    monkeypatch.setattr(bootstrap_politicians, "get_settings", lambda: settings)

    exit_code = bootstrap_politicians.main(
        ["--dry-run", "--raw-document-id", str(document_id)]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["new_count"] == 1
    assert payload["new"][0]["display_name"] == "Maria Rossi"
    assert database_counts(settings) == (0, 0)


def test_cli_apply_then_second_dry_run_is_idempotent(
    tmp_path, monkeypatch, capsys
):
    settings, _, document_id = setup_database(tmp_path, [parsed_record()])
    monkeypatch.setattr(bootstrap_politicians, "get_settings", lambda: settings)

    assert bootstrap_politicians.main(
        ["--apply", "--raw-document-id", str(document_id)]
    ) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["politicians_created"] == 1
    assert applied["identifiers_created"] == 1

    assert bootstrap_politicians.main(
        ["--dry-run", "--raw-document-id", str(document_id)]
    ) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["new_count"] == 0
    assert repeated["matched_count"] == 1
    assert repeated["matched"][0]["method"] == "official_source_identifier"
    assert database_counts(settings) == (1, 1)


def test_cli_apply_reports_invalid_record_and_does_not_write(
    tmp_path, monkeypatch, capsys
):
    malformed = parsed_record()
    malformed["mandate_start"] = "not-a-date"
    settings, _, document_id = setup_database(tmp_path, [malformed])
    monkeypatch.setattr(bootstrap_politicians, "get_settings", lambda: settings)

    exit_code = bootstrap_politicians.main(
        ["--apply", "--raw-document-id", str(document_id)]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["safe_to_apply"] is False
    assert payload["invalid_count"] == 1
    assert payload["invalid"][0]["candidate_index"] == 0
    assert database_counts(settings) == (0, 0)
