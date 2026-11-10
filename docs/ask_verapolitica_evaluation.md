# Ask VeraPolitica evaluation

This is an engineering benchmark for **Ask VeraPolitica v1**. Metrics describe
performance on a named gold set only. They are **not** a universal accuracy
claim for the product or for any language model.

There are three slices. They share the same runner, scorer, and CLI. They are not
interchangeable. Do not add their pass counts together.

## Synthetic gold v1

Path: `evaluation/ask_verapolitica/v1/cases.json`
Dataset id: `ask-verapolitica-gold/v1`
CLI alias: `synthetic-v1` (default)

The runner seeds a throwaway SQLite world (Meloni, Mario Rossi, Anna Rossi,
unpublished Luca Bianchi) and maps stable keys such as `autonomia` to local IDs.
Cases never depend on production or demo databases. This slice is
regression-oriented and controlled.

Current deterministic baseline on this set: **54/54**. That figure is not a
universal Ask accuracy claim.

## Paraphrase gold v1

Path: `evaluation/ask_verapolitica/paraphrase_v1/`
Dataset id: `ask-verapolitica-gold/paraphrase-v1`
CLI alias: `paraphrase-v1`

This slice uses the same throwaway synthetic world as `synthetic-v1`. The
questions are Italian paraphrases (IRPEF, SSN, pronto soccorso, tassazione,
assunzioni, università, studenti) plus keyword controls, abstentions, and
unpublished-leak checks.

It exists to measure **Recall@12** of hybrid retrieve (paraphrase map + lexical
overlap + optional Postgres full-text) against the **keyword-only** planner that
shipped before that work. Ask still returns at most 12 pledges, so a labeled
hit in the result list is Recall@12 on that query.

`--retrieve keyword` disables hybrid synonyms, paraphrase matching, and
full-text ranking. `--retrieve hybrid` is production Ask. `--compare-retrieve`
runs both on the same gold and writes a JSON comparison.

The frozen comparison is `evaluation/ask_verapolitica/paraphrase_v1/compare.json`.
Regenerate it after changing retrieve or the gold; do not edit the numbers by
hand. The figures describe this set only.

## Real-corpus gold v1

Path: `evaluation/ask_verapolitica/real_v1/`
Dataset id: `ask-verapolitica-gold/real-v1`
CLI alias: `real-v1`

This slice reads the **unified demo** published corpus at
`data/unified_demo/verapolitica.db` in SQLite `query_only` mode. It does not
seed a synthetic world and it does not fall back to synthetic-v1 if the corpus
is missing.

The published Ask-visible world frozen here (corpus date 2026-10-16):

- 22 published politician profiles
- 21 published classified explicit promises, all owned by Giorgia Meloni
- 1 published assessment (`in_progress` on autonomia differenziata)
- 20 published promises with no approved assessment
- source host: `www.gazzettaufficiale.it`
- no published surname collision, so this slice has **no natural ambiguity case**

The set is messier and more representative than synthetic-v1, and it will change
when the unified demo is rebuilt. A high score here is still not universal
accuracy.

### Versioning / fingerprint

`evaluation/ask_verapolitica/real_v1/corpus.json` freezes:

- corpus name/date and relative database path
- SHA-256 of the published classified promises (title, statement, topic,
  public verdict, source URL)
- stable politician/pledge keys with `title_prefix` (not auto-increment IDs)
- documented `frozen_id` values for that corpus only

If the live unified demo no longer matches `published_fingerprint`, the
evaluator fails instead of scoring the wrong world. Regenerate `real_v1` or
restore that corpus; do not silently edit expectations to chase a new demo
build.

Keys are resolved by published name / title prefix. Numeric IDs in
`frozen_id` are documentation.

## Case fields

Each case may include:

- `id`, `category`, `question`
- `expected_intent`
- `expected_politician_key` / `expected_politician_name`
- `expected_pledge_keys`
- `expected_verdict`, `expected_topic`
- `expected_source_url` / `expected_source_host`
- `expected_count`
- `should_abstain`, `should_require_clarification`
- `expect_unrated`, `expect_invalid`, `expect_zero_results`
- `forbidden_claims`, `forbidden_verdicts`, `forbidden_titles`
- `notes`

The scorer does **not** match free-form Italian sentences.

## What is measured

- intent accuracy
- politician / entity accuracy
- pledge retrieval precision, recall, and F1
- **Recall@12**: macro-average of `|gold ∩ top 12| / |gold|` on cases that name
  at least one relevant published promise
- published-verdict consistency
- topic match accuracy (when the gold names a topic)
- source / citation accuracy (URL or host)
- abstention accuracy / unsupported-query accuracy
- clarification accuracy (ambiguous identity; synthetic-v1 only today)
- forbidden-claim and unpublished-title leaks
- invented-URL rate
- **zero-result precision**: when the gold answer is empty, Ask must not invent
  a pledge

Count questions compare retrieved published rows to `expected_count`.

## What is not measured

- Fluency, tone, or exact wording of the Italian answer
- General political knowledge or live web search
- Embedding / vector retrieval quality
- Pledge scoring, Draft 2, evidence judging, or scheduler behaviour
- Coverage of a future production corpus

## Deterministic vs AI-enabled evaluation

Default (`--ai off`) calls `AskVeraPoliticaService` with no completer. Ollama is
not required.

`--ai fake` uses `FakeTextCompleter`. Synthesis is scored on retrieved context,
published verdicts, forbidden claims, and URLs — not on sentence identity.

```bash
python -m evaluation.eval_ask_verapolitica
python -m evaluation.eval_ask_verapolitica --dataset synthetic-v1
python -m evaluation.eval_ask_verapolitica --dataset real-v1
python -m evaluation.eval_ask_verapolitica --dataset real-v1 --ai fake
python -m evaluation.eval_ask_verapolitica --dataset paraphrase-v1 --retrieve hybrid
python -m evaluation.eval_ask_verapolitica --dataset paraphrase-v1 --retrieve keyword
python -m evaluation.eval_ask_verapolitica --dataset paraphrase-v1 --compare-retrieve \
  --json-output evaluation/ask_verapolitica/paraphrase_v1/compare.json
python -m evaluation.eval_ask_verapolitica --category unsupported
python -m evaluation.eval_ask_verapolitica --case-id pol-meloni-in-corso
python -m evaluation.eval_ask_verapolitica --json-output evaluation/reports/ask-v1.json
```

`real-v1` needs the local unified demo. It will not create or mutate that
database.

## Limitations

- All three slices are Italian and small. None is a production-accuracy claim.
- Real-v1 currently has one assessed pledge and one politician with promises.
- Variants on synthetic-v1 are limited. Use paraphrase-v1 for the
  keyword-vs-hybrid Recall@12 comparison.
- `--ai fake` does not measure a real model.
- Synthetic-v1 exposed planner bugs that were fixed narrowly. Real-v1 may
  report honest misses without product changes.

## Why results are not universal model accuracy claims

Ask answers from **already published** pledges, verdicts, topics, and approved
sources. Reporting “98% accurate” without naming the slice
(`ask-verapolitica-gold/v1`, `ask-verapolitica-gold/real-v1`, or
`ask-verapolitica-gold/paraphrase-v1`) would overclaim.
