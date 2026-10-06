from backend.app.ai.base import (
    ExtractionProviderError,
    ExtractionProviderOutputError,
    ExtractionProviderTimeoutError,
)
from backend.app.demo.api_errors import classify_demo_error
from backend.app.services.proposal_extraction_service import (
    ProposalExtractionProviderFailure,
)


def test_timeout_maps_to_safe_code():
    code, message, status = classify_demo_error(
        ExtractionProviderTimeoutError("The local Ollama model timed out")
    )
    assert code == "local_ai_timeout"
    assert status == 504
    assert "allowed time" in message


def test_connection_refused_maps_to_unavailable():
    wrapped = ProposalExtractionProviderFailure(
        "Ollama is not running at http://127.0.0.1:11434. Start it with: ollama serve",
        run_id=3,
    )
    wrapped.__cause__ = ExtractionProviderError("connection refused")
    code, message, status = classify_demo_error(wrapped)
    assert code == "local_ai_unavailable"
    assert status == 503
    assert "Traceback" not in message


def test_unexpected_provider_exception_stays_generic():
    wrapped = ProposalExtractionProviderFailure("extraction provider failed", run_id=1)
    wrapped.__cause__ = RuntimeError("secret traceback /tmp/verapolitica.db")
    code, message, status = classify_demo_error(wrapped)
    assert code == "local_ai_failed"
    assert status == 500
    assert "traceback" not in message.casefold()
    assert "/tmp/" not in message
    assert "secret" not in message
    malformed = classify_demo_error(
        ExtractionProviderOutputError("Ollama returned malformed JSON", raw_output="{")
    )
    schema = classify_demo_error(
        ExtractionProviderOutputError(
            "Ollama JSON did not match proposal_claim_schema_v1",
            raw_output={"candidates": []},
        )
    )
    assert malformed[0] == "local_ai_invalid_output"
    assert malformed[2] == 422
    assert schema[0] == "local_ai_schema"
    assert schema[2] == 422
