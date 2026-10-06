# VeraPolitica

VeraPolitica ingests official national political data from Senato della Repubblica,
Camera dei Deputati, and Governo Italiano. Each source-specific collector, parser,
and mapper feeds the same source-independent pipeline. Raw responses are preserved and
meaningful changes are detected with canonical normalized hashes. Changed records
are mapped deterministically into transient CandidateProfile objects. The domain includes
stable Politician identities, generic official-source identifiers, immutable
PoliticianVersion snapshots, a read-only deterministic MatchingService, and an
explicit bootstrap command for initial identity creation. Unsafe or ambiguous
identity results are persisted as human-reviewable IdentityResolutionCases. Matched candidates can
now be compared with their current version and persisted as reviewable ProfileDrafts
with field-level Evidence. Explicit human decisions can reject a draft or atomically
publish it as a new immutable PoliticianVersion.

VeraPolitica also supports an internal, evidence-grounded AI extraction path for
operator-approved official HTML and text-based PDF documents. AI output is schema
validated, checked against deterministic document chunks, and can create only
reviewable ProposalDrafts. AI never publishes directly. Citizen authentication,
OCR, RAG, embeddings, and arbitrary web crawling are not implemented.
CandidateProfiles remain transient and normal ingestion never creates Politicians,
and matching and diffing never mutate the database. A separate transactional
identity service may attach a newly discovered official identifier after one safe
deterministic match or an explicit human identity decision. Publication is only available
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

SQLite is the default local/test/demo database. PostgreSQL is the
production-like engine. See [docs/database-and-migrations.md](docs/database-and-migrations.md)
and [docs/scheduled-jobs.md](docs/scheduled-jobs.md).

## Database

Tests and `python -m scripts.prepare_demo` keep using SQLite with
`metadata.create_all`. Persistent PostgreSQL databases must be migrated
explicitly:

```bash
createdb verapolitica
export VERAPOLITICA_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/verapolitica
alembic upgrade head
alembic current
```

The application never runs `alembic upgrade head` on startup. If a PostgreSQL
schema is behind head, it logs a warning.

## Scheduled ingestion jobs

Existing operator commands still work. The job CLI records run history:

```bash
python -m scripts.run_jobs senato
python -m scripts.run_jobs camera
python -m scripts.run_jobs governo
python -m scripts.run_jobs proposals
python -m scripts.run_jobs territories
python -m scripts.run_jobs territorial-offices
python -m scripts.run_jobs list
```

Schedules stay disabled unless you set a cron variable, then start a separate
process:

```bash
export VERAPOLITICA_SCHEDULE_SENATO_CRON="0 3 * * *"
python -m scripts.run_scheduler
```

Inspect runs through `/admin/jobs` with the existing admin bearer token. There is
no public job API.

## Evidence-grounded AI extraction

The focused extraction path is:

```text
official document -> RawDocument -> deterministic text -> DocumentChunk
  -> structured provider -> schema validation -> evidence validation
  -> ProposalObservation -> ProposalDraft -> human review -> publication
```

Supported inputs are UTF-8 HTML and text-based PDF. A PDF with no extractable text
fails with an OCR-required error; OCR is intentionally out of scope. Chunks use
deterministic page/paragraph-aware character limits and retain page, character, and
SHA-256 metadata. No vector index or semantic retrieval is involved.

Live calls are disabled unless `VERAPOLITICA_LLM_PROVIDER=openai`, a model, and an
API key are explicitly configured. The model and all size/request limits are
environment-configurable; API keys are never persisted. Tests and the demo use the
deterministic fake provider and never require network access or paid calls.

Run an internal extraction with:

```bash
python -m scripts.run_ai_extraction \
  --file path/to/official-programme.pdf \
  --source-url https://official.example/programme.pdf
```

For an offline deterministic run, add
`--fake-response data/fixtures/ai/synthetic_fake_response.json`. The command prints
the extraction run and draft IDs and never approves or publishes them.

An optional live smoke test may use the Piano Nazionale di Ripresa e Resilienza PDF
published under `https://www.governo.it/sites/governo.it/files/PNRR.pdf`. It is an
official institutional source because it is hosted on the Governo Italiano domain.
Download and inspect it manually before supplying the local file and that URL to the
command. VeraPolitica does not crawl it, and no paid call is run automatically.

## AI extraction evaluation

The versioned synthetic gold set under `evaluation/gold/v1/` measures claim
detection, proposal/promise classification, evidence, actors, topics, exact
date/numeric fields, abstention, and hallucination rate without an LLM judge.
Evaluation runs only in-memory document extraction and the provider boundary; it
never creates proposals or drafts.

```bash
python -m scripts.evaluate_ai_extraction \
  --dataset evaluation/gold/v1 \
  --provider fake \
  --profile perfect \
  --output-dir evaluation/reports/perfect
```

