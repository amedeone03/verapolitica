from base64 import b64encode
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.demo.fake_extraction_fixtures import NO_FIXTURE_MESSAGE
from backend.app.main import create_app
from backend.app.models import AIExtractionRun, Proposal, ProposalDraft
from scripts.reset_ceo_ai_demo import reset_ceo_ai_demo


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'upload.db'}",
        raw_storage_path=tmp_path / "raw",
        demo_upload_path=tmp_path / "uploads",
        enable_demo_ui=True,
        admin_reviewer_identity="ceo-editor",
        admin_api_key="ceo-demo-admin-key-local-only",
    )


def test_sample_document_creates_unpublished_fake_draft(tmp_path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        page = client.get("/demo/ai-upload")
        assert page.status_code == 200
        assert "AI-assisted document analysis" in page.text
        assert "REAL LOCAL AI" in page.text
        assert "Deterministic demo fallback" in page.text
        assert "Demo mode — simulated AI provider" in page.text
        assert "Load sample official document" in page.text
        assert 'enctype="multipart/form-data"' in page.text
        assert 'accept=".pdf,.html,.htm,application/pdf,text/html"' in page.text
        assert 'id="document-file"' in page.text
        assert 'type="file"' in page.text
        assert "Choose PDF or HTML" in page.text
        assert 'for="document-file"' in page.text
        assert 'id="choose-file-button"' in page.text
        assert "No file selected." in page.text
        assert "/demo/ai-upload.js" in page.text
        assert "<script" in page.text
        assert "bytesToBase64" not in page.text
        script = client.get("/demo/ai-upload.js")
        assert script.status_code == 200
        assert "new FormData" in script.text
        assert 'form.append("document", chosen, chosen.name)' in script.text
        assert "Selected: " in script.text
        assert "Unsupported file type" in script.text
        assert "label[for='document-file']" in script.text
        assert "bytesToBase64" not in script.text
        assert "showPicker" in script.text
        assert "AbortController" in script.text
        assert "CLIENT_TIMEOUT_MS = 200000" in script.text
        assert "failStep" in script.text
        assert "stopLoading" in script.text
        assert "finally" in script.text
        assert "Local AI analysis did not complete in time. Please retry." in script.text
        assert 'data-step="validate"' in page.text
        assert 'data-step="draft"' in page.text
        assert "2–3 minutes" in page.text
        assert "unpublished editorial draft" in page.text
        assert page.text.count("scheda-ddl?did=60485") >= 1
        assert 'id="force-rerun"' in page.text
        assert "Force a new AI run" in page.text
        assert "force_rerun" in script.text

        result = client.post("/demo/ai-upload/sample", follow_redirects=True)
        assert result.status_code == 200
        assert "Simulated AI extraction — CEO demo" in result.text
        assert "cure palliative" in result.text
        assert "Evidence from official source" in result.text
        assert "Nothing becomes public until an editor approves it." in result.text
        assert "fake" in result.text
        assert "simulated-ceo-demo" in result.text
        public = client.get("/proposals")
        assert public.json()["total"] == 0

    engine = create_db_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            draft = session.scalar(select(ProposalDraft))
            run_row = session.scalar(select(AIExtractionRun))
            assert draft.status.value == "pending"
            assert session.get(Proposal, draft.proposal_id).published_at is None
            assert run_row.provider == "fake"
            assert run_row.model == "simulated-ceo-demo"
    finally:
        engine.dispose()


def test_arbitrary_html_without_fixture_fails_closed(tmp_path):
    settings = _settings(tmp_path)
    payload = {
        "filename": "other.html",
        "content_base64": b64encode(b"<html><p>Unrelated official page</p></html>").decode(),
        "source_url": "https://dati.senato.it/ddl/1.html",
        "source_name": "Senato della Repubblica",
        "mode": "fake",
    }
    with TestClient(create_app(settings)) as client:
        result = client.post("/demo/ai-upload", json=payload, follow_redirects=True)
        assert result.status_code == 200
        assert NO_FIXTURE_MESSAGE in result.text
        assert client.get("/proposals").json()["total"] == 0


def test_unsupported_file_is_rejected(tmp_path):
    settings = _settings(tmp_path)
    payload = {
        "filename": "notes.exe",
        "content_base64": b64encode(b"MZ").decode(),
        "source_url": "",
        "source_name": "Senato della Repubblica",
    }
    with TestClient(create_app(settings)) as client:
        result = client.post("/demo/ai-upload", json=payload, follow_redirects=True)
        assert result.status_code == 200
        assert "Unsupported file type" in result.text


def test_approval_publishes_without_ai_metadata_and_reset_clears_demo(tmp_path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        created = client.post("/demo/ai-upload/sample", follow_redirects=True)
        assert created.status_code == 200
        draft_id = int(created.url.path.rsplit("/", 1)[-1])
        assert client.get("/proposals").json()["total"] == 0
        started = client.post(
            f"/demo/ai-draft/{draft_id}/start-review", follow_redirects=True
        )
        assert "still unpublished" in started.text
        approved = client.post(
            f"/demo/ai-draft/{draft_id}/approve", follow_redirects=True
        )
        assert "View published citizen page" in approved.text
        listing = client.get("/proposals")
        assert listing.json()["total"] == 1
        proposal_id = listing.json()["items"][0]["id"]
        public = client.get(f"/proposals/{proposal_id}").json()
        serialized = str(public).casefold()
        assert public["sources"][0]["name"] == "Senato della Repubblica"
        assert "fake" not in serialized
        assert "simulated-ceo-demo" not in serialized
        assert "confidence" not in serialized
        assert "prompt" not in serialized
        assert "schema_version" not in serialized
        assert "reviewer" not in serialized
        assert "ollama" not in serialized
        assert "chunk_selection" not in serialized
        html = client.get(f"/app/?proposal={proposal_id}").text
        assert "fake" not in html.casefold()
        assert "simulated-ceo-demo" not in html.casefold()
        assert "ollama" not in html.casefold()
        assert "qwen" not in html.casefold()

    reset = reset_ceo_ai_demo(settings=settings)
    assert reset["proposals"] == 1
    engine = create_db_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Proposal)) == 0
            assert session.scalar(select(func.count()).select_from(AIExtractionRun)) == 0
    finally:
        engine.dispose()


