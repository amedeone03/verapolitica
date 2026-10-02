# Repeatable local demo

The demo uses only these dedicated paths:

- `data/demo/verapolitica_demo.db`
- `data/demo/raw/`

The preparation command validates these targets, removes only the demo database,
its SQLite sidecars, and demo raw directory, then rebuilds the state from the local
fixture at `data/fixtures/demo/senato_demo.json`. It never reads from or resets the
normal development database or raw storage.

## Prepare or reset

From the repository root with the virtual environment active:

```bash
python -m scripts.prepare_demo
```

The command is both setup and reset. Every run recreates this state:

- Politician 1, Anna Rossi: published version 1 with 14 citations.
- Draft 2 for Politician 2, Luca Bianchi: pending with 14 Evidence rows.
- Politician 2 has no public version until Draft 2 is approved.

## Start the API

```bash
export VERAPOLITICA_DATABASE_URL="sqlite:///./data/demo/verapolitica_demo.db"
export VERAPOLITICA_RAW_STORAGE_PATH="./data/demo/raw"
export VERAPOLITICA_ADMIN_API_KEY="verapolitica-demo-admin"
export VERAPOLITICA_ADMIN_REVIEWER_IDENTITY="demo-presenter"
uvicorn backend.app.main:app --reload
```

Swagger is available at `http://127.0.0.1:8000/docs`. Use the Authorize button with
the bearer value `verapolitica-demo-admin` for `/admin/*` operations.

## Presentation sequence

1. Open `GET /politicians/1`. Show the approved profile and its 14 immutable public
   citations.
2. Open `GET /admin/drafts/2`. Show the pending proposed profile, field-level diff,
   and 14 internal Evidence rows.
3. Call `POST /admin/drafts/2/start-review`. The draft moves to `in_review`; no
   final Review exists yet.
4. Call `POST /admin/drafts/2/approve` with an optional note. The approval creates
   one Review, version, current-version pointer, and citation snapshot atomically.
5. Open `GET /politicians/2`. Show the newly public profile and immutable citations.

To restore the original pending state after a rehearsal, stop the API and run:

```bash
python -m scripts.prepare_demo
```
