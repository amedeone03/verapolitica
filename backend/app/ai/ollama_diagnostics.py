from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import ValidationError

from backend.app.ai.base import ExtractionChunk, StructuredExtractionRequest
from backend.app.pipeline.chunk_selection import chunk_prompt_text, estimate_tokens
from backend.app.pipeline.prompts import load_proposal_extraction_prompt
from backend.app.schemas import PoliticalClaimExtraction


StructuredFormat = Literal["json_schema", "json"]
DEFAULT_OLLAMA_NUM_CTX = 8_192
MAX_SCHEMA_REPAIR_ATTEMPTS = 2
INVALID_JSON_PREVIEW_CHARS = 2_000
USER_PREFIX = (
    "Extract candidates from these official document chunks. "
    "Return only schema-valid JSON. Do not invent politician IDs "
    "or database identifiers. Every actor name must appear verbatim "
    "inside some evidence.supporting_text. The phrase "
    "Iniziativa Governativa does not contain Governo; if the actor is "
    "Governo, copy a short excerpt such as Governo Meloni-I.\n\n"
)
OLLAMA_JSON_FORMAT_INSTRUCTIONS = """
Return ONLY valid JSON. No markdown. No commentary.

Top-level format:
{"candidates":[]}

Every candidate object MUST include ALL of these fields:
claim_type, exact_statement, normalized_title, summary, topic, actor_mentions,
announced_at, target_date, evidence, confidence, abstention_reason.

A candidate must NEVER be partially populated. Do not return a candidate that
has confidence or abstention_reason but is missing claim_type, exact_statement,
normalized_title, or evidence.

If there is insufficient evidence for a complete candidate, return:
{"candidates":[]}

When the source is an official parliamentary bill / DISEGNO DI LEGGE:
- the bill itself may constitute a `proposal`
- use the official bill title or another exact source sentence as the
  evidence-grounded statement
- an explicit "Iniziativa Governativa" may support a government *role*, but
  actor_mentions.name must still appear verbatim in supporting_text
- if the actor name is "Governo", copy a short exact span that contains those
  letters, such as "Governo Meloni-I"; do not cite only "Iniziativa Governativa"
- current parliamentary status does NOT make the bill cease to be a proposal
- do not require natural-language wording such as "proponiamo..."
- do not infer facts not present in the selected chunks
- if the title / initiative cannot be grounded exactly, abstain with
  {"candidates":[]}
- every actor_mentions.name MUST appear as an exact substring of at least one
  evidence.supporting_text excerpt; add a separate evidence item if needed
- if you cannot copy an actor name into evidence, set actor_mentions to []
- for an institutional government actor named "Governo", copy a short exact
  excerpt that contains the literal characters "Governo" (for example
  "Governo Meloni-I" or "dal Governo"). "Iniziativa Governativa" alone is
  not enough, because it does not contain the substring "Governo"
- prefer a small number of topics directly supported by the selected evidence
- do not invent politician IDs or resolve names against a database

Evidence.supporting_text rules:
- MUST be an exact substring of a sent chunk
- MUST be <= 600 characters
- SHOULD normally be concise, ideally <= 300 characters
- MUST include only the minimum text needed to support the associated claim
- MUST NOT paste an entire metadata block or minister list when a shorter
  exact excerpt is sufficient
Never return supporting_text longer than 600 characters.

Optional dates:
- announced_at: include only when an explicit announcement or presentation
  date is present in the cited source text
- target_date: include only when the source explicitly states a future
  deadline or target date for the proposal itself
- do NOT use today's date as target_date
- a decree-law conversion expiry / "scadenza" is not a proposal target_date
  unless the source says it is the proposal's own deadline
- if unsupported, return null. Prefer null over a guessed date.

Short fictional example of an official bill candidate:
{"candidates":[{"claim_type":"proposal","exact_statement":"Disposizioni per la digitalizzazione degli archivi comunali.","normalized_title":"Disposizioni per la digitalizzazione degli archivi comunali","summary":"Disegno di legge di iniziativa governativa sulla digitalizzazione degli archivi comunali.","topic":"public_administration","actor_mentions":[{"name":"Governo","role":"government"}],"announced_at":null,"target_date":null,"evidence":[{"chunk_index":0,"page":null,"supporting_text":"Disposizioni per la digitalizzazione degli archivi comunali."},{"chunk_index":0,"page":null,"supporting_text":"Governo Meloni-I"}],"confidence":"high","abstention_reason":null}]}

Allowed enum values only:
- claim_type: "proposal" | "explicit_promise" | null
- topic: "economy" | "healthcare" | "education" | "environment" | "housing" | "transport" | "justice" | "immigration" | "foreign_policy" | "public_administration" | "other" | null
- actor role: "proposer" | "sponsor" | "co_sponsor" | "government" | "commitment_owner"
- confidence: "high" | "medium" | "low" | null
- abstention_reason: "insufficient_evidence" | "ambiguous_actor" | "unclear_commitment" | "incomplete_context" | "unsupported_document_content" | null
- announced_at / target_date: "YYYY-MM-DD" | null
- evidence.chunk_index: integer >= 0 already present in the input
- evidence.page: integer >= 1 only when the supplied chunk shows a page number; otherwise null
- evidence.supporting_text: exact substring copied from the supplied chunks,
  never longer than 600 characters

If the input chunks do not show page numbers, every evidence.page MUST be null.

Short fictional example of a complete candidate:
{"candidates":[{"claim_type":"proposal","exact_statement":"Si istituisce un fondo sperimentale di 2 milioni di euro per le biblioteche comunali.","normalized_title":"Fondo sperimentale per le biblioteche comunali","summary":"Il Governo propone un fondo di 2 milioni di euro per le biblioteche comunali.","topic":"education","actor_mentions":[{"name":"Governo","role":"government"}],"announced_at":null,"target_date":null,"evidence":[{"chunk_index":0,"page":null,"supporting_text":"Si istituisce un fondo sperimentale di 2 milioni di euro per le biblioteche comunali."},{"chunk_index":0,"page":null,"supporting_text":"Presentato dal Governo."}],"confidence":"high","abstention_reason":null}]}

Copy evidence excerpts exactly. Do not invent actors, titles, dates, or amounts.
If actor_mentions is not [], every name must already appear inside some
evidence.supporting_text. Do not add actors that are missing from evidence.
Never return supporting_text longer than 600 characters.
""".strip()
CONCISE_JSON_SCHEMA_INSTRUCTIONS = OLLAMA_JSON_FORMAT_INSTRUCTIONS
SCHEMA_REPAIR_INSTRUCTIONS = """
Your previous JSON did not match the required schema.
Return the complete corrected JSON only.
Do not omit required fields.
Every evidence.supporting_text must be an exact substring and at most 600 characters.
If a date is not explicitly supported, set it to null.
If you cannot support a complete candidate from the evidence, return {"candidates":[]}.
""".strip()
SEMANTIC_REPAIR_INSTRUCTIONS = """
Your previous JSON was schema-valid but failed semantic validation.
Correct only the unsupported fields.
If an optional field has no explicit support, set it to null.
Preserve valid evidence and other valid fields where possible.
Do not invent new facts.
Return the complete corrected JSON only.
""".strip()
FINAL_OUTPUT_REQUIREMENTS = """
Final output requirements:
- Return complete schema-valid JSON with a top-level candidates array.
- Every evidence.supporting_text MUST be an exact verbatim substring of a sent chunk.
- Every evidence.supporting_text MUST be <= 600 characters. Do not paraphrase. Do not use ellipses to shorten a span that is not itself in the source.
- Every actor_mentions.name MUST appear verbatim inside cited evidence.supporting_text.
- announced_at and target_date must follow temporal semantics: announcement/presentation dates may be announced_at; procedural scadenza / conversion expiry is not target_date.
- If an optional field is unsupported, set it to null.
""".strip()


