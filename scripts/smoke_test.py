from __future__ import annotations

import argparse
import json
import sys

import httpx


READ_ONLY_PATHS = (
    "/health/live",
    "/health/ready",
    "/regions?offset=0&limit=1",
    "/glossary?offset=0&limit=1",
    "/search?q=test&limit=1",
)


def run_smoke(
    base_url: str,
    *,
    timeout: float = 10.0,
) -> dict[str, object]:
    base = base_url.rstrip("/")
    failures: list[str] = []
    with httpx.Client(
        base_url=base,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        for path in READ_ONLY_PATHS:
            response = client.get(path)
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
    return {"ok": not failures, "failures": failures, "base_url": base}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only production smoke test. Does not mutate data."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_smoke(args.base_url, timeout=args.timeout)
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
