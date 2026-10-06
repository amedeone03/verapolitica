# Production runbook

VeraPolitica V1 is a small-team deployment: one web process, one scheduler
process, managed PostgreSQL, and a persistent volume for raw documents.
HTTPS terminates at the hosting provider or reverse proxy. The application
listens for HTTP internally.

```text
Internet
  -> HTTPS / managed reverse proxy
  -> gunicorn web process (Uvicorn workers)
  -> PostgreSQL

Separate process:
  python -m scripts.run_scheduler
```

Do not run Kubernetes, Redis, Celery, or a second scheduler replica.

## Prerequisites

- PostgreSQL 16
- Python 3.13+ with `backend/requirements.txt`, or the repository Dockerfile
- Persistent disk/volume for `VERAPOLITICA_RAW_STORAGE_PATH`
- A long random `VERAPOLITICA_ADMIN_API_KEY` (24+ characters)
- Explicit CORS and trusted-host allowlists
- Provider TLS, DNS, and proxy rate limiting

Copy `.env.example` and fill production values. Never commit `.env`.

Example production configuration (placeholders only):

```bash
VERAPOLITICA_ENV=production
VERAPOLITICA_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/verapolitica
VERAPOLITICA_RAW_STORAGE_PATH=/var/lib/verapolitica/raw
VERAPOLITICA_ADMIN_API_KEY=replace-with-a-long-random-secret
VERAPOLITICA_ADMIN_REVIEWER_IDENTITY=production-editor
VERAPOLITICA_CORS_ORIGINS=https://verapolitica.it,https://www.verapolitica.it
VERAPOLITICA_TRUSTED_HOSTS=verapolitica.it,www.verapolitica.it
VERAPOLITICA_FORWARDED_ALLOW_IPS=   # set only to the proxy IP or CIDR
VERAPOLITICA_LOG_FORMAT=json
VERAPOLITICA_ENABLE_DEMO_UI=false
VERAPOLITICA_ENABLE_API_DOCS=false
VERAPOLITICA_WEB_HOST=0.0.0.0
VERAPOLITICA_WEB_PORT=8000
VERAPOLITICA_WEB_WORKERS=2
VERAPOLITICA_JOB_STALE_AFTER_MINUTES=60
```

Leave `VERAPOLITICA_LLM_*` blank unless a paid extraction run is intentional.
Leave schedule cron variables blank until you are ready for live ingestion.

## Migrations

The application never runs Alembic automatically.

```bash
pg_dump "$DATABASE_URL" -Fc -f backup.dump   # see backup section
python -m alembic upgrade head
python -m alembic current
```

If the schema is behind head, `/health/ready` returns 503. Start web only after
`alembic current` matches head.

## Startup commands

Web (production ASGI, not `uvicorn --reload`):

```bash
python -m scripts.run_web
```

Equivalent:

```bash
gunicorn backend.app.main:app \
  -k uvicorn.workers.UvicornWorker \
  --bind "$VERAPOLITICA_WEB_HOST:$VERAPOLITICA_WEB_PORT" \
  --workers "$VERAPOLITICA_WEB_WORKERS"
```

Scheduler (exactly one replica):

```bash
python -m scripts.run_scheduler
```

Citizen UI is served at `/app/`. `/demo/` is off in production unless
`VERAPOLITICA_ENABLE_DEMO_UI=true`. OpenAPI `/docs` is off unless
`VERAPOLITICA_ENABLE_API_DOCS=true`.

## Health checks

| Endpoint | Use | Checks |
| --- | --- | --- |
| `GET /health/live` | process liveness / Docker HEALTHCHECK | process is up |
| `GET /health/ready` | load balancer readiness | DB ping + Alembic head |
| `GET /health` | compatibility | DB ping; does not fail the process |

Liveness does not depend on Senato, Camera, or Governo availability.

```bash
python -m scripts.smoke_test --base-url https://verapolitica.it
python -m scripts.release_check
```

`release_check` does not run ingestion. It must not print DSNs or API keys.

## Deployment order

1. Take a PostgreSQL backup.
2. Deploy the migration-compatible image/code.
3. Run `alembic upgrade head`.
4. Start or restart the web process.
5. Start or restart the single scheduler process.
6. Confirm `/health/live` and `/health/ready`.
7. Run the read-only smoke test.

