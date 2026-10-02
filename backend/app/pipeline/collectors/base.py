from dataclasses import dataclass
from datetime import datetime
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
