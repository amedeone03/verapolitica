# Production configuration

This document lists VeraPolitica environment variables for a production VPS.
It is not a deployment runbook. Copy `.env.production.example` to a gitignored
`.env.production` (or export the same names in the process environment) and fill
in real values when the server is available.

All application settings use the `VERAPOLITICA_` prefix. There is no separate
`SECRET_KEY`; admin authentication is `VERAPOLITICA_ADMIN_API_KEY`.

Local development continues to use `.env.example`. Demo launchers use
gitignored `.env.unified-demo` / `.env.ceo-demo` and must not be copied to the
VPS.

Production validation runs when `VERAPOLITICA_ENV=production`. Missing or unsafe
required values raise `ProductionConfigError` at process start.

## Required

| Variable | Example format | Used by | Notes |
| --- | --- | --- | --- |
| `VERAPOLITICA_ENV` | `production` | `Settings`, demo-script guards, logging | Must be `production`. Other values skip production validation. |
| `VERAPOLITICA_PUBLIC_BASE_URL` | `https://example.com` | production validator; public site origin | Absolute `http(s)` URL. Its origin must appear in CORS and its host in trusted hosts. Prefer HTTPS. |
| `VERAPOLITICA_DATABASE_URL` | `postgresql+psycopg://USER:PASSWORD@HOST:5432/verapolitica` | SQLAlchemy, Alembic, jobs | PostgreSQL required. `postgres://` and `postgresql://` are rewritten to `postgresql+psycopg://`. SQLite is rejected. Alembic owns schema: run `alembic upgrade head` on a fresh or existing database before web start; never rely on `create_all`. Backup first. |
| `VERAPOLITICA_ADMIN_API_KEY` | long random string, 24+ characters | `/admin/*` Bearer auth | Required. Short, well-known, demo, CI, and documentation placeholder values are rejected. Never commit the real value. |
| `VERAPOLITICA_CORS_ORIGINS` | `https://example.com` | FastAPI CORS middleware | Comma-separated allowlist. `*` is rejected. Must include the public base URL origin. |
| `VERAPOLITICA_TRUSTED_HOSTS` | `example.com,www.example.com` | TrustedHost middleware | Comma-separated allowlist. `*` is rejected. Must include the public base URL host. |
| `VERAPOLITICA_RAW_STORAGE_PATH` | `/var/lib/verapolitica/raw` | collectors, provenance artifacts | Absolute path on a persistent volume. Relative paths and demo trees (`ceo_demo`, `unified_demo`, `data/demo`) are rejected. |

## Security / process

| Variable | Required | Default if unset | Used by | Notes |
| --- | --- | --- | --- | --- |
| `VERAPOLITICA_ADMIN_REVIEWER_IDENTITY` | optional | `admin-editor` | final review records | Server-side reviewer label; never taken from request JSON. |
| `VERAPOLITICA_FORWARDED_ALLOW_IPS` | optional | empty (ignore `X-Forwarded-*`) | uvicorn `ProxyHeadersMiddleware` | Set only to trusted proxy IPs/CIDRs. `*` is rejected in production. |
| `VERAPOLITICA_MAX_REQUEST_BODY_BYTES` | optional | `1048576` (1 MiB) | request middleware | Production must stay ≤ 2 MiB (no HTTP uploads). Demo `/demo/*` uses the AI document cap instead. |
| `VERAPOLITICA_ENABLE_DEMO_UI` | optional | off in production | `/demo/` mount | Must not be `true` in production. Demo routes are also not mounted when `env=production`. |
| `VERAPOLITICA_ENABLE_API_DOCS` | optional | off in production | `/docs`, `/redoc`, `/openapi.json` | Leave `false` unless docs are intentionally public. |
| `VERAPOLITICA_WEB_HOST` | optional | `0.0.0.0` | `scripts.run_web` | Bind address behind the reverse proxy. |
| `VERAPOLITICA_WEB_PORT` | optional | `8000` | `scripts.run_web` | On Render, `PORT` overrides this when `RENDER=true`. |
| `VERAPOLITICA_WEB_WORKERS` | optional | `2` | gunicorn | Production ASGI workers. Do not use `uvicorn --reload`. |

## Logging

| Variable | Required | Default if unset | Used by | Notes |
| --- | --- | --- | --- | --- |
| `VERAPOLITICA_LOG_FORMAT` | optional | `json` when `env=production` | logging | Use `json` in production. Invalid values fall back to json/text by environment. |
| `VERAPOLITICA_LOG_LEVEL` | optional | `INFO` | logging | Standard Python log level name. |

There is no `DEBUG` flag. OpenAPI docs are the closest debug surface and default
off in production.

## Database pool

| Variable | Required | Default | Used by |
| --- | --- | --- | --- |
| `VERAPOLITICA_DB_POOL_SIZE` | optional | `5` | SQLAlchemy engine |
| `VERAPOLITICA_DB_MAX_OVERFLOW` | optional | `5` | SQLAlchemy engine |
| `VERAPOLITICA_DB_POOL_TIMEOUT` | optional | `30` | SQLAlchemy engine |
| `VERAPOLITICA_DB_POOL_RECYCLE` | optional | `1800` | SQLAlchemy engine |

## Storage (optional)

| Variable | Required | Default | Used by | Notes |
| --- | --- | --- | --- | --- |
| `VERAPOLITICA_PORTRAITS_PATH` | optional | unset | `GET /portraits` | JSON map of politician portraits. Leave blank if unused. |
| `VERAPOLITICA_DEMO_UPLOAD_PATH` | no | `./data/ceo_demo/uploads` | demo editorial upload only | Demo-only. Production does not mount demo routes; do not set this on the VPS. |

## AI / Ollama

