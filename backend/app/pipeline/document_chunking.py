from dataclasses import dataclass
from hashlib import sha256

from backend.app.pipeline.document_extraction import ExtractedDocument


class ChunkingLimitError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DocumentChunkData:
    chunk_index: int
    text: str
    page_start: int | None
    page_end: int | None
    char_start: int
    char_end: int
    chunk_hash: str


def _split_long_span(text: str, start: int, max_chars: int):
    cursor = 0
    while cursor < len(text):
        limit = min(cursor + max_chars, len(text))
        if limit < len(text):
            boundary = text.rfind(" ", cursor, limit + 1)
            if boundary > cursor:
                limit = boundary
        segment = text[cursor:limit].strip()
        leading = len(text[cursor:limit]) - len(text[cursor:limit].lstrip())
        if segment:
            segment_start = start + cursor + leading
            yield segment, segment_start, segment_start + len(segment)
        cursor = limit
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1


def chunk_document(
    document: ExtractedDocument,
    *,
    max_chunk_chars: int,
    max_chunks: int,
) -> tuple[DocumentChunkData, ...]:
    if max_chunk_chars < 100:
        raise ValueError("max_chunk_chars must be at least 100")
    if max_chunks < 1:
        raise ValueError("max_chunks must be positive")
    pending: list[tuple[str, int, int]] = []
    chunks: list[DocumentChunkData] = []

    def flush(page_number: int | None) -> None:
        nonlocal pending
        if not pending:
            return
        text = "\n\n".join(item[0] for item in pending)
        chunks.append(
            DocumentChunkData(
                chunk_index=len(chunks),
                text=text,
                page_start=page_number,
                page_end=page_number,
                char_start=pending[0][1],
                char_end=pending[-1][2],
                chunk_hash=sha256(text.encode("utf-8")).hexdigest(),
            )
        )
        pending = []
        if len(chunks) > max_chunks:
            raise ChunkingLimitError(
                f"document exceeds the configured maximum of {max_chunks} chunks"
            )

    for page in document.pages:
        local_cursor = 0
        for paragraph in page.text.split("\n\n"):
            paragraph_start = page.text.find(paragraph, local_cursor)
            if paragraph_start < 0:
                paragraph_start = local_cursor
            local_cursor = paragraph_start + len(paragraph)
            absolute_start = page.char_start + paragraph_start
            spans = (
                ((paragraph, absolute_start, absolute_start + len(paragraph)),)
                if len(paragraph) <= max_chunk_chars
                else tuple(_split_long_span(paragraph, absolute_start, max_chunk_chars))
            )
            for span in spans:
                proposed_length = sum(len(item[0]) for item in pending)
                proposed_length += max(0, 2 * len(pending)) + len(span[0])
                if pending and proposed_length > max_chunk_chars:
                    flush(page.page_number)
                pending.append(span)
                if len(span[0]) >= max_chunk_chars:
                    flush(page.page_number)
        flush(page.page_number)
    return tuple(chunks)
