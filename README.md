# VeraPolitica

VeraPolitica is beginning with a deterministic ingestion slice for official Senato
della Repubblica data. This slice collects current-senator SPARQL JSON, stores the
raw response, parses structured records, and detects meaningful changes using a
canonical normalized hash. Changed records are mapped deterministically into
source-independent, transient CandidateProfile objects.

It does not yet perform LLM extraction, matching, diffing, drafting, review,
publication, or frontend rendering. CandidateProfiles are not persisted.

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

## Run tests

```bash
python -m pytest
```

Tests use temporary SQLite databases, mocked HTTP, and temporary raw storage. They
do not call the live Senato endpoint.
