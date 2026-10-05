from pathlib import Path

import pytest
from sqlalchemy import select

from backend.app.models import DocumentChunk, RawDocument, RawDocumentStatus, Source
from backend.app.pipeline.document_chunking import chunk_document
from backend.app.pipeline.document_extraction import (
    OCRRequiredError,
    extract_html,
    extract_pdf,
)
from backend.app.pipeline.official_document_pipeline import OfficialDocumentPipeline


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "fixtures"
    / "ai"
    / "synthetic_official_programme.html"
)


def _pdf_bytes(text: str | None) -> bytes:
    escaped = (text or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{number} 0 obj\n".encode("ascii"))
        payload.extend(body)
        payload.extend(b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(payload)


def test_html_text_extraction_is_deterministic_and_ignores_scripts():
    first = extract_html(FIXTURE.read_bytes())
    second = extract_html(FIXTURE.read_bytes())

    assert first == second
    assert "build 100 new clinics" in first.text
    assert "must never be extracted" not in first.text
    assert first.pages[0].page_number is None


def test_text_pdf_extraction_preserves_page_metadata():
    extracted = extract_pdf(_pdf_bytes("We will build 100 clinics by 2030."))

    assert extracted.text == "We will build 100 clinics by 2030."
    assert extracted.pages[0].page_number == 1
    assert extracted.parser_version == "pypdf_text_v1"


def test_pdf_without_extractable_text_fails_closed_as_ocr_required():
    with pytest.raises(OCRRequiredError, match="OCR is required"):
        extract_pdf(_pdf_bytes(None))


def test_chunking_is_deterministic_and_hashes_content():
    extracted = extract_html(FIXTURE.read_bytes())

    first = chunk_document(extracted, max_chunk_chars=250, max_chunks=20)
    second = chunk_document(extracted, max_chunk_chars=250, max_chunks=20)

    assert first == second
    assert [item.chunk_index for item in first] == list(range(len(first)))
    assert all(len(item.chunk_hash) == 64 for item in first)
    assert all(item.char_start < item.char_end for item in first)


def test_official_document_pipeline_reuses_raw_storage_and_persists_chunks(
    session_factory, raw_storage
):
    with session_factory() as session:
        source = Source(
            key="official-example",
            name="Synthetic official source",
            base_url="https://official.example",
        )
        session.add(source)
        session.commit()
        source_id = source.id
    pipeline = OfficialDocumentPipeline(
        session_factory,
        raw_storage,
        max_document_bytes=100_000,
        max_chunk_chars=500,
        max_chunks=20,
    )

    result = pipeline.ingest(
        source_id=source_id,
        source_key="official-example",
        source_url="https://official.example/programme.html",
        content_type="text/html",
        content=FIXTURE.read_bytes(),
    )

    with session_factory() as session:
        document = session.get(RawDocument, result.raw_document_id)
        chunks = tuple(
            session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.raw_document_id == result.raw_document_id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
        assert document.process_status is RawDocumentStatus.PARSED
        assert document.raw_sha256 == result.raw_sha256
        assert document.normalized_text
        assert len(chunks) == result.chunk_count
