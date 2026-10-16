# Release checklist

Use before promoting a VeraPolitica V1 build. First VPS bring-up follows
[production_deployment.md](production_deployment.md) and
[first_deploy_checklist.md](first_deploy_checklist.md).

## Before deploy

- [ ] Git working tree clean; deploy SHA recorded (`git rev-parse HEAD`)
- [ ] GitHub Backend CI green on that SHA (Python tests, PostgreSQL migrations, Docker image)
- [ ] `python -m pytest -q` and `python -m compileall -q backend scripts tests` if you built locally
- [ ] `.env.production` filled from `.env.production.example` (never committed)
- [ ] `VERAPOLITICA_ENV=production`
- [ ] `PUBLIC_BASE_URL`, CORS, and trusted hosts match the public origin/host
- [ ] PostgreSQL URL / compose `POSTGRES_*` are real secrets (not example `verapolitica`)
- [ ] `VERAPOLITICA_ADMIN_API_KEY` is long, random, not a demo/placeholder
- [ ] `VERAPOLITICA_RAW_STORAGE_PATH` persists (`/var/lib/verapolitica/raw` in compose)
- [ ] `VERAPOLITICA_ENABLE_DEMO_UI=false` and `VERAPOLITICA_ENABLE_API_DOCS=false`
- [ ] `VERAPOLITICA_LOG_FORMAT=json`
- [ ] Scheduler cron blank; LLM provider blank
- [ ] `python -m scripts.prepare_demo` will not be run

## If this is an upgrade (data already exists)

- [ ] PostgreSQL dump + raw archive taken and copied off-VPS
- [ ] Restore has been tested at least once on an isolated database

## Runtime

- [ ] `migrate` succeeded; `alembic current` equals `alembic heads` (`e2b8f6c03d41`)
- [ ] `web` up; **scheduler container not running**
- [ ] `GET /health/live` → 200
- [ ] `GET /health/ready` → 200 with `schema_current: true`
- [ ] `GET /app/` and `GET /politicians` → 200
- [ ] `/demo/` and `/docs` absent
- [ ] Unauthenticated `GET /admin/drafts` → 401
- [ ] `python -m scripts.smoke_test --base-url … --production` is read-only and green
- [ ] Logs do not print DSNs or the admin key

## Public exposure (when DNS/TLS are in scope)

- [ ] Reverse proxy to `127.0.0.1:8000`; `FORWARDED_ALLOW_IPS` is the proxy only
- [ ] HTTPS works; HSTS only after that
- [ ] Rate limit and body size set at the proxy ([production_security.md](production_security.md))

## After release

- [ ] Watch readiness failures and 5xx
- [ ] Confirm disk for PostgreSQL and raw storage
- [ ] First ingest uses official scripts, then editorial publish — not demo seed
- [ ] First backup copied off-VPS after ingest

The current public HTTP surface is the V1 contract. Do not break existing
clients for a `/v1` rename in this release.
