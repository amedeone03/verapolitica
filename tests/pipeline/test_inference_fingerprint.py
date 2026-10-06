from types import SimpleNamespace

from backend.app.pipeline.chunk_selection import (
    CANONICAL_METADATA_PACK_VERSION,
    CHUNK_SELECTION_VERSION,
    EXTRACTION_PURPOSE_ARTICLES,
    EXTRACTION_PURPOSE_CANONICAL,
    PROXIMITY_TOKEN_PACK_VERSION,
    SENT_CHUNK_POLICY_VERSION,
)
from backend.app.pipeline.inference_fingerprint import (
    INFERENCE_FINGERPRINT_VERSION,
    build_inference_fingerprint,
    effective_prompt_text,
)


def _provider(**attrs):
    values = {"provider_name": "fake", "model_name": "fake-extraction-v1"}
    values.update(attrs)
    return SimpleNamespace(**values)


def _fingerprint(**overrides):
    kwargs = {
        "document_raw_sha256": "a" * 64,
        "document_normalized_sha256": "b" * 64,
        "provider": _provider(),
        "prompt_text": "extract political claims",
        "prompt_version": "proposal_extraction_v1",
        "schema_version": "proposal_claim_schema_v1",
        "max_selected_chunks": 16,
        "max_chunks_per_run": 40,
        "max_document_tokens": 4500,
    }
    kwargs.update(overrides)
    return build_inference_fingerprint(**kwargs)


def test_fingerprint_is_deterministic_and_omits_raw_document_id():
    first = _fingerprint()
    second = _fingerprint()
    assert first.digest == second.digest
    assert len(first.digest) == 64
    assert first.fields["fingerprint_version"] == INFERENCE_FINGERPRINT_VERSION
    assert first.fields["selector_version"] == CHUNK_SELECTION_VERSION
    assert first.fields["sent_chunk_policy_version"] == SENT_CHUNK_POLICY_VERSION
    assert "raw_document_id" not in first.fields
    assert "source_id" not in first.fields
    audit = first.as_audit()
    assert audit["sha256"] == first.digest
    assert audit["document_raw_sha256"] == "a" * 64


def test_prompt_text_model_and_budget_change_the_digest():
    baseline = _fingerprint()
    prompt_changed = _fingerprint(prompt_text="extract political claims with extra guidance")
    model_changed = _fingerprint(provider=_provider(model_name="other-model"))
    budget_changed = _fingerprint(max_document_tokens=2000)
    ctx_changed = _fingerprint(provider=_provider(_num_ctx=4096))
    assert prompt_changed.digest != baseline.digest
    assert model_changed.digest != baseline.digest
    assert budget_changed.digest != baseline.digest
    assert ctx_changed.digest != baseline.digest


def test_ollama_prompt_hash_includes_json_format_instructions():
    fake = _fingerprint()
    ollama = _fingerprint(
        provider=_provider(
            provider_name="ollama",
            model_name="qwen2.5:7b",
            _num_ctx=8192,
            _structured_format="json",
        )
    )
    assert ollama.digest != fake.digest
    assert ollama.fields["structured_format"] == "json"
    assert ollama.fields["num_ctx"] == 8192
    assert ollama.fields["temperature"] == 0
    json_fp = _fingerprint(
        provider=_provider(
            provider_name="ollama",
            model_name="qwen2.5:7b",
            _num_ctx=8192,
            _structured_format="json",
        )
    )
    schema_fp = _fingerprint(
        provider=_provider(
            provider_name="ollama",
            model_name="qwen2.5:7b",
            _num_ctx=8192,
            _structured_format="json_schema",
        )
    )
    assert schema_fp.digest != json_fp.digest
    json_prompt = effective_prompt_text(
        "extract political claims",
        _provider(provider_name="ollama", _structured_format="json"),
    )
    assert "Return ONLY valid JSON" in json_prompt


def test_fingerprint_changes_with_packing_policy_and_extraction_purpose():
    baseline = _fingerprint()
    purpose_changed = _fingerprint(extraction_purpose=EXTRACTION_PURPOSE_ARTICLES)
    policy_changed = _fingerprint(
        sent_chunk_policy_version=PROXIMITY_TOKEN_PACK_VERSION
    )
    assert baseline.fields["extraction_purpose"] == EXTRACTION_PURPOSE_CANONICAL
    assert baseline.fields["sent_chunk_policy_version"] == CANONICAL_METADATA_PACK_VERSION
    assert purpose_changed.digest != baseline.digest
    assert policy_changed.digest != baseline.digest
    assert SENT_CHUNK_POLICY_VERSION == CANONICAL_METADATA_PACK_VERSION
