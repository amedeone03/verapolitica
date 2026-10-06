import json

import httpx
import pytest

from backend.app.ai import (
    ExtractionChunk,
    ExtractionProviderError,
    ExtractionProviderOutputError,
    OllamaStructuredExtractionProvider,
    StructuredExtractionRequest,
    probe_ollama,
)


PROMPT = "proposal_extraction_v1"
VALID_CLAIMS = {
    "candidates": [
        {
            "claim_type": "proposal",
            "exact_statement": "Disegno di legge per le cure palliative",
            "normalized_title": "Disegno di legge per le cure palliative",
            "summary": None,
            "topic": "healthcare",
            "actor_mentions": [],
            "announced_at": "2026-09-18",
            "target_date": None,
            "evidence": [
                {
                    "chunk_index": 0,
                    "page": 1,
                    "supporting_text": "Disegno di legge per le cure palliative",
                }
            ],
            "confidence": "high",
            "abstention_reason": None,
        }
    ]
}


def _request() -> StructuredExtractionRequest:
    return StructuredExtractionRequest(
        source_url="https://www.senato.it/leg/19/BGT/Schede/Ddliter/2047.htm",
        prompt=PROMPT,
        chunks=(
            ExtractionChunk(
                chunk_index=0,
                text="Disegno di legge per le cure palliative. Presentato da Governo.",
                page_start=1,
                page_end=1,
            ),
        ),
    )


def _provider(handler) -> OllamaStructuredExtractionProvider:
    return OllamaStructuredExtractionProvider(
        model_name="qwen2.5:7b",
        base_url="http://127.0.0.1:11434",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_ollama_provider_parses_schema_json():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "qwen2.5:7b"
        assert payload["format"] == "json"
        assert payload["stream"] is False
        assert payload["options"]["num_ctx"] == 8192
        assert payload["options"]["temperature"] == 0
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": json.dumps(VALID_CLAIMS)},
                "prompt_eval_count": 11,
                "eval_count": 7,
                "created_at": "2026-10-06T00:00:00Z",
            },
        )

    result = _provider(handler).extract(_request())
    assert result.output.candidates[0].normalized_title.startswith("Disegno di legge")
    assert result.usage.input_tokens == 11
    assert result.provider_response_id == "2026-10-06T00:00:00Z"


def test_tiny_real_schema_request_shape_and_diagnostics():
    from backend.app.ai.ollama_diagnostics import OLLAMA_JSON_FORMAT_INSTRUCTIONS, build_ollama_chat_payload
    from backend.app.pipeline.prompts import load_proposal_extraction_prompt

    tiny = (
        "DISEGNO DI LEGGE\n"
        "Titolo: Misure per la sicurezza degli edifici scolastici.\n"
        "Presentato dal Governo.\n"
        "Stato: presentato."
    )
    request = StructuredExtractionRequest(
        source_url="https://www.senato.it/leg/19/BGT/Schede/Ddliter/2047.htm",
        prompt=load_proposal_extraction_prompt(),
        chunks=(
            ExtractionChunk(chunk_index=0, text=tiny, page_start=1, page_end=1),
        ),
    )
    captured = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        payload = json.loads(http_request.content.decode("utf-8"))
        captured["payload"] = payload
        assert payload["format"] == "json"
        assert OLLAMA_JSON_FORMAT_INSTRUCTIONS in payload["messages"][0]["content"]
        assert "Return ONLY valid JSON" in payload["messages"][0]["content"]
        assert '{"candidates":[]}' in payload["messages"][0]["content"].replace(" ", "")
        assert "Misure per la sicurezza" in payload["messages"][1]["content"]
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps(VALID_CLAIMS)}},
        )

    provider = _provider(handler)
    provider.extract(request)
    payload, diagnostics = build_ollama_chat_payload(
        request,
        model_name="qwen2.5:7b",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=180,
    )
    dumped = json.dumps(diagnostics.as_dict())
    assert diagnostics.format_type == "json"
    assert diagnostics.stream is False
    assert diagnostics.num_ctx == 8192
    assert diagnostics.message_count == 2
    assert diagnostics.selected_chunk_count == 1
    assert diagnostics.selected_chunk_indexes == (0,)
    assert diagnostics.json_schema_chars == 0
    assert diagnostics.request_body_bytes > 4_000
    assert diagnostics.estimated_input_tokens > 0
    assert diagnostics.estimated_input_tokens < 6_000
    assert "DISEGNO DI LEGGE" in payload["messages"][0]["content"]
    assert "Iniziativa Governativa" in payload["messages"][0]["content"]
    assert "proponiamo" in payload["messages"][0]["content"]
    assert "actor_mentions.name MUST appear" in payload["messages"][0]["content"]
    assert "edifici scolastici" not in dumped
    assert "Misure per la sicurezza" not in dumped
    assert payload["options"]["num_ctx"] == 8192
    assert provider.last_diagnostics is not None
    assert provider.last_diagnostics.elapsed_ms is not None
    assert provider.last_diagnostics.timed_out is False
    assert provider.last_diagnostics.response_status == 200
    assert provider.last_diagnostics.error_code is None
    assert provider.last_diagnostics.as_dict()["sent_chunk_count"] == 1
    assert provider.last_diagnostics.as_dict()["elapsed_seconds"] is not None