def proposal_claim_json_schema() -> dict[str, Any]:
    return PoliticalClaimExtraction.model_json_schema()


def render_chunk_payload(chunks: tuple[ExtractionChunk, ...]) -> str:
    return "\n\n".join(chunk_prompt_text(chunk) for chunk in chunks)


def compact_validation_issues(exc: BaseException) -> tuple[str, ...]:
    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, ValidationError):
        items: list[str] = []
        for error in cause.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            message = str(error.get("msg") or "invalid")
            items.append(f"{location}: {message}" if location else message)
            if len(items) >= 16:
                break
        return tuple(items)
    raw = getattr(exc, "raw_output", None)
    if isinstance(raw, dict) and "candidates" not in raw:
        return ("root: missing candidates",)
    return ("schema_mismatch",)


def validation_error_categories(issues: tuple[str, ...]) -> tuple[str, ...]:
    categories: list[str] = []
    seen: set[str] = set()
    for issue in issues:
        lowered = issue.casefold()
        if "claim_type" in lowered:
            label = "missing_claim_type"
        elif "exact_statement" in lowered:
            label = "missing_exact_statement"
        elif "normalized_title" in lowered:
            label = "missing_normalized_title"
        elif "evidence" in lowered:
            label = "missing_evidence"
        elif "confidence" in lowered:
            label = "missing_confidence"
        elif "candidates" in lowered:
            label = "missing_candidates"
        elif "abstention" in lowered:
            label = "invalid_abstention"
        else:
            label = "schema_mismatch"
        if label not in seen:
            seen.add(label)
            categories.append(label)
    return tuple(categories or ("schema_mismatch",))


