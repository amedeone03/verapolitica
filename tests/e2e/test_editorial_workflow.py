from contextlib import contextmanager
from dataclasses import dataclass

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.models import (
    Evidence,
    EvidenceExtractionMethod,
    Politician,
    PoliticianVersion,
    PoliticianVersionCitation,
    ProfileDraft,
    ProfileDraftKind,
    ProfileDraftStatus,
    RawDocument,
    Review,
    ReviewDecision,
)
from backend.app.pipeline.collectors import SenatoCollector
from backend.app.pipeline.ingestion_pipeline import IngestionPipeline, IngestionResult
from backend.app.pipeline.mappers import SenatoCandidateProfileMapper
from backend.app.pipeline.parsers import SenatoParser
from backend.app.schemas import CandidateProfile, DraftCreatedResult, MatchedResult
from backend.app.services import (
    CandidateRebuildResult,
    DraftService,
    IndexedCandidate,
    MatchingService,
    PoliticianBootstrapService,
    PublishService,
)


ADMIN_HEADERS = {"Authorization": "Bearer e2e-admin-key"}


@dataclass(frozen=True)
class PendingWorkflow:
    candidate: CandidateProfile
    politician_id: int
    draft_id: int
    raw_document_id: int


def senato_payload(*, profession: str = "Avvocata") -> dict:
    def value(content: str, node_type: str = "literal") -> dict:
        return {"type": node_type, "value": content}

    return {
        "head": {"vars": ["senatorUri", "firstName", "lastName"]},
        "results": {
            "bindings": [
                {
                    "senatorUri": value(
                        "https://dati.senato.it/senatore/e2e-1", "uri"
                    ),
                    "firstName": value("Maria"),
                    "lastName": value("Rossi"),
                    "gender": value("female"),
                    "birthDate": value("1970-01-02"),
                    "birthCity": value("Roma"),
                    "birthProvince": value("Roma"),
                    "birthCountry": value("Italia"),
                    "profession": value(profession),
                    "photoUrl": value(
                        "https://www.senato.it/photo/e2e-1.jpg", "uri"
                    ),
                    "homepage": value(
                        "https://www.senato.it/senatore/e2e-1", "uri"
                    ),
                    "mandateUri": value(
                        "https://dati.senato.it/mandato/e2e-1-19", "uri"
                    ),
                    "mandateType": value("elettivo"),
                    "mandateStart": value("2022-10-13"),
                    "legislature": value("19"),
                    "electionRegion": value("Lazio"),
                }
            ]
        },
    }


