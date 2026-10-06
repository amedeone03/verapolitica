import json
import logging

from backend.app.core.config import Settings
from backend.app.core.logging import (
    JsonLogFormatter,
    redact_value,
    sanitize_log_text,
)


def test_sanitize_log_text_redacts_secrets():
    message = (
        "Authorization: Bearer super-secret-token "
        "VERAPOLITICA_ADMIN_API_KEY=another-secret "
        "postgresql+psycopg://verapolitica:hunter2@db/verapolitica"
    )
    redacted = sanitize_log_text(message)
    assert "super-secret-token" not in redacted
    assert "another-secret" not in redacted
    assert "hunter2" not in redacted
    assert "[redacted]" in redacted
    assert "[redacted-db-url]" in redacted


def test_redact_value_hides_sensitive_keys():
    assert redact_value("Authorization", "Bearer abc") == "[redacted]"
    assert redact_value("path", "/health/live") == "/health/live"


def test_json_formatter_includes_request_fields_without_secrets():
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="verapolitica.http",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Authorization: Bearer leaked-token request completed",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-12345678"
    record.path = "/health/live"
    record.method = "GET"
    record.status_code = 200
    record.duration_ms = 4
    payload = json.loads(formatter.format(record))
    assert payload["request_id"] == "req-12345678"
    assert payload["path"] == "/health/live"
    assert payload["status_code"] == 200
    assert "leaked-token" not in payload["message"]
    assert Settings(log_format="json").resolved_log_format == "json"
