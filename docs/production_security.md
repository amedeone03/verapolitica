# Production security

This is the V1 threat boundary for exposing VeraPolitica on a VPS. It is not a
pentest report, compliance certification, or the final editorial identity
system.

Shared `VERAPOLITICA_ADMIN_API_KEY` is a **temporary** production control for a
small editorial team. It is not per-editor login, SSO, or RBAC. Replace it with
real editorial accounts before the team grows.

Do not treat this document as permission to skip a reverse proxy. TLS, HSTS,
and request rate limits belong at the proxy in a later VPS step.

## Threat boundary

Assumed:

- Citizen visitors are unauthenticated and read-only.
- Editorial writes use one shared bearer token.
- Attackers probe `/admin`, forge `Host` / `Origin` / `X-Forwarded-*`, try
  path traversal, oversized bodies, and secret leakage in errors.
- Official source endpoints may be slow; already-published data must still
  serve.

Out of scope for V1: OAuth, citizen accounts, Redis/distributed rate limiting,
WAF product selection, and paid cloud IAM.

## Public vs admin surfaces

| Class | Routes | Production |
| --- | --- | --- |
| **public** | `GET /politicians`, `/proposals`, `/search`, `/regions`, `/municipalities`, `/parliamentary-groups`, `/political-parties`, `/referendums`, `/voting-guides`, `/glossary`, `/portraits`, scorecards/methodology, citizen UI `/app/` | Mounted. Read-only published records. Pagination and search length are capped. |
| **admin/editor protected** | `/admin/drafts`, `/admin/identity-resolution`, `/admin/proposals/drafts`, `/admin/referendums/drafts`, `/admin/jobs`, `/admin/pledges` | Mounted. HTTP Bearer `VERAPOLITICA_ADMIN_API_KEY` on the whole `/admin` router. |
| **internal/operator** | `python -m scripts.run_web`, `run_scheduler`, `backup_postgres`, `restore_postgres`, `release_check`, `smoke_test`, `alembic`, ingestion CLIs | Not HTTP. Run on the host/container with env access. |
| **demo-only** | `/demo/*` (editorial UI, AI upload, pledge-review HTML), demo uploads | **Not mounted** when `env=production` or `ENABLE_DEMO_UI=false`. Production validation rejects `ENABLE_DEMO_UI=true`. |
| **should not exist in production** | `/docs`, `/redoc`, `/openapi.json`, debug `/__boom`-style routes, demo reset HTTP | Docs default off. No debug routes shipped. Reset is CLI-only and refuses production. |

Health:

- `GET /health/live` — process up (no secrets)
- `GET /health/ready` — DB + Alembic head (no DSN)
- `GET /health` — compatibility; may show degraded DB without connection strings

Raw documents and demo uploads are **not** public file routes. Admin draft
payloads include hashes and source URLs, not filesystem paths.

## Admin API-key model

- Scheme: `Authorization: Bearer <key>` only. Query strings, JSON bodies, and
  `X-Admin-Key` are ignored.
- Comparison hashes both sides with SHA-256, then `secrets.compare_digest`.
- Missing or invalid tokens return **401** with `WWW-Authenticate: Bearer`.
- Unconfigured key returns **503**.
- Production rejects short, placeholder, and well-known keys (24+ characters).
- Reviewer identity comes from `VERAPOLITICA_ADMIN_REVIEWER_IDENTITY`, not the
  request body.
- The key is `SecretStr`; JSON dumps of Settings mask it. Logs redact bearer
  tokens and `VERAPOLITICA_*KEY` assignments.

Limitations: anyone with the key is a full editor; rotation is a process
restart; there is no per-action ACL.

## Demo / internal isolation

`create_app` mounts demo routers and `/demo` static files only when
`demo_ui_enabled and not is_production`. Production also refuses
`VERAPOLITICA_ENABLE_DEMO_UI=true` at settings load.

Local/demo behavior (`prepare_demo`, AI upload, CEO demo) is unchanged for
non-production environments.

## Upload and file safety

