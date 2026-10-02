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

Open the citizen interface at:

```text
http://127.0.0.1:8000/app/
```

Open the editorial presentation UI at:

```text
http://127.0.0.1:8000/demo/
```

Both interfaces are dependency-free static pages served by FastAPI, so no second
frontend process is required. The citizen interface calls only the public
`/politicians` endpoints and contains no admin credential or editorial actions.
The editorial UI defaults to `http://127.0.0.1:8000` and uses the embedded bearer
value `verapolitica-demo-admin`; that value is demo-only and does not weaken
backend authentication.

Swagger remains available as a fallback at `http://127.0.0.1:8000/docs`. Use its
Authorize button with the same bearer value for `/admin/*` operations.

## Presentation sequence

1. Open `/app/`. Show Anna Rossi in the public archive and open her verified profile
   with grouped official citations. Luca Bianchi is absent because he has no
   published version.
2. Switch to `/demo/`. In the **Pending proposal** card, show Luca's proposed
   profile, readable field diff, and 14 supporting Evidence entries. The lower
   public-result card says that Luca is not public yet.
3. Select **Start review**. The draft badge and workflow move to **In review**; no
   final Review exists yet.
4. Select **Approve & publish** and confirm the final action. The UI calls the real
   approval endpoint with the note `Official evidence verified during demo`.
5. Show the editorial workflow at **Published**, then return to `/app/` and refresh.
   Luca now appears automatically because the public API exposes his approved
   version.
6. Open Luca's profile at `/app/?politician=2`. Show the approved personal and
   mandate data, 14 verified data references, and the grouped Senato source link.

The **Reject** action is available for an alternate presentation path and also asks
for confirmation. If the API is unavailable, authentication fails, or the draft is
already final, the UI shows a readable error and refreshes state where appropriate.

To restore the original pending state after a rehearsal, stop the API and run:

```bash
python -m scripts.prepare_demo
```

Reload both `http://127.0.0.1:8000/app/` and
`http://127.0.0.1:8000/demo/` after reset. Anna is public again, Luca is absent
from the citizen archive, and Draft 2 is pending. There is deliberately no browser
reset action or reset API.