Profiles `noisy`, `wrong_evidence`, `wrong_type`, and `abstention` demonstrate metric
regressions deterministically. Compare report JSON files with `--compare RUN_A
RUN_B`. Optional real-model evaluation requires both an explicit OpenAI model and
`VERAPOLITICA_LLM_API_KEY`; no paid evaluation runs automatically. See
`docs/ai-evaluation.md` for frozen definitions and dataset format.

## Run one ingestion

From the repository root:

```bash
# Backward-compatible default: Senato
python -m scripts.run_ingestion

# Explicit source selection
python -m scripts.run_ingestion --source senato
python -m scripts.run_ingestion --source camera
python -m scripts.run_ingestion --source governo
```

Territorial reference data and current mayors are a separate operator command.
Tests and local work should use fixtures. Live downloads are explicit:

```bash
python -m scripts.run_territorial_ingestion territories --fixture data/fixtures/territorial/istat.xlsx
python -m scripts.run_territorial_ingestion offices --fixture data/fixtures/territorial/dait_mayors.csv

# explicit live downloads, isolated storage recommended
python -m scripts.run_territorial_ingestion territories --live \
  --database-url sqlite:///./data/smoke/territorial.db \
  --raw-storage-path ./data/smoke/raw
python -m scripts.run_territorial_ingestion offices --live \
  --database-url sqlite:///./data/smoke/territorial.db \
  --raw-storage-path ./data/smoke/raw
```

Office ingestion requires territories first. The DAIT feed is not a complete census
of Italian mayors and never creates politicians from names. See
`docs/territorial-sources.md`.

By default this creates `data/verapolitica.db` and stores immutable raw payloads
under `data/raw/`. The command prints the RawDocument ID, both hashes, change result,
storage key, and collector/parser versions.
The output also reports how many CandidateProfiles and identity-resolution cases
were produced. Unchanged source data produces zero candidates and no new cases.

Camera ingestion uses the official Camera open-data SPARQL endpoint and maps current
XIX-legislature deputies. Camera-specific RDF bindings remain inside its collector,
parser, mapper, and provenance; the CandidateProfile and every downstream service
remain source-independent.

Senato and Camera ingestion also collect their official structured parliamentary-
group membership data. Each raw document is a versioned bundle containing the exact
people and group SPARQL response bodies. Group observations are normalized into
institution- and legislature-scoped `ParliamentaryGroup` rows and time-bounded
`ParliamentaryGroupMembership` rows only after the politician is resolved through
an existing exact source identifier. Unresolved people are reported and skipped;
the group pipeline never creates a Politician. Repeated runs are idempotent, while
new official end dates update the existing interval and group transfers append a
new interval without deleting history.

`ParliamentaryGroup` is an institutional chamber concept. It is deliberately not a
`PoliticalParty`, and no party affiliation is inferred from a group membership.

Political parties and time-bounded affiliations have their own domain models and
transactional persistence service. An affiliation may be stored only from an
explicit official assertion for an already-resolved Politician; neither a
parliamentary group nor an electoral list can create one. No production affiliation
collector is enabled yet: Camera and Senato publish groups and election lists,
Governo's current profile pages do not publish a consistent party-membership field,
and the official national party register identifies parties but not their members.
The public API therefore returns an empty `political_parties` collection until a
supported explicit source is available.

`PoliticalParty`, `ParliamentaryGroup`, `ElectoralList`, and `Coalition` are distinct
concepts. VeraPolitica currently models only the first two and performs no automatic
conversion between them.

## Proposal and explicit-promise tracker

The first deterministic proposal source is the official Senato linked-data DDL
feed. It supplies stable DDL URIs, titles, presentation dates, initiative records,
Senator URIs, official status labels, and status dates. The adapter uses a separate
`senato-ddl` Source stream, so legislative changes cannot alter the normal Senato
politician change detector.

```bash
python -m scripts.run_proposal_ingestion
```

The default window is the latest 100 DDL resources; configure it with
`VERAPOLITICA_SENATO_PROPOSAL_RECORD_LIMIT`. Raw SPARQL JSON is preserved, canonical
records drive normalized change detection, and changed records become transient
`ProposalObservation` objects. Sync creates only internal `Proposal` identities and
evidence-backed `ProposalDraft` rows. It never publishes them.

`Proposal != Promise`. A legislative DDL remains a `legislative_proposal`, including
when its initiative is governmental. `explicit_promise` is supported by the domain
and deterministic synthetic fixtures only; it requires exact commitment text, a
commitment owner, and official evidence. There is no campaign-programme extraction
or classification of vague language.

Every public proposal and later status transition requires human approval. Approval
atomically appends an immutable `ProposalStatusEvent`, publishes safely resolved
actors, updates current status, creates the final `ProposalReview`, and closes the
draft. Rejection creates no public event. Original Senato labels remain alongside
normalized statuses; an unknown label fails mapping rather than being guessed.