def ingest_candidate(
    session_factory,
    source,
    raw_storage,
    *,
    profession: str = "Avvocata",
) -> tuple[CandidateProfile, IngestionResult]:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.params["format"] == "application/sparql-results+json"
        return httpx.Response(
            200,
            headers={"content-type": "application/sparql-results+json"},
            json=senato_payload(profession=profession),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        result = IngestionPipeline(
            session_factory=session_factory,
            storage=raw_storage,
            collector=SenatoCollector(
                "https://dati.senato.it/sparql",
                legislature=19,
                client=http_client,
            ),
            parser=SenatoParser(),
            profile_mapper=SenatoCandidateProfileMapper(),
        ).run(source_id=source.id, source_key=source.key)

    assert result.change_detected is True
    assert len(result.candidate_profiles) == 1
    return result.candidate_profiles[0], result


def bootstrap_candidate(
    session_factory,
    candidate: CandidateProfile,
    raw_document_id: int,
) -> int:
    bootstrap = PoliticianBootstrapService(session_factory)
    rebuilt = CandidateRebuildResult(
        raw_document_id=raw_document_id,
        candidates=(IndexedCandidate(candidate_index=0, profile=candidate),),
        invalid=(),
    )
    plan = bootstrap.plan(rebuilt, dry_run=False)
    report = bootstrap.apply(plan)
    politician_id = report.new[0].created_politician_id
    assert politician_id is not None
    return politician_id


def create_draft(session_factory, candidate: CandidateProfile) -> DraftCreatedResult:
    with session_factory() as session:
        match = MatchingService(session).match(candidate)
        assert isinstance(match, MatchedResult)
    result = DraftService(session_factory).create(candidate, match)
    assert isinstance(result, DraftCreatedResult)
    return result


def prepare_pending_workflow(
    session_factory,
    source,
    raw_storage,
) -> PendingWorkflow:
    candidate, ingestion = ingest_candidate(session_factory, source, raw_storage)
    politician_id = bootstrap_candidate(
        session_factory,
        candidate,
        ingestion.raw_document_id,
    )
    draft = create_draft(session_factory, candidate)
    assert draft.politician_id == politician_id
    return PendingWorkflow(
        candidate=candidate,
        politician_id=politician_id,
        draft_id=draft.draft_id,
        raw_document_id=ingestion.raw_document_id,
    )


@contextmanager
def api_client(session_factory, tmp_path):
    engine = session_factory.kw["bind"]
    app = create_app(
        Settings(
            database_url=str(engine.url),
            raw_storage_path=tmp_path / "api-raw",
            admin_api_key="e2e-admin-key",
            admin_reviewer_identity="e2e-editor",
        )
    )
    with TestClient(app) as client:
        yield client


def recursive_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(
            *(recursive_keys(nested) for nested in value.values())
        )
    if isinstance(value, list):
        return set().union(*(recursive_keys(item) for item in value))
    return set()


def test_complete_editorial_flow_publishes_only_after_explicit_approval(
    session_factory,
    source,
    raw_storage,
    tmp_path,
):
    workflow = prepare_pending_workflow(session_factory, source, raw_storage)

    with session_factory() as session:
        draft = session.get(ProfileDraft, workflow.draft_id)
        assert draft.status is ProfileDraftStatus.PENDING
        expected_citations = {
            (
                evidence.field_path,
                "Senato della Repubblica",
                evidence.source_url,
                evidence.source_field_name,
            )
            for evidence in draft.evidence
        }

    with api_client(session_factory, tmp_path) as client:
        assert client.get(f"/politicians/{workflow.politician_id}").status_code == 404

        started = client.post(
            f"/admin/drafts/{workflow.draft_id}/start-review",
            headers=ADMIN_HEADERS,
        )
        assert started.status_code == 200
        assert started.json()["final_draft_status"] == "in_review"
        assert client.get(f"/politicians/{workflow.politician_id}").status_code == 404

        with session_factory() as session:
            assert session.get(ProfileDraft, workflow.draft_id).status is (
                ProfileDraftStatus.IN_REVIEW
            )
            assert session.scalar(select(func.count()).select_from(Review)) == 0

        approved = client.post(
            f"/admin/drafts/{workflow.draft_id}/approve",
            headers=ADMIN_HEADERS,
            json={"note": "E2E evidence checked"},
        )
        assert approved.status_code == 200
        version_id = approved.json()["created_version_id"]

        public = client.get(f"/politicians/{workflow.politician_id}")

    assert public.status_code == 200
    payload = public.json()
    assert payload["profile"]["given_name"] == "Maria"
    assert payload["profile"]["profession"] == "Avvocata"
    actual_citations = {
        (
            citation["field_path"],
            citation["source_name"],
            citation["source_url"],
            citation["source_field"],
        )
        for citation in payload["citations"]
    }
    assert actual_citations == expected_citations

    private_fields = {
        "draft_id",
        "raw_document_id",
        "reviewer",
        "note",
        "status",
        "storage_key",
        "raw_sha256",
        "normalized_sha256",
    }
    assert recursive_keys(payload).isdisjoint(private_fields)

    with session_factory() as session:
        draft = session.get(ProfileDraft, workflow.draft_id)
        politician = session.get(Politician, workflow.politician_id)
        assert draft.status is ProfileDraftStatus.APPROVED
        assert politician.current_version_id == version_id
        assert session.scalar(select(func.count()).select_from(Review)) == 1
        assert session.scalar(select(func.count()).select_from(PoliticianVersion)) == 1
        assert session.scalar(
            select(func.count()).select_from(PoliticianVersionCitation)
        ) == len(expected_citations)


def test_rejected_draft_and_unpublished_identity_never_become_public(
    session_factory,
    source,
    raw_storage,
    tmp_path,
):
    workflow = prepare_pending_workflow(session_factory, source, raw_storage)

    with api_client(session_factory, tmp_path) as client:
        rejected = client.post(
            f"/admin/drafts/{workflow.draft_id}/reject",
            headers=ADMIN_HEADERS,
            json={"note": "Evidence rejected"},
        )
        detail = client.get(f"/politicians/{workflow.politician_id}")
        listing = client.get("/politicians")

    assert rejected.status_code == 200
    assert rejected.json()["decision"] == "rejected"
    assert detail.status_code == 404
    assert listing.status_code == 200
    assert listing.json()["items"] == []
    with session_factory() as session:
        draft = session.get(ProfileDraft, workflow.draft_id)
        politician = session.get(Politician, workflow.politician_id)
        review = session.scalar(select(Review))
        assert draft.status is ProfileDraftStatus.REJECTED
        assert politician.current_version_id is None
        assert review.decision is ReviewDecision.REJECTED
        assert session.scalar(select(func.count()).select_from(PoliticianVersion)) == 0


def test_double_approval_is_blocked_without_duplicate_publication_records(
    session_factory,
    source,
    raw_storage,
    tmp_path,
):
    workflow = prepare_pending_workflow(session_factory, source, raw_storage)
    path = f"/admin/drafts/{workflow.draft_id}/approve"

    with api_client(session_factory, tmp_path) as client:
        first = client.post(path, headers=ADMIN_HEADERS, json={})
        second = client.post(path, headers=ADMIN_HEADERS, json={})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "draft_not_reviewable"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Review)) == 1
        assert session.scalar(select(func.count()).select_from(PoliticianVersion)) == 1
        evidence_count = session.scalar(select(func.count()).select_from(Evidence))
        citation_count = session.scalar(
            select(func.count()).select_from(PoliticianVersionCitation)
        )
        assert citation_count == evidence_count


