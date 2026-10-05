from dataclasses import dataclass
from typing import Protocol

from backend.app.schemas import StructuredExtractionResult


class ExtractionProviderError(RuntimeError):
    pass


class ExtractionProviderTimeoutError(ExtractionProviderError):
    pass


class ExtractionProviderRateLimitError(ExtractionProviderError):
    pass


class ExtractionProviderOutputError(ExtractionProviderError):
    def __init__(self, message: str, *, raw_output: object | None = None) -> None:
        super().__init__(message)
        self.raw_output = raw_output


@dataclass(frozen=True, slots=True)
class ExtractionChunk:
    chunk_index: int
    text: str
    page_start: int | None
    page_end: int | None


@dataclass(frozen=True, slots=True)
class StructuredExtractionRequest:
    source_url: str
    prompt: str
    chunks: tuple[ExtractionChunk, ...]


class StructuredExtractionProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def extract(
        self, request: StructuredExtractionRequest
    ) -> StructuredExtractionResult: ...