def test_upload_route_is_local_only(tmp_path):
    hidden = Settings(
        database_url=f"sqlite:///{tmp_path / 'hidden.db'}",
        raw_storage_path=tmp_path / "raw",
        enable_demo_ui=False,
    )
    with TestClient(create_app(hidden)) as client:
        assert client.get("/demo/ai-upload").status_code == 404


LOCAL_HTML = (
    b"<html><body><h1>Disegno di legge DDL S. 2047</h1>"
    b"<p>Dati generali. Presentato da Sen. Neri. Articolo 1. "
    b"Si impegna a stanziare 5 milioni di euro.</p></body></html>"
)
LOCAL_STATEMENT = "Disegno di legge DDL S. 2047"


def _local_result():
    from backend.app.schemas import StructuredExtractionResult

    return StructuredExtractionResult.model_validate(
        {
            "output": {
                "candidates": [
                    {
                        "claim_type": "proposal",
                        "exact_statement": LOCAL_STATEMENT,
                        "normalized_title": LOCAL_STATEMENT,
                        "summary": "Presentato da Sen. Neri. 5 milioni di euro.",
                        "topic": "economy",
                        "actor_mentions": [{"name": "Sen. Neri", "role": "proposer"}],
                        "announced_at": None,
                        "target_date": None,
                        "evidence": [
                            {
                                "chunk_index": 0,
                                "page": None,
                                "supporting_text": LOCAL_STATEMENT,
                            },
                            {
                                "chunk_index": 0,
                                "page": None,
                                "supporting_text": "Sen. Neri",
                            },
                        ],
                        "confidence": "high",
                        "abstention_reason": None,
                    }
                ]
            }
        }
    )


