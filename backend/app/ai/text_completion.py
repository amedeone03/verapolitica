"""Plain-text completion for citizen explanations.

Uses the same Settings (provider/model/timeout) as extraction. It does not
evaluate pledges and is never required for app startup.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import httpx

from backend.app.ai.base import (
    ExtractionProviderError,
    ExtractionProviderTimeoutError,
)
from backend.app.core.config import Settings


class TextCompleter(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def complete(self, *, system: str, user: str) -> str: ...


class FakeTextCompleter:
    provider_name = "fake"

    def __init__(
        self,
        output: str | Callable[[str, str], str],
        *,
        model_name: str = "fake-explainer",
        error: Exception | None = None,
    ) -> None:
        self._output = output
        self._model_name = model_name
        self.error = error
        self.requests: list[tuple[str, str]] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    def complete(self, *, system: str, user: str) -> str:
        self.requests.append((system, user))
        if self.error is not None:
            raise self.error
        text = self._output(system, user) if callable(self._output) else self._output
        return str(text).strip()


class OllamaTextCompleter:
    provider_name = "ollama"

    def __init__(
        self,
        *,
        model_name: str,
        base_url: str,
        timeout_seconds: float,
        client: httpx.Client | None = None,
    ) -> None:
        self._model_name = model_name
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client

    @property
    def model_name(self) -> str:
        return self._model_name

    def complete(self, *, system: str, user: str) -> str:
        body = {
            "model": self._model_name,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            if self._client is not None:
                response = self._client.post("/api/chat", json=body)
            else:
                response = httpx.post(
                    f"{self._base_url}/api/chat",
                    json=body,
                    timeout=self._timeout_seconds,
                )
            response.raise_for_status()
            content = (response.json().get("message") or {}).get("content") or ""
        except httpx.TimeoutException as exc:
            raise ExtractionProviderTimeoutError("explanation model timed out") from exc
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise ExtractionProviderError("explanation model request failed") from exc
        text = str(content).strip()
        if not text:
            raise ExtractionProviderError("explanation model returned empty text")
        return text


class OpenAITextCompleter:
    provider_name = "openai"

    def __init__(self, *, api_key: str, model_name: str, timeout_seconds: float) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise ExtractionProviderError(
                "the openai package is required for the OpenAI provider"
            ) from exc
        self._model_name = model_name
        self._client = OpenAI(api_key=api_key, timeout=timeout_seconds)

    @property
    def model_name(self) -> str:
        return self._model_name

    def complete(self, *, system: str, user: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                temperature=0,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            content = response.choices[0].message.content or ""
        except Exception as exc:
            raise ExtractionProviderError("explanation model request failed") from exc
        text = str(content).strip()
        if not text:
            raise ExtractionProviderError("explanation model returned empty text")
        return text


def completer_from_settings(settings: Settings) -> TextCompleter | None:
    if not settings.ai_extraction_enabled:
        return None
    provider = (settings.llm_provider or "").strip().casefold()
    model = (settings.llm_model or "").strip()
    timeout = min(float(settings.llm_timeout_seconds), 45.0)
    if provider == "ollama":
        return OllamaTextCompleter(
            model_name=model,
            base_url=settings.ollama_base_url,
            timeout_seconds=timeout,
        )
    if provider == "openai":
        key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
        return OpenAITextCompleter(
            api_key=key, model_name=model, timeout_seconds=timeout
        )
    return None
