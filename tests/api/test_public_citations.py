from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.models import (
    Evidence,
    EvidenceExtractionMethod,
    ImmutablePoliticianVersionCitationError,
    Politician,
    PoliticianVersion,
    PoliticianVersionCitation,
    ProfileDraft,
    ProfileDraftKind,
    ProfileDraftStatus,
    RawDocument,
    RawDocumentStatus,
    Review,
    Source,
)
from backend.app.services import (
    PublishPersistenceError,
    PublishService,
    normalize_person_name,
)


def profile_data(*, profession: str = "Avvocata") -> dict:
    return {
        "given_name": "Maria",
        "family_name": "Rossi",
        "birth_date": "1970-01-02",
        "birth_place": None,
        "gender": "female",
        "profession": profession,
        "image_url": None,
        "official_homepage_url": None,
        "mandates": [],
    }


def seed_draft_with_evidence(session_factory, source) -> tuple[int, int]:
    with session_factory() as session:
        politician = Politician(
            canonical_given_name="Maria",
            canonical_family_name="Rossi",
            normalized_name=normalize_person_name("Maria", "Rossi"),
            birth_date=date(1970, 1, 2),
        )
        document = RawDocument(
            source_id=source.id,
            retrieved_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
            source_url="https://dati.senato.it/sparql",
            content_type="application/json",
            storage_key="private/raw.json",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="senato_collector_v1",
            parser_version="senato_parser_v1",
        )
        session.add_all((politician, document))
        session.flush()
        draft = ProfileDraft(
            politician_id=politician.id,
            raw_document_id=document.id,
            kind=ProfileDraftKind.INITIAL,
            status=ProfileDraftStatus.PENDING,
            profile_schema_version=1,
            proposed_profile_data=profile_data(),
            diff_data={"status": "initial", "changes": []},
        )
        session.add(draft)
        session.flush()
        evidence_values = (
            ("profession", "profession", "Avvocata", "record-1"),
            ("birth_date", "birthDate", "1970-01-02", "record-1"),
            ("given_name", "firstName", "Maria", "record-1"),
            # Different internal record metadata maps to the same public citation.
            ("profession", "profession", "Avvocata", "record-duplicate"),
        )
        session.add_all(
            Evidence(
                draft_id=draft.id,
                field_path=field_path,
                raw_document_id=document.id,
                source_url="https://dati.senato.it/sparql",
                source_record_identifier=record_identifier,
                source_field_name=source_field,
                source_value=source_value,
                extraction_method=EvidenceExtractionMethod.DETERMINISTIC,
            )
            for field_path, source_field, source_value, record_identifier in evidence_values
        )
        session.commit()
        return politician.id, draft.id


def make_client(session_factory, tmp_path) -> TestClient:
    engine = session_factory.kw["bind"]
    return TestClient(
        create_app(
            Settings(
                database_url=str(engine.url),
                raw_storage_path=tmp_path / "raw",
                admin_api_key="admin-secret",
                admin_reviewer_identity="api-editor",
            )
        )
    )


def test_approval_creates_deduplicated_ordered_immutable_citation_snapshot(
    session_factory, source
):
    politician_id, draft_id = seed_draft_with_evidence(session_factory, source)

    result = PublishService(session_factory).approve(draft_id, reviewer="editor")

    with session_factory() as session:
        citations = list(
            session.scalars(
                select(PoliticianVersionCitation)
                .where(
                    PoliticianVersionCitation.politician_version_id
                    == result.created_version_id
                )
                .order_by(
                    PoliticianVersionCitation.field_path,
                    PoliticianVersionCitation.source_name,
                    PoliticianVersionCitation.source_url,
                )
            )
        )
        assert [citation.field_path for citation in citations] == [
            "birth_date",
            "given_name",
            "profession",
        ]
        assert {citation.source_name for citation in citations} == {
            "Senato della Repubblica"
        }
        assert session.get(Politician, politician_id).current_version_id == (
            result.created_version_id
        )

        citations[0].source_name = "Changed"
        with pytest.raises(ImmutablePoliticianVersionCitationError):
            session.commit()


def test_detail_exposes_only_safe_snapshot_and_list_stays_compact(
    session_factory, source, tmp_path
):
    politician_id, draft_id = seed_draft_with_evidence(session_factory, source)
    PublishService(session_factory).approve(draft_id, reviewer="secret-editor")

    with make_client(session_factory, tmp_path) as client:
        detail = client.get(f"/politicians/{politician_id}")
        listing = client.get("/politicians")

    assert detail.status_code == 200
    payload = detail.json()
    assert payload["citation_count"] == 3
    assert [citation["field_path"] for citation in payload["citations"]] == [
        "birth_date",
        "given_name",
        "profession",
    ]
    assert payload["citations"][0] == {
        "field_path": "birth_date",
        "source_name": "Senato della Repubblica",
        "source_url": "https://dati.senato.it/sparql",
        "source_field": "birthDate",
    }
    serialized = detail.text.casefold()
    for private_name in (
        "draft_id",
        "raw_document_id",
        "storage_key",
        "raw_sha256",
        "normalized_sha256",
        "reviewer",
        "note",
        "source_record_identifier",
        "extraction_method",
    ):
        assert private_name not in serialized

    list_item = listing.json()["items"][0]
    assert list_item["citation_count"] == 3
    assert "citations" not in list_item