def test_local_ollama_upload_creates_unpublished_draft(tmp_path, monkeypatch):
    from backend.app.ai.ollama_provider import OllamaStructuredExtractionProvider
    from backend.app.api import demo_editorial

    settings = _settings(tmp_path)
    monkeypatch.setattr(
        demo_editorial,
        "probe_ollama",
        lambda **kwargs: {
            "available": True,
            "has_model": True,
            "message": "Ollama is running locally. No API cost.",
            "models": ("qwen2.5:7b",),
        },
    )
    def fake_extract(self, request):
        from datetime import datetime, timezone

        from backend.app.ai.ollama_diagnostics import (
            OllamaAttemptRecord,
            build_ollama_chat_payload,
            stamp_diagnostics,
        )

        _payload, diagnostics = build_ollama_chat_payload(
            request,
            model_name=self.model_name,
            base_url="http://127.0.0.1:11434",
            timeout_seconds=1,
        )
        self.last_diagnostics = stamp_diagnostics(
            diagnostics,
            started_at=datetime.now(timezone.utc),
            response_status=200,
            attempts=(
                OllamaAttemptRecord(
                    attempt=1,
                    validation_status="schema_invalid",
                    validation_error_categories=("missing_claim_type",),
                    elapsed_ms=12,
                    response_status=200,
                ),
                OllamaAttemptRecord(
                    attempt=2,
                    validation_status="accepted",
                    validation_error_categories=(),
                    elapsed_ms=20,
                    response_status=200,
                ),
            ),
        )
        return _local_result()

    monkeypatch.setattr(OllamaStructuredExtractionProvider, "extract", fake_extract)
    payload = {
        "filename": "ddl-s-2047.html",
        "content_base64": b64encode(LOCAL_HTML).decode(),
        "source_url": "https://www.senato.it/leg/19/BGT/Schede/Ddliter/2047.htm",
        "source_name": "Senato della Repubblica",
        "mode": "local",
    }
    with TestClient(create_app(settings)) as client:
        created = client.post("/demo/ai-upload", json=payload, follow_redirects=True)
        assert created.status_code == 200
        assert "LOCAL AI ANALYSIS" in created.text
        assert LOCAL_STATEMENT in created.text
        assert "Evidence from official document" in created.text
        assert "unpublished draft" in created.text
        assert "Human review is required" in created.text
        assert "qwen2.5:7b" in created.text
        assert "proposal_extraction_v1" not in created.text
        assert "proposal_claim_schema_v1" not in created.text
        assert "Local AI attempts" not in created.text
        assert "schema validation failed" not in created.text
        assert "fingerprint" not in created.text.casefold()
        assert "Nothing becomes public until an editor approves it." in created.text
        assert client.get("/proposals").json()["total"] == 0
        draft_id = int(created.url.path.rsplit("/", 1)[-1])
        started = client.post(
            f"/demo/ai-draft/{draft_id}/start-review", follow_redirects=True
        )
        assert "still unpublished" in started.text
        approved = client.post(
            f"/demo/ai-draft/{draft_id}/approve", follow_redirects=True
        )
        assert "View published citizen page" in approved.text
        listing = client.get("/proposals").json()
        assert listing["total"] == 1
        public = client.get(f"/proposals/{listing['items'][0]['id']}").json()
        serialized = str(public).casefold()
        assert "ollama" not in serialized
        assert "qwen" not in serialized
        assert "confidence" not in serialized
        assert "chunk_selection" not in serialized
        assert "proposal_extraction_v1" not in serialized
        assert "local ai attempts" not in serialized
        assert "schema validation failed" not in serialized
        html = client.get(f"/app/?proposal={listing['items'][0]['id']}").text.casefold()
        assert "ollama" not in html
        assert "qwen" not in html
        assert "local ai attempts" not in html
        assert "schema validation failed" not in html


