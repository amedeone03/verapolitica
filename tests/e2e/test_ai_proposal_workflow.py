from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.ai import FakeExtractionProvider
from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.models import ProposalDraft, Source
from backend.app.pipeline.official_document_pipeline import OfficialDocumentPipeline
from backend.app.schemas import StructuredExtractionResult
from backend.app.services import ProposalExtractionService


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "fixtures"
    / "ai"
    / "synthetic_official_programme.html"
)
PROMISE = "The Civic Example Party commits to build 100 new clinics by 2030."
PROPOSAL = "The programme proposes a national housing transparency register."
ADMIN_HEADERS = {"Authorization": "Bearer ai-admin"}


def _provider(*, evidence=PROMISE, model="fake-ai-e2e-v1"):
    return FakeExtractionProvider(
        StructuredExtractionResult.model_validate(
            {
                "output": {
                    "candidates": [
                        {
                            "claim_type": "explicit_promise",
                            "exact_statement": PROMISE,
                            "normalized_title": "Build 100 new clinics by 2030",
                            "summary": "Synthetic E2E commitment.",
                            "topic": "healthcare",
                            "actor_mentions": [
                                {
                                    "name": "The Civic Example Party",
                                    "role": "commitment_owner",
                                }
                            ],
                            "announced_at": None,
                            "target_date": "2030-12-31",
                            "evidence": [
                                {
                                    "chunk_index": 0,
                                    "page": None,
                                    "supporting_text": evidence,
                                }
                            ],
                            "confidence": "high",
                            "abstention_reason": None,
                        }
                    ]
                }
            }
        ),
        model_name=model,
    )


def _proposal_provider():
    return FakeExtractionProvider(
        StructuredExtractionResult.model_validate(
            {
                "output": {
                    "candidates": [
                        {
                            "claim_type": "proposal",
                            "exact_statement": PROPOSAL,
                            "normalized_title": "Create a housing transparency register",
                            "summary": None,
                            "topic": "housing",
                            "actor_mentions": [],
                            "announced_at": None,
                            "target_date": None,
                            "evidence": [
                                {
                                    "chunk_index": 0,
                                    "page": None,
                                    "supporting_text": PROPOSAL,
                                }
                            ],
                            "confidence": "medium",
                            "abstention_reason": None,
                        }
                    ]
                }
            }
        ),
        model_name="fake-ai-rejected-v1",
    )


def test_fake_ai_document_to_reviewed_public_promise_e2e(
    session_factory, raw_storage, tmp_path
):
    with session_factory() as session:
        source = Source(
            key="official-ai-e2e",
            name="Synthetic official AI E2E source",
            base_url="https://official.example",
        )
        session.add(source)
        session.commit()
        source_id = source.id
    ingestion = OfficialDocumentPipeline(
        session_factory,
        raw_storage,
        max_document_bytes=100_000,
        max_chunk_chars=10_000,
        max_chunks=5,
    ).ingest(
        source_id=source_id,
        source_key="official-ai-e2e",
        source_url="https://official.example/synthetic-programme.html",
        content_type="text/html",
        content=FIXTURE.read_bytes(),
    )
    service = ProposalExtractionService(
        session_factory,
        _provider(),
        max_chunks_per_run=5,
        max_evidence_excerpt_chars=600,
    )
    extraction = service.extract(ingestion.raw_document_id)
    draft_id = extraction.draft_ids[0]
    settings = Settings(
        database_url=str(session_factory.kw["bind"].url),
        raw_storage_path=tmp_path / "raw",
        admin_api_key="ai-admin",
        admin_reviewer_identity="ai-editor",
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/proposals").json()["total"] == 0
        detail = client.get(
            f"/admin/proposals/drafts/{draft_id}", headers=ADMIN_HEADERS
        )
        assert detail.status_code == 200
        assert detail.json()["ai_assistance"]["prompt_version"] == (
            "proposal_extraction_v1"
        )
        assert detail.json()["ai_assistance"]["evidence"][0][
            "supporting_text"
        ] == PROMISE
        client.post(
            f"/admin/proposals/drafts/{draft_id}/start-review",
            headers=ADMIN_HEADERS,
        )
        approved = client.post(
            f"/admin/proposals/drafts/{draft_id}/approve",
            headers=ADMIN_HEADERS,
            json={"note": "Official excerpt checked manually"},
        )
        assert approved.status_code == 200
        proposal_id = approved.json()["proposal_id"]
        public = client.get(f"/proposals/{proposal_id}")
        assert public.status_code == 200
        assert public.json()["exact_statement"] == PROMISE
        assert "ai_assistance" not in public.json()
        assert "confidence" not in public.json()

    repeated = service.extract(ingestion.raw_document_id)
    assert repeated.run_id == extraction.run_id
    with session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(ProposalDraft)) == 1
        )

    invalid = ProposalExtractionService(
        session_factory,
        _provider(
            evidence="Invented evidence that is absent.",
            model="fake-ai-invalid-evidence-v1",
        ),
        max_chunks_per_run=5,
        max_evidence_excerpt_chars=600,
    ).extract(ingestion.raw_document_id)
    assert invalid.rejected_count == 1
    assert invalid.draft_ids == ()

    rejectable = ProposalExtractionService(
        session_factory,
        _proposal_provider(),
        max_chunks_per_run=5,
        max_evidence_excerpt_chars=600,
    ).extract(ingestion.raw_document_id)
    with TestClient(create_app(settings)) as client:
        rejected = client.post(
            f"/admin/proposals/drafts/{rejectable.draft_ids[0]}/reject",
            headers=ADMIN_HEADERS,
            json={"note": "AI-assisted draft rejected after human review"},
        )
        assert rejected.status_code == 200
        assert client.get(
            f"/proposals/{rejected.json()['proposal_id']}"
        ).status_code == 404
