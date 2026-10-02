from datetime import datetime, timedelta, timezone

import pytest

from backend.app.models import RawDocument, RawDocumentStatus
from backend.app.services import CandidateRebuildError, RawDocumentCandidateRebuilder


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


def add_document(
    session_factory,
    source,
    *,
    records,
    status=RawDocumentStatus.PARSED,
    retrieved_at=None,
) -> int:
    with session_factory() as session:
        document = RawDocument(
            source_id=source.id,
            retrieved_at=retrieved_at or datetime(2026, 10, 2, tzinfo=timezone.utc),
            source_url="https://dati.senato.it/sparql",
            content_type="application/json",
            storage_key="senato/test.json",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64 if status is RawDocumentStatus.PARSED else None,
            structured_records=records if status is RawDocumentStatus.PARSED else None,
            process_status=status,
            change_detected=True if status is RawDocumentStatus.PARSED else None,
            collector_version="senato_collector_v1",
            parser_version="senato_parser_v1",
        )
        session.add(document)
        session.commit()
        return document.id


def test_rebuilds_candidates_from_selected_successful_document(
    session_factory, source
):
    document_id = add_document(
        session_factory,
        source,
        records=[parsed_record("100"), parsed_record("101")],
    )

    result = RawDocumentCandidateRebuilder(session_factory).rebuild(
        raw_document_id=document_id
    )

    assert result.raw_document_id == document_id
    assert [item.candidate_index for item in result.candidates] == [0, 1]
    assert result.candidates[1].profile.identity.source_identifiers[0].value.endswith(
        "/101"
    )
    assert result.invalid == ()


def test_rebuild_defaults_to_latest_successful_document(session_factory, source):
    first_id = add_document(
        session_factory,
        source,
        records=[parsed_record("100")],
        retrieved_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    latest_id = add_document(
        session_factory,
        source,
        records=[parsed_record("200")],
        retrieved_at=datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(days=1),
    )

    result = RawDocumentCandidateRebuilder(session_factory).rebuild()

    assert result.raw_document_id == latest_id
    assert result.raw_document_id != first_id
    assert result.candidates[0].profile.identity.source_identifiers[0].value.endswith(
        "/200"
    )


def test_malformed_stored_record_is_reported_without_losing_valid_records(
    session_factory, source
):
    malformed = parsed_record("999")
    malformed["mandate_start"] = "not-a-date"
    document_id = add_document(
        session_factory,
        source,
        records=[parsed_record("100"), malformed],
    )

    result = RawDocumentCandidateRebuilder(session_factory).rebuild(
        raw_document_id=document_id
    )

    assert len(result.candidates) == 1
    assert result.invalid[0].candidate_index == 1
    assert result.invalid[0].source_record_id.endswith("/999")
    assert "not-a-date" in result.invalid[0].error


@pytest.mark.parametrize("status", [RawDocumentStatus.COLLECTED, RawDocumentStatus.FAILED])
def test_rejects_document_that_was_not_successfully_parsed(
    session_factory, source, status
):
    document_id = add_document(session_factory, source, records=None, status=status)

    with pytest.raises(CandidateRebuildError, match="not successfully parsed"):
        RawDocumentCandidateRebuilder(session_factory).rebuild(
            raw_document_id=document_id
        )


def test_rejects_missing_document(session_factory, source):
    with pytest.raises(CandidateRebuildError, match="does not exist"):
        RawDocumentCandidateRebuilder(session_factory).rebuild(raw_document_id=999)
