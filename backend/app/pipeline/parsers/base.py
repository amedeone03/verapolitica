from dataclasses import dataclass
from typing import Any, Protocol


class ParserError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    structured_records: list[dict[str, Any]]
    normalized_text: str
    canonical_json: str
    parser_version: str


class Parser(Protocol):
    version: str

    def parse(self, content: bytes) -> ParsedDocument: ...
