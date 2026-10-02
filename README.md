# VeraPolitica

VeraPolitica is beginning with a deterministic ingestion slice for official Senato
della Repubblica data. This slice collects current-senator SPARQL JSON, stores the
raw response, parses structured records, and detects meaningful changes using a
canonical normalized hash. Changed records are mapped deterministically into
source-independent, transient CandidateProfile objects. The domain now includes
stable Politician identities, generic official-source identifiers, immutable
PoliticianVersion snapshots, a read-only deterministic MatchingService, and an
explicit bootstrap command for initial identity creation.

It does not yet perform LLM extraction, version creation, diffing, drafting,
review, publication, API serving, or frontend rendering. CandidateProfiles are
not persisted, normal ingestion never creates Politicians, and matching never
mutates the database.

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

## Run tests

```bash
python -m pytest
```

Tests use temporary SQLite databases, mocked HTTP, and temporary raw storage. They
do not call the live Senato endpoint.
