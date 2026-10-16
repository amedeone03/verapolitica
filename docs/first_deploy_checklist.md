# First-deploy checklist

Use with [production_deployment.md](production_deployment.md). Check items in
order on the VPS. Scheduler, demo, AI, and real DNS stay off until the matching
row.

## Host

- [ ] VPS reachable over SSH
- [ ] Non-root user can run `docker compose`
- [ ] Docker Engine + Compose plugin installed
- [ ] Git and curl installed
- [ ] Disk/RAM acceptable for a small-team V1 (see runbook)

## Code

- [ ] Repo cloned under `/opt/verapolitica/repo`
- [ ] `git checkout` of intended `main` commit
- [ ] `git rev-parse HEAD` recorded
- [ ] `git status` clean
- [ ] GitHub Backend CI green on that SHA (Python, PostgreSQL, Docker image)

## Configuration

- [ ] `.env.production` copied from `.env.production.example`, mode `0600`
- [ ] `VERAPOLITICA_ENV=production`
- [ ] `PUBLIC_BASE_URL` / CORS / trusted hosts match the real domain
- [ ] Strong `VERAPOLITICA_ADMIN_API_KEY` (24+, not a placeholder)
- [ ] Strong `POSTGRES_PASSWORD` (not the example value)
- [ ] Cron variables blank
- [ ] LLM provider blank
- [ ] Demo UI and API docs `false`

## Stack

- [ ] `db` healthy
- [ ] `migrate` succeeded (`alembic current` = `e2b8f6c03d41`)
- [ ] `web` running; **no** scheduler container
- [ ] `curl` `/health/live` → 200 (use `Host: YOUR_DOMAIN` on localhost)
- [ ] `curl` `/health/ready` → 200, `schema_current: true`
- [ ] `GET /app/` → 200
- [ ] `GET /politicians` → 200
- [ ] `/demo/` and `/docs` absent
- [ ] `GET /admin/drafts` without a key → 401
- [ ] Logs do not print the DB password or admin key

```bash
python -m scripts.smoke_test --base-url http://127.0.0.1:8000 --production \
  --host-header YOUR_DOMAIN
```

## Public HTTPS (when ready; skip until the VPS should be public)

- [ ] Reverse proxy to `127.0.0.1:8000`
- [ ] `FORWARDED_ALLOW_IPS` set only to the proxy
- [ ] A/AAAA records point at the VPS
- [ ] TLS certificate issued
- [ ] `https://YOUR_DOMAIN/health/ready` → 200
- [ ] HSTS enabled only after HTTPS works
- [ ] `python -m scripts.smoke_test --base-url https://YOUR_DOMAIN --production`

## Data and backup (after schema is up; not demo seed)

- [ ] Official ingest via `run_territorial_ingestion` / `run_ingestion` (not `prepare_demo`)
- [ ] Bootstrap politicians only after a dry-run
- [ ] Editorial review/publish for anything public
- [ ] First backup (db dump from `db` container + raw archive) copied off-VPS