Live extraction stays disabled until provider and model are both set. Setting
`VERAPOLITICA_ENV=production` does not start an AI job. Extraction is invoked
by operator commands such as `python -m scripts.run_ai_extraction`.

| Variable | Required | Default | Used by | Notes |
| --- | --- | --- | --- | --- |
| `VERAPOLITICA_LLM_PROVIDER` | optional | empty (disabled) | AI extraction | `ollama` or `openai`. Leave blank. |
| `VERAPOLITICA_LLM_MODEL` | if provider set | empty | AI extraction | Required when a provider is configured. |
| `VERAPOLITICA_LLM_API_KEY` | if provider is `openai` | empty | OpenAI provider | SecretStr. Not required for Ollama. |
| `VERAPOLITICA_OLLAMA_BASE_URL` | if provider is `ollama` | `http://127.0.0.1:11434` | Ollama provider | Local Ollama listen URL. |
| `VERAPOLITICA_OLLAMA_NUM_CTX` | optional | `8192` | Ollama provider | |
| `VERAPOLITICA_OLLAMA_STRUCTURED_FORMAT` | optional | `json` | Ollama provider | `json` or `json_schema`. |
| `VERAPOLITICA_LLM_TIMEOUT_SECONDS` | optional | `180` | AI extraction | |
| `VERAPOLITICA_LLM_MAX_RETRIES` | optional | `1` | AI extraction | |

Document size/chunk limits (`VERAPOLITICA_AI_MAX_*`) and evaluation thresholds
(`VERAPOLITICA_AI_EVAL_*`) keep their code defaults. Tune them locally via
`.env.example`; they are not required to boot production.

## Scheduler

The web process never starts the scheduler. Blank cron values disable each job.
Keep every schedule blank until a later deployment step.

| Variable | Required | Default | Used by | Notes |
| --- | --- | --- | --- | --- |
| `VERAPOLITICA_SCHEDULE_SENATO_CRON` | optional | empty | `scripts.run_scheduler` | Five-field UTC cron. |
| `VERAPOLITICA_SCHEDULE_CAMERA_CRON` | optional | empty | `scripts.run_scheduler` | |
| `VERAPOLITICA_SCHEDULE_GOVERNO_CRON` | optional | empty | `scripts.run_scheduler` | |
| `VERAPOLITICA_SCHEDULE_PROPOSALS_CRON` | optional | empty | `scripts.run_scheduler` | |
| `VERAPOLITICA_SCHEDULE_TERRITORIES_CRON` | optional | empty | `scripts.run_scheduler` | |
| `VERAPOLITICA_SCHEDULE_TERRITORIAL_OFFICES_CRON` | optional | empty | `scripts.run_scheduler` | |
| `VERAPOLITICA_SCHEDULE_CIVIC_REMINDERS_CRON` | optional | empty | `scripts.run_scheduler` | |
| `VERAPOLITICA_SCHEDULE_PLEDGE_EVIDENCE_CRON` | optional | empty | `scripts.run_scheduler` | |
| `VERAPOLITICA_JOB_MAX_RETRIES` | optional | `1` | job runner | |
| `VERAPOLITICA_JOB_RETRY_BACKOFF_SECONDS` | optional | `2` | job runner | |
| `VERAPOLITICA_JOB_STALE_AFTER_MINUTES` | optional | `60` | stale-run recovery | |

## Official source endpoints

These have public institutional defaults and are optional to override.

| Variable | Default | Used by |
| --- | --- | --- |
| `VERAPOLITICA_SENATO_SPARQL_ENDPOINT` | `https://dati.senato.it/sparql` | Senato collector |
| `VERAPOLITICA_SENATO_LEGISLATURE` | `19` | Senato collector |
| `VERAPOLITICA_SENATO_REQUEST_TIMEOUT_SECONDS` | `30` | Senato collector |
| `VERAPOLITICA_SENATO_PROPOSAL_RECORD_LIMIT` | `100` | Senato proposal collector |
| `VERAPOLITICA_CAMERA_SPARQL_ENDPOINT` | `https://dati.camera.it/sparql` | Camera collector |
| `VERAPOLITICA_CAMERA_LEGISLATURE` | `19` | Camera collector |
| `VERAPOLITICA_CAMERA_REQUEST_TIMEOUT_SECONDS` | `30` | Camera collector |
| `VERAPOLITICA_GOVERNO_INDEX_URL` | `https://www.governo.it/it/ministri-e-sottosegretari` | Governo collector |
| `VERAPOLITICA_GOVERNO_REQUEST_TIMEOUT_SECONDS` | `30` | Governo collector |
| `VERAPOLITICA_ISTAT_MUNICIPALITIES_XLSX_URL` | ISTAT municipalities workbook URL | territorial ingestion |
| `VERAPOLITICA_DAIT_CURRENT_MAYORS_CSV_URL` | DAIT current-mayors CSV URL | territorial offices |
| `VERAPOLITICA_TERRITORIAL_REQUEST_TIMEOUT_SECONDS` | `60` | territorial ingestion |

## Not application settings

| Name | Where it appears | Production? |
| --- | --- | --- |
| `RENDER`, `PORT` | `scripts/run_web.py` | Platform-only. Ignored on a generic VPS. |
| `VERAPOLITICA_POSTGRES_TEST_URL` | PostgreSQL pytest job | Tests only. |
| `VERAPOLITICA_SENTRY_DSN` | none | Unused. Not a Settings field. |

## Safe production behavior when values are left at template defaults

- Scheduler stays disabled (blank cron).
- AI extraction stays disabled (blank provider/model).
- Demo UI is off and cannot be turned on.
- API docs are off unless explicitly enabled.
- CORS and hosts are explicit allowlists; wildcards fail startup.
- SQLite, relative demo storage paths, and weak admin keys fail startup.