def preview_invalid_json(value: object) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    if len(text) > INVALID_JSON_PREVIEW_CHARS:
        return text[:INVALID_JSON_PREVIEW_CHARS] + "…"
    return text


@dataclass(frozen=True, slots=True)
class OllamaAttemptRecord:
    attempt: int
    validation_status: str
    validation_error_categories: tuple[str, ...]
    elapsed_ms: int | None
    response_status: int | None
    timed_out: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_body_bytes: int | None = None
    semantic_validation_errors: tuple[dict[str, str | None], ...] = ()
    repaired_fields: tuple[str, ...] = ()
    raw_output: dict[str, Any] | list[Any] | None = None

    def as_dict(self) -> dict[str, object]:
        elapsed_seconds = None
        if self.elapsed_ms is not None:
            elapsed_seconds = round(self.elapsed_ms / 1000, 3)
        payload: dict[str, object] = {
            "attempt": self.attempt,
            "validation_status": self.validation_status,
            "validation_error_categories": list(self.validation_error_categories),
            "elapsed_ms": self.elapsed_ms,
            "elapsed_seconds": elapsed_seconds,
            "response_status": self.response_status,
            "timed_out": self.timed_out,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "request_body_bytes": self.request_body_bytes,
        }
        if self.semantic_validation_errors:
            payload["semantic_validation_errors"] = list(
                self.semantic_validation_errors
            )
        if self.repaired_fields:
            payload["repaired_fields"] = list(self.repaired_fields)
        if self.raw_output is not None:
            payload["raw_output"] = self.raw_output
        return payload


@dataclass(frozen=True, slots=True)
class OllamaRequestDiagnostics:
    model: str
    endpoint: str
    stream: bool
    format_type: StructuredFormat
    num_ctx: int | None
    message_count: int
    system_prompt_chars: int
    user_document_chars: int
    json_schema_chars: int
    request_body_bytes: int
    estimated_input_tokens: int
    selected_chunk_count: int
    selected_chunk_indexes: tuple[int, ...]
    selected_pages: tuple[int, ...]
    timeout_seconds: float
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_ms: int | None = None
    timed_out: bool = False
    response_status: int | None = None
    error_code: str | None = None
    attempt_count: int = 1
    attempts: tuple[OllamaAttemptRecord, ...] = ()

    def as_dict(self) -> dict[str, object]:
        elapsed_seconds = None
        if self.elapsed_ms is not None:
            elapsed_seconds = round(self.elapsed_ms / 1000, 3)
        return {
            "model": self.model,
            "endpoint": self.endpoint,
            "stream": self.stream,
            "format_type": self.format_type,
            "num_ctx": self.num_ctx,
            "message_count": self.message_count,
            "system_prompt_chars": self.system_prompt_chars,
            "user_document_chars": self.user_document_chars,
            "json_schema_chars": self.json_schema_chars,
            "request_body_bytes": self.request_body_bytes,
            "estimated_input_tokens": self.estimated_input_tokens,
            "selected_chunk_count": self.selected_chunk_count,
            "selected_chunk_indexes": list(self.selected_chunk_indexes),
            "selected_pages": list(self.selected_pages),
            "sent_chunk_count": self.selected_chunk_count,
            "sent_chunk_indexes": list(self.selected_chunk_indexes),
            "sent_pages": list(self.selected_pages),
            "timeout_seconds": self.timeout_seconds,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_ms": self.elapsed_ms,
            "elapsed_seconds": elapsed_seconds,
            "timed_out": self.timed_out,
            "response_status": self.response_status,
            "error_code": self.error_code,
            "attempt_count": self.attempt_count,
            "attempts": [item.as_dict() for item in self.attempts],
        }


