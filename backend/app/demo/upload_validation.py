from __future__ import annotations

import re
from pathlib import Path

from backend.app.pipeline.document_extraction import (
    DocumentExtractionError,
    OCRRequiredError,
    UnsupportedDocumentError,
    extract_document,
)

ALLOWED_SUFFIXES = {".html", ".htm", ".pdf"}
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class DemoUploadError(ValueError):
    pass


def sanitize_upload_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    cleaned = _UNSAFE_NAME.sub("-", base).strip(".-")
    if len(cleaned) > 80:
        stem = Path(cleaned).stem[:60].strip(".-") or "document"
        suffix = Path(cleaned).suffix[:8]
        cleaned = f"{stem}{suffix}"
    if not cleaned:
        raise DemoUploadError("The uploaded filename is not usable.")
    suffix = Path(cleaned).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DemoUploadError(
            "Unsupported file type. Upload .html, .htm, or a text-based .pdf."
        )
    return cleaned


def content_type_for_upload(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix == ".pdf":
        if not content.lstrip().startswith(b"%PDF"):
            raise DemoUploadError("File does not look like a PDF.")
        return "application/pdf"
    raise DemoUploadError(
        "Unsupported file type. Upload .html, .htm, or a text-based .pdf."
    )


def validate_upload_content(
    *,
    filename: str,
    content: bytes,
    max_bytes: int,
) -> tuple[str, str]:
    safe_name = sanitize_upload_filename(filename)
    if not content:
        raise DemoUploadError("The uploaded file is empty.")
    if len(content) > max_bytes:
        raise DemoUploadError(
            f"The uploaded file exceeds the {max_bytes} byte demo limit."
        )
    content_type = content_type_for_upload(safe_name, content)
    try:
        extract_document(content, content_type)
    except OCRRequiredError as exc:
        raise DemoUploadError(
            "This PDF has no extractable text. Scanned PDFs are not supported."
        ) from exc
    except UnsupportedDocumentError as exc:
        raise DemoUploadError(
            "Unsupported file type. Upload .html, .htm, or a text-based .pdf."
        ) from exc
    except DocumentExtractionError as exc:
        raise DemoUploadError("The uploaded document could not be read as text.") from exc
    return safe_name, content_type
