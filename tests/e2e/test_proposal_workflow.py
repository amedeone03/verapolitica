from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.models import (
    Politician,
    PoliticianSourceIdentifier,
    PoliticianVersion,
    ProposalDraft,
    ProposalReview,
    ProposalStatusEvent,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.schemas import (
    PoliticalMandate,
    PoliticianVersionProfile,
    ProposalActorObservation,
    ProposalEvidenceObservation,
    ProposalObservation,
)
from backend.app.services import ProposalService, normalize_person_name


ADMIN_HEADERS = {"Authorization": "Bearer proposal-admin"}
NOW = datetime(2026, 1, 11, 12, tzinfo=timezone.utc)


def create_document(session, source_id: int, marker: str) -> RawDocument:
    document = RawDocument(
        source_id=source_id,
        retrieved_at=NOW,
        source_url="https://dati.senato.it/sparql",
        content_type="application/json",
        storage_key=f"senato-ddl/{marker}.json",
        raw_sha256=marker[0] * 64,
        normalized_sha256=marker[-1] * 64,
        structured_records=[],
        process_status=RawDocumentStatus.PARSED,
        change_detected=True,
        collector_version="fixture_v1",
        parser_version="fixture_v1",
    )
    session.add(document)
    session.flush()
    return document


def proposal_observation(
    document_id: int,
    *,
    identifier: str = "https://dati.senato.it/ddl/synthetic-e2e",
    title: str = "Synthetic national housing proposal",
    status_label: str = "da assegn. a commis.",
    normalized_status: str = "introduced",
    status_date: date = date(2026, 1, 10),
) -> ProposalObservation:
    return ProposalObservation(
        source_key="senato-ddl",
        raw_document_id=document_id,
        proposal_identifier=identifier,
        title=title,
        proposal_type="legislative_proposal",
        introduced_at=date(2026, 1, 10),
        source_status_label=status_label,
        normalized_status=normalized_status,
        status_effective_at=status_date,
        status_source_identifier=f"{identifier}#{status_date}-{normalized_status}",
        official_url=identifier,
        source_field="osr:statoDdl",
        observed_at=NOW,
        actors=(
            ProposalActorObservation(
                actor_type="politician",
                role="proposer",
                display_name="Sen. Anna Rossi",
                authority_key="senato-repubblica",
                source_identifier="https://dati.senato.it/senatore/e2e-anna",
                source_field="osr:senatore",
            ),
        ),
        evidence=tuple(
            ProposalEvidenceObservation(
                field_path=field_path,
                source_url=identifier,
                source_field=source_field,
                source_value=value,
            )
            for field_path, source_field, value in (
                ("title", "osr:titolo", title),
                ("proposal_type", "rdf:type", "osr:Ddl"),
                ("introduced_at", "osr:dataPresentazione", "2026-01-10"),
                ("current_status", "osr:statoDdl", status_label),
                (
                    "actors[0]",
                    "osr:senatore",
                    "https://dati.senato.it/senatore/e2e-anna",
                ),
            )
        ),
    )


def test_complete_proposal_workflow_and_status_update_are_review_gated(
    session_factory, tmp_path
):
    with session_factory() as session:
        people_source = Source(
            key="senato-repubblica",
            name="Senato della Repubblica",
            base_url="https://dati.senato.it",
        )
        proposal_source = Source(
            key="senato-ddl",
            name="Senato della Repubblica — Disegni di legge",
            base_url="https://dati.senato.it",
        )
        session.add_all((people_source, proposal_source))
        session.flush()
        politician = Politician(
            canonical_given_name="Anna",
            canonical_family_name="Rossi",
            normalized_name=normalize_person_name("Anna", "Rossi"),
            birth_date=date(1970, 1, 1),
        )
        session.add(politician)
        session.flush()
        profile = PoliticianVersionProfile(
            given_name="Anna",
            family_name="Rossi",
            birth_date=date(1970, 1, 1),
            birth_place=None,
            gender=None,
            profession=None,
            image_url=None,
            official_homepage_url=None,
            mandates=(
                PoliticalMandate(
                    institution="Senato della Repubblica",
                    office="senator",
                    legislature="19",
                    mandate_type="elected",
                    start_date=date(2022, 10, 13),
                ),
            ),
        )
        version = PoliticianVersion(
            politician_id=politician.id,
            version_number=1,
            profile_schema_version=1,
            profile_data=profile.model_dump(mode="json"),
            published_at=NOW,
        )
        session.add(version)
        session.flush()
        politician.current_version_id = version.id
        session.add(
            PoliticianSourceIdentifier(
                politician_id=politician.id,
                source_id=people_source.id,
                value="https://dati.senato.it/senatore/e2e-anna",
            )
        )
        document = create_document(session, proposal_source.id, "ab")
        session.commit()
        proposal_source_id = proposal_source.id
        politician_id = politician.id
        document_id = document.id

    initial = ProposalService(session_factory).sync(
        (proposal_observation(document_id),)
    )
    draft_id = initial.details[0].draft_id
    settings = Settings(
        database_url=str(session_factory.kw["bind"].url),
        raw_storage_path=tmp_path / "raw",
        admin_api_key="proposal-admin",
        admin_reviewer_identity="proposal-editor",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/proposals").json()["items"] == []
        assert client.get("/admin/proposals/drafts").status_code == 401
        detail = client.get(
            f"/admin/proposals/drafts/{draft_id}", headers=ADMIN_HEADERS
        )
        assert detail.status_code == 200
        assert detail.json()["proposed"]["source_status_label"] == (
            "da assegn. a commis."
        )
        assert len(detail.json()["evidence"]) == 5
        started = client.post(
            f"/admin/proposals/drafts/{draft_id}/start-review",
            headers=ADMIN_HEADERS,
        )
        assert started.json()["final_draft_status"] == "in_review"
        approved = client.post(
            f"/admin/proposals/drafts/{draft_id}/approve",
            headers=ADMIN_HEADERS,
            json={"note": "Official DDL record checked"},
        )
        assert approved.status_code == 200
        proposal_id = approved.json()["proposal_id"]
        repeated = client.post(
            f"/admin/proposals/drafts/{draft_id}/approve",
            headers=ADMIN_HEADERS,
            json={},
        )
        assert repeated.status_code == 409
        public = client.get(f"/proposals/{proposal_id}")
        assert public.status_code == 200
        assert public.json()["current_status"] == "introduced"
        assert public.json()["actors"][0]["role"] == "proposer"
        assert public.json()["actors"][0]["politician_id"] == politician_id
        politician_detail = client.get(f"/politicians/{politician_id}")
        assert politician_detail.json()["proposals"][0]["role"] == "proposer"

    with session_factory() as session:
        updated_document = create_document(session, proposal_source_id, "cd")
        session.commit()
        updated_document_id = updated_document.id
    update = ProposalService(session_factory).sync(
        (
            proposal_observation(
                updated_document_id,
                status_label="esame in comm.",
                normalized_status="under_review",
                status_date=date(2026, 2, 3),
            ),
        )
    )
    update_draft_id = update.details[0].draft_id
    with TestClient(create_app(settings)) as client:
        before = client.get(f"/proposals/{proposal_id}")
        assert [event["status"] for event in before.json()["status_history"]] == [
            "introduced"
        ]
        client.post(
            f"/admin/proposals/drafts/{update_draft_id}/approve",
            headers=ADMIN_HEADERS,
            json={},
        )
        after = client.get(f"/proposals/{proposal_id}")
        assert after.json()["current_status"] == "under_review"
        assert [event["status"] for event in after.json()["status_history"]] == [
            "introduced",
            "under_review",
        ]
        assert "raw_document_id" not in str(after.json())
        assert "reviewer" not in str(after.json())

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ProposalStatusEvent)) == 2
        assert session.scalar(select(func.count()).select_from(ProposalReview)) == 2