def system_prompt_for_format(
    prompt: str,
    *,
    structured_format: StructuredFormat,
) -> str:
    del structured_format
    return prompt.rstrip() + "\n\n" + OLLAMA_JSON_FORMAT_INSTRUCTIONS


def build_ollama_chat_payload(
    request: StructuredExtractionRequest,
    *,
    model_name: str,
    base_url: str,
    timeout_seconds: float,
    num_ctx: int = DEFAULT_OLLAMA_NUM_CTX,
    structured_format: StructuredFormat = "json",
) -> tuple[dict[str, Any], OllamaRequestDiagnostics]:
    schema = proposal_claim_json_schema()
    schema_text = json.dumps(schema, ensure_ascii=False)
    document_text = render_chunk_payload(request.chunks)
    user_content = USER_PREFIX + document_text
    system_content = system_prompt_for_format(
        request.prompt or load_proposal_extraction_prompt(),
        structured_format=structured_format,
    )
    format_value: Any = "json" if structured_format == "json" else schema
    payload: dict[str, Any] = {
        "model": model_name,
        "stream": False,
        "format": format_value,
        "options": {"temperature": 0, "num_ctx": num_ctx},
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    pages = tuple(
        sorted(
            {
                page
                for chunk in request.chunks
                for page in (chunk.page_start, chunk.page_end)
                if page is not None
            }
        )
    )
    diagnostics = OllamaRequestDiagnostics(
        model=model_name,
        endpoint=f"{base_url.rstrip('/')}/api/chat",
        stream=False,
        format_type=structured_format,
        num_ctx=num_ctx,
        message_count=len(payload["messages"]),
        system_prompt_chars=len(system_content),
        user_document_chars=len(user_content),
        json_schema_chars=0 if structured_format == "json" else len(schema_text),
        request_body_bytes=len(body),
        estimated_input_tokens=estimate_tokens(
            system_content
            + user_content
            + (schema_text if structured_format == "json_schema" else "")
        ),
        selected_chunk_count=len(request.chunks),
        selected_chunk_indexes=tuple(chunk.chunk_index for chunk in request.chunks),
        selected_pages=pages,
        timeout_seconds=timeout_seconds,
    )
    return payload, diagnostics


def stamp_diagnostics(
    diagnostics: OllamaRequestDiagnostics,
    *,
    started_at: datetime,
    finished_at: datetime | None = None,
    timed_out: bool = False,
    response_status: int | None = None,
    error_code: str | None = None,
    attempts: tuple[OllamaAttemptRecord, ...] = (),
) -> OllamaRequestDiagnostics:
    done = finished_at or datetime.now(timezone.utc)
    elapsed_ms = int((done - started_at).total_seconds() * 1000)
    if attempts:
        elapsed_ms = sum(item.elapsed_ms or 0 for item in attempts)
        last = attempts[-1]
        timed_out = timed_out or last.timed_out
        if response_status is None:
            response_status = last.response_status
    return replace(
        diagnostics,
        started_at=started_at.isoformat(),
        finished_at=done.isoformat(),
        elapsed_ms=elapsed_ms,
        timed_out=timed_out,
        response_status=response_status,
        error_code=error_code,
        attempt_count=len(attempts) or 1,
        attempts=attempts,
    )


def build_repair_chat_payload(
    original_payload: dict[str, Any],
    *,
    invalid_json: object,
    validation_errors: tuple[str, ...],
    kind: str = "schema",
    extra_instruction: str = "",
) -> dict[str, Any]:
    header = (
        SEMANTIC_REPAIR_INSTRUCTIONS
        if kind == "semantic"
        else SCHEMA_REPAIR_INSTRUCTIONS
    )
    error_lines = "\n".join(
        f"- {item}" for item in validation_errors
    ) or "- validation error"
    extra = f"\n\n{extra_instruction.strip()}" if extra_instruction.strip() else ""
    repair = (
        f"{header}\n\n"
        f"{FINAL_OUTPUT_REQUIREMENTS}\n\n"
        f"Validation errors:\n{error_lines}{extra}\n\n"
        "Previous JSON:\n"
        f"{preview_invalid_json(invalid_json)}"
    )
    messages = list(original_payload.get("messages") or [])
    messages.append({"role": "assistant", "content": preview_invalid_json(invalid_json)})
    messages.append({"role": "user", "content": repair})
    return {**original_payload, "messages": messages}
