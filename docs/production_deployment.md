# Production deployment (first VPS)

This is the **canonical first-deploy procedure**. Follow it when the CEO
provides a Linux VPS, SSH access, the public domain, and production secrets.

Do not start from [production-runbook.md](production-runbook.md) (day-2
operations), [production_containers.md](production_containers.md) (compose
shape), or README snippets. Those remain supporting references.

Live checkbox list: [first_deploy_checklist.md](first_deploy_checklist.md).

This document does **not** configure a real VPS, DNS, or TLS by itself. It
tells the operator exactly what to do when those exist.

Current Alembic head: `e2b8f6c03d41`. GitHub **Backend CI** (Python tests,
PostgreSQL migrations, Docker image) must be green on the commit you deploy.

---

## Assumptions

```text
Internet
  → reverse proxy (HTTPS, later in this procedure)
  → VeraPolitica web container (HTTP, 127.0.0.1:8000)
  → PostgreSQL container (not published on the host)
```

Compose services for first deploy:

| Service | First deploy |
| --- | --- |
| `db` | yes |
| `migrate` | yes (oneshot `alembic upgrade head`) |
| `web` | yes, after migrate succeeds |
| `scheduler` | **no** — do not pass `--profile scheduler` |

Persistent data:

- Docker volume `verapolitica_pg` (PostgreSQL)
- Docker volume `verapolitica_raw` → `/var/lib/verapolitica/raw` in the
  container (uid **10001**)

**Not required** to bring the public site up:

- Ollama, qwen, any LLM
- Redis, vector database, Kubernetes
- scheduler / cron
- demo UI, demo seed, `prepare_demo`
- OpenAPI `/docs`

Citizen UI is served by the web container at `/app/`. There is no separate
frontend service.

---

## 1. VPS prerequisites

Vendor-neutral. Ubuntu 24.04 LTS or Debian 12 are the usual targets; any
current Linux that runs Docker Engine is acceptable.

Must exist before step 2:

- SSH access
- A non-root account that can run Docker (for example user `deploy` in group
  `docker`)
- Docker Engine + Compose **plugin** (`docker compose version`)
- Git, curl
- PostgreSQL 16 client tools **on the host** only if you will run
  `scripts.backup_postgres` there; with compose, dumps use the `db` container
  (it already has `pg_dump`)
- Disk for images, PostgreSQL, and raw files
- Outbound HTTPS to GitHub and official sources (Senato / Camera / Governo /
  ISTAT / DAIT) when you ingest later

Practical sizing for this small-team V1 (not a load-test result):

| | Practical minimum | More comfortable |
| --- | --- | --- |
| CPU | 2 vCPU | 4 vCPU |
| RAM | 4 GiB | 8 GiB |
| Disk | 40 GiB | 80 GiB+ if raw archives grow |

Open host ports: **22** (SSH) and later **80/443** for the proxy. Do not
publish PostgreSQL (`5432`) on the public interface. Compose already binds
the app as `127.0.0.1:8000` only.

---

## 2. Directory layout

Recommended host layout:

```text
/opt/verapolitica/repo          clone (deploy user)
/opt/verapolitica/repo/.env.production   secrets, mode 0600, never in git
/var/lib/verapolitica/raw       optional bind-mount; else Docker volume
/var/lib/verapolitica/backups   operator backups, mode 0700
```

| Path | Owner | Notes |
| --- | --- | --- |
| `/opt/verapolitica/repo` | deploy user | code only; image user cannot write `/app` |
| `.env.production` | deploy user, `0600` | gitignored |
| container `/var/lib/verapolitica/raw` | uid **10001** | compose named volume `verapolitica_raw` |
| `/var/lib/verapolitica/backups` | deploy user, `0700` | host-side copies; keep a second copy off-VPS |

Default compose uses **named volumes**, not host bind-mounts. That is valid
for first deploy. If you bind-mount `/var/lib/verapolitica/raw` later, run
`chown 10001:10001` on that directory or the web process cannot write.

---

## 3. Clone a known commit

Deploy a **CI-green commit on `main`**, not a dirty working tree.

```bash
sudo mkdir -p /opt/verapolitica /var/lib/verapolitica/backups
sudo chown "$USER":"$USER" /opt/verapolitica /var/lib/verapolitica/backups
chmod 700 /var/lib/verapolitica/backups
cd /opt/verapolitica
git clone https://github.com/amedeone03/verapolitica.git repo
cd repo
git fetch origin
git checkout main
git pull --ff-only origin main
git rev-parse HEAD
git status
```

