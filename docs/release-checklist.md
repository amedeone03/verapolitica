# Release checklist

Use this before promoting a VeraPolitica V1 build to staging or production.

## Quality

- [ ] `python -m pytest -q` is green
- [ ] PostgreSQL CI job is green (`pytest -m postgres` against a migrated DB)
- [ ] `python -m compileall -q backend scripts tests`
- [ ] `git diff --check` is clean
- [ ] Docker image builds (`docker build -t verapolitica:release .`)
- [ ] Alembic revisions reviewed; `alembic upgrade head` is the deploy step
- [ ] No real secrets in git (`.env` ignored, examples are placeholders)

## Configuration

- [ ] `VERAPOLITICA_ENV=production`
- [ ] PostgreSQL `VERAPOLITICA_DATABASE_URL`
- [ ] `VERAPOLITICA_ADMIN_API_KEY` is long, random, and not a demo/test value
- [ ] `VERAPOLITICA_CORS_ORIGINS` is an HTTPS allowlist (not `*`)
- [ ] `VERAPOLITICA_TRUSTED_HOSTS` lists the public hostnames
- [ ] `VERAPOLITICA_FORWARDED_ALLOW_IPS` set only if a trusted proxy exists
- [ ] `VERAPOLITICA_RAW_STORAGE_PATH` is a persistent volume
- [ ] `VERAPOLITICA_ENABLE_DEMO_UI=false`
- [ ] `VERAPOLITICA_ENABLE_API_DOCS=false` unless docs are intentionally public
- [ ] `VERAPOLITICA_LOG_FORMAT=json`
- [ ] Paid AI provider config is blank, or provider+model+key are intentional
- [ ] Cron schedules are intentional; scheduler runs as a single replica

## Data safety

- [ ] Database backup taken and a restore has been tested at least once
- [ ] `python -m scripts.prepare_demo` will not be run
- [ ] `python -m scripts.release_check` reports no synthetic civic contamination
- [ ] Raw storage is writable and will survive container replacement

## Runtime

- [ ] `alembic upgrade head` then `alembic current`
- [ ] Web: `python -m scripts.run_web`
- [ ] Scheduler: `python -m scripts.run_scheduler` (one process)
- [ ] `GET /health/live` returns 200
- [ ] `GET /health/ready` returns 200 with `schema_current: true`
- [ ] `python -m scripts.smoke_test --base-url ...` is read-only and green
- [ ] Invalid admin bearer is 401
- [ ] `/demo/` is unavailable
- [ ] `/docs` matches the chosen docs policy
- [ ] Domain, DNS, and HTTPS are confirmed at the provider
- [ ] Source ingestion sanity: one operator job or a recent successful
      `/admin/jobs` row, if live sources are in use

## After release

- [ ] Watch 5xx rate, readiness failures, and job failures
- [ ] Confirm disk/volume capacity for PostgreSQL and raw storage
- [ ] Keep a single scheduler heartbeat (recent job history or process uptime)

The current public HTTP surface is the V1 contract. Do not break existing
clients for a `/v1` rename in this release.