Actors resolve only through exact existing official identifiers. Unresolved
presenter metadata remains in the editorial draft and is never linked by name. A
governmental initiative is represented as the institution `Governo Italiano`, not
as inferred ownership by a person or party. The live feed exposes current DDL phase
metadata; reviewed history accumulates over successive observations and does not
claim to backfill every within-phase event.

Governo ingestion uses the official current office-holder index and its linked
official profile pages. Because Governo does not expose an equivalent structured
people endpoint, the collector preserves the index and all discovered profile HTML
inside one deterministic raw bundle. The parser uses semantic HTML metadata and
official links rather than page positions. Its stable identifier is the official
Drupal node shortlink when present, falling back to the canonical profile URL.

The Governo adapter maps offices, institutions, appointment dates, official image
and profile URLs, and birth data only when the biography states it explicitly. It
does not infer professions from prose. Most current profiles do not publish a birth
date, so those candidates cannot safely use name-plus-birth-date fallback matching.
Routine candidate processing creates or reuses a human identity-resolution case;
bootstrap still reports them as invalid rather than creating possible duplicate people.
Exact official identifiers continue to match normally. The adapter also groups
multiple official pages with the same displayed name into one candidate and retains
all of their identifiers and mandates; exact-name grouping and simple displayed-name
splitting are known MVP limitations.

## Resolve incomplete or ambiguous identities

Automatic identity resolution remains limited to an exact official source identifier
or normalized full name plus exact birth date. It never links on name alone.

An `uncertain` result, or a candidate without the birth date required for fallback,
creates one durable `IdentityResolutionCase`. The deduplication key is the Source row
plus the candidate's lexically first official identifier for that source. Repeated
processing reuses the same case and preserves its original CandidateProfile snapshot.
A complete candidate with no match remains in the existing explicit bootstrap path.

Authenticated editors can inspect conservative same-name suggestions and then:

- link the case to an existing Politician;
- explicitly authorize creation of a new Politician;
- mark the case ignored without attaching an identifier.

Linking and creation attach every identifier from the stored candidate through the
same PoliticianIdentityService validation used by automatic linking. Identifier
attachment and the terminal case decision share one transaction. Terminal cases
cannot be decided again, and identity-resolution data is never exposed publicly.

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

The equivalent Governo Source key is `governo-italiano`.

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

curl \
  -H "Authorization: Bearer $VERAPOLITICA_ADMIN_API_KEY" \
  http://127.0.0.1:8000/admin/identity-resolution
```

The API exposes draft review plus identity-resolution listing, detail, link-existing,
create-new, and ignore actions. Reviewer identity always comes from authenticated
server context. Route handlers delegate transactions to the corresponding services.

## Read the Public API

The public routes require no bearer token:

```bash
curl "http://127.0.0.1:8000/politicians?offset=0&limit=50"
curl http://127.0.0.1:8000/politicians/1
curl "http://127.0.0.1:8000/proposals?offset=0&limit=50"
curl http://127.0.0.1:8000/proposals/1
```

Only Politicians whose `current_version_id` references a published immutable
PoliticianVersion are visible. The API never falls back to the highest version
number and does not expose drafts, Reviews, Evidence, hashes, or raw storage data.
Politician detail responses include a curated citation snapshot copied from the
approved draft's Evidence during publication. List items expose only
`citation_count` to stay compact. Versions published before citation snapshots were
introduced remain readable with an empty citation list.
Detail responses also include current and historical parliamentary-group
memberships, ordered current first, with chamber, legislature, official dates,
optional role, and an official source link. Internal group IDs and RDF identifiers
are not exposed.
Political-party affiliations, when supported by an explicit official assertion, are
returned separately in `political_parties`, current first and then historical. They
are never inferred from `parliamentary_groups`.
On an update, citations for unchanged fields are inherited from the baseline version,
while citations for changed fields come from the newly approved Evidence. A version
can therefore cite Senato and Camera independently without collapsing their identity.
Interactive OpenAPI documentation is available at
`http://127.0.0.1:8000/docs` while Uvicorn is running.

Proposal routes expose only approved records. Detail includes accurate actor roles,
the current normalized status, original official labels, an ordered approved
timeline, and official links. Politician detail includes linked published records
under `proposals`; co-sponsorship is displayed as co-sponsorship, not authorship.
The citizen UI has a separate `/app/?view=proposals` archive.

## Run tests

```bash
python -m pytest
```

Tests use temporary SQLite databases, mocked HTTP, deterministic fixtures, and
temporary raw storage. They do not call live Senato, Camera, or Governo endpoints.
Alembic upgrades a throwaway SQLite database in `tests/db`. Optional PostgreSQL
checks need a server and:

```bash
pytest -m postgres
```

## Continuous integration

GitHub Actions runs the SQLite backend suite, Alembic upgrade/downgrade checks, and
an optional PostgreSQL service job for pushes to `main` and pull requests targeting
`main`. Run the same default command locally from the repository root:

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
- Pending identity resolution: Case 1 for the Governo fixture's Carlo Verdi.

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