Production HTTP has **no upload route**. Operator AI extraction is CLI
(`python -m scripts.run_ai_extraction`) into `RAW_STORAGE_PATH`, which is
outside `/app` static files.

Demo uploads (local only):

- Allowed suffixes `.html` / `.htm` / `.pdf`; PDFs must start with `%PDF`
- Filename sanitized (no path traversal, no `.exe`)
- Size capped by `VERAPOLITICA_AI_MAX_DOCUMENT_BYTES`
- Stored under `VERAPOLITICA_DEMO_UPLOAD_PATH`, never under `/app`

Portraits:

- `GET /portraits/{id}/image` serves only a hex filename matching
  `^[0-9a-f]{24}\.(jpg|png|webp)$` resolved inside the portraits directory
- `politician_id` is a positive integer, not a filesystem path
- Non-HTTPS remote URLs are dropped from the listing

Citizen static files are Starlette `StaticFiles` rooted at `frontend/app`.

## Abuse / request limits

In-process (per gunicorn worker, **not** a cluster-wide limiter):

- `VERAPOLITICA_MAX_REQUEST_BODY_BYTES` (default 1 MiB; production max 2 MiB)
- Demo `/demo/*` uses the AI document cap plus a small multipart overhead
- Search `q` max 200 characters; public `limit` ≤ 100 (search ≤ 50)
- Gunicorn `--limit-request-line 8190` and field-count/size caps

**Reverse proxy must rate-limit** public GET traffic and cap
`client_max_body_size` (for example 1m). Do not add Redis for this milestone.

Admin POST bodies are still attacker-usable **after** the bearer token is
stolen; keep the key off the citizen UI.

## CORS / host / proxy

Unchanged from Step 1:

- Production CORS is an explicit origin allowlist; `*` rejected
- CORS methods are `GET`, `HEAD`, `OPTIONS` (citizen UI is read-only; admin is
  not a browser CORS client)
- `allow_credentials=False`
- Trusted hosts required; `*` rejected
- `PUBLIC_BASE_URL` origin/host must appear in those allowlists
- `X-Forwarded-*` ignored unless `VERAPOLITICA_FORWARDED_ALLOW_IPS` is set;
  `*` rejected

## Error handling and secrets

Production 500s return `internal_error` plus `request_id`. No stack traces,
DSNs, or keys in the client body. Validation errors in production omit Pydantic
`input` / `ctx` (submitted values). Persistence failures use a generic message.

`.env` / `.env.production` stay gitignored. Docker build context excludes
`.env*`, `tests`, `data`, `frontend/demo`, `backups`. Backup manifests omit
secrets. DB readiness payloads use `"database": "error"`, not the URL.

## Security headers

FastAPI sets on every response:

- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`
- `X-Frame-Options: DENY`
- `Content-Security-Policy` with `frame-ancestors 'none'`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`

`/docs` (when enabled) gets a looser CSP for Swagger CDN assets.

**Reverse proxy (later VPS step) owns:**

- TLS / HTTPS redirect
- `Strict-Transport-Security` (do not set HSTS on the HTTP app port)
- Optional extra CSP if the proxy is the public HTTPS terminator

Do not duplicate HSTS inside gunicorn; the app speaks HTTP to the proxy.

## API documentation

`/docs`, `/redoc`, and `/openapi.json` are off unless
`VERAPOLITICA_ENABLE_API_DOCS=true`. Local development keeps them on by
default (`env=development`). Leave them off on the VPS.

## Containers

- Image user `verapolitica` (uid 10001), not root
- Application code in `/app` stays root-owned (not world-writable)
- Only `/var/lib/verapolitica/raw` is writable for provenance files
- Compose publishes `127.0.0.1:8000` only; PostgreSQL port is not published
- No `privileged`, no Docker socket mount
- Scheduler is an opt-in compose profile and still idle until cron is set

## What remains for real auth later

- Per-editor accounts, MFA, session expiry, audit of *who* published
- Split roles (reviewer vs ingestion operator)
- Distributed rate limiting / WAF
- DNS, TLS certificates, Caddy (see [production_deployment.md](production_deployment.md) §7)
- Enabling the scheduler only after those controls exist
