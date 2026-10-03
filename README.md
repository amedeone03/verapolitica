# VeraPolitica

VeraPolitica ingests official national political data from Senato della Repubblica
and Camera dei Deputati. Each source-specific SPARQL collector, parser, and mapper
feeds the same source-independent pipeline. Raw responses are preserved and
meaningful changes are detected with canonical normalized hashes. Changed records
are mapped deterministically into transient CandidateProfile objects. The domain includes
stable Politician identities, generic official-source identifiers, immutable
PoliticianVersion snapshots, a read-only deterministic MatchingService, and an
explicit bootstrap command for initial identity creation. Matched candidates can
now be compared with their current version and persisted as reviewable ProfileDrafts
with field-level Evidence. Explicit human decisions can reject a draft or atomically
publish it as a new immutable PoliticianVersion.

It does not perform LLM extraction, citizen authentication, or frontend rendering.
CandidateProfiles are not persisted, normal ingestion never creates Politicians,
and matching and diffing never mutate the database. A separate transactional
identity service may attach a newly discovered official identifier after one safe
deterministic match. Publication is only available
through an explicit review action. The read-only public API exposes only the
immutable version selected by a Politician's current-version pointer.

## Setup

Create and activate a virtual environment, then install the pinned dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Configuration defaults are shown in `.env.example`. Copy them into `.env` only when
you need to override the defaults.

## Run one ingestion

From the repository root:

```bash
# Backward-compatible default: Senato
python -m scripts.run_ingestion

# Explicit source selection
python -m scripts.run_ingestion --source senato
python -m scripts.run_ingestion --source camera
```

By default this creates `data/verapolitica.db` and stores immutable raw payloads
under `data/raw/`. The command prints the RawDocument ID, both hashes, change result,
storage key, and collector/parser versions.
The output also reports how many CandidateProfiles were produced. Unchanged source
data produces zero candidates.

Camera ingestion uses the official Camera open-data SPARQL endpoint and maps current
XIX-legislature deputies. Camera-specific RDF bindings remain inside its collector,
parser, mapper, and provenance; the CandidateProfile and every downstream service
remain source-independent.

## Bootstrap politician identities

Bootstrap is a separate, explicit operator action. It rebuilds transient
CandidateProfiles from a successfully parsed RawDocument, classifies every record,
and emits a detailed JSON report. Start with a dry-run against the latest parsed
Senato document:

```bash
python -m scripts.bootstrap_politicians --dry-run
```

For the latest parsed Camera document, select its generic Source key:

```bash
python -m scripts.bootstrap_politicians \
  --dry-run \
  --source-key camera-deputati
```

To select a specific stored snapshot:

```bash
python -m scripts.bootstrap_politicians --dry-run --raw-document-id 12
```

If the report has no uncertain or invalid records, create only the candidates
classified as new:

```bash
python -m scripts.bootstrap_politicians --apply --raw-document-id 12
```

Apply creates each new Politician and its source identifiers in one database
transaction. Matched candidates are skipped. Any uncertain or invalid candidate
blocks all writes. Repeating the command is idempotent because existing identifiers
match their Politicians and the database also enforces identifier uniqueness.

## Create one profile draft

Draft creation is another explicit operator action. Select one record from a stored,
successfully parsed RawDocument:

```bash
python -m scripts.create_profile_draft \
  --raw-document-id 12 \
  --candidate-index 0
```

The command rebuilds that transient CandidateProfile, requires one deterministic
Politician match, and explicitly links any new identifier from that candidate's
official source before computing the diff. It then creates a pending ProfileDraft
plus Evidence in one transaction. If the candidate equals the current version it
returns `no_changes` and writes nothing. A changed field without source provenance,
including a removal without explicit absence evidence, blocks creation.

Identifier linking is separate from MatchingService. It is idempotent, preserves
multiple legitimate identifiers from one source, and refuses an identifier already
owned by another Politician. `new` and `uncertain` matches never trigger linking.

Creating a meaningful new draft supersedes existing `pending` and `in_review`
drafts only after the new diff and all evidence have been validated. This command
does not approve, publish, or create PoliticianVersions.

## Review and publish one draft

Approve a reviewable draft and atomically create its next immutable version:

```bash
python -m scripts.review_profile_draft \
  --draft-id 1 \
  --approve \
  --reviewer "demo-editor"
```

Reject a draft without creating a version:

```bash
python -m scripts.review_profile_draft \
  --draft-id 2 \
  --reject \
  --reviewer "demo-editor" \
  --note "Evidence requires clarification"
```

