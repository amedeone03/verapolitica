from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

from backend.app.core.config import Settings
from backend.app.core.request_context import current_request_id


_SECRET_PATTERNS = (
    (re.compile(r"(?i)(authorization:\s*bearer\s+)\S+"), r"\1[redacted]"),
    (
        re.compile(
            r"(?i)(VERAPOLITICA_(?:ADMIN_API_KEY|LLM_API_KEY|DATABASE_URL)=)\S+"
        ),
        r"\1[redacted]",
    ),
    (re.compile(r"postgresql\+psycopg://[^\s\"']+"), "[redacted-db-url]"),
)


def sanitize_log_text(value: str) -> str:
    redacted = value
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-admin-key",
        "admin_api_key",
        "llm_api_key",
        "password",
        "secret",
        "dsn",
        "database_url",
        "verapolitica_admin_api_key",
        "verapolitica_llm_api_key",
        "verapolitica_database_url",
    }
)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize_log_text(record.getMessage()),
        }
        request_id = getattr(record, "request_id", None) or current_request_id()
        if request_id:
            payload["request_id"] = request_id
        for key in (
            "path",
            "method",
            "status_code",
            "duration_ms",
            "job_run_id",
            "job_name",
            "source",
            "result",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, ensure_ascii=False, default=str)


def redact_value(key: str, value: object) -> object:
    if key.casefold() in SENSITIVE_KEYS:
        return "[redacted]"
    return value


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if settings.resolved_log_format == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        class _TextFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                return sanitize_log_text(super().format(record))

        handler.setFormatter(
            _TextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    logging.getLogger("uvicorn.access").handlers.clear()
