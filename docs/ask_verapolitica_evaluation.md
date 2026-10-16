# Ask VeraPolitica evaluation

This is an engineering benchmark for **Ask VeraPolitica v1**. Metrics describe
performance on the curated gold set only. They are **not** a universal accuracy
claim for the product or for any language model.

## Dataset

Versioned gold: `evaluation/ask_verapolitica/v1/cases.json`.

The runner seeds a throwaway SQLite world (Meloni, Mario Rossi, Anna Rossi,
unpublished Luca Bianchi) and maps stable keys such as `autonomia` or
`giorgia-meloni` to local IDs. Cases never depend on production or demo
databases.

Each case may include:

- `id`, `category`, `question`
- `expected_intent`
- `expected_politician_key` / `expected_politician_name`
- `expected_pledge_keys`
- `expected_verdict`, `expected_topic`
- `expected_source_url` / `expected_source_host`
- `should_abstain`, `should_require_clarification`
- `expect_unrated`, `expect_invalid`
- `forbidden_claims`, `forbidden_verdicts`, `forbidden_titles`
- `notes`

The set covers politician + pledge queries, verdict filters, topics, pledge
explanations, source/evidence questions, promises with no published assessment,
unsupported political opinions, prompt-injection attempts, ambiguous surnames,
limited natural variants, empty/malformed/oversized requests, and adversarial
verdict contradictions.

## What is measured

The scorer does **not** match free-form Italian sentences. It checks:

- intent accuracy
- politician / entity accuracy
- pledge retrieval precision, recall, and F1
- published-verdict consistency
- topic match accuracy (when the gold names a topic)
- source / citation accuracy (URL or host)
- abstention accuracy / unsupported-query accuracy
- clarification accuracy (ambiguous identity)
- forbidden-claim and unpublished-title leaks
- invented-URL rate

A case passes when none of its applicable checks fail.

## What is not measured

- Fluency, tone, or exact wording of the Italian answer
- General political knowledge or live web search
- Embedding / vector retrieval quality
- Pledge scoring, Draft 2, evidence judging, or scheduler behaviour
- Production data coverage (the world is synthetic and small)

## Deterministic vs AI-enabled evaluation

Default run (`--ai off`) calls `AskVeraPoliticaService` with no completer. The
deterministic path is fully evaluable and does not need Ollama or a live HTTP
server.

`--ai fake` uses `FakeTextCompleter`. Synthesis is still scored on retrieved
context, published verdicts, forbidden claims, and URLs — not on sentence
identity. A local provider is optional and is not part of the default CLI.

```bash
python -m evaluation.eval_ask_verapolitica
python -m evaluation.eval_ask_verapolitica --ai fake
python -m evaluation.eval_ask_verapolitica --category unsupported
python -m evaluation.eval_ask_verapolitica --case-id pol-meloni-in-corso
python -m evaluation.eval_ask_verapolitica --json-output evaluation/reports/ask-v1.json
```

JSON reports include an explicit disclaimer that the numbers apply only to this
gold set.

## Limitations

- The gold world is small and Italian. A high pass rate here does not mean Ask
  VeraPolitica is generally accurate on the live corpus.
- Variants are limited (Meloni / Giorgia Meloni, tasse / fiscalità, liste
  d’attesa / sanità). This is not a fuzzy-search benchmark.
- Optional AI evaluation with `FakeTextCompleter` does not measure a real model.
- Building this set exposed three planner/retrieval bugs (plural “non sono
  ancora valutate”, numeric CAP codes matching pledge text, named-pledge
  status questions listing a different pledge). Those are product fixes, not
  evaluation-only workarounds.

## Why results are not universal model accuracy claims

Ask VeraPolitica answers from **already published** pledges, verdicts, topics,
and approved sources. The gold set encodes those retrieval and safety
expectations. Reporting “98% accurate” without naming this curated set would
overclaim: the figure is pass rate (or a named metric) **on
`ask-verapolitica-gold/v1`**, nothing more.
