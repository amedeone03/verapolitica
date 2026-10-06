from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import ValidationError

from backend.app.ai.base import (
    ExtractionProviderError,
    ExtractionProviderOutputError,
    ExtractionProviderTimeoutError,
    StructuredExtractionRequest,
)
from backend.app.ai.ollama_diagnostics import (
    DEFAULT_OLLAMA_NUM_CTX,
    MAX_SCHEMA_REPAIR_ATTEMPTS,
    OllamaAttemptRecord,
    StructuredFormat,
    build_ollama_chat_payload,
    build_repair_chat_payload,
    compact_validation_issues,
    stamp_diagnostics,
    validation_error_categories,
)
from backend.app.schemas import (
    PoliticalClaimExtraction,
    ProviderUsage,
    StructuredExtractionResult,
)


DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
logger = logging.getLogger("verapolitica.ai.ollama")


class OllamaStructuredExtractionProvider:
    provider_name = "ollama"

    def __init__(
        self,
        *,
        model_name: str,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 180.0,
        num_ctx: int = DEFAULT_OLLAMA_NUM_CTX,
        structured_format: StructuredFormat = "json",
        client: httpx.Client | None = None,
    ) -> None:
        self._model_name = model_name
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._num_ctx = num_ctx
        self._structured_format: StructuredFormat = structured_format
        self._client = client
        self.last_diagnostics = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def extract(
        self, request: StructuredExtractionRequest
    ) -> StructuredExtractionResult:
        payload, diagnostics = build_ollama_chat_payload(
            request,
            model_name=self._model_name,
            base_url=self._base_url,
            timeout_seconds=self._timeout_seconds,
            num_ctx=self._num_ctx,
            structured_format=self._structured_format,
        )
        overall_started = datetime.now(timezone.utc)
        logger.info(
            "ollama extraction request %s",
            json.dumps(diagnostics.as_dict(), ensure_ascii=False, sort_keys=True),
        )
        attempts: list[OllamaAttemptRecord] = []
        current_payload = payload
        last_body: dict[str, Any] | None = None
        last_status = 200
        parsed: PoliticalClaimExtraction | None = None
        for attempt_number in range(1, MAX_SCHEMA_REPAIR_ATTEMPTS + 1):
            request_body_bytes = len(
                json.dumps(current_payload, ensure_ascii=False).encode("utf-8")
            )
            started_at = datetime.now(timezone.utc)
            try:
                response = self._post("/api/chat", current_payload)
            except ExtractionProviderTimeoutError:
                attempts.append(
                    OllamaAttemptRecord(
                        attempt=attempt_number,
                        validation_status="timeout",
                        validation_error_categories=("timeout",),
                        elapsed_ms=int(
                            (datetime.now(timezone.utc) - started_at).total_seconds()
                            * 1000
                        ),
                        response_status=None,
                        timed_out=True,
                        request_body_bytes=request_body_bytes,
                    )
                )
                self.last_diagnostics = stamp_diagnostics(
                    diagnostics,
                    started_at=overall_started,
                    timed_out=True,
                    error_code="local_ai_timeout",
                    attempts=tuple(attempts),
                )
                logger.warning(
                    "ollama extraction timeout %s",
                    json.dumps(
                        self.last_diagnostics.as_dict(),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
                raise
            except Exception:
                attempts.append(
                    OllamaAttemptRecord(
                        attempt=attempt_number,
                        validation_status="unavailable",
                        validation_error_categories=("connection",),
                        elapsed_ms=int(
                            (datetime.now(timezone.utc) - started_at).total_seconds()
                            * 1000
                        ),
                        response_status=None,
                        request_body_bytes=request_body_bytes,
                    )
                )
                self.last_diagnostics = stamp_diagnostics(
                    diagnostics,
                    started_at=overall_started,
                    error_code="local_ai_unavailable",
                    attempts=tuple(attempts),
                )
                logger.warning(
                    "ollama extraction unavailable %s",
                    json.dumps(
                        self.last_diagnostics.as_dict(),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
                raise
            elapsed_ms = int(
                (datetime.now(timezone.utc) - started_at).total_seconds() * 1000
            )
            body: dict[str, Any] | None = None
            try:
                body = self._json_body(response)
                content = ""
                message = body.get("message")
                if isinstance(message, dict):
                    content = str(message.get("content") or "")
                parsed = self._parse_claims(content, raw=body)
            except ExtractionProviderOutputError as exc:
                lowered = str(exc).casefold()
                schema_failure = "proposal_claim_schema" in lowered
                issues = compact_validation_issues(exc)
                attempts.append(
                    OllamaAttemptRecord(
                        attempt=attempt_number,
                        validation_status=(
                            "schema_invalid" if schema_failure else "malformed_json"
                        ),
                        validation_error_categories=validation_error_categories(issues),
                        elapsed_ms=elapsed_ms,
                        response_status=response.status_code,
                        input_tokens=_optional_int(
                            body.get("prompt_eval_count") if body is not None else None
                        ),
                        output_tokens=_optional_int(
                            body.get("eval_count") if body is not None else None
                        ),
                        request_body_bytes=request_body_bytes,
                    )
                )
                if (
                    schema_failure
                    and attempt_number < MAX_SCHEMA_REPAIR_ATTEMPTS
                ):
                    logger.warning(
                        "ollama extraction schema retry %s",
                        json.dumps(
                            {
                                "attempt": attempt_number,
                                "validation_error_categories": list(
                                    attempts[-1].validation_error_categories
                                ),
                                "sent_chunk_indexes": list(
                                    diagnostics.selected_chunk_indexes
                                ),
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    )
                    current_payload = build_repair_chat_payload(
                        payload,
                        invalid_json=exc.raw_output,
                        validation_errors=issues,
                    )
                    continue
                error_code = (
                    "local_ai_schema" if schema_failure else "local_ai_invalid_output"
                )
                self.last_diagnostics = stamp_diagnostics(
                    diagnostics,
                    started_at=overall_started,
                    response_status=response.status_code,
                    error_code=error_code,
                    attempts=tuple(attempts),
                )
                logger.warning(
                    "ollama extraction invalid output %s",
                    json.dumps(
                        self.last_diagnostics.as_dict(),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
                raise
            except ExtractionProviderError:
                attempts.append(
                    OllamaAttemptRecord(
                        attempt=attempt_number,
                        validation_status="http_error",
                        validation_error_categories=("http_error",),
                        elapsed_ms=elapsed_ms,
                        response_status=response.status_code,
                        request_body_bytes=request_body_bytes,
                    )
                )
                self.last_diagnostics = stamp_diagnostics(
                    diagnostics,
                    started_at=overall_started,
                    response_status=response.status_code,
                    error_code="local_ai_unavailable",
                    attempts=tuple(attempts),
                )
                logger.warning(
                    "ollama extraction http error %s",
                    json.dumps(
                        self.last_diagnostics.as_dict(),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
                raise
            assert body is not None
            attempts.append(
                OllamaAttemptRecord(
                    attempt=attempt_number,
                    validation_status="accepted",
                    validation_error_categories=(),
                    elapsed_ms=elapsed_ms,
                    response_status=response.status_code,
                    input_tokens=_optional_int(body.get("prompt_eval_count")),
                    output_tokens=_optional_int(body.get("eval_count")),
                    request_body_bytes=request_body_bytes,
                )
            )
            last_body = body
            last_status = response.status_code
            break
        if parsed is None or last_body is None:
            raise ExtractionProviderOutputError(
                "Ollama JSON did not match proposal_claim_schema_v1",
                raw_output=None,
            )
        self.last_diagnostics = stamp_diagnostics(
            diagnostics,
            started_at=overall_started,
            response_status=last_status,
            attempts=tuple(attempts),
        )
        logger.info(
            "ollama extraction finished %s",
            json.dumps(
                self.last_diagnostics.as_dict(),
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        return StructuredExtractionResult(
            output=parsed,
            usage=ProviderUsage(
                request_count=len(attempts),
                input_tokens=_sum_optional(item.input_tokens for item in attempts),
                output_tokens=_sum_optional(item.output_tokens for item in attempts),
            ),
            provider_response_id=str(last_body.get("created_at") or "") or None,
        )

    def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        url = f"{self._base_url}{path}"
        try:
            if self._client is not None:
                return self._client.post(url, json=payload)
            with httpx.Client(timeout=self._timeout_seconds) as client:
                return client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise ExtractionProviderTimeoutError(
                "The local Ollama model timed out before returning structured output."
            ) from exc
        except httpx.HTTPError as exc:
            raise ExtractionProviderError(
                f"Ollama is not running at {self._base_url}. Start it with: ollama serve"
            ) from exc

    def _json_body(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 404:
            raise ExtractionProviderError(
                f"Ollama model {self._model_name!r} is not installed. "
                f"Run: ollama pull {self._model_name}"
            )
        if response.status_code >= 400:
            detail = response.text.strip()[:300] or f"HTTP {response.status_code}"
            raise ExtractionProviderError(f"Ollama extraction failed: {detail}")
        try:
            body = response.json()
        except ValueError as exc:
            raise ExtractionProviderOutputError(
                "Ollama returned a non-JSON response",
                raw_output=response.text[:4_000],
            ) from exc
        if not isinstance(body, dict):
            raise ExtractionProviderOutputError(
                "Ollama returned an unexpected JSON payload",
                raw_output=body,
            )
        error = body.get("error")
        if error:
            message = str(error)
            if "not found" in message.casefold():
                raise ExtractionProviderError(
                    f"Ollama model {self._model_name!r} is not installed. "
                    f"Run: ollama pull {self._model_name}"
                )
            raise ExtractionProviderError(f"Ollama extraction failed: {message}")
        return body

    def _parse_claims(
        self, content: str, *, raw: object
    ) -> PoliticalClaimExtraction:
        text = content.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        try:
            payload = json.loads(text) if text else raw
        except json.JSONDecodeError as exc:
            raise ExtractionProviderOutputError(
                "Ollama returned malformed JSON",
                raw_output=content[:4_000],
            ) from exc
        try:
            if isinstance(payload, dict) and "candidates" in payload:
                return PoliticalClaimExtraction.model_validate(payload)
            if isinstance(payload, dict) and "output" in payload:
                return StructuredExtractionResult.model_validate(payload).output
            raise ExtractionProviderOutputError(
                "Ollama JSON did not match proposal_claim_schema_v1",
                raw_output=payload,
            )
        except ValidationError as exc:
            raise ExtractionProviderOutputError(
                "Ollama JSON did not match proposal_claim_schema_v1",
                raw_output=payload,
            ) from exc


def probe_ollama(
    *,
    base_url: str,
    model_name: str | None = None,
    timeout_seconds: float = 2.0,
    client: httpx.Client | None = None,
) -> dict[str, object]:
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        if client is not None:
            response = client.get(url)
        else:
            with httpx.Client(timeout=timeout_seconds) as http:
                response = http.get(url)
    except httpx.HTTPError:
        return {
            "available": False,
            "message": f"Ollama is not running at {base_url.rstrip('/')}. Start it with: ollama serve",
            "models": (),
            "has_model": False,
        }
    if response.status_code >= 400:
        return {
            "available": False,
            "message": "Ollama did not accept the local status check.",
            "models": (),
            "has_model": False,
        }
    try:
        payload = response.json()
    except ValueError:
        return {
            "available": False,
            "message": "Ollama returned an unreadable status payload.",
            "models": (),
            "has_model": False,
        }
    models = tuple(
        str(item.get("name") or "")
        for item in (payload.get("models") or [])
        if isinstance(item, dict) and item.get("name")
    )
    has_model = False
    if model_name:
        has_model = any(
            item == model_name or item.startswith(f"{model_name}:")
            for item in models
        )
    if model_name and not has_model:
        message = (
            f"Ollama is running, but model {model_name!r} is not installed. "
            f"Run: ollama pull {model_name}"
        )
    else:
        message = "Ollama is running locally. No API cost."
    return {
        "available": True,
        "message": message,
        "models": models,
        "has_model": has_model if model_name else bool(models),
    }


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def _sum_optional(values) -> int | None:
    total = 0
    seen = False
    for value in values:
        if value is None:
            continue
        seen = True
        total += value
    return total if seen else None