def test_stale_draft_cannot_overwrite_newer_published_version(
    session_factory,
    source,
    raw_storage,
    tmp_path,
):
    initial = prepare_pending_workflow(session_factory, source, raw_storage)
    first_publication = PublishService(session_factory).approve(
        initial.draft_id,
        reviewer="first-editor",
    )
    candidate, ingestion = ingest_candidate(
        session_factory,
        source,
        raw_storage,
        profession="Magistrata",
    )
    stale_draft = create_draft(session_factory, candidate)
    assert stale_draft.baseline_version_id == first_publication.created_version_id

    with session_factory() as session:
        original = session.get(ProfileDraft, stale_draft.draft_id)
        competing = ProfileDraft(
            politician_id=initial.politician_id,
            baseline_version_id=first_publication.created_version_id,
            raw_document_id=ingestion.raw_document_id,
            kind=ProfileDraftKind.UPDATE,
            status=ProfileDraftStatus.PENDING,
            profile_schema_version=1,
            proposed_profile_data={
                **original.proposed_profile_data,
                "profession": "Docente",
            },
            diff_data=original.diff_data,
        )
        session.add(competing)
        session.flush()
        session.add(
            Evidence(
                draft_id=competing.id,
                field_path="profession",
                raw_document_id=ingestion.raw_document_id,
                source_url="https://dati.senato.it/sparql",
                source_record_identifier="concurrent-record",
                source_field_name="profession",
                source_value="Docente",
                extraction_method=EvidenceExtractionMethod.DETERMINISTIC,
            )
        )
        session.commit()
        competing_id = competing.id

    newer = PublishService(session_factory).approve(
        competing_id,
        reviewer="second-editor",
    )
    with api_client(session_factory, tmp_path) as client:
        stale_response = client.post(
            f"/admin/drafts/{stale_draft.draft_id}/approve",
            headers=ADMIN_HEADERS,
            json={},
        )
        public = client.get(f"/politicians/{initial.politician_id}")

    assert stale_response.status_code == 409
    assert stale_response.json()["error"]["code"] == "stale_draft"
    assert public.json()["profile"]["profession"] == "Docente"
    with session_factory() as session:
        politician = session.get(Politician, initial.politician_id)
        assert politician.current_version_id == newer.created_version_id
        assert session.get(ProfileDraft, stale_draft.draft_id).status is (
            ProfileDraftStatus.PENDING
        )
        assert session.get(ProfileDraft, stale_draft.draft_id).review is None


def test_publication_failure_rolls_back_every_layer(
    session_factory,
    source,
    raw_storage,
    tmp_path,
):
    workflow = prepare_pending_workflow(session_factory, source, raw_storage)

    def fail_citation_insert(mapper, connection, target):
        del mapper, connection, target
        raise RuntimeError("injected E2E citation failure")

    event.listen(PoliticianVersionCitation, "before_insert", fail_citation_insert)
    try:
        with api_client(session_factory, tmp_path) as client:
            response = client.post(
                f"/admin/drafts/{workflow.draft_id}/approve",
                headers=ADMIN_HEADERS,
                json={},
            )
            public = client.get(f"/politicians/{workflow.politician_id}")
    finally:
        event.remove(
            PoliticianVersionCitation,
            "before_insert",
            fail_citation_insert,
        )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "persistence_error"
    assert public.status_code == 404
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Review)) == 0
        assert session.scalar(select(func.count()).select_from(PoliticianVersion)) == 0
        assert session.scalar(
            select(func.count()).select_from(PoliticianVersionCitation)
        ) == 0
        assert session.get(Politician, workflow.politician_id).current_version_id is None
        assert session.get(ProfileDraft, workflow.draft_id).status is (
            ProfileDraftStatus.PENDING
        )
