from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from backend.app.ai.ollama_diagnostics import system_prompt_for_format
from backend.app.pipeline.chunk_selection import (
    CHUNK_SELECTION_VERSION,
    EXTRACTION_PURPOSE_CANONICAL,
    SENT_CHUNK_POLICY_VERSION,
)
from backend.app.schemas import PoliticalClaimExtraction


INFERENCE_FINGERPRINT_VERSION = "inference_fingerprint_v1"


def _digest_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def schema_content_sha256() -> str:
    schema = PoliticalClaimExtraction.model_json_schema()
    return _digest_text(_canonical_json(schema))


def effective_prompt_text(prompt_text: str, provider: object) -> str:
    if getattr(provider, "provider_name", "") != "ollama":
        return prompt_text
    structured_format = getattr(provider, "_structured_format", "json") or "json"
    return system_prompt_for_format(
        prompt_text, structured_format=structured_format
    )


def provider_inference_options(provider: object) -> dict[str, Any]:
    name = getattr(provider, "provider_name", "")
    num_ctx = getattr(provider, "_num_ctx", None)
    structured_format = getattr(provider, "_structured_format", None)
    temperature = getattr(provider, "_temperature", None)
    if name == "ollama" and temperature is None:
        temperature = 0
    return {
        "num_ctx": num_ctx,
        "temperature": temperature,
        "structured_format": structured_format,
    }


@dataclass(frozen=True, slots=True)
class InferenceFingerprint:
    digest: str
    fields: dict[str, Any]

    def as_audit(self) -> dict[str, Any]:
        return {
            "version": INFERENCE_FINGERPRINT_VERSION,
            "sha256": self.digest,
            **self.fields,
        }


def build_inference_fingerprint(
    *,
    document_raw_sha256: str,
    document_normalized_sha256: str | None,
    provider: object,
    prompt_text: str,
    prompt_version: str,
    schema_version: str,
    max_selected_chunks: int,
    max_chunks_per_run: int,
    max_document_tokens: int,
    extraction_purpose: str = EXTRACTION_PURPOSE_CANONICAL,
    sent_chunk_policy_version: str | None = None,
) -> InferenceFingerprint:
    options = provider_inference_options(provider)
    prompt_content = effective_prompt_text(prompt_text, provider)
    policy_version = sent_chunk_policy_version or SENT_CHUNK_POLICY_VERSION
    fields: dict[str, Any] = {
        "fingerprint_version": INFERENCE_FINGERPRINT_VERSION,
        "document_raw_sha256": document_raw_sha256,
        "document_normalized_sha256": document_normalized_sha256 or "",
        "provider": getattr(provider, "provider_name", ""),
        "model": getattr(provider, "model_name", ""),
        "prompt_content_sha256": _digest_text(prompt_content),
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "schema_content_sha256": schema_content_sha256(),
        "selector_version": CHUNK_SELECTION_VERSION,
        "sent_chunk_policy_version": policy_version,
        "extraction_purpose": extraction_purpose,
        "max_selected_chunks": min(max_selected_chunks, max_chunks_per_run),
        "max_chunks_per_run": max_chunks_per_run,
        "max_document_tokens": max_document_tokens,
        "num_ctx": options["num_ctx"],
        "temperature": options["temperature"],
        "structured_format": options["structured_format"],
    }
    digest = _digest_text(_canonical_json(fields))
    return InferenceFingerprint(digest=digest, fields=fields)
