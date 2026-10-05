from dataclasses import dataclass
from datetime import datetime
import base64
import json
from typing import Protocol


class CollectorError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CollectedDocument:
    content: bytes
    source_url: str
    content_type: str
    retrieved_at: datetime
    collector_version: str


class Collector(Protocol):
    version: str

    def collect(self) -> CollectedDocument: ...


def encode_sparql_bundle(
    *, schema: str, people_response: bytes, parliamentary_groups_response: bytes
) -> bytes:
    """Preserve both official response bodies byte-for-byte in one raw document."""

    return json.dumps(
        {
            "schema": schema,
            "people_response_base64": base64.b64encode(people_response).decode("ascii"),
            "parliamentary_groups_response_base64": base64.b64encode(
                parliamentary_groups_response
            ).decode("ascii"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
