import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import Any, Protocol


class ParserError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    structured_records: list[dict[str, Any]]
    normalized_text: str
    canonical_json: str
    parser_version: str
    parliamentary_group_records: list[dict[str, Any]] = field(default_factory=list)


class Parser(Protocol):
    version: str

    def parse(self, content: bytes) -> ParsedDocument: ...


def split_sparql_bundle(
    payload: dict[str, Any], *, expected_schema: str, source_name: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return the people payload and optional group payload from a raw bundle.

    Legacy single-query fixtures and stored documents remain parseable.
    """

    if payload.get("schema") != expected_schema:
        return payload, None
    try:
        people_bytes = base64.b64decode(payload["people_response_base64"], validate=True)
        groups_bytes = base64.b64decode(
            payload["parliamentary_groups_response_base64"], validate=True
        )
        people_payload = json.loads(people_bytes.decode("utf-8-sig"))
        groups_payload = json.loads(groups_bytes.decode("utf-8-sig"))
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ParserError(f"Invalid {source_name} SPARQL response bundle: {exc}") from exc
    if not isinstance(people_payload, dict) or not isinstance(groups_payload, dict):
        raise ParserError(f"Invalid {source_name} SPARQL response bundle payloads")
    return people_payload, groups_payload
