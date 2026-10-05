from collections.abc import Callable

from pydantic import ValidationError

from backend.app.ai.base import (
    ExtractionProviderError,
    ExtractionProviderOutputError,
    StructuredExtractionRequest,
)
from backend.app.schemas import StructuredExtractionResult


class FakeExtractionProvider:
    """Deterministic provider for tests, fixtures, and manual dry runs."""

    provider_name = "fake"

    def __init__(
        self,
        output: StructuredExtractionResult | dict | Callable[
            [StructuredExtractionRequest], StructuredExtractionResult | dict
        ],
        *,
        model_name: str = "fake-extraction-v1",
        error: ExtractionProviderError | None = None,
    ) -> None:
        self._output = output
        self._model_name = model_name
        self.error = error
        self.requests: list[StructuredExtractionRequest] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    def extract(
        self, request: StructuredExtractionRequest
    ) -> StructuredExtractionResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        raw = self._output(request) if callable(self._output) else self._output
        if isinstance(raw, StructuredExtractionResult):
            return raw
        try:
            return StructuredExtractionResult.model_validate(raw)
        except ValidationError as exc:
            raise ExtractionProviderOutputError(
                f"fake provider returned invalid structured output: {exc}",
                raw_output=raw,
            ) from exc
