# VeraPolitica MVP presenter runbook

## Unified local demo (preferred on Mac)

One environment combines the verified CEO/Senate snapshot with Government
profiles, portraits, pledges, and the local qwen3 AI editorial flow.

It writes only under `data/unified_demo/`. It does not reset or delete
`data/ceo_demo/` or `data/demo/`.

Build once (uses the existing CEO SPARQL snapshot when present, then overlays
governo.it; needs internet for Government / programme / portraits):

```bash
cd /Users/ameboz/verapolitica
source .venv/bin/activate
set -a
source .env.unified-demo
set +a
python -m scripts.prepare_unified_demo --seed-from-ceo
```

Rebuild only the unified tree:

```bash
python -m scripts.prepare_unified_demo --rebuild --seed-from-ceo
```

Offline fixture build (tests / no network):

```bash
python -m scripts.prepare_unified_demo --offline --no-portraits
```

Launch (does not rebuild data):

```bash
cd /Users/ameboz/verapolitica
source .venv/bin/activate
set -a
source .env.unified-demo
set +a
.venv/bin/python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Or `./scripts/run_unified_demo.sh`.

After an AI walkthrough, restore the published baseline without dropping
Senate / Government / pledges / portraits:

```bash
python -m scripts.reset_unified_demo --dry-run
python -m scripts.reset_unified_demo
```

The older CEO (`.env.ceo-demo`) and synthetic/real `data/demo` launchers remain
available until this unified flow is the default.

## Real-data demo (default on Windows)

`scripts\run_demo.cmd` (and the local `avvia-demo.cmd`) rebuilds the demo from
official sources with `python -m scripts.prepare_real_demo`; it needs internet:

- **Profiles**: the current Government from governo.it, through the production
  Governo collector, parser and mapper. The Prime Minister, Deputy Prime
  Ministers and Ministers are published; Deputy Ministers and Undersecretaries
  stay as pending drafts for the editorial demo. governo.it pages publish no
  birth date, so identity creation goes through identity-resolution cases that
  the `demo-setup` editor resolves; every decision is recorded.
- **Commitments**: the official *dichiarazioni programmatiche* (25 Oct 2022) are
  ingested as an operator-approved document. Whole sentences that state a
  concrete commitment are selected deterministically
  (`backend/app/pipeline/pledge_candidates.py`), checked to be verbatim in the
  stored text, published as explicit promises owned by the Prime Minister and
  classified automatically (flagged for editorial review). **No fulfilment
  verdict is created**: every commitment is "not yet rated", so the score is
  withheld until editors approve evidence-backed assessments.
- **Portraits** (`data/demo/portraits.json`, served at `GET /portraits`): the
  official portrait when the source publishes one, otherwise a freely licensed
  Wikimedia Commons photo found through Wikidata, accepted only for a single
  exact-name match of an Italian politician. Author and licence are shown on
  the profile. No match means a monogram in the same glass style.
- A run report is written to `data/demo/real_demo_report.json`.

The synthetic presenter walkthrough below is still available with
`scripts\run_demo.cmd synthetic` (or `python -m scripts.prepare_demo`).

## Synthetic presenter walkthrough

This demonstration is deterministic and network-free. It uses only:

- `data/demo/verapolitica_demo.db`
- `data/demo/raw/`
- the local fixture `data/fixtures/demo/senato_demo.json`
- the local fixture `data/fixtures/governo/governo_office_holders.json`
- synthetic AI audit metadata and evidence created by `scripts.prepare_demo`

The reset code validates those paths before removing anything. It never reads,
modifies, or resets the normal development database or raw storage.

The demo is SQLite-only and uses `metadata.create_all`. It does not require
PostgreSQL or Alembic. Scheduled ingestion stays disabled during a presentation.
The header search box can find Anna, Milano, Lombardia, the synthetic housing
proposal, Anna's parliamentary group, and the clearly synthetic Demo Civic
Alliance party. Luca and Carlo stay hidden until publication or resolution.
The header can also find the published synthetic civic referendum and glossary
terms such as quorum. The unpublished civic draft stays hidden.

## Pre-demo setup

From the repository root, start the complete demo with one command:

```bash
./scripts/run_demo.sh
```

On Windows, run `scripts\run_demo.cmd` instead (from cmd, PowerShell, or a
double-click). It creates `.venv` with Python 3.13 if needed, installs the
dependencies, rebuilds the demo data and starts the server on the same address.

The launcher uses the repository `.venv`, rebuilds the isolated demo state, applies
demo-only environment variables, and starts FastAPI on `127.0.0.1:8000`. Keep this
terminal visible so you can stop the application with `Ctrl+C`.

Expected opening state:

- Anna Rossi — Politician 1, published version 1, 14 public citation references.
- Luca Bianchi — Politician 2, not public, with pending Draft 2 and 14 Evidence rows.
- Anna and Luca each have one deterministic current Senato parliamentary-group
  membership; Anna's is immediately visible on her public profile and Luca's appears
  after publication.
- No political-party affiliation is seeded. The profile shows the separate party
  section in its honest empty state because the current production sources do not
  provide a safe explicit affiliation feed; the Senato group is not converted.
- Carlo Verdi — pending Identity Resolution Case 1 from the Governo fixture; no
  Politician is created automatically.
- One clearly synthetic proposal linked to Anna is public with an `introduced`
  timeline event. Proposal Draft 2 contains a pending synthetic transition to
  `under_review` and is marked as an AI-assisted draft using the deterministic fake
  provider. The public timeline remains unchanged until editorial approval.
- Lombardia and Milano are seeded from ISTAT-style reference data. Giulia Neri is a
  clearly synthetic published demo mayor of Milano and must not be presented as a
  real office holder. Regional presidents are not imported.
- One clearly synthetic upcoming civic referendum is published and labelled as
  demo-only. A second synthetic referendum draft remains unpublished until
  editorial approval. A source-backed voting guide and glossary terms are
  published. Reminder candidates are generated only by the operator job.

Open these tabs before presenting:

- Citizen interface: `http://127.0.0.1:8000/app/`
- Editorial demo: `http://127.0.0.1:8000/demo/`
- Swagger backup: `http://127.0.0.1:8000/docs`