def test_json_format_fallback_is_validated_by_pydantic():
    from backend.app.ai.ollama_diagnostics import OLLAMA_JSON_FORMAT_INSTRUCTIONS
    from backend.app.pipeline.prompts import load_proposal_extraction_prompt

    def handler(http_request: httpx.Request) -> httpx.Response:
        payload = json.loads(http_request.content.decode("utf-8"))
        assert payload["format"] == "json"
        assert OLLAMA_JSON_FORMAT_INSTRUCTIONS in payload["messages"][0]["content"]
        assert payload["options"]["num_ctx"] == 8192
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps(VALID_CLAIMS)}},
        )

    provider = OllamaStructuredExtractionProvider(
        model_name="qwen2.5:7b",
        base_url="http://127.0.0.1:11434",
        structured_format="json",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = provider.extract(
        StructuredExtractionRequest(
            source_url="https://www.senato.it/leg/19/BGT/Schede/Ddliter/2047.htm",
            prompt=load_proposal_extraction_prompt(),
            chunks=(
                ExtractionChunk(
                    chunk_index=0,
                    text="Disegno di legge per le cure palliative. Presentato da Governo.",
                    page_start=1,
                    page_end=1,
                ),
            ),
        )
    )
    assert result.output.candidates[0].claim_type.value == "proposal"
    assert provider.last_diagnostics.format_type == "json"
    assert provider.last_diagnostics.json_schema_chars == 0


def test_ollama_provider_rejects_malformed_json():
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "{not-json"}},
        )

    provider = _provider(handler)
    with pytest.raises(ExtractionProviderOutputError, match="malformed JSON"):
        provider.extract(_request())
    assert provider.last_diagnostics is not None
    assert provider.last_diagnostics.response_status == 200
    assert provider.last_diagnostics.error_code == "local_ai_invalid_output"
    assert provider.last_diagnostics.attempt_count == 1


TINY_SCHOOL_SAFETY = (
    "DISEGNO DI LEGGE\n"
    "Il Governo propone l'istituzione di un fondo di 10 milioni di euro "
    "per la sicurezza degli edifici scolastici.\n"
    "Il fondo è previsto per l'anno 2027."
)


