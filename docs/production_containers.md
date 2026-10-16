# Production-like containers

This is the local compose stack used to prove VeraPolitica can run as
containers before a VPS reverse proxy and TLS are configured. It is not the
final VPS deployment guide.

Citizen UI is served by FastAPI from `frontend/app` at `/app/`. There is no
separate frontend container.

```text
Internet
  -> reverse proxy (HTTPS, later)
  -> web container (HTTP, gunicorn + Uvicorn workers, 0.0.0.0:8000)
  -> db container (PostgreSQL 16)

One-shot:
  migrate  (alembic upgrade head)

Opt-in:
  scheduler  (--profile scheduler; cron still blank by default)
```

The web process does not terminate TLS. `VERAPOLITICA_PUBLIC_BASE_URL` is the
public HTTPS origin even when the container listens for HTTP.

## Services

| Service | Role | Starts by default |
| --- | --- | --- |
| `db` | PostgreSQL 16 | yes |
| `migrate` | `python -m alembic upgrade head`, then exits | yes (oneshot) |
| `web` | `python -m scripts.run_web` | yes, after migrate succeeds |
| `scheduler` | `python -m scripts.run_scheduler` | **no** (compose profile `scheduler`) |

Do not add Redis, Kubernetes, a vector database, or an Ollama/GPU container to
this stack. Normal startup does not call an LLM.

## Required env file

Copy `.env.production.example` to gitignored `.env.production` and fill values.
Compose fails if that file is missing.

```bash
cp .env.production.example .env.production
```

For **local** production-like use, set:

```bash
VERAPOLITICA_PUBLIC_BASE_URL=http://127.0.0.1:8000
VERAPOLITICA_CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
VERAPOLITICA_TRUSTED_HOSTS=localhost,127.0.0.1,web,testserver
VERAPOLITICA_ADMIN_API_KEY=<24+ random characters>
```

`POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` in the example are
**development-only** compose credentials. Compose always points
`VERAPOLITICA_DATABASE_URL` at service `db`, so the `HOST` in the template is
not used inside this stack.

## Startup order

1. `db` becomes healthy (`pg_isready`).
2. `migrate` runs `alembic upgrade head`. Failure prevents `web` from starting.
3. `web` starts gunicorn (`python -m scripts.run_web`). No `--reload`, no
   `create_all`, no auto-migrate.

```bash
./scripts/run_production_compose.sh up --build
# equivalent:
# docker compose --env-file .env.production up --build
```

Do not run `./scripts/run_demo.sh` against this stack.

## Health

| Probe | URL | Meaning |
| --- | --- | --- |
| Container HEALTHCHECK | `GET /health/live` | process is up (DB blip does not restart web) |
| App readiness / smoke | `GET /health/ready` | PostgreSQL reachable and Alembic head |

## Persistent volumes

| Volume | Mount | Survives restart | Back up |
| --- | --- | --- | --- |
| `verapolitica_pg` | PostgreSQL data dir | yes | **yes** — [backup_and_restore.md](backup_and_restore.md) |
| `verapolitica_raw` | `/var/lib/verapolitica/raw` | yes | **yes** (raw provenance) |

Optional later bind-mounts (not created by default):

- `VERAPOLITICA_PORTRAITS_PATH` JSON + image files
- demo upload path — **do not mount**; demo UI is off in production

Do not persist pytest caches or `.venv`.

## Web process

- Bind: `0.0.0.0` inside the container; published as `127.0.0.1:8000` on the host
- Port / workers: `VERAPOLITICA_WEB_PORT`, `VERAPOLITICA_WEB_WORKERS`
- Logs: `VERAPOLITICA_LOG_FORMAT=json`
- Runner: gunicorn + `uvicorn.workers.UvicornWorker` (existing `scripts.run_web`)

## Demo / AI / scheduler safety

Default compose does **not** start the scheduler. Cron variables stay blank in
the env template, so even `--profile scheduler` registers no jobs until a later
step sets cron.

Default env keeps `VERAPOLITICA_ENABLE_DEMO_UI=false`, LLM provider blank, and
does not run `prepare_demo` / unified-demo seed. Demo SQLite trees are not
mounted. The image does not include `frontend/demo`.

## Shutdown and reset

```bash
./scripts/run_production_compose.sh down
```

Volumes are kept. To throw away local compose data:

```bash
./scripts/run_production_compose.sh down --volumes
```

Never run demo reset scripts (`prepare_demo`, `reset_unified_demo`) against
this PostgreSQL volume.

## Reverse proxy (later)

Real nginx/Caddy, DNS, and TLS are a later VPS step. The expected boundary is:

```text
Internet -> HTTPS reverse proxy -> HTTP web container
```

Set `VERAPOLITICA_FORWARDED_ALLOW_IPS` only to that proxy. Leave it empty for
this local stack.