The citizen interface calls only public JSON endpoints. It contains
no admin credential or editorial actions. Regions and municipalities are available
from the same `/app/` navigation. Giulia Neri is labelled as a synthetic demo mayor.
Referendums, How to vote, and Glossary are available from the same navigation.
The synthetic referendum is labelled demo-only and is not a current official vote.

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
   parliamentary-group section, and official source section. Note that a
   parliamentary group is not being presented as a political party. The independent
   Political party section remains empty rather than inferring one from the group.
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
11. **Review a proposal transition.** Open `/app/?view=proposals`, then the Proposal
    status update card in `/demo/`. The original official label and normalized
    status appear together. Show the internal AI provider/prompt metadata and short
    validated excerpt; note that citizens do not see model confidence or prompts.
    Approve it and refresh the public proposal: the second
    immutable timeline event appears only after review. Emphasize that the demo
    proposal is synthetic and is not presented as a real political fact.
12. **Civic calendar.** Open `/app/?view=referendums`. The published synthetic
    referendum shows date, scope, status, and an official-source / demo label.
    Open the detail for the official question and quorum text. Open How to vote
    and Glossary. In `/demo/`, approve the unpublished referendum draft, refresh
    `/app/?view=referendums`, and confirm the second record appears. Reminders
    stay internal: they are candidate rows, not email.

## Backup plan

If a presentation page is unavailable, use Swagger at `/docs`.

Public checks:

```text
GET /politicians
GET /politicians/1
GET /politicians/2
GET /proposals
GET /proposals/1
GET /referendums
GET /voting-guides
GET /glossary
GET /search?q=quorum
```

Editorial sequence using bearer token `verapolitica-demo-admin`:

```text
GET  /admin/drafts/2
POST /admin/drafts/2/start-review
POST /admin/drafts/2/approve
GET  /admin/identity-resolution/1
GET  /admin/proposals/drafts/2
POST /admin/proposals/drafts/2/start-review
POST /admin/proposals/drafts/2/approve
GET  /admin/referendums/drafts/2
POST /admin/referendums/drafts/2/start-review
POST /admin/referendums/drafts/2/approve
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
