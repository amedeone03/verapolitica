from pathlib import Path

import pytest

from backend.app.demo.upload_validation import (
    DemoUploadError,
    sanitize_upload_filename,
    validate_upload_content,
)
from backend.app.pipeline.document_extraction import extract_document
from tests.demo.pdf_fixtures import build_empty_text_pdf, build_text_pdf


def test_sanitize_filename_strips_paths_and_rejects_unsupported_types():
    assert sanitize_upload_filename("../../Senato DDL.html") == "Senato-DDL.html"
    with pytest.raises(DemoUploadError, match="Unsupported file type"):
        sanitize_upload_filename("notes.exe")


def test_validate_upload_rejects_empty_and_oversized_files():
    with pytest.raises(DemoUploadError, match="empty"):
        validate_upload_content(filename="doc.html", content=b"", max_bytes=100)
    with pytest.raises(DemoUploadError, match="exceeds"):
        validate_upload_content(
            filename="doc.html",
            content=b"<html>too big</html>",
            max_bytes=4,
        )


def test_scanned_pdf_is_rejected():
    with pytest.raises(DemoUploadError, match="Scanned PDFs"):
        validate_upload_content(
            filename="scan.pdf",
            content=build_empty_text_pdf(),
            max_bytes=1_000_000,
        )


def test_text_pdf_is_accepted_by_extension_and_magic_bytes():
    content = build_text_pdf("Disegno di legge DDL S. 2047")
    name, content_type = validate_upload_content(
        filename="DDL S. 2047.pdf",
        content=content,
        max_bytes=10_000,
    )
    assert name.endswith(".pdf")
    assert content_type == "application/pdf"
    extracted = extract_document(content, content_type)
    assert extracted.format == "pdf"
    assert extracted.pages
    assert "Disegno di legge" in extracted.text


def test_invalid_pdf_magic_bytes_are_rejected():
    with pytest.raises(DemoUploadError, match="does not look like a PDF"):
        validate_upload_content(
            filename="fake.pdf",
            content=b"this is not a pdf",
            max_bytes=10_000,
        )


def test_five_megabyte_text_pdf_is_within_limit():
    content = build_text_pdf("Atto Senato", pad_bytes=5_200_000)
    assert 5_000_000 < len(content) < 10_000_000
    name, content_type = validate_upload_content(
        filename="ddl-2047.pdf",
        content=content,
        max_bytes=50_000_000,
    )
    assert name == "ddl-2047.pdf"
    assert content_type == "application/pdf"


def test_html_is_accepted_as_plain_data():
    name, content_type = validate_upload_content(
        filename="ddl.html",
        content=b"<html><script>alert(1)</script><p>DDL 60476</p></html>",
        max_bytes=10_000,
    )
    assert name == "ddl.html"
    assert content_type == "text/html"
    assert Path("ddl.html").name == name
