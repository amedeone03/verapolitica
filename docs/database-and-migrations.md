# Database and migrations

VeraPolitica supports two SQLAlchemy-compatible databases through
`VERAPOLITICA_DATABASE_URL`.

| Environment | Database | Schema strategy |
| --- | --- | --- |
| Tests, deterministic demo, lightweight local SQLite | SQLite | `metadata.create_all` |
| Development PostgreSQL and **production** | PostgreSQL | Alembic migrations only |

Production requires PostgreSQL. Alembic owns the production schema. The
application never calls `metadata.create_all()` as a substitute for migrations
when `VERAPOLITICA_DATABASE_URL` is PostgreSQL. Do not remove SQLite support
for local/demo work. Do not auto-migrate PostgreSQL on application start.

Current Alembic head: `e2b8f6c03d41` (linear chain from `1864a1eb302a`).

## SQLite

Default:

```bash
export VERAPOLITICA_DATABASE_URL=sqlite:///./data/verapolitica.db
```

SQLite remains the test engine and the isolated demo engine
(`data/demo/verapolitica_demo.db`). FastAPI, operator scripts, and
`python -m scripts.prepare_demo` call `create_all` for SQLite so local work stays
fast.

Alembic migrations also run against empty SQLite databases. That path is used by
migration tests; it is not required for the demo.

## PostgreSQL

Use the psycopg 3 SQLAlchemy dialect. Take a backup before any production
migration.

Fresh empty database:

```bash
createdb verapolitica
export VERAPOLITICA_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/verapolitica
python -m alembic upgrade head
python -m alembic current
```

Existing database (upgrade to latest schema):

```bash
python -m scripts.backup_postgres --output-dir /mnt/offsite/verapolitica
python -m alembic upgrade head
python -m alembic current
```

See [backup_and_restore.md](backup_and_restore.md). Restore with `pg_restore`
into an empty database **before** running `alembic upgrade head`, unless the
restored schema is behind the new code.

`alembic current` must match `alembic heads` (`e2b8f6c03d41`) before starting
web processes. `/health/ready` returns 503 until that is true, including when
PostgreSQL is unreachable.

The search and civic revisions run `CREATE EXTENSION IF NOT EXISTS pg_trgm`.
The database role used for migrations must be allowed to create that extension.

Docker is not required for local PostgreSQL. `pytest -m postgres` is the
repeatable empty-database smoke (fresh migrate, upgrade-from-prior, no
`create_all`). A GitHub Actions service container runs the same marker.

## Alembic

Configuration lives in `alembic.ini` and `alembic/env.py`. Revisions use
`Base.metadata` from the SQLAlchemy models. Do not duplicate model metadata in
migration helpers. Do not squash or rewrite history unless a revision is a
blocker.

```bash
python -m alembic upgrade head
python -m alembic current
python -m alembic heads
python -m alembic history
```

The initial revision (`1864a1eb302a`) creates the base schema. Later additive
revisions add search columns, civic tables, pledge scoring tables, and
unpublished pledge evidence candidates.

PostgreSQL/dev startup **warns** when the database revision is behind head. It
never runs `alembic upgrade head` automatically. `/health/ready` fails until the
schema is current.

Operator commands that persist to the configured database (`run_ingestion`,
`run_proposal_ingestion`, `run_territorial_ingestion`, `run_ai_extraction`,
`run_jobs`, `run_scheduler`) use the same split: SQLite may `create_all`;
PostgreSQL requires an explicit migration.

## Production data (not demo seed)

A migrated empty PostgreSQL database has schema only. It does not contain
politicians, proposals, or territories.

Populate production later with the operator ingestion commands, then editorial
review and publish:

- `python -m scripts.run_ingestion` (Senato / Camera / Governo)
- `python -m scripts.run_proposal_ingestion`
- `python -m scripts.run_territorial_ingestion`
- `python -m scripts.bootstrap_politicians` (explicit identity bootstrap after ingestion)

These are not a one-shot production dump import. A dedicated production
bootstrap/import command may still be needed later.

Demo scripts are **not** a production strategy. They refuse
`VERAPOLITICA_ENV=production` and write only under `data/demo/` or
`data/unified_demo/`:

- `python -m scripts.prepare_demo` — synthetic SQLite demo
- `python -m scripts.prepare_unified_demo` / `reset_unified_demo` — local unified demo
- `python -m scripts.prepare_real_demo` — demo rebuilt from official sources into SQLite

## Moving off an existing SQLite file

This milestone does not ship an automatic SQLite → PostgreSQL data copy.

Supported development path:

1. Create a fresh PostgreSQL database.
2. Run `alembic upgrade head`.
3. Re-ingest official data with the existing operator commands.
4. Rebuild demo/test data from fixtures (`python -m scripts.prepare_demo`) only for local demo DBs.

## Types and constraints

Enums are stored as strings (`native_enum=False`) so SQLite and PostgreSQL share
one migration. JSON columns use SQLAlchemy `JSON`, not JSONB. Datetimes are
timezone-aware. Overlapping ingestion jobs are blocked by a partial unique index
on `ingestion_job_runs.job_name` where `status = 'running'`.