Record the SHA. Confirm GitHub **Backend CI** is green for that SHA (Python
tests, PostgreSQL migrations, Docker image).

---

## 4. Production environment file

```bash
cp .env.production.example .env.production
chmod 600 .env.production
```

Fill at least:

| Variable | First-deploy value |
| --- | --- |
| `VERAPOLITICA_ENV` | `production` |
| `VERAPOLITICA_PUBLIC_BASE_URL` | `https://YOUR_DOMAIN` (HTTPS origin even before TLS exists) |
| `VERAPOLITICA_CORS_ORIGINS` | that origin (and `https://www.YOUR_DOMAIN` if used) |
| `VERAPOLITICA_TRUSTED_HOSTS` | `YOUR_DOMAIN,www.YOUR_DOMAIN` |
| `VERAPOLITICA_ADMIN_API_KEY` | 24+ random characters; **not** a demo/placeholder |
| `VERAPOLITICA_ADMIN_REVIEWER_IDENTITY` | operator label, e.g. `production-editor` |
| `VERAPOLITICA_RAW_STORAGE_PATH` | `/var/lib/verapolitica/raw` (compose already forces this inside containers) |
| `VERAPOLITICA_WEB_HOST` | `0.0.0.0` |
| `VERAPOLITICA_WEB_PORT` | `8000` |
| `VERAPOLITICA_WEB_WORKERS` | `2` |
| `VERAPOLITICA_LOG_FORMAT` | `json` |
| `VERAPOLITICA_LOG_LEVEL` | `INFO` |
| `VERAPOLITICA_ENABLE_DEMO_UI` | `false` |
| `VERAPOLITICA_ENABLE_API_DOCS` | `false` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | **new secrets**; never the example `verapolitica` / `verapolitica` on a public VPS |

Leave **blank**:

- every `VERAPOLITICA_SCHEDULE_*_CRON`
- `VERAPOLITICA_LLM_PROVIDER`, `VERAPOLITICA_LLM_MODEL`, `VERAPOLITICA_LLM_API_KEY`

`VERAPOLITICA_FORWARDED_ALLOW_IPS`: leave empty until the reverse proxy exists,
then set it **only** to that proxy’s address or CIDR (`*` is rejected).

Compose **overrides** `VERAPOLITICA_DATABASE_URL` to
`postgresql+psycopg://POSTGRES_USER:POSTGRES_PASSWORD@db:5432/POSTGRES_DB`.
The `HOST` in the template file is unused inside this stack. Settings
reference: [production_configuration.md](production_configuration.md).

Generate an admin key (example; do not commit the result):

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## 5. Start the database, then precheck

```bash
cd /opt/verapolitica/repo
./scripts/run_production_compose.sh up -d db
./scripts/run_production_compose.sh ps
./scripts/run_production_compose.sh logs db
```

Wait until `db` is healthy (`pg_isready` in the compose healthcheck).

Inside the official `postgres:16` image the `POSTGRES_USER` role is a
database superuser, so `CREATE EXTENSION pg_trgm` (used by search/civic
revisions) succeeds. If migrate later fails on `pg_trgm`:

1. Confirm you did not replace `db` with a locked-down managed Postgres that
   forbids extensions.
2. `./scripts/run_production_compose.sh exec db \
     psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'`
3. Do **not** remove the extension or the trigram indexes from Alembic.

Do not run `metadata.create_all` against this database.

---

## 6. Migrate, then start web

**Fresh first deploy** (empty volume): no database backup is possible yet.
Migrate, then verify tooling after the first real ingest (step 12).

**Later upgrades** (data already exists): backup first
([backup_and_restore.md](backup_and_restore.md)), then migrate.

```bash
# Builds images, runs migrate, starts web. Do NOT add --profile scheduler.
./scripts/run_production_compose.sh up -d --build
```

Order enforced by compose:

1. `db` healthy
2. `migrate` runs `python -m alembic upgrade head` and must exit 0
3. `web` starts `python -m scripts.run_web` (gunicorn, no `--reload`)

Verify schema:

```bash
./scripts/run_production_compose.sh run --rm --no-deps migrate \
  python -m alembic current
./scripts/run_production_compose.sh run --rm --no-deps migrate \
  python -m alembic heads
```