def test_local_mode_reports_ollama_unavailable_without_traceback(tmp_path, monkeypatch):
    from backend.app.ai.base import ExtractionProviderError
    from backend.app.ai.ollama_provider import OllamaStructuredExtractionProvider

    settings = _settings(tmp_path)

    def down(self, request):
        del request
        raise ExtractionProviderError(
            "Ollama is not running at http://127.0.0.1:11434. Start it with: ollama serve"
        )

    monkeypatch.setattr(OllamaStructuredExtractionProvider, "extract", down)
    payload = {
        "filename": "ddl.html",
        "content_base64": b64encode(LOCAL_HTML).decode(),
        "source_url": "https://www.senato.it/leg/19/BGT/Schede/Ddliter/2047.htm",
        "source_name": "Senato della Repubblica",
        "mode": "local",
    }
    with TestClient(create_app(settings)) as client:
        result = client.post("/demo/ai-upload", json=payload, follow_redirects=True)
        assert result.status_code == 200
        assert "Traceback" not in result.text
        assert "Local AI service unavailable" in result.text
        assert client.get("/proposals").json()["total"] == 0


def test_malformed_local_model_output_is_safe(tmp_path, monkeypatch):
    from backend.app.ai.base import ExtractionProviderOutputError
    from backend.app.ai.ollama_provider import OllamaStructuredExtractionProvider

    settings = _settings(tmp_path)

    def boom(self, request):
        del request
        raise ExtractionProviderOutputError(
            "Ollama returned malformed JSON",
            raw_output="{bad",
        )

    monkeypatch.setattr(OllamaStructuredExtractionProvider, "extract", boom)
    payload = {
        "filename": "ddl.html",
        "content_base64": b64encode(LOCAL_HTML).decode(),
        "source_url": "https://www.senato.it/leg/19/BGT/Schede/Ddliter/2047.htm",
        "source_name": "Senato della Repubblica",
        "mode": "local",
    }
    with TestClient(create_app(settings)) as client:
        result = client.post("/demo/ai-upload", json=payload, follow_redirects=True)
        assert result.status_code == 200
        assert "invalid JSON" in result.text
        assert "Traceback" not in result.text
        assert client.get("/proposals").json()["total"] == 0


def test_multipart_pdf_ingest_does_not_run_ai(tmp_path):
    from sqlalchemy import select

    from backend.app.models import AIExtractionRun, Proposal, RawDocument
    from tests.demo.pdf_fixtures import build_text_pdf

    settings = _settings(tmp_path)
    pdf = build_text_pdf("Disegno di legge DDL S. 2047. Presentato da Governo.")
    with TestClient(create_app(settings)) as client:
        result = client.post(
            "/demo/ai-upload/ingest",
            files={"document": ("DDL S. 2047.pdf", pdf, "")},
            data={
                "source_url": "https://www.senato.it/leg/19/BGT/Schede/Ddliter/2047.htm",
                "source_name": "Senato della Repubblica",
                "mode": "local",
            },
        )
        assert result.status_code == 200
        payload = result.json()
        assert payload["page_count"] == 1
        assert payload["filename"].endswith(".pdf")
        assert client.get("/proposals").json()["total"] == 0

    engine = create_db_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(RawDocument)) == 1
            assert session.scalar(select(func.count()).select_from(AIExtractionRun)) == 0
            assert session.scalar(select(func.count()).select_from(Proposal)) == 0
    finally:
        engine.dispose()


def test_multipart_empty_mime_large_pdf_is_accepted(tmp_path):
    from tests.demo.pdf_fixtures import build_text_pdf

    settings = _settings(tmp_path)
    pdf = build_text_pdf("Atto Senato", pad_bytes=5_200_000)
    with TestClient(create_app(settings)) as client:
        result = client.post(
            "/demo/ai-upload/ingest",
            files={"document": ("ddl-2047.pdf", pdf, "application/octet-stream")},
            data={
                "source_url": "https://www.senato.it/leg/19/BGT/Schede/Ddliter/2047.htm",
                "source_name": "Senato della Repubblica",
                "mode": "local",
            },
        )
        assert result.status_code == 200
        assert result.json()["page_count"] == 1
        assert client.get("/proposals").json()["total"] == 0


