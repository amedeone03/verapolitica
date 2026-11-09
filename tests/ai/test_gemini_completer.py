import httpx
import pytest

from backend.app.ai.base import (
    ExtractionProviderError,
    ExtractionProviderRateLimitError,
)
from backend.app.ai.text_completion import GeminiTextCompleter, completer_from_settings
from backend.app.core.config import AppEnvironment, Settings


def _settings(**overrides) -> Settings:
    values = {
        "env": AppEnvironment.TEST,
        "database_url": "sqlite:///:memory:",
        "admin_api_key": "test-admin-secret",
        "trusted_hosts": "testserver",
        "enable_demo_ui": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_gemini_completer_reads_candidate_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "gemini-2.5-flash:generateContent" in str(request.url)
        assert request.headers.get("x-goog-api-key") == "studio-key"
        assert b"system_instruction" in request.content
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "Risposta sui dati pubblicati."}]}}
                ]
            },
        )

    completer = GeminiTextCompleter(
        api_key="studio-key",
        model_name="gemini-2.5-flash",
        timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert completer.complete(system="regole", user="domanda") == "Risposta sui dati pubblicati."


def test_gemini_rate_limit_and_empty_output():
    def limited(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota"}})

    busy = GeminiTextCompleter(
        api_key="k",
        model_name="gemini-2.5-flash",
        timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(limited)),
    )
    with pytest.raises(ExtractionProviderRateLimitError):
        busy.complete(system="s", user="u")

    def empty(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [{"content": {"parts": []}}]})

    silent = GeminiTextCompleter(
        api_key="k",
        model_name="gemini-2.5-flash",
        timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(empty)),
    )
    with pytest.raises(ExtractionProviderError, match="empty"):
        silent.complete(system="s", user="u")


def test_completer_from_settings_gemini_is_ask_only():
    settings = _settings(
        llm_provider="gemini",
        llm_model="gemini-2.5-flash",
        llm_api_key="studio-key-not-for-extraction",
    )
    assert settings.ai_ask_enabled is True
    assert settings.ai_extraction_enabled is False
    completer = completer_from_settings(settings)
    assert completer is not None
    assert completer.provider_name == "gemini"
    assert completer.model_name == "gemini-2.5-flash"


def test_blank_provider_disables_ask_wording():
    settings = _settings(llm_provider=None, llm_model=None)
    assert settings.ai_ask_enabled is False
    assert completer_from_settings(settings) is None
