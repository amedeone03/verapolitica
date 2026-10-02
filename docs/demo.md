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

Open the presentation UI at:

```text
http://127.0.0.1:8000/demo/
```

The UI is a dependency-free static page served by FastAPI, so no second frontend
process is required. It defaults to `http://127.0.0.1:8000` and has a reconnect
field for another local API URL. The embedded bearer value
`verapolitica-demo-admin` is demo-only and does not weaken backend authentication.

Swagger remains available as a fallback at `http://127.0.0.1:8000/docs`. Use its
Authorize button with the same bearer value for `/admin/*` operations.

## Presentation sequence

1. In the **Published profile** card, show Anna Rossi, version 1, and a sample of her
   14 immutable public citations.
2. In the **Pending proposal** card, show Luca Bianchi's proposed profile, readable
   field diff, and 14 supporting Evidence entries. The lower public-result card says
   that Luca is not public yet.
3. Select **Start review**. The draft badge and workflow move to **In review**; no
   final Review exists yet.
4. Select **Approve & publish** and confirm the final action. The UI calls the real
   approval endpoint with the note `Official evidence verified during demo`.
5. Show the workflow at **Published** and the newly revealed Luca Bianchi public
   profile with its 14 immutable citations.

The **Reject** action is available for an alternate presentation path and also asks
for confirmation. If the API is unavailable, authentication fails, or the draft is
already final, the UI shows a readable error and refreshes state where appropriate.

To restore the original pending state after a rehearsal, stop the API and run:

```bash
python -m scripts.prepare_demo
```

Reload `http://127.0.0.1:8000/demo/` after reset. There is deliberately no browser
reset action or reset API.
