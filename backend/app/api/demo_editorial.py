from base64 import b64decode
from datetime import datetime, timezone
from html import escape
import logging
from pathlib import Path as FilePath
import re
from typing import Annotated, Literal
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker
from starlette.datastructures import UploadFile as StarletteUploadFile

from backend.app.ai import DEFAULT_OLLAMA_MODEL, OllamaStructuredExtractionProvider, probe_ollama
from backend.app.api.deps import get_api_settings, get_db_session, get_session_factory
from backend.app.core.config import Settings
from backend.app.demo.api_errors import demo_json_error
from backend.app.demo.fake_extraction_fixtures import (
    DEMO_FAKE_FIXTURES,
    NO_FIXTURE_MESSAGE,
    match_demo_fixture,
)
from backend.app.demo.upload_validation import DemoUploadError, validate_upload_content
from backend.app.models import (
    AIExtractionCandidate,
    AIExtractionCandidateEvidence,
    ProposalDraft,
    ProposalDraftStatus,
)
from backend.app.pipeline.chunk_selection import (
    coverage_note_from_payload,
    evidence_summary_from_payload,
)
from backend.app.pipeline.official_document_pipeline import OfficialDocumentPipelineError
from backend.app.schemas import ExtractedPoliticalClaim, ProposalObservation
from backend.app.services.official_extraction_runner import (
    extract_ingested_document,
    ingest_official_document,
    preview_chunk_selection,
)
from backend.app.services.official_source_display import citizen_source_url
from backend.app.services.proposal_extraction_service import ProposalExtractionError
from backend.app.services.proposal_review_service import (
    ProposalDraftNotFoundError,
    ProposalReviewService,
    ProposalReviewServiceError,
)
from backend.app.storage import StorageError


SIMULATION_LABEL = "Simulated AI extraction — CEO demo"
LOCAL_ANALYSIS_LABEL = "LOCAL AI ANALYSIS"
DEMO_MODE_LABEL = "Demo mode — simulated AI provider"
LOCAL_MODE_LABEL = "Real local AI — Ollama"
FALLBACK_MODE_LABEL = "Deterministic demo fallback"
router = APIRouter(prefix="/demo", tags=["demo-editorial"])
logger = logging.getLogger("verapolitica.demo")
_MONEY_RE = re.compile(
    r"(€\s?\d[\d.\s]{0,24}\d(?:\s?(?:mln|milioni|miliardi|euro|eur))?|"
    r"\d[\d.\s]{1,24}\d\s?(?:euro|eur|mln|milioni|miliardi))",
    re.IGNORECASE,
)


