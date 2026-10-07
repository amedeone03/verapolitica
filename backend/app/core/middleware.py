from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.app.core.request_context import request_id_var


logger = logging.getLogger("verapolitica.http")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

# FastAPI's Swagger UI and ReDoc pages load their bundles from jsdelivr and
# bootstrap with an inline script. They are disabled in production by default
# (Settings.api_docs_enabled); this relaxed policy applies to those pages only.
DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc"})
DOCS_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "img-src 'self' data: https:; "
    "font-src 'self' https://fonts.gstatic.com; "
    "worker-src 'self' blob:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def resolve_request_id(incoming: str | None) -> str:
    candidate = (incoming or "").strip()
    if _REQUEST_ID.fullmatch(candidate):
        return candidate
    return str(uuid.uuid4())


def apply_security_headers(response: Response, path: str = "") -> None:
    if path in DOCS_PATHS:
        response.headers.setdefault(
            "Content-Security-Policy", DOCS_CONTENT_SECURITY_POLICY
        )
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = resolve_request_id(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "unhandled request failure",
                    extra={
                        "path": request.url.path,
                        "method": request.method,
                        "request_id": request_id,
                    },
                )
                raise
            duration_ms = int((time.perf_counter() - started) * 1000)
            response.headers["X-Request-ID"] = request_id
            apply_security_headers(response, request.url.path)
            logger.info(
                "request completed",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "request_id": request_id,
                },
            )
            return response
        finally:
            request_id_var.reset(token)
