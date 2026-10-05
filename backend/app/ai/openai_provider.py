from backend.app.ai.base import (
    ExtractionProviderError,
    ExtractionProviderOutputError,
    ExtractionProviderRateLimitError,
    ExtractionProviderTimeoutError,
    StructuredExtractionRequest,
)
from backend.app.schemas import (
    PoliticalClaimExtraction,
    ProviderUsage,
    StructuredExtractionResult,
)


class OpenAIExtractionProvider:
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - installation failure
            raise ExtractionProviderError(
                "the openai package is required for the OpenAI provider"
            ) from exc
        self._model_name = model_name
        self._client = OpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    def extract(
        self, request: StructuredExtractionRequest
    ) -> StructuredExtractionResult:
        chunk_text = "\n\n".join(
            (
                f"--- CHUNK {chunk.chunk_index}"
                + (
                    f" (pages {chunk.page_start}-{chunk.page_end})"
                    if chunk.page_start is not None
                    else ""
                )
                + f" ---\n{chunk.text}"
            )
            for chunk in request.chunks
        )
        try:
            response = self._client.responses.parse(
                model=self._model_name,
                input=[
                    {"role": "system", "content": request.prompt},
                    {
                        "role": "user",
                        "content": (
                            "Extract candidates from these official document chunks:\n\n"
                            + chunk_text
                        ),
                    },
                ],
                text_format=PoliticalClaimExtraction,
            )
        except Exception as exc:
            try:
                from openai import APITimeoutError, RateLimitError
            except ImportError:  # pragma: no cover
                APITimeoutError = RateLimitError = ()  # type: ignore[assignment]
            if isinstance(exc, APITimeoutError):
                raise ExtractionProviderTimeoutError("OpenAI request timed out") from exc
            if isinstance(exc, RateLimitError):
                raise ExtractionProviderRateLimitError(
                    "OpenAI request was rate limited"
                ) from exc
            raise ExtractionProviderError(f"OpenAI extraction failed: {exc}") from exc
        parsed = response.output_parsed
        if not isinstance(parsed, PoliticalClaimExtraction):
            raise ExtractionProviderOutputError(
                "OpenAI response did not contain schema-valid parsed output"
            )
        usage = getattr(response, "usage", None)
        return StructuredExtractionResult(
            output=parsed,
            usage=ProviderUsage(
                request_count=1,
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
            ),
            provider_response_id=getattr(response, "id", None),
        )
