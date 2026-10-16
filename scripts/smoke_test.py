from __future__ import annotations

import argparse
import json
import sys

import httpx


READ_ONLY_PATHS = (
    "/health/live",
    "/health/ready",
    "/app/",
    "/politicians?offset=0&limit=1",
    "/proposals?offset=0&limit=1",
    "/referendums?offset=0&limit=1",
    "/regions?offset=0&limit=1",
    "/glossary?offset=0&limit=1",
    "/search?q=test&limit=1",
)

PRODUCTION_ABSENT_PATHS = (
    "/demo/",
    "/docs",
    "/redoc",
    "/openapi.json",
)
ADMIN_UNAUTH_PATH = "/admin/drafts"


def run_smoke(
    base_url: str,
    *,
    timeout: float = 10.0,
    production: bool = False,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    base = base_url.rstrip("/")
    failures: list[str] = []
    request_headers = dict(headers or {})
    with httpx.Client(
        base_url=base,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        for path in READ_ONLY_PATHS:
            response = client.get(path, headers=request_headers)
            request_id = response.headers.get("x-request-id")
            if path.startswith("/health/ready") and response.status_code == 503:
                failures.append(f"{path} not ready ({response.status_code})")
            elif response.status_code >= 400:
                failures.append(f"{path} returned {response.status_code}")
            body = response.text.casefold()
            if "authorization" in body or "api_key" in body:
                failures.append(f"{path} leaked a credential-like field")
            if request_id is None and path.startswith("/health"):
                failures.append(f"{path} missing X-Request-ID")
            if path.startswith("/health/ready") and response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    failures.append("/health/ready is not JSON")
                else:
                    blob = json.dumps(payload).casefold()
                    if "password" in blob or "postgresql+psycopg://" in blob:
                        failures.append("/health/ready leaked a database secret")
                    if production and payload.get("schema_current") is not True:
                        failures.append("/health/ready schema_current is not true")
        if production:
            for path in PRODUCTION_ABSENT_PATHS:
                response = client.get(path, headers=request_headers)
                if response.status_code != 404:
                    failures.append(
                        f"{path} should be absent in production ({response.status_code})"
                    )
            admin = client.get(ADMIN_UNAUTH_PATH, headers=request_headers)
            if admin.status_code != 401:
                failures.append(
                    f"{ADMIN_UNAUTH_PATH} should be 401 without a key "
                    f"({admin.status_code})"
                )
            admin_blob = admin.text.casefold()
            if "postgresql+psycopg://" in admin_blob or "admin_api_key" in admin_blob:
                failures.append("admin 401 leaked a secret")
    return {
        "ok": not failures,
        "failures": failures,
        "base_url": base,
        "production": production,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only production smoke test. Does not mutate data."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--production",
        action="store_true",
        help="Also require demo/docs absent and admin unauthenticated 401",
    )
    parser.add_argument(
        "--host-header",
        default="",
        help="Optional Host header (TrustedHost) when probing 127.0.0.1",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    headers = {"Host": args.host_header} if args.host_header.strip() else None
    payload = run_smoke(
        args.base_url,
        timeout=args.timeout,
        production=args.production,
        headers=headers,
    )
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