def test_realistic_tiny_proposal_document_is_sent_as_json():
    from backend.app.pipeline.prompts import load_proposal_extraction_prompt

    captured = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        payload = json.loads(http_request.content.decode("utf-8"))
        captured["payload"] = payload
        assert payload["format"] == "json"
        assert TINY_SCHOOL_SAFETY.split("\n")[0] in payload["messages"][1]["content"]
        assert "10 milioni di euro" in payload["messages"][1]["content"]
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps({
                "candidates": [
                    {
                        "claim_type": "proposal",
                        "exact_statement": (
                            "Il Governo propone l'istituzione di un fondo di 10 milioni di euro "
                            "per la sicurezza degli edifici scolastici."
                        ),
                        "normalized_title": "Fondo per la sicurezza degli edifici scolastici",
                        "summary": "Fondo di 10 milioni di euro per le scuole nel 2027.",
                        "topic": "education",
                        "actor_mentions": [{"name": "Governo", "role": "government"}],
                        "announced_at": None,
                        "target_date": "2027-12-31",
                        "evidence": [
                            {
                                "chunk_index": 0,
                                "page": 1,
                                "supporting_text": (
                                    "Il Governo propone l'istituzione di un fondo di 10 milioni di euro "
                                    "per la sicurezza degli edifici scolastici."
                                ),
                            }
                        ],
                        "confidence": "high",
                        "abstention_reason": None,
                    }
                ]
            })}},
        )

    result = _provider(handler).extract(
        StructuredExtractionRequest(
            source_url="https://www.senato.it/leg/19/BGT/Schede/Ddliter/2047.htm",
            prompt=load_proposal_extraction_prompt(),
            chunks=(
                ExtractionChunk(
                    chunk_index=0,
                    text=TINY_SCHOOL_SAFETY,
                    page_start=1,
                    page_end=1,
                ),
            ),
        )
    )
    claim = result.output.candidates[0]
    assert claim.claim_type.value == "proposal"
    assert "10 milioni di euro" in (claim.exact_statement or "")
    assert claim.evidence[0].supporting_text in TINY_SCHOOL_SAFETY
    assert captured["payload"]["format"] == "json"


INCOMPLETE_CANDIDATE = {
    "candidates": [{"confidence": "high", "abstention_reason": None}]
}


def test_ollama_provider_repairs_schema_mismatch_once():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        calls.append(payload)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={"message": {"content": json.dumps(INCOMPLETE_CANDIDATE)}},
            )
        assert payload["format"] == "json"
        assert len(payload["messages"]) >= 4
        repair = payload["messages"][-1]["content"]
        assert "did not match the required schema" in repair
        assert "confidence" in repair.casefold() or "claim_type" in repair.casefold()
        assert "Disegno di legge per le cure palliative" in payload["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps(VALID_CLAIMS)},
                "prompt_eval_count": 4,
                "eval_count": 3,
            },
        )

    provider = _provider(handler)
    result = provider.extract(_request())
    assert len(calls) == 2
    assert result.output.candidates[0].claim_type.value == "proposal"
    assert result.usage.request_count == 2
    attempts = provider.last_diagnostics.as_dict()["attempts"]
    assert provider.last_diagnostics.attempt_count == 2
    assert attempts[0]["validation_status"] == "schema_invalid"
    assert attempts[1]["validation_status"] == "accepted"
    dumped = json.dumps(provider.last_diagnostics.as_dict())
    assert "Disegno di legge per le cure palliative" not in dumped


def test_ollama_provider_rejects_schema_mismatch():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        del request
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps(INCOMPLETE_CANDIDATE)}},
        )

    provider = _provider(handler)
    with pytest.raises(ExtractionProviderOutputError, match="proposal_claim_schema_v1"):
        provider.extract(_request())
    assert len(calls) == 2
    assert provider.last_diagnostics.error_code == "local_ai_schema"
    assert provider.last_diagnostics.response_status == 200
    assert provider.last_diagnostics.attempt_count == 2
    statuses = [item.validation_status for item in provider.last_diagnostics.attempts]
    assert statuses == ["schema_invalid", "schema_invalid"]


def test_ollama_unavailable_and_missing_model():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ExtractionProviderError, match="ollama serve"):
        _provider(down).extract(_request())

    def missing(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(404, text="model not found")

    with pytest.raises(ExtractionProviderError, match="ollama pull"):
        _provider(missing).extract(_request())


def test_probe_ollama_reports_running_and_missing_model():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "llama3.2:3b"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    present = probe_ollama(
        base_url="http://127.0.0.1:11434",
        model_name="llama3.2:3b",
        client=client,
    )
    missing = probe_ollama(
        base_url="http://127.0.0.1:11434",
        model_name="qwen2.5:7b",
        client=client,
    )
    assert present["available"] is True
    assert present["has_model"] is True
    assert missing["has_model"] is False
    assert "ollama pull" in str(missing["message"])