`alembic current` must equal `alembic heads` (`e2b8f6c03d41`). If migrate
failed, `web` will not start (`depends_on: service_completed_successfully`).

Useful compose commands (always via the helper so `.env.production` is used):

```bash
./scripts/run_production_compose.sh ps
./scripts/run_production_compose.sh logs -f web
./scripts/run_production_compose.sh logs migrate
./scripts/run_production_compose.sh logs db
./scripts/run_production_compose.sh restart web
./scripts/run_production_compose.sh down          # keeps volumes
# ./scripts/run_production_compose.sh down --volumes   # DESTROYS data — not a rollback
```

Until the reverse proxy exists, probe with the public Host header (TrustedHost
will reject `Host: 127.0.0.1` if that name is not in `TRUSTED_HOSTS`):

```bash
curl -sS -H "Host: YOUR_DOMAIN" http://127.0.0.1:8000/health/live
curl -sS -H "Host: YOUR_DOMAIN" http://127.0.0.1:8000/health/ready
```

---

## 7. Reverse proxy (when you are ready for public HTTPS)

Do not skip this before pointing DNS at the VPS. The app speaks **HTTP** on
`127.0.0.1:8000` and does not terminate TLS.

Implementation-neutral (nginx, Caddy, or the provider’s load balancer). The
proxy must:

| Responsibility | Notes |
| --- | --- |
| Terminate HTTPS | Certificates for `YOUR_DOMAIN` (and `www` if used) |
| Proxy to `http://127.0.0.1:8000` | Preserve the URI path |
| Forward `Host`, `X-Forwarded-For`, `X-Forwarded-Proto` | Then set `VERAPOLITICA_FORWARDED_ALLOW_IPS` to the proxy only |
| `client_max_body_size` ~ 1m | Matches `VERAPOLITICA_MAX_REQUEST_BODY_BYTES` |
| Rate-limit public GET and `/admin` | Process-local limits are not cluster-wide |
| Security headers | App already sets CSP / `X-Frame-Options` / nosniff; proxy may add HSTS |
| HSTS | **Only after** HTTPS is confirmed |
| Client IP | Trust forwarding headers only from the proxy |

Placeholders:

```text
domain:            YOUR_DOMAIN
certificate:       /etc/ssl/YOUR_DOMAIN/fullchain.pem
private key:       /etc/ssl/YOUR_DOMAIN/privkey.pem
upstream:          http://127.0.0.1:8000
forwarded_allow:   PROXY_IP_OR_CIDR
```

Details: [production_security.md](production_security.md).

---

## 8. DNS and HTTPS checklist (do not run until the VPS is ready)

1. Create **A** (and **AAAA** if you have IPv6) for `YOUR_DOMAIN` → VPS.
2. Wait for propagation; `dig YOUR_DOMAIN` (or equivalent) matches the VPS.
3. Issue the TLS certificate (Let’s Encrypt or the provider).
4. `curl -sS https://YOUR_DOMAIN/health/live` and `/health/ready` return 200.
5. Then enable HSTS on the proxy.

Keep DNS unpublished or pointed elsewhere until health/ready is green on
localhost with the correct `Host` header.

---

## 9. First-deploy smoke

From a machine that can reach the public origin (or `127.0.0.1:8000` with
`Host: YOUR_DOMAIN`):

```bash
# Inside the repo, after the stack is up (TrustedHost needs the public name):
python -m scripts.smoke_test --base-url http://127.0.0.1:8000 --production \
  --host-header YOUR_DOMAIN
# After HTTPS:
python -m scripts.smoke_test --base-url https://YOUR_DOMAIN --production
```

`--production` is read-only. It checks live/ready/`/app/`/public GETs, asserts
`/demo/` and `/docs` are absent, and asserts `/admin/drafts` is **401** without
a key. Default smoke (no flag) stays valid for local development.

Also confirm:

```bash
./scripts/run_production_compose.sh ps    # no scheduler container
./scripts/run_production_compose.sh logs web | tail
```

Logs must not print the admin key or a PostgreSQL password. JSON request logs
include `request_id`, not Authorization headers.

`python -m scripts.release_check` needs the production settings/DB; run it
inside `web` if you use it. It does not ingest.

---

## 10. First production data (not demo)

A migrated database is **schema only**. Empty `/politicians` is expected until
official ingest + editorial publish.