Rollback: restore the previous image only if it is schema-compatible with the
current database. Alembic downgrade is not a safe production data rollback.
Restore from backup when a migration must be undone.

## Ingestion checks

Inspect `/admin/jobs` with the bearer token. Look for `status=failed`,
`stale_recovered=true`, `duration_ms`, and `attempt_count`.

A `running` row older than `VERAPOLITICA_JOB_STALE_AFTER_MINUTES` is marked
failed on the next job start or scheduler start. History is kept. A fresh
running row still blocks overlap.

Do not start a second scheduler. Do not run `python -m scripts.prepare_demo`
against production.

## Backup

Prefer the managed provider's automated snapshots plus a periodic logical dump.

```bash
pg_dump "$DATABASE_URL" -Fc -f "verapolitica-$(date -u +%Y%m%dT%H%M%SZ).dump"
```

Do not embed passwords in scripts or docs. Use the environment or a secret
manager. Keep dumps off the web container. Define retention (for example 7 daily
+ 4 weekly) with the provider.

Also back up the raw-storage volume. Published provenance depends on immutable
raw artifacts.

A backup that has never been restored is unverified.

## Restore

Restore into a new database when possible:

```bash
createdb verapolitica_restore
pg_restore --dbname "$RESTORE_DATABASE_URL" backup.dump
# or: pg_restore --clean --if-exists ... only on an isolated restore target
export VERAPOLITICA_DATABASE_URL="$RESTORE_DATABASE_URL"
python -m alembic current
python -m scripts.release_check
python -m scripts.smoke_test --base-url http://127.0.0.1:8000
```

Verify row counts for `politicians`, `proposals`, `referendums`,
`ingestion_job_runs`, and `raw_documents` against the pre-incident notes.
Remount the matching raw-storage snapshot.

## Raw storage

Local filesystem storage is the V1 production path. Mount
`VERAPOLITICA_RAW_STORAGE_PATH` on a persistent volume. Ephemeral container
disks will lose provenance artifacts on replace.

There is no S3 adapter in this milestone.

## Docker

```bash
docker build -t verapolitica:local .
docker compose up --build
```

`compose.yaml` is for local production-like testing only. Its passwords are not
production secrets. Run `alembic upgrade head` via the `migrate` service before
web/scheduler start.

Container HEALTHCHECK uses `/health/live`, not readiness, so a brief database
blip does not restart the web container in a loop.

## Provider notes

Render, Railway, Fly.io, and the major clouds can all run this shape:

- web service: `python -m scripts.run_web`
- worker service: `python -m scripts.run_scheduler`
- managed PostgreSQL
- persistent disk for raw storage
- HTTPS at the edge

Set `VERAPOLITICA_FORWARDED_ALLOW_IPS` to the proxy addresses if you need
correct HTTPS scheme/host behind `X-Forwarded-*`. Leave it empty to ignore
forwarded headers.

Rate limiting belongs at the reverse proxy. Process-local limits are not a
distributed control.

## Troubleshooting

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Process exits at start | production config validation | Fix env; see the raised `ProductionConfigError` |
| `/health/ready` 503 | DB down or Alembic behind | Check DB, run `alembic upgrade head` |
| 400 Invalid host | `VERAPOLITICA_TRUSTED_HOSTS` | Add the public hostname |
| CORS browser errors | origin not allowlisted | Add the exact HTTPS origin |
| `/demo/` visible | demo UI enabled | Set `VERAPOLITICA_ENABLE_DEMO_UI=false` |
| Jobs stuck `running` | crashed worker | Wait for stale recovery or inspect `/admin/jobs` |
| Duplicate ingestion | two schedulers | Stop extras; keep one replica |
| 401 on `/admin` | missing/invalid bearer | Rotate the server-side key; do not log it |
| Empty citizen data | no reviewed publications | Ingest, review, publish; do not seed demo data |

## Incident basics

1. Check `/health/live` and `/health/ready`.
2. Preserve logs (JSON request_id, job_run_id).
3. Do not run `prepare_demo` or destructive resets.
4. Pause the scheduler if ingestion is harmful.
5. Restore from a verified backup if data is wrong.
6. Rotate `VERAPOLITICA_ADMIN_API_KEY` if it leaked.
