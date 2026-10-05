# VeraPolitica MVP presenter runbook

This demonstration is deterministic and network-free. It uses only:

- `data/demo/verapolitica_demo.db`
- `data/demo/raw/`
- the local fixture `data/fixtures/demo/senato_demo.json`
- the local fixture `data/fixtures/governo/governo_office_holders.json`

The reset code validates those paths before removing anything. It never reads,
modifies, or resets the normal development database or raw storage.

## Pre-demo setup

From the repository root, start the complete demo with one command:

```bash
./scripts/run_demo.sh
```

The launcher uses the repository `.venv`, rebuilds the isolated demo state, applies
demo-only environment variables, and starts FastAPI on `127.0.0.1:8000`. Keep this
terminal visible so you can stop the application with `Ctrl+C`.

Expected opening state:

- Anna Rossi — Politician 1, published version 1, 14 public citation references.
- Luca Bianchi — Politician 2, not public, with pending Draft 2 and 14 Evidence rows.
- Carlo Verdi — pending Identity Resolution Case 1 from the Governo fixture; no
  Politician is created automatically.

Open these tabs before presenting:

- Citizen interface: `http://127.0.0.1:8000/app/`
- Editorial demo: `http://127.0.0.1:8000/demo/`
- Swagger backup: `http://127.0.0.1:8000/docs`

The citizen interface calls only the public `/politicians` endpoints. It contains
no admin credential or editorial actions. The editorial page is visibly marked as
a demo and uses the local-only credential `verapolitica-demo-admin`.

### Manual startup fallback

If the helper is unavailable, use:

```bash
source .venv/bin/activate
python -m scripts.prepare_demo
export VERAPOLITICA_DATABASE_URL="sqlite:///./data/demo/verapolitica_demo.db"
export VERAPOLITICA_RAW_STORAGE_PATH="./data/demo/raw"
export VERAPOLITICA_ADMIN_API_KEY="verapolitica-demo-admin"
export VERAPOLITICA_ADMIN_REVIEWER_IDENTITY="demo-presenter"
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

## 3–5 minute presentation script

1. **Set the premise.** “VeraPolitica does not let politicians edit their own
   profiles. Public information starts with official institutional sources and is
   published only after human verification.”
2. **Show an existing public profile.** In `/app/`, point out that only Anna Rossi
   is visible. Open her profile and show the Verified indicator, current mandate,
   and official source section.
3. **Explain traceability.** Anna has 14 verified data references grouped under one
   Senato source. Point out the official source link: every displayed fact remains
   traceable without overwhelming citizens with duplicate source cards. Opening the
   external link is optional and is the only part that requires internet access.
4. **Show the publication boundary.** Return to the archive: Luca Bianchi is absent
   because identity creation alone does not make a profile public.
5. **Enter the editorial workspace.** Switch to `/demo/`. First show Carlo's
   Identity Resolution section: the official source lacks a birth date, so VeraPolitica
   presents explicit create/link/ignore actions instead of matching on name alone.
   Then show that Anna is already Published · Verified and Luca has a Pending
   proposal with a readable diff and field-level supporting Evidence.
6. **Start human review.** Select **Start review**. Point out the visible transition
   from Pending to In review and the updated controls. No final Review record exists
   at this intermediate stage.
7. **Approve and publish.** Select **Approve & publish**, then confirm. Explain that
   the backend atomically creates the final Review, immutable published Version,
   current-version pointer, and immutable citation snapshot.
8. **Show the terminal state.** The workflow now says Published, the success message
   is visible, and review controls are disabled.
9. **Return to citizens.** Refresh `/app/`. Luca now appears because the public API
   exposes only his newly approved current version.
10. **Close on evidence.** Open Luca at `/app/?politician=2`. Show version 1, the
    approved profile, 14 verified data references, and the grouped Senato link.

## Backup plan

If a presentation page is unavailable, use Swagger at `/docs`.

Public checks:

```text
GET /politicians
GET /politicians/1
GET /politicians/2
```

Editorial sequence using bearer token `verapolitica-demo-admin`:

```text
GET  /admin/drafts/2
POST /admin/drafts/2/start-review
POST /admin/drafts/2/approve
GET  /admin/identity-resolution/1
```

Before approval, `GET /politicians/2` returns 404. After approval, it returns Luca's
published profile and citations. If the approval path has already been used, reset
the dataset rather than trying to reverse a final decision.

## Reset

Stop the application with `Ctrl+C`, then either rerun the launcher:

```bash
./scripts/run_demo.sh
```

or reset without starting the server:

```bash
python -m scripts.prepare_demo
```

After reset, reload `/app/` and `/demo/`. Anna is public, Luca is absent from the
citizen archive, Draft 2 is Pending, and Identity Resolution Case 1 is Pending
again. There is deliberately no browser reset control or reset API.

## Language and terminology

The MVP interfaces remain in English to keep the already-tested presentation flow
consistent. Italian localization is a post-MVP improvement; no localization system
is included. “Verified” means checked against cited official sources. It does not
mean endorsement, political quality, or validation of subjective claims.
