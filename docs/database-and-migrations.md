# Database and migrations

VeraPolitica supports two SQLAlchemy-compatible databases through
`VERAPOLITICA_DATABASE_URL`.

| Environment | Database | Schema strategy |
| --- | --- | --- |
| Tests, deterministic demo, lightweight local SQLite | SQLite | `metadata.create_all` |
| Normal development and production-like usage | PostgreSQL | Alembic migrations |

Do not remove SQLite support. Do not auto-migrate PostgreSQL on application start.

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

Use the psycopg 3 SQLAlchemy dialect:

```bash
createdb verapolitica
export VERAPOLITICA_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/verapolitica
alembic upgrade head
python -m scripts.run_web
```

Docker is not required. A GitHub Actions service container is optional CI coverage
only.

## Alembic

Configuration lives in `alembic.ini` and `alembic/env.py`. Revisions use
`Base.metadata` from the SQLAlchemy models. Do not duplicate model metadata in
migration helpers.

```bash
alembic upgrade head
alembic current
alembic history
alembic downgrade -1
```

The initial revision creates the current full schema, including job-run history.

PostgreSQL/dev startup **warns** when the database revision is behind head. It
never runs `alembic upgrade head` automatically. `/health/ready` fails until the
schema is current.

Operator commands that persist to the configured database (`run_ingestion`,
`run_proposal_ingestion`, `run_territorial_ingestion`, `run_ai_extraction`,
`run_jobs`, `run_scheduler`) use the same split: SQLite may `create_all`;
PostgreSQL requires an explicit migration.

## Moving off an existing SQLite file

This milestone does not ship an automatic SQLite → PostgreSQL data copy.

Supported development path:

1. Create a fresh PostgreSQL database.
2. Run `alembic upgrade head`.
3. Re-ingest official data with the existing operator commands.
4. Rebuild demo/test data from fixtures (`python -m scripts.prepare_demo`).

## Types and constraints

Enums are stored as strings (`native_enum=False`) so SQLite and PostgreSQL share
one migration. JSON columns use SQLAlchemy `JSON`, not JSONB. Datetimes are
timezone-aware. Overlapping ingestion jobs are blocked by a partial unique index
on `ingestion_job_runs.job_name` where `status = 'running'`.