class DemoUploadPayload(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    source_url: str = ""
    source_name: str = ""
    mode: Literal["auto", "local", "fake"] = "auto"


class DemoSelectPayload(BaseModel):
    raw_document_id: int = Field(gt=0)


class DemoExtractPayload(BaseModel):
    raw_document_id: int = Field(gt=0)
    filename: str = Field(min_length=1, max_length=255)
    mode: Literal["local", "fake"]
    fixture_key: str = ""
    source_url: str = ""
    source_name: str = ""


def demo_local_model(settings: Settings) -> str:
    return (settings.llm_model or "").strip() or DEFAULT_OLLAMA_MODEL


def _demo_local_provider(settings: Settings) -> OllamaStructuredExtractionProvider:
    return OllamaStructuredExtractionProvider(
        model_name=demo_local_model(settings),
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
        num_ctx=settings.ollama_num_ctx,
        structured_format=settings.ollama_structured_format,  # type: ignore[arg-type]
    )


def _ollama_status(settings: Settings) -> dict[str, object]:
    return probe_ollama(
        base_url=settings.ollama_base_url,
        model_name=demo_local_model(settings),
        timeout_seconds=0.4,
    )


def _optional_https_url(value: str) -> str | None:
    stripped = value.strip()
    if not stripped:
        return None
    parsed = urlsplit(stripped)
    if parsed.scheme != "https" or not parsed.hostname:
        raise DemoUploadError("Official source URL must be an absolute HTTPS URL.")
    return stripped


def _store_upload(directory: FilePath, filename: str, content: bytes) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (directory / f"{stamp}-{filename}").write_bytes(content)
    except OSError as exc:
        raise DemoUploadError("Upload could not be saved") from exc


def _fixture_by_key(key: str):
    for fixture in DEMO_FAKE_FIXTURES:
        if fixture.key == key:
            return fixture
    return None


def _friendly_error(exc: BaseException) -> str:
    message = str(exc).strip() or "Document analysis failed. Nothing was published."
    if "\n" in message or ".py" in message or "Traceback" in message:
        return "Document analysis failed. Nothing was published."
    lowered = message.casefold()
    if "unsupported file type" in lowered or "does not look like a pdf" in lowered:
        return "Unsupported file type"
    if "exceeds the" in lowered and "byte" in lowered:
        return "File too large"
    if "ocr" in lowered or "no extractable text" in lowered:
        return "PDF contains no extractable text"
    if "could not be saved" in lowered:
        return "Upload could not be saved"
    if "not running" in lowered or "not installed" in lowered or "ollama serve" in lowered:
        return "Local AI service unavailable"
    if "malformed json" in lowered or "invalid structured output" in lowered:
        return "The local model returned invalid JSON. Nothing was published."
    if "proposal_claim_schema" in lowered:
        return "Local AI returned an incomplete structured result. No draft was created."
    if "maximum of" in lowered and "chunks" in lowered:
        return "This document is too large to process in the demo."
    if "no relevant evidence" in lowered:
        return "No relevant evidence sections could be selected from this document."
    return message[:400]


def _local_attempt_html(run) -> str:
    if run is None or run.provider != "ollama":
        return ""
    payload = run.provider_response if isinstance(run.provider_response, dict) else {}
    diagnostics = payload.get("ollama_diagnostics") if isinstance(payload, dict) else None
    if not isinstance(diagnostics, dict):
        return ""
    attempts = diagnostics.get("attempts") or []
    count = int(diagnostics.get("attempt_count") or len(attempts) or 1)
    labels = {1: "First attempt", 2: "Second attempt"}
    status_labels = {
        "accepted": "accepted",
        "schema_invalid": "schema validation failed",
        "malformed_json": "invalid JSON",
        "timeout": "timed out",
        "unavailable": "unavailable",
        "http_error": "provider error",
    }
    rows = [
        (
            '<div class="data-point"><small>Local AI attempts</small>'
            f"<strong>{escape(str(count))}</strong></div>"
        )
    ]
    if count < 2:
        return "".join(rows)
    for item in attempts:
        if not isinstance(item, dict):
            continue
        number = item.get("attempt")
        status = status_labels.get(
            str(item.get("validation_status") or ""),
            str(item.get("validation_status") or "unknown"),
        )
        label = labels.get(number, f"Attempt {number}")
        rows.append(
            f'<div class="data-point"><small>{escape(str(label))}</small>'
            f"<strong>{escape(status)}</strong></div>"
        )
    return "".join(rows)


def _resolve_mode(
    requested: str,
    *,
    settings: Settings,
    content: bytes,
) -> Literal["local", "fake"]:
    if requested == "fake":
        return "fake"
    if requested == "local":
        return "local"
    status_payload = _ollama_status(settings)
    if status_payload.get("available"):
        return "local"
    if match_demo_fixture(content) is not None:
        return "fake"
    raise DemoUploadError(
        "Local AI is not running. Start Ollama with `ollama serve`, or use "
        "Deterministic demo fallback."
    )


def _render_upload(
    *,
    settings: Settings,
    notice: str | None = None,
    error: bool = False,
) -> HTMLResponse:
    fixture = DEMO_FAKE_FIXTURES[0]
    ollama = _ollama_status(settings)
    ollama_ok = bool(ollama.get("available"))
    has_model = bool(ollama.get("has_model"))
    default_mode = "local" if ollama_ok else "fake"
    model_name = demo_local_model(settings)
    status_class = "is-connected" if ollama_ok and has_model else (
        "is-error" if not ollama_ok else ""
    )
    status_text = str(ollama.get("message") or "")
    body = f"""
        <section class="hero">
          <div>
            <p class="eyebrow">Editorial tool</p>
            <h1>AI-assisted document analysis</h1>
            <p class="hero-copy">
              Upload an official HTML or text-based PDF. VeraPolitica extracts the
              text locally, selects relevant evidence sections, and runs structured
              extraction. The result is an unpublished editorial draft.
              Nothing becomes public until an editor approves it.
            </p>
          </div>
          <div class="api-config">
            <span class="badge badge-review">{escape(LOCAL_MODE_LABEL if default_mode == "local" else DEMO_MODE_LABEL)}</span>
            <p class="hero-copy" style="margin-top:12px">
              Two modes: <strong>REAL LOCAL AI</strong> via Ollama (no API cost),
              and <strong>Deterministic demo fallback</strong> if the local model
              is unavailable.
            </p>
          </div>
        </section>
        <section class="card proposal-review-card">
          <div class="card-header">
            <div>
              <p class="eyebrow">Official document</p>
              <h2>Upload or load the sample Senato DDL</h2>
            </div>
          </div>
          <div class="card-body">
            <div class="mode-switch" role="radiogroup" aria-label="Extraction mode">
              <label class="mode-card{" is-selected" if default_mode == "local" else ""}">
                <input type="radio" name="extract-mode" value="local"{" checked" if default_mode == "local" else ""} />
                <strong>REAL LOCAL AI</strong>
                <small>Provider: Ollama · no API cost</small>
              </label>
              <label class="mode-card{" is-selected" if default_mode == "fake" else ""}">
                <input type="radio" name="extract-mode" value="fake"{" checked" if default_mode == "fake" else ""} />
                <strong>{escape(FALLBACK_MODE_LABEL)}</strong>
                <small>{escape(DEMO_MODE_LABEL)}</small>
              </label>
            </div>
            <p class="connection-pill {status_class}" id="ollama-status">
              <span class="status-dot"></span>
              {escape(status_text)} Model: <code>{escape(model_name)}</code>
            </p>
            <form id="sample-form" method="post" action="/demo/ai-upload/sample">
              <p>
                The sample is real official Senato HTML for DDL 60476. The
                deterministic fallback uses a fixture, not a live LLM.
              </p>
              <button class="button button-secondary" type="submit">
                Load sample official document
              </button>
            </form>
            <div class="section-rule"></div>
            <form id="upload-form" method="post" action="/demo/ai-upload/ingest" enctype="multipart/form-data">
            <input id="document-file" class="file-input-hidden" type="file" name="document" accept=".pdf,.html,.htm,application/pdf,text/html" hidden />
            <div id="drop-zone" class="drop-zone" tabindex="0" role="button" aria-controls="document-file" aria-label="Drop official HTML or PDF, or press Enter to choose a file">
              <strong>Drop official HTML or PDF here</strong>
              <p>Accepted: .html, .htm, text-based .pdf</p>
              <label for="document-file" id="choose-file-button" class="button button-secondary file-picker-button" tabindex="0">Choose PDF or HTML</label>
            </div>
            <p id="selected-file" class="hero-copy" aria-live="polite">No file selected.</p>
            <div class="profile-grid">
              <label class="data-point">
                <small>Official source URL (required for local AI)</small>
                <input id="source-url" name="source_url" type="url" placeholder="{escape(fixture.source_url)}" />
              </label>
              <label class="data-point">
                <small>Source name</small>
                <input id="source-name" name="source_name" type="text" value="{escape(fixture.source_name)}" />
              </label>
            </div>
            <input type="hidden" id="mode-field" name="mode" value="{escape(default_mode)}" />
            <div class="button-group" style="margin-top:18px">
              <button id="analyze-button" class="button button-primary" type="submit" disabled>
                Analyze
              </button>
            </div>
            </form>
            <div id="progress-panel" class="progress-panel" hidden>
              <p class="eyebrow">Working locally</p>
              <ol class="progress-steps">
                <li data-step="ingest">Processing document</li>
                <li data-step="pages">Waiting for page count</li>
                <li data-step="select">Selecting relevant evidence</li>
                <li data-step="selected">Waiting for selected sections</li>
                <li data-step="sent">Waiting for sections sent to local AI</li>
                <li data-step="extract">Running local AI</li>
              </ol>
              <p id="progress-copy" class="hero-copy">Preparing…</p>
            </div>
          </div>
        </section>
        <div id="demo-config" hidden
          data-default-mode="{escape(default_mode)}"
          data-model="{escape(model_name)}"></div>
        <script src="/demo/ai-upload.js?v=evidence-summary"></script>
    """
    return _page(
        body,
        title="AI-assisted document analysis",
        notice=notice,
        error=error,
        mode_label=LOCAL_MODE_LABEL if default_mode == "local" else DEMO_MODE_LABEL,
    )


def _prepare_upload(
    *,
    settings: Settings,
    filename: str,
    content: bytes,
    source_url: str,
    source_name: str,
    mode: str,
) -> dict:
    safe_name, content_type = validate_upload_content(
        filename=filename,
        content=content,
        max_bytes=settings.ai_max_document_bytes,
    )
    resolved_mode = _resolve_mode(mode, settings=settings, content=content)
    fixture = match_demo_fixture(content)
    if resolved_mode == "fake" and fixture is None:
        raise DemoUploadError(NO_FIXTURE_MESSAGE)
    official_url = _optional_https_url(source_url)
    if official_url is None:
        if fixture is not None:
            official_url = fixture.source_url
        else:
            raise DemoUploadError(
                "Provide the official HTTPS source URL for this document."
            )
    display_name = source_name.strip() or (
        fixture.source_name if fixture is not None else "Official source"
    )
    _store_upload(settings.demo_upload_path, safe_name, content)
    ingestion = ingest_official_document(
        settings=settings,
        content=content,
        source_url=official_url,
        source_name=display_name,
        content_type=content_type,
        source_key=fixture.source_key if fixture is not None else None,
    )
    return {
        "filename": safe_name,
        "mode": resolved_mode,
        "fixture_key": fixture.key if fixture is not None else "",
        "source_url": official_url,
        "source_name": display_name,
        **ingestion,
    }


def _extract_prepared(*, settings: Settings, prepared: dict) -> dict:
    if prepared["mode"] == "fake":
        fixture = _fixture_by_key(prepared.get("fixture_key") or "")
        if fixture is None:
            raise DemoUploadError(NO_FIXTURE_MESSAGE)
        summary = extract_ingested_document(
            settings=settings,
            raw_document_id=prepared["raw_document_id"],
            fake_response=fixture.response_path,
        )
    else:
        summary = extract_ingested_document(
            settings=settings,
            raw_document_id=prepared["raw_document_id"],
            provider=_demo_local_provider(settings),
        )
    draft_ids = summary.get("proposal_draft_ids") or []
    if not draft_ids or summary.get("accepted_count", 0) < 1:
        if prepared["mode"] == "fake":
            raise DemoUploadError(NO_FIXTURE_MESSAGE)
        if summary.get("abstained_count", 0) > 0:
            raise DemoUploadError(
                "The local model abstained because the selected evidence was insufficient. "
                "Nothing was published."
            )
        raise DemoUploadError(
            "The local model did not produce any evidence-backed proposal. "
            "Nothing was published."
        )
    document = quote(prepared["filename"])
    notice = (
        "Local AI extraction complete. The draft is unpublished."
        if prepared["mode"] == "local"
        else "Simulated extraction complete. The draft is unpublished."
    )
    return {
        **summary,
        "redirect": (
            f"/demo/ai-draft/{draft_ids[0]}"
            f"?document={document}"
            f"&notice={quote(notice)}"
        ),
    }


def _analyze_document(
    *,
    settings: Settings,
    filename: str,
    content: bytes,
    source_url: str,
    source_name: str,
    mode: str = "auto",
) -> RedirectResponse:
    try:
        prepared = _prepare_upload(
            settings=settings,
            filename=filename,
            content=content,
            source_url=source_url,
            source_name=source_name,
            mode=mode,
        )
        extracted = _extract_prepared(settings=settings, prepared=prepared)
    except DemoUploadError as exc:
        return RedirectResponse(
            url=f"/demo/ai-upload?notice={quote(_friendly_error(exc))}&error=1",
            status_code=303,
        )
    except (
        OfficialDocumentPipelineError,
        ProposalExtractionError,
        StorageError,
        ValueError,
        OSError,
    ) as exc:
        return RedirectResponse(
            url=f"/demo/ai-upload?notice={quote(_friendly_error(exc))}&error=1",
            status_code=303,
        )
    return RedirectResponse(url=extracted["redirect"], status_code=303)


async def _load_ingest_payload(
    request: Request,
) -> tuple[str, bytes, str, str, str]:
    header = (request.headers.get("content-type") or "").casefold()
    if "multipart/form-data" in header:
        form = await request.form()
        upload = form.get("document")
        if not isinstance(upload, StarletteUploadFile):
            raise DemoUploadError("The uploaded file could not be read.")
        filename = upload.filename or "document.pdf"
        content = await upload.read()
        return (
            filename,
            content,
            str(form.get("source_url") or ""),
            str(form.get("source_name") or ""),
            str(form.get("mode") or "auto"),
        )
    try:
        payload = DemoUploadPayload.model_validate(await request.json())
        return (
            payload.filename,
            b64decode(payload.content_base64),
            payload.source_url,
            payload.source_name,
            payload.mode,
        )
    except DemoUploadError:
        raise
    except Exception as exc:
        raise DemoUploadError("The uploaded file could not be read.") from exc


def _json_error(exc: BaseException) -> JSONResponse:
    return demo_json_error(exc, default_status=400)


def _page(
    body: str,
    *,
    title: str,
    notice: str | None = None,
    error: bool = False,
    mode_label: str = DEMO_MODE_LABEL,
) -> HTMLResponse:
    banner = ""
    if notice:
        kind = " is-error" if error else ""
        banner = f'<div class="notice is-visible{kind}" role="status">{escape(notice)}</div>'
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
    <link rel="stylesheet" href="/demo/styles.css?v=evidence-summary" />
  </head>
  <body>
    <div class="page-shell">
      <header class="topbar">
        <a class="brand" href="/demo/ai-upload" aria-label="VeraPolitica editorial demo">
          <span class="brand-mark" aria-hidden="true">VP</span>
          <span>
            <strong>VeraPolitica</strong>
            <small>Local editorial inspection</small>
          </span>
        </a>
        <div class="status-cluster">
          <span class="mode-pill">{escape(mode_label)}</span>
        </div>
      </header>
      <main>
        {banner}
        {body}
      </main>
      <footer>
        <span>Local editorial view. Not part of the public citizen archive.</span>
        <span>Nothing becomes public until an editor approves it.</span>
      </footer>
    </div>
  </body>
</html>"""
    return HTMLResponse(html)


def _badge(status_value: str) -> tuple[str, str]:
    mapping = {
        "pending": ("Pending", "badge-pending"),
        "in_review": ("In review", "badge-review"),
        "approved": ("Approved", "badge-approved"),
        "rejected": ("Rejected", "badge-rejected"),
        "superseded": ("Superseded", "badge-muted"),
        "accepted": ("Accepted", "badge-approved"),
    }
    return mapping.get(status_value, (status_value.replace("_", " ").title(), "badge-muted"))


def _load_draft(session: Session, draft_id: int) -> ProposalDraft:
    draft = session.scalar(
        select(ProposalDraft)
        .where(ProposalDraft.id == draft_id)
        .options(
            selectinload(ProposalDraft.evidence),
            selectinload(ProposalDraft.review),
        )
    )
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="proposal draft not found",
        )
    return draft


def _ai_candidate(session: Session, draft: ProposalDraft) -> AIExtractionCandidate | None:
    return session.scalar(
        select(AIExtractionCandidate)
        .where(AIExtractionCandidate.proposal_draft_id == draft.id)
        .options(
            selectinload(AIExtractionCandidate.run),
            selectinload(AIExtractionCandidate.evidence).selectinload(
                AIExtractionCandidateEvidence.chunk
            ),
        )
    )


def _numeric_facts(*texts: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for match in _MONEY_RE.findall(text or ""):
            value = " ".join(match.split())
            key = value.casefold()
            if key not in seen:
                seen.add(key)
                found.append(value)
    return found


def _render_draft(
    draft: ProposalDraft,
    candidate: AIExtractionCandidate | None,
    *,
    notice: str | None = None,
    error: bool = False,
    document_name: str | None = None,
) -> HTMLResponse:
    observation = ProposalObservation.model_validate(draft.proposed_data)
    unresolved = observation.metadata.get("_unresolved_actors") or []
    resolved = observation.metadata.get("_resolved_actors") or []
    if not isinstance(unresolved, list):
        unresolved = []
    if not isinstance(resolved, list):
        resolved = []
    status_label, status_class = _badge(draft.status.value)
    provider = candidate.run.provider if candidate is not None else "none"
    local = provider == "ollama"
    simulated = provider == "fake"
    label = (
        LOCAL_ANALYSIS_LABEL
        if local
        else SIMULATION_LABEL if simulated else "AI-assisted draft"
    )
    extracted = None
    if candidate is not None:
        extracted = ExtractedPoliticalClaim.model_validate(candidate.model_output)
    actor_rows = []
    for actor in observation.actors:
        actor_rows.append(
            f"<li><strong>{escape(actor.display_name)}</strong>"
            f"<small>{escape(actor.role.value)} · {escape(actor.actor_type.value)}</small></li>"
        )
    if not actor_rows:
        actor_rows.append("<li>No actor mention extracted.</li>")
    evidence_rows = []
    if candidate is not None:
        for item in candidate.evidence:
            chunk_index = item.chunk.chunk_index if item.chunk is not None else "n/a"
            page = "n/a" if item.page is None else str(item.page)
            evidence_rows.append(
                "<article class='evidence evidence-highlight'>"
                f"<p class='eyebrow'>Evidence from official source</p>"
                f"<strong>Exact excerpt · chunk {escape(str(chunk_index))}"
                f" · page {escape(page)}</strong>"
                f"<blockquote class='evidence-value'>{escape(item.supporting_text)}</blockquote>"
                "</article>"
            )
    if not evidence_rows:
        evidence_rows.append("<p>No AI evidence is attached to this draft.</p>")
    final = draft.status in {
        ProposalDraftStatus.APPROVED,
        ProposalDraftStatus.REJECTED,
        ProposalDraftStatus.SUPERSEDED,
    }
    start_disabled = "disabled" if draft.status is not ProposalDraftStatus.PENDING else ""
    decide_disabled = "disabled" if final else ""
    topic = extracted.topic.value if extracted is not None and extracted.topic else "not provided"
    confidence = (
        extracted.confidence.value
        if extracted is not None and extracted.confidence
        else "not provided"
    )
    model = candidate.run.model if candidate is not None else "none"
    prompt = candidate.run.prompt_version if candidate is not None else "none"
    schema = candidate.run.schema_version if candidate is not None else "none"
    attempt_html = _local_attempt_html(candidate.run if candidate is not None else None)
    validation = candidate.status.value if candidate is not None else "not an AI draft"
    validation_label, validation_class = _badge(validation)
    public_link = f"/app/?proposal={draft.proposal_id}"
    source_url = citizen_source_url(str(observation.official_url))
    unresolved_count = len(unresolved)
    resolved_count = len(resolved)
    actor_status = (
        "Resolved to a published identity"
        if resolved_count and not unresolved_count
        else "Unresolved — stored as a source mention only"
    )
    document_label = document_name or "Official uploaded document"
    published = draft.status is ProposalDraftStatus.APPROVED
    citizen_button = (
        f'<a class="button button-primary" href="{public_link}">View published citizen page</a>'
        if published
        else ""
    )
    selection = {}
    if candidate is not None and isinstance(candidate.run.provider_response, dict):
        raw_selection = candidate.run.provider_response.get("chunk_selection")
        if isinstance(raw_selection, dict):
            selection = raw_selection
    coverage = coverage_note_from_payload(selection) if selection else ""
    dates = []
    if observation.introduced_at:
        dates.append(f"Announced {observation.introduced_at.isoformat()}")
    target = observation.metadata.get("target_date")
    if target:
        dates.append(f"Target {escape(str(target))}")
    date_label = "; ".join(dates) if dates else "not extracted"
    money_bits = _numeric_facts(
        observation.exact_statement or "",
        observation.summary or "",
        *(item.supporting_text for item in (candidate.evidence if candidate else ())),
    )
    money_label = "; ".join(money_bits) if money_bits else "not extracted"
    evidence_heading = (
        "Evidence from official document" if local else "Evidence from official source"
    )
    summary_items = evidence_summary_from_payload(selection) if selection else []
    summary_block = ""
    if summary_items:
        items = "".join(f"<li>{escape(item)}</li>" for item in summary_items)
        summary_block = (
            '<div class="evidence-selected-summary">'
            '<p class="eyebrow">Evidence selected</p>'
            f"<ul>{items}</ul>"
            "</div>"
        )
    coverage_block = (
        f'<p class="hero-copy coverage-note">{escape(coverage)}</p>' if coverage else ""
    )
    coverage_block = f"{coverage_block}{summary_block}"
    incomplete = ""
    if selection and not selection.get("full_document_coverage"):
        incomplete = (
            '<p class="hero-copy">This is extraction of supported political facts from '
            "selected evidence sections, not an exhaustive legal summary of the full document.</p>"
        )
    body = f"""
        <section class="hero">
          <div>
            <p class="eyebrow">Local editorial inspection</p>
            <h1>{escape(label)}</h1>
            <p class="hero-copy">
              Document: <strong>{escape(document_label)}</strong>
            </p>
            {coverage_block}
            {incomplete}
            <p class="hero-copy">
              This screen is for the operator walkthrough. The citizen archive does not
              show provider, model, prompt, confidence, or reviewer metadata.
            </p>
          </div>
          <div class="api-config">
            <span class="badge {status_class}">{escape(status_label)}</span>
            <p class="hero-copy" style="margin-top:12px">Draft {draft.id} · Proposal {draft.proposal_id}</p>
            <small>Nothing becomes public until an editor approves it.</small>
          </div>
        </section>
        <section class="card proposal-review-card evidence-panel">
          <div class="card-header">
            <div>
              <p class="eyebrow">Official source</p>
              <h2 class="wrap-title">{escape(observation.title)}</h2>
            </div>
            <span class="badge {validation_class}">{escape(validation_label)}</span>
          </div>
          <div class="card-body">
            <p>{escape(observation.exact_statement or observation.summary or "")}</p>
            <div class="profile-grid">
              <div class="data-point"><small>Document</small><strong>{escape(document_label)}</strong></div>
              <div class="data-point"><small>Official source</small><strong><a href="{escape(source_url)}" target="_blank" rel="noopener noreferrer">Senato della Repubblica</a></strong></div>
              <div class="data-point"><small>Proposal type</small><strong>{escape(observation.proposal_type.value.replace("_", " "))}</strong></div>
              <div class="data-point"><small>Status</small><strong>{escape(observation.source_status_label or observation.normalized_status.value)}</strong></div>
              <div class="data-point"><small>Topics</small><strong>{escape(topic)}</strong></div>
              <div class="data-point"><small>Actors</small><strong>{escape(observation.actors[0].display_name if observation.actors else "none")}</strong></div>
              <div class="data-point"><small>Actor resolution</small><strong>{escape(actor_status)}</strong></div>
              <div class="data-point"><small>Important dates</small><strong>{date_label}</strong></div>
              <div class="data-point"><small>Numeric / financial facts</small><strong>{escape(money_label)}</strong></div>
              <div class="data-point"><small>Confidence</small><strong>{escape(confidence)}</strong></div>
              <div class="data-point"><small>Validation</small><strong>{escape(validation)}</strong></div>
              <div class="data-point"><small>Provider</small><strong>{escape(provider)}</strong></div>
              <div class="data-point"><small>Model</small><strong>{escape(model)}</strong></div>
              <div class="data-point"><small>Prompt</small><strong>{escape(prompt)}</strong></div>
              <div class="data-point"><small>Schema</small><strong>{escape(schema)}</strong></div>
              {attempt_html}
            </div>
            <div class="section-rule"></div>
            <div class="subheading"><h3>{escape(evidence_heading)}</h3><span>Exact substring of the official document</span></div>
            <div class="evidence-list">{''.join(evidence_rows)}</div>
            <div class="section-rule"></div>
            <div class="subheading"><h3>Actors</h3><span>No name-only identity linking</span></div>
            <ul class="possible-match-list">{''.join(actor_rows)}</ul>
          </div>
          <div class="review-bar">
            <div>
              <strong>Human decision</strong>
              <small>Nothing becomes public until an editor approves it.</small>
            </div>
            <div class="button-group">
              <form method="post" action="/demo/ai-draft/{draft.id}/start-review">
                <button class="button button-secondary" type="submit" {start_disabled}>Start review</button>
              </form>
              <form method="post" action="/demo/ai-draft/{draft.id}/reject">
                <button class="button button-danger" type="submit" {decide_disabled}>Reject</button>
              </form>
              <form method="post" action="/demo/ai-draft/{draft.id}/approve">
                <button class="button button-primary" type="submit" {decide_disabled}>Approve</button>
              </form>
              {citizen_button}
            </div>
          </div>
        </section>
        <section class="reset-card">
          <div>
            <p class="eyebrow">Reset</p>
            <p>python -m scripts.reset_ceo_ai_demo</p>
          </div>
          <a class="button button-secondary" href="/demo/ai-upload">Analyze another document</a>
        </section>
    """
    return _page(
        body,
        title=f"{label} · draft {draft.id}",
        notice=notice,
        error=error,
        mode_label=LOCAL_MODE_LABEL if local else DEMO_MODE_LABEL,
    )


@router.get("/ai-upload", response_class=HTMLResponse)
def upload_page(
    settings: Annotated[Settings, Depends(get_api_settings)],
    notice: str | None = None,
    error: int = 0,
) -> HTMLResponse:
    return _render_upload(settings=settings, notice=notice, error=bool(error))


@router.post("/ai-upload/sample")
def upload_sample(
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> RedirectResponse:
    fixture = DEMO_FAKE_FIXTURES[0]
    return _analyze_document(
        settings=settings,
        filename=fixture.document_name,
        content=fixture.html_path.read_bytes(),
        source_url=fixture.source_url,
        source_name=fixture.source_name,
        mode="fake",
    )


@router.post("/ai-upload")
async def upload_document(
    request: Request,
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> RedirectResponse:
    try:
        payload = DemoUploadPayload.model_validate(await request.json())
        content = b64decode(payload.content_base64)
    except Exception:
        return RedirectResponse(
            url=f"/demo/ai-upload?notice={quote('The uploaded file could not be read.')}&error=1",
            status_code=303,
        )
    return _analyze_document(
        settings=settings,
        filename=payload.filename,
        content=content,
        source_url=payload.source_url,
        source_name=payload.source_name,
        mode=payload.mode,
    )


@router.post("/ai-upload/ingest")
async def ingest_document(
    request: Request,
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> JSONResponse:
    try:
        filename, content, source_url, source_name, mode = await _load_ingest_payload(
            request
        )
        prepared = _prepare_upload(
            settings=settings,
            filename=filename,
            content=content,
            source_url=source_url,
            source_name=source_name,
            mode=mode,
        )
        return JSONResponse(
            {
                "raw_document_id": prepared["raw_document_id"],
                "page_count": prepared["page_count"],
                "chunk_count": prepared["chunk_count"],
                "filename": prepared["filename"],
                "mode": prepared["mode"],
                "fixture_key": prepared["fixture_key"],
                "source_url": prepared["source_url"],
                "source_name": prepared["source_name"],
            }
        )
    except (
        DemoUploadError,
        OfficialDocumentPipelineError,
        StorageError,
        ValueError,
        OSError,
    ) as exc:
        return _json_error(exc)
    except Exception:
        return JSONResponse(
            {"error": "The uploaded file could not be read."},
            status_code=400,
        )


@router.post("/ai-upload/select")
def select_document_chunks(
    payload: DemoSelectPayload,
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> JSONResponse:
    try:
        selection = preview_chunk_selection(
            settings=settings,
            raw_document_id=payload.raw_document_id,
        )
        return JSONResponse(selection)
    except (ValueError, OSError) as exc:
        return _json_error(exc)
    except Exception as exc:
        logger.exception("demo select failed")
        return demo_json_error(exc)


@router.post("/ai-upload/extract")
def extract_document_claims(
    payload: DemoExtractPayload,
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> JSONResponse:
    try:
        extracted = _extract_prepared(
            settings=settings,
            prepared={
                "raw_document_id": payload.raw_document_id,
                "filename": payload.filename,
                "mode": payload.mode,
                "fixture_key": payload.fixture_key,
                "source_url": payload.source_url,
                "source_name": payload.source_name,
            },
        )
        return JSONResponse({"redirect": extracted["redirect"]})
    except (
        DemoUploadError,
        OfficialDocumentPipelineError,
        ProposalExtractionError,
        StorageError,
        ValueError,
        OSError,
    ) as exc:
        return demo_json_error(exc)
    except Exception as exc:
        logger.exception("demo extract failed")
        return demo_json_error(exc)


@router.get("/ai-draft/{draft_id}", response_class=HTMLResponse)
def inspect_ai_draft(
    draft_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_db_session)],
    notice: str | None = None,
    document: str | None = None,
) -> HTMLResponse:
    draft = _load_draft(session, draft_id)
    return _render_draft(
        draft,
        _ai_candidate(session, draft),
        notice=notice,
        document_name=FilePath(document).name if document else None,
    )


@router.post("/ai-draft/{draft_id}/start-review")
def start_ai_draft_review(
    draft_id: Annotated[int, Path(gt=0)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> RedirectResponse:
    try:
        ProposalReviewService(session_factory).start_review(draft_id)
    except ProposalDraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProposalReviewServiceError as exc:
        return RedirectResponse(
            url=f"/demo/ai-draft/{draft_id}?notice={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/demo/ai-draft/{draft_id}?notice={quote('Review started. The draft is still unpublished.')}",
        status_code=303,
    )


@router.post("/ai-draft/{draft_id}/approve")
def approve_ai_draft(
    draft_id: Annotated[int, Path(gt=0)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> RedirectResponse:
    return _finalize(
        session_factory,
        settings,
        draft_id,
        "approve",
        "CEO showcase: reviewed official Senato DDL record",
    )


@router.post("/ai-draft/{draft_id}/reject")
def reject_ai_draft(
    draft_id: Annotated[int, Path(gt=0)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> RedirectResponse:
    return _finalize(
        session_factory,
        settings,
        draft_id,
        "reject",
        "CEO showcase: reviewed official Senato DDL record",
    )


def _finalize(
    session_factory: sessionmaker[Session],
    settings: Settings,
    draft_id: int,
    action: Literal["approve", "reject"],
    note: str,
) -> RedirectResponse:
    service = ProposalReviewService(session_factory)
    reviewer = settings.admin_reviewer_identity
    try:
        if action == "approve":
            service.approve(draft_id, reviewer=reviewer, note=note)
            message = "Approved and published. Citizen view still hides internal AI metadata."
        else:
            service.reject(draft_id, reviewer=reviewer, note=note)
            message = "Rejected. The draft remains unpublished."
    except ProposalDraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProposalReviewServiceError as exc:
        return RedirectResponse(
            url=f"/demo/ai-draft/{draft_id}?notice={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/demo/ai-draft/{draft_id}?notice={quote(message)}",
        status_code=303,
    )
