import html
from io import BytesIO
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser


class DocumentExtractionError(ValueError):
    pass


class UnsupportedDocumentError(DocumentExtractionError):
    pass


class OCRRequiredError(DocumentExtractionError):
    pass


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    page_number: int | None
    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    text: str
    pages: tuple[ExtractedPage, ...]
    format: str
    parser_version: str
    warnings: tuple[str, ...] = ()


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in value.split("\n")]
    paragraphs: list[str] = []
    pending: list[str] = []
    for line in lines:
        if line:
            pending.append(line)
        elif pending:
            paragraphs.append(" ".join(pending))
            pending = []
    if pending:
        paragraphs.append(" ".join(pending))
    return "\n\n".join(paragraphs).strip()


class _OfficialHTMLTextParser(HTMLParser):
    _block_tags = {
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dt",
        "figcaption",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "p",
        "section",
        "td",
        "th",
        "title",
    }
    _ignored_tags = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        del attrs
        tag = tag.lower()
        if tag in self._ignored_tags:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag in self._block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._ignored_tags and self._ignored_depth:
            self._ignored_depth -= 1
        elif self._ignored_depth == 0 and tag in self._block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


def extract_html(content: bytes) -> ExtractedDocument:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentExtractionError("HTML document is not valid UTF-8") from exc
    parser = _OfficialHTMLTextParser()
    try:
        parser.feed(decoded)
        parser.close()
    except Exception as exc:
        raise DocumentExtractionError(f"Unable to parse HTML document: {exc}") from exc
    text = normalize_text(html.unescape("".join(parser.parts)))
    if not text:
        raise DocumentExtractionError("HTML document contains no extractable text")
    return ExtractedDocument(
        text=text,
        pages=(ExtractedPage(None, text, 0, len(text)),),
        format="html",
        parser_version="official_html_text_v1",
    )


def extract_pdf(content: bytes) -> ExtractedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - installation failure
        raise DocumentExtractionError("pypdf is required for PDF extraction") from exc
    try:
        document = PdfReader(BytesIO(content), strict=True)
    except Exception as exc:
        raise DocumentExtractionError(f"Unable to open PDF document: {exc}") from exc
    if document.is_encrypted:
        raise DocumentExtractionError("Encrypted PDF documents are not supported")
    page_values: list[tuple[int, str]] = []
    empty_pages = 0
    for index, page in enumerate(document.pages):
        try:
            text = normalize_text(page.extract_text() or "")
        except Exception as exc:
            raise DocumentExtractionError(
                f"Unable to extract PDF page {index + 1}: {exc}"
            ) from exc
        if text:
            page_values.append((index + 1, text))
        else:
            empty_pages += 1
    if not page_values:
        raise OCRRequiredError(
            "PDF contains no extractable text; OCR is required and is not supported"
        )
    pages: list[ExtractedPage] = []
    combined_parts: list[str] = []
    cursor = 0
    for page_number, text in page_values:
        if combined_parts:
            combined_parts.append("\n\n")
            cursor += 2
        start = cursor
        combined_parts.append(text)
        cursor += len(text)
        pages.append(ExtractedPage(page_number, text, start, cursor))
    warnings = (
        (f"{empty_pages} PDF page(s) contained no extractable text",)
        if empty_pages
        else ()
    )
    return ExtractedDocument(
        text="".join(combined_parts),
        pages=tuple(pages),
        format="pdf",
        parser_version="pypdf_text_v1",
        warnings=warnings,
    )


def extract_document(content: bytes, content_type: str) -> ExtractedDocument:
    media_type = content_type.partition(";")[0].strip().lower()
    if media_type in {"text/html", "application/xhtml+xml"}:
        return extract_html(content)
    if media_type == "application/pdf":
        return extract_pdf(content)
    raise UnsupportedDocumentError(f"Unsupported official document type: {content_type}")