Do **not** run `prepare_demo`, `prepare_unified_demo`, or `prepare_real_demo`.
They refuse `VERAPOLITICA_ENV=production` and are the wrong data path.

Operator commands (existing scripts; **not** a one-shot bootstrap). Run them
in `web` so they see `db` and raw storage:

```bash
# Territories before offices (offices require municipalities).
./scripts/run_production_compose.sh exec web \
  python -m scripts.run_territorial_ingestion territories --live
./scripts/run_production_compose.sh exec web \
  python -m scripts.run_territorial_ingestion offices --live

./scripts/run_production_compose.sh exec web \
  python -m scripts.run_ingestion --source senato
./scripts/run_production_compose.sh exec web \
  python -m scripts.run_ingestion --source camera
./scripts/run_production_compose.sh exec web \
  python -m scripts.run_ingestion --source governo

# Identity bootstrap is explicit and separate. Dry-run first.
./scripts/run_production_compose.sh exec web \
  python -m scripts.bootstrap_politicians --dry-run --source-key senato-repubblica
# only then, if the dry-run is acceptable:
# ./scripts/run_production_compose.sh exec web \
#   python -m scripts.bootstrap_politicians --apply --source-key senato-repubblica

./scripts/run_production_compose.sh exec web \
  python -m scripts.run_proposal_ingestion
```

There is **no** dedicated one-shot production importer. That is a known gap,
not an invitation to invent unsafe automation.

After ingest, records are not all public. Editorial **review and publish**
through `/admin` (Bearer token) remains required. AI extraction is a later
operator CLI (`run_ai_extraction`); it must not bulk-publish.

Optional job wrapper with history: `python -m scripts.run_jobs senato` (still
not the scheduler).

---

## 11. Backups

Full procedure: [backup_and_restore.md](backup_and_restore.md).

**Fresh DB (this first deploy):** skip pre-migrate dump. After the first
successful ingest, prove the tools work and copy files **off the VPS**.

Compose does **not** publish `5432`. The app image does not ship `pg_dump`.
Use the `db` container for SQL dumps and `web` for the raw archive:

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p /var/lib/verapolitica/backups
./scripts/run_production_compose.sh exec -T db \
  pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  > /var/lib/verapolitica/backups/verapolitica-postgres-${STAMP}.dump
./scripts/run_production_compose.sh run --rm \
  -v /var/lib/verapolitica/backups:/backups \
  web python -m scripts.backup_postgres --skip-postgres --output-dir /backups
chmod 600 /var/lib/verapolitica/backups/*
# copy the directory off the VPS (other disk, other host). Do not rely on this VPS alone.
```

**Future schema upgrades:** backup DB + raw + verify checksums/manifest, **then**
`alembic upgrade head`. Suggested retention (manual; no cron in this step): 7
daily, 4 weekly, one off-VPS copy.

---

## 12. Rollback

**A. Application-only** (no Alembic revision change):

1. `./scripts/run_production_compose.sh stop web`
2. `git checkout <previous-known-good-sha>` (CI-green)
3. `./scripts/run_production_compose.sh up -d --build`  
   `migrate` is a no-op if already at head.
4. Smoke `/health/ready`.

**B. Schema-changing rollback:** restore the pre-migration PostgreSQL dump and
matching raw archive into an empty database. Do **not** casually
`alembic downgrade` in production. See [backup_and_restore.md](backup_and_restore.md)
restore order (restore dump **before** migrate unless the dump is behind new
code).

**C. Failed first deploy (never public):** leave DNS/proxy unpublished. Read
`logs migrate` / `logs web`. Fix env or schema. Retry. Do not
`down --volumes` unless you intend to wipe the first database.

---

## 13. Logs and later observability

```bash
./scripts/run_production_compose.sh logs --tail=200 web
./scripts/run_production_compose.sh logs migrate
./scripts/run_production_compose.sh logs db
curl -sS -H "Host: YOUR_DOMAIN" http://127.0.0.1:8000/health/ready
```

No SaaS monitor is wired. Later (not this step): uptime check on
`/health/ready` and optional error tracking. `VERAPOLITICA_SENTRY_DSN` is
**not** an application setting.

---

## 14. After first deploy (explicitly later)

- Reverse proxy + DNS + TLS + HSTS (steps 7–8) if not already done
- Off-VPS backup copies
- Editorial publish of ingested data
- Scheduler profile **only** when cron values are intentional and a single
  replica is understood
- Paid/local LLM only as a deliberate operator action