def test_multipart_invalid_and_oversized_pdf_are_rejected(tmp_path):
    from tests.demo.pdf_fixtures import build_text_pdf

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'upload.db'}",
        raw_storage_path=tmp_path / "raw",
        demo_upload_path=tmp_path / "uploads",
        enable_demo_ui=True,
        admin_reviewer_identity="ceo-editor",
        admin_api_key="ceo-demo-admin-key-local-only",
        ai_max_document_bytes=1000,
    )
    with TestClient(create_app(settings)) as client:
        invalid = client.post(
            "/demo/ai-upload/ingest",
            files={"document": ("fake.pdf", b"not-a-pdf", "")},
            data={"source_url": "https://www.senato.it/ddl/1", "mode": "local"},
        )
        assert invalid.status_code == 400
        assert invalid.json()["error"] == "Unsupported file type"
        oversized = client.post(
            "/demo/ai-upload/ingest",
            files={"document": ("big.pdf", build_text_pdf("DDL", pad_bytes=2000), "")},
            data={"source_url": "https://www.senato.it/ddl/1", "mode": "local"},
        )
        assert oversized.status_code == 400
        assert oversized.json()["error"] == "File too large"


def _ingest_local(client):
    result = client.post(
        "/demo/ai-upload/ingest",
        files={"document": ("tiny.html", LOCAL_HTML, "text/html")},
        data={
            "source_url": "https://www.senato.it/leg/19/BGT/Schede/Ddliter/2047.htm",
            "source_name": "Senato della Repubblica",
            "mode": "local",
        },
    )
    assert result.status_code == 200
    return result.json()


def _extract_payload(ingested):
    return {
        "raw_document_id": ingested["raw_document_id"],
        "filename": ingested["filename"],
        "mode": ingested["mode"],
        "fixture_key": ingested.get("fixture_key") or "",
        "source_url": ingested["source_url"],
        "source_name": ingested["source_name"],
    }


def test_extract_timeout_returns_safe_json_error(tmp_path, monkeypatch):
    from backend.app.ai.base import ExtractionProviderTimeoutError
    from backend.app.ai.ollama_provider import OllamaStructuredExtractionProvider

    settings = _settings(tmp_path)

    def timeout(self, request):
        del request
        raise ExtractionProviderTimeoutError(
            "The local Ollama model timed out before returning structured output."
        )

    monkeypatch.setattr(OllamaStructuredExtractionProvider, "extract", timeout)
    with TestClient(create_app(settings)) as client:
        ingested = _ingest_local(client)
        result = client.post("/demo/ai-upload/extract", json=_extract_payload(ingested))
        assert result.status_code == 504
        body = result.json()
        assert body["status"] == "error"
        assert body["error_code"] == "local_ai_timeout"
        assert body["message"] == "Local AI analysis did not complete within the allowed time."
        assert "Traceback" not in result.text
        assert "/Users/" not in result.text
        listing = client.get("/proposals").json()
        assert listing["total"] == 0
        assert "ollama" not in str(listing).casefold()


def test_extract_connection_error_returns_safe_json_error(tmp_path, monkeypatch):
    from backend.app.ai.base import ExtractionProviderError
    from backend.app.ai.ollama_provider import OllamaStructuredExtractionProvider

    settings = _settings(tmp_path)

    def down(self, request):
        del request
        raise ExtractionProviderError(
            "Ollama is not running at http://127.0.0.1:11434. Start it with: ollama serve"
        )

    monkeypatch.setattr(OllamaStructuredExtractionProvider, "extract", down)
    with TestClient(create_app(settings)) as client:
        ingested = _ingest_local(client)
        result = client.post("/demo/ai-upload/extract", json=_extract_payload(ingested))
        assert result.status_code == 503
        body = result.json()
        assert body["error_code"] == "local_ai_unavailable"
        assert body["message"] == "Local AI service unavailable"
        assert "Traceback" not in result.text
        assert client.get("/proposals").json()["total"] == 0