def test_later_draft_evidence_does_not_change_published_snapshot(
    session_factory, source, tmp_path
):
    politician_id, approved_draft_id = seed_draft_with_evidence(
        session_factory, source
    )
    result = PublishService(session_factory).approve(
        approved_draft_id, reviewer="editor"
    )

    with session_factory() as session:
        approved_draft = session.get(ProfileDraft, approved_draft_id)
        later_draft = ProfileDraft(
            politician_id=politician_id,
            baseline_version_id=result.created_version_id,
            raw_document_id=approved_draft.raw_document_id,
            kind=ProfileDraftKind.UPDATE,
            status=ProfileDraftStatus.PENDING,
            profile_schema_version=1,
            proposed_profile_data=profile_data(profession="Magistrata"),
            diff_data={"status": "update", "changes": []},
        )
        session.add(later_draft)
        session.flush()
        session.add(
            Evidence(
                draft_id=later_draft.id,
                field_path="profession",
                raw_document_id=approved_draft.raw_document_id,
                source_url="https://example.test/later-draft",
                source_record_identifier="later-record",
                source_field_name="laterField",
                source_value="Magistrata",
                extraction_method=EvidenceExtractionMethod.DETERMINISTIC,
            )
        )
        session.commit()

    with make_client(session_factory, tmp_path) as client:
        payload = client.get(f"/politicians/{politician_id}").json()

    assert payload["current_version_number"] == 1
    assert payload["profile"]["profession"] == "Avvocata"
    assert all(
        citation["source_url"] == "https://dati.senato.it/sparql"
        for citation in payload["citations"]
    )


def test_update_inherits_unchanged_citations_and_replaces_changed_field_source(
    session_factory, source
):
    politician_id, initial_draft_id = seed_draft_with_evidence(
        session_factory, source
    )
    initial = PublishService(session_factory).approve(
        initial_draft_id, reviewer="editor"
    )

    with session_factory() as session:
        camera = Source(
            key="camera-deputati",
            name="Camera dei Deputati",
            base_url="https://dati.camera.it",
        )
        session.add(camera)
        session.flush()
        document = RawDocument(
            source_id=camera.id,
            retrieved_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
            source_url="https://dati.camera.it/sparql",
            content_type="application/json",
            storage_key="camera/update.json",
            raw_sha256="c" * 64,
            normalized_sha256="d" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="camera_collector_v1",
            parser_version="camera_parser_v1",
        )
        session.add(document)
        session.flush()
        draft = ProfileDraft(
            politician_id=politician_id,
            baseline_version_id=initial.created_version_id,
            raw_document_id=document.id,
            kind=ProfileDraftKind.UPDATE,
            status=ProfileDraftStatus.PENDING,
            profile_schema_version=1,
            proposed_profile_data=profile_data(profession="Magistrata"),
            diff_data={
                "status": "update",
                "changes": [
                    {
                        "field_path": "profession",
                        "change_type": "changed",
                        "old_value": "Avvocata",
                        "new_value": "Magistrata",
                    }
                ],
            },
        )
        session.add(draft)
        session.flush()
        session.add(
            Evidence(
                draft_id=draft.id,
                field_path="profession",
                raw_document_id=document.id,
                source_url="https://dati.camera.it/sparql",
                source_record_identifier="camera-record",
                source_field_name="profession",
                source_value="Magistrata",
                extraction_method=EvidenceExtractionMethod.DETERMINISTIC,
            )
        )
        session.commit()
        draft_id = draft.id

    update = PublishService(session_factory).approve(draft_id, reviewer="editor")

    with session_factory() as session:
        citations = session.scalars(
            select(PoliticianVersionCitation).where(
                PoliticianVersionCitation.politician_version_id
                == update.created_version_id
            )
        ).all()
        assert {(item.field_path, item.source_name) for item in citations} == {
            ("birth_date", "Senato della Repubblica"),
            ("given_name", "Senato della Repubblica"),
            ("profession", "Camera dei Deputati"),
        }


def test_legacy_version_without_snapshot_returns_empty_citations(
    session_factory, tmp_path
):
    with session_factory() as session:
        politician = Politician(
            canonical_given_name="Legacy",
            canonical_family_name="Rossi",
            normalized_name=normalize_person_name("Legacy", "Rossi"),
            birth_date=date(1970, 1, 2),
        )
        session.add(politician)
        session.flush()
        version = PoliticianVersion(
            politician_id=politician.id,
            version_number=1,
            profile_schema_version=1,
            profile_data={**profile_data(), "given_name": "Legacy"},
            published_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        session.add(version)
        session.flush()
        politician.current_version_id = version.id
        session.commit()
        politician_id = politician.id

    with make_client(session_factory, tmp_path) as client:
        response = client.get(f"/politicians/{politician_id}")

    assert response.status_code == 200
    assert response.json()["citations"] == []
    assert response.json()["citation_count"] == 0


def test_citation_failure_rolls_back_entire_publication(session_factory, source):
    politician_id, draft_id = seed_draft_with_evidence(session_factory, source)

    def fail_citation_insert(mapper, connection, target):
        del mapper, connection, target
        raise RuntimeError("injected citation failure")

    event.listen(PoliticianVersionCitation, "before_insert", fail_citation_insert)
    try:
        with pytest.raises(PublishPersistenceError, match="rolled back"):
            PublishService(session_factory).approve(draft_id, reviewer="editor")
    finally:
        event.remove(
            PoliticianVersionCitation, "before_insert", fail_citation_insert
        )

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PoliticianVersion)) == 0
        assert session.scalar(select(func.count()).select_from(Review)) == 0
        assert (
            session.scalar(select(func.count()).select_from(PoliticianVersionCitation))
            == 0
        )
        assert session.get(Politician, politician_id).current_version_id is None
        assert session.get(ProfileDraft, draft_id).status is ProfileDraftStatus.PENDING