def test_rejected_proposal_never_appears_in_public_api(session_factory, tmp_path):
    with session_factory() as session:
        source = Source(
            key="senato-ddl",
            name="Senato DDL",
            base_url="https://dati.senato.it",
        )
        session.add(source)
        session.flush()
        document = create_document(session, source.id, "ab")
        session.commit()
        document_id = document.id
    observed = proposal_observation(
        document_id,
        identifier="https://dati.senato.it/ddl/synthetic-rejected",
        title="Synthetic rejected proposal",
    )
    draft_id = ProposalService(session_factory).sync((observed,)).details[0].draft_id
    settings = Settings(
        database_url=str(session_factory.kw["bind"].url),
        raw_storage_path=tmp_path / "raw",
        admin_api_key="proposal-admin",
        admin_reviewer_identity="proposal-editor",
    )
    with TestClient(create_app(settings)) as client:
        rejected = client.post(
            f"/admin/proposals/drafts/{draft_id}/reject",
            headers=ADMIN_HEADERS,
            json={"note": "Not suitable for publication"},
        )
        assert rejected.status_code == 200
        proposal_id = rejected.json()["proposal_id"]
        assert client.get(f"/proposals/{proposal_id}").status_code == 404
        assert client.get("/proposals").json()["total"] == 0
    with session_factory() as session:
        assert session.get(ProposalDraft, draft_id).status.value == "rejected"
        assert session.scalar(select(func.count()).select_from(ProposalStatusEvent)) == 0