Only `pending` and `in_review` drafts can receive a final decision. Approval verifies
that the draft baseline is still current, then creates the Review, version, current
pointer, and approved status in one transaction. Rejection creates only the final
Review and rejected status. Repeating either final action is blocked.

## Run the Admin API

Set a local admin secret and reviewer identity, then start Uvicorn:

```bash
export VERAPOLITICA_ADMIN_API_KEY="replace-with-a-long-random-secret"
export VERAPOLITICA_ADMIN_REVIEWER_IDENTITY="local-editor"
uvicorn backend.app.main:app --reload
```

The health endpoint is public. Every `/admin/*` endpoint requires the bearer token:

```bash
curl http://127.0.0.1:8000/health

curl \
  -H "Authorization: Bearer $VERAPOLITICA_ADMIN_API_KEY" \
  http://127.0.0.1:8000/admin/drafts
```

The API exposes draft listing, detail, start-review, approval, and rejection. Route
handlers delegate final actions to ReviewService and PublishService.

## Read the Public API

The public routes require no bearer token:

```bash
curl "http://127.0.0.1:8000/politicians?offset=0&limit=50"
curl http://127.0.0.1:8000/politicians/1
```

Only Politicians whose `current_version_id` references a published immutable
PoliticianVersion are visible. The API never falls back to the highest version
number and does not expose drafts, Reviews, Evidence, hashes, or raw storage data.
Politician detail responses include a curated citation snapshot copied from the
approved draft's Evidence during publication. List items expose only
`citation_count` to stay compact. Versions published before citation snapshots were
introduced remain readable with an empty citation list.
On an update, citations for unchanged fields are inherited from the baseline version,
while citations for changed fields come from the newly approved Evidence. A version
can therefore cite Senato and Camera independently without collapsing their identity.
Interactive OpenAPI documentation is available at
`http://127.0.0.1:8000/docs` while Uvicorn is running.

## Run tests

```bash
python -m pytest
```

Tests use temporary SQLite databases, mocked HTTP, deterministic fixtures, and
temporary raw storage. They do not call live Senato or Camera endpoints.

## Continuous integration

GitHub Actions runs the backend test suite automatically for pushes to `main` and
pull requests targeting `main`. Run the same command locally from the repository
root:

```bash
python -m pytest -q
```

## End-to-end regression coverage

The E2E suite exercises the MVP across its real application boundaries with a
mocked official Senato response and temporary SQLite database:

```text
source data -> ingestion -> bootstrap/matching -> draft + Evidence
-> review -> publication + citation snapshot -> public API
```

It also verifies that rejected, stale, unpublished, duplicate-approval, and failed
publication paths cannot expose unapproved content. Run only these scenarios with:

```bash
python -m pytest -q tests/e2e
```

## Demo setup

Prepare—or reset—the deterministic, network-free presentation database:

```bash
python -m scripts.prepare_demo
```

For the shortest presentation setup, run the safe demo-only launcher instead:

```bash
./scripts/run_demo.sh
```

It recreates only `data/demo/`, applies the documented demo environment, and starts
the application on `127.0.0.1:8000`. It never touches the normal development
database.

The command touches only `data/demo/verapolitica_demo.db` and `data/demo/raw/`.
It always recreates these stable IDs:

- Published profile: Politician 1, Anna Rossi, version 1, 14 citations.
- Pending review: Draft 2 for Politician 2, Luca Bianchi, 14 Evidence rows.

Start FastAPI against the demo state:

```bash
export VERAPOLITICA_DATABASE_URL="sqlite:///./data/demo/verapolitica_demo.db"
export VERAPOLITICA_RAW_STORAGE_PATH="./data/demo/raw"
export VERAPOLITICA_ADMIN_API_KEY="verapolitica-demo-admin"
export VERAPOLITICA_ADMIN_REVIEWER_IDENTITY="demo-presenter"
uvicorn backend.app.main:app --reload
```

Open the two complementary interfaces:

- Citizen archive: `http://127.0.0.1:8000/app/`
- Editorial demo: `http://127.0.0.1:8000/demo/`

The citizen archive uses only the public API. Initially it shows Anna Rossi while
Luca Bianchi is absent. In the editorial demo, inspect Draft 2 and approve it using
the real review workflow. Refresh the citizen archive: Luca now appears, and
`http://127.0.0.1:8000/app/?politician=2` shows his approved profile and grouped
official citations. After a rehearsal, stop the API and rerun
`python -m scripts.prepare_demo` to restore the original pending state. Swagger
remains available at `/docs`. See [docs/demo.md](docs/demo.md) for the presenter
runbook.
