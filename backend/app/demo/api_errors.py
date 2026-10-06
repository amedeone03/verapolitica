from __future__ import annotations

from fastapi.responses import JSONResponse

from backend.app.ai.base import (
    ExtractionProviderError,
    ExtractionProviderOutputError,
    ExtractionProviderTimeoutError,
)
from backend.app.demo.upload_validation import DemoUploadError
from backend.app.services.proposal_extraction_service import (
    ProposalExtractionError,
    ProposalExtractionProviderFailure,
)


TIMEOUT_MESSAGE = "Local AI analysis did not complete within the allowed time."
UNAVAILABLE_MESSAGE = "Local AI service unavailable"
INVALID_JSON_MESSAGE = "The local model returned invalid JSON. Nothing was published."
SCHEMA_MESSAGE = (
    "Local AI returned an incomplete structured result. No draft was created."
)
EMPTY_MESSAGE = (
    "The local model did not produce any evidence-backed proposal. Nothing was published."
)
GENERIC_MESSAGE = "Document analysis failed. Nothing was published."


def _root_exception(exc: BaseException) -> BaseException:
    cause = getattr(exc, "__cause__", None)
    return cause if isinstance(cause, BaseException) else exc


def _safe_message(exc: BaseException, fallback: str) -> str:
    message = str(exc).strip()
    if not message or "\n" in message or ".py" in message or "Traceback" in message:
        return fallback
    return message[:400]


def classify_demo_error(
    exc: BaseException,
    *,
    default_status: int | None = None,
) -> tuple[str, str, int]:
    root = _root_exception(exc)
    message = str(exc).strip() or str(root).strip()
    lowered = message.casefold()
    if isinstance(root, ExtractionProviderTimeoutError) or "timed out" in lowered:
        return "local_ai_timeout", TIMEOUT_MESSAGE, 504
    if isinstance(root, ExtractionProviderOutputError):
        if "malformed json" in lowered:
            return "local_ai_invalid_output", INVALID_JSON_MESSAGE, 422
        if "proposal_claim_schema" in lowered or "schema-valid" in lowered:
            return "local_ai_schema", SCHEMA_MESSAGE, 422
        return "local_ai_invalid_output", INVALID_JSON_MESSAGE, 422
    if isinstance(root, ExtractionProviderError):
        if "not running" in lowered or "connection refused" in lowered or "ollama serve" in lowered:
            return "local_ai_unavailable", UNAVAILABLE_MESSAGE, 503
        if "timed out" in lowered:
            return "local_ai_timeout", TIMEOUT_MESSAGE, 504
        return "local_ai_unavailable", UNAVAILABLE_MESSAGE, 503
    if isinstance(exc, DemoUploadError):
        if "abstain" in lowered or "did not produce" in lowered:
            return "local_ai_empty", _safe_message(exc, EMPTY_MESSAGE), 422
        if "not running" in lowered or "ollama serve" in lowered:
            return "local_ai_unavailable", UNAVAILABLE_MESSAGE, 503
        if "unsupported file type" in lowered or "does not look like a pdf" in lowered:
            return "unsupported_file_type", "Unsupported file type", 400
        if "exceeds the" in lowered and "byte" in lowered:
            return "file_too_large", "File too large", 400
        if "ocr" in lowered or "no extractable text" in lowered:
            return "unreadable_pdf", "PDF contains no extractable text", 400
        if "could not be saved" in lowered:
            return "upload_failed", "Upload could not be saved", 400
        return "upload_failed", _safe_message(exc, GENERIC_MESSAGE), 400
    if isinstance(exc, ProposalExtractionError):
        if "missing chunk" in lowered or "supporting evidence" in lowered:
            return "local_ai_evidence", (
                "The local model cited evidence that was not in the sent document sections. "
                "Nothing was published."
            ), 422
        if "no relevant evidence" in lowered:
            return "no_evidence", (
                "No relevant evidence sections could be selected from this document."
            ), 400
        if isinstance(exc, ProposalExtractionProviderFailure):
            return "local_ai_failed", GENERIC_MESSAGE, 500
        return "local_ai_failed", GENERIC_MESSAGE, 500
    if default_status is not None:
        if "maximum of" in lowered and "chunks" in lowered:
            return "document_too_large", "This document is too large to process in the demo.", 400
        if "no extractable sections" in lowered or "no relevant evidence" in lowered:
            return "no_evidence", (
                "No relevant evidence sections could be selected from this document."
            ), 400
        return "upload_failed", _safe_message(exc, GENERIC_MESSAGE), default_status
    return "local_ai_failed", GENERIC_MESSAGE, 500


def demo_error_body(
    exc: BaseException,
    *,
    default_status: int | None = None,
) -> tuple[dict[str, str], int]:
    code, message, status_code = classify_demo_error(
        exc, default_status=default_status
    )
    return (
        {
            "status": "error",
            "error_code": code,
            "message": message,
            "error": message,
        },
        status_code,
    )


def demo_json_error(
    exc: BaseException,
    *,
    default_status: int | None = None,
) -> JSONResponse:
    body, status_code = demo_error_body(exc, default_status=default_status)
    return JSONResponse(body, status_code=status_code)
