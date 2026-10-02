# VeraPolitica

VeraPolitica is beginning with a deterministic ingestion slice for official Senato
della Repubblica data. This slice collects current-senator SPARQL JSON, stores the
raw response, parses structured records, and detects meaningful changes using a
canonical normalized hash. Changed records are mapped deterministically into
source-independent, transient CandidateProfile objects. The domain now includes
stable Politician identities, generic official-source identifiers, immutable
PoliticianVersion snapshots, a read-only deterministic MatchingService, and an
explicit bootstrap command for initial identity creation. Matched candidates can
now be compared with their current version and persisted as reviewable ProfileDrafts
with field-level Evidence. Explicit human decisions can reject a draft or atomically
publish it as a new immutable PoliticianVersion.

It does not yet perform LLM extraction, API serving, authentication, or frontend
rendering. CandidateProfiles are not persisted, normal ingestion never creates
Politicians, and matching and diffing never mutate the database. Publication is
only available through an explicit review action.

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
python -m scripts.run_ingestion
```

By default this creates `data/verapolitica.db` and stores immutable raw payloads
under `data/raw/`. The command prints the RawDocument ID, both hashes, change result,
storage key, and collector/parser versions.
The output also reports how many CandidateProfiles were produced. Unchanged source
data produces zero candidates.

## Bootstrap politician identities

Bootstrap is a separate, explicit operator action. It rebuilds transient
CandidateProfiles from a successfully parsed RawDocument, classifies every record,
and emits a detailed JSON report. Start with a dry-run against the latest parsed
Senato document:

```bash
python -m scripts.bootstrap_politicians --dry-run
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
Politician match, computes a field-level diff, and creates a pending ProfileDraft
plus Evidence in one transaction. If the candidate equals the current version it
returns `no_changes` and writes nothing. A changed field without source provenance,
including a removal without explicit absence evidence, blocks creation.

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

## Run tests

```bash
python -m pytest
```

Tests use temporary SQLite databases, mocked HTTP, and temporary raw storage. They
do not call the live Senato endpoint.