def test_extract_malformed_and_schema_errors_are_safe(tmp_path, monkeypatch):
    from backend.app.ai.base import ExtractionProviderOutputError
    from backend.app.ai.ollama_provider import OllamaStructuredExtractionProvider
    from backend.app.models import AIExtractionRun, Proposal
    from sqlalchemy import select

    settings = _settings(tmp_path)

    def malformed(self, request):
        del request
        raise ExtractionProviderOutputError(
            "Ollama returned malformed JSON",
            raw_output="{bad",
        )

    monkeypatch.setattr(OllamaStructuredExtractionProvider, "extract", malformed)
    with TestClient(create_app(settings)) as client:
        ingested = _ingest_local(client)
        result = client.post("/demo/ai-upload/extract", json=_extract_payload(ingested))
        assert result.status_code == 422
        body = result.json()
        assert body["error_code"] == "local_ai_invalid_output"
        assert "invalid JSON" in body["message"]
        assert "Traceback" not in result.text
        assert client.get("/proposals").json()["total"] == 0

    def schema_miss(self, request):
        del request
        raise ExtractionProviderOutputError(
            "Ollama JSON did not match proposal_claim_schema_v1",
            raw_output={"candidates": [{"confidence": "high", "abstention_reason": None}]},
        )

    monkeypatch.setattr(OllamaStructuredExtractionProvider, "extract", schema_miss)
    with TestClient(create_app(settings)) as client:
        ingested = _ingest_local(client)
        result = client.post("/demo/ai-upload/extract", json=_extract_payload(ingested))
        assert result.status_code == 422
        body = result.json()
        assert body["error_code"] == "local_ai_schema"
        assert "incomplete structured result" in body["message"]
        assert client.get("/proposals").json()["total"] == 0

    engine = create_db_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            run = session.scalar(select(AIExtractionRun))
            assert run.status.value == "failed"
            assert session.scalar(select(func.count()).select_from(Proposal)) == 0
            assert session.scalar(select(func.count()).select_from(ProposalDraft)) == 0
    finally:
        engine.dispose()


def test_force_rerun_creates_new_run_without_publishing(tmp_path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        created = client.post("/demo/ai-upload/sample", follow_redirects=True)
        assert created.status_code == 200
        assert client.get("/proposals").json()["total"] == 0
        engine = create_db_engine(settings.database_url)
        try:
            session_factory = create_session_factory(engine)
            with session_factory() as session:
                first_run = session.scalar(select(AIExtractionRun))
                raw_document_id = first_run.raw_document_id
                first_run_id = first_run.id
        finally:
            engine.dispose()
        reused = client.post(
            "/demo/ai-upload/extract",
            json={
                "raw_document_id": raw_document_id,
                "filename": "ceo_ddl_60476.html",
                "mode": "fake",
                "fixture_key": "ceo-ddl-60476",
                "source_url": "https://dati.senato.it/ddl/60476.html",
                "source_name": "Senato della Repubblica",
                "force_rerun": False,
            },
        )
        assert reused.status_code == 200
        forced = client.post(
            "/demo/ai-upload/extract",
            json={
                "raw_document_id": raw_document_id,
                "filename": "ceo_ddl_60476.html",
                "mode": "fake",
                "fixture_key": "ceo-ddl-60476",
                "source_url": "https://dati.senato.it/ddl/60476.html",
                "source_name": "Senato della Repubblica",
                "force_rerun": True,
            },
        )
        assert forced.status_code == 200
        assert "/demo/ai-draft/" in forced.json()["redirect"]
        assert client.get("/proposals").json()["total"] == 0

    engine = create_db_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            run_ids = set(session.scalars(select(AIExtractionRun.id)))
            assert first_run_id in run_ids
            assert len(run_ids) == 2
            assert session.scalar(select(func.count()).select_from(ProposalDraft)) == 1
            proposal = session.scalar(select(Proposal))
            assert proposal.published_at is None
    finally:
        engine.dispose()

