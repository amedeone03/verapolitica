# AI extraction evaluation

VeraPolitica evaluates extraction quality against manually verified, versioned gold
labels. Evaluation is an engineering tool: it does not publish, create a
`ProposalObservation`, or call `ProposalService`.

## Gold dataset

The initial synthetic dataset is `evaluation/gold/v1/manifest.json`. Each case
references a local HTML/PDF document and records expected claims, type, exact
statement, actors and roles, controlled topic, exact dates, numeric commitments,
evidence chunk/page/excerpt, abstention expectation, and notes. Labels are strict
Pydantic data rather than Python test constants.

Changing labels requires a new dataset version or an explicit version bump. The
loader confines document paths to the dataset directory, runs production
deterministic extraction/chunking, and verifies that every gold excerpt occurs in
its declared chunk and page.

## Deterministic matching

No model grades another model. Predictions are matched one-to-one within a case:

1. unique NFC/whitespace/casefold-normalized exact statement;
2. unique normalized title + exact normalized actor/role set + claim type.

An ambiguous edge is left unmatched and reported. There are no embeddings, cosine
similarity, semantic search, synonym inference, or LLM judge.

## Metrics

- Claim TP: one prediction matched to one gold claim.
- Claim FP: a non-abstaining prediction with no match.
- Claim FN: an expected claim with no match.
- Precision, recall, and F1 use those claim counts with safe zero denominators.
- Type accuracy is measured on matched claims; per-type precision/recall/F1 and a
  confusion matrix include spurious and missing claims.
- Evidence is correct only when every predicted excerpt is valid in its chunk/page
  and every expected evidence item is covered. Wrong and missing evidence are
  counted separately.
- Actor metrics compare normalized `(name, role)` sets. Database identity resolution
  is deliberately not evaluated.
- Topic and dates use exact controlled/ISO values. Numeric commitments use exact
  decimal value + immediate normalized unit; years from 1900–2100 are excluded from
  numeric commitments.
- A case predicts abstention when it emits no claims and either emits an abstention
  candidate or an empty output. Precision, recall, accuracy, missed abstentions, and
  inappropriate claim generation are reported.

The project hallucination rate is:

```text
(unmatched predictions + matched predictions with failed grounding)
/ all non-abstaining predictions
```

It does not label stylistic differences as hallucinations. Duplicate and provider
failure behavior remain separately visible in case results.

## Running evaluation

Deterministic perfect fake-provider run:

```bash
python -m scripts.evaluate_ai_extraction \
  --dataset evaluation/gold/v1 \
  --provider fake \
  --profile perfect \
  --output-dir evaluation/reports/perfect
```

Other profiles are `noisy`, `wrong_evidence`, `wrong_type`, and `abstention`.
Generated `report.json` and `report.md` are ignored by Git. Reports include complete
case results, aggregate metrics, run/provider/prompt/schema versions, failures,
threshold results, and request/token metadata.

Compare two runs:

```bash
python -m scripts.evaluate_ai_extraction \
  --compare evaluation/reports/perfect/report.json \
            evaluation/reports/noisy/report.json
```

The comparison reports deterministic metric deltas and both model/prompt identities.

## Engineering thresholds

Defaults are configurable, not claims of production readiness:

- precision at least `0.90`
- evidence accuracy at least `0.95`
- hallucination rate at most `0.05`

Use `VERAPOLITICA_AI_EVAL_*` variables or CLI flags. Threshold failure returns a
nonzero CLI status after writing the complete reports. Production review and
publication never consult these thresholds.

## Optional real provider

No paid request runs automatically. Configure `VERAPOLITICA_LLM_API_KEY`, then use:

```bash
python -m scripts.evaluate_ai_extraction \
  --dataset evaluation/gold/v1 \
  --provider openai \
  --model YOUR_CONFIGURED_MODEL \
  --output-dir evaluation/reports/openai-run
```

A missing key/model fails before the first case. API prices are not hard-coded;
request/input/output token counts are metadata only.

Per-case provider, schema, or extraction failures do not erase the run. Remaining
cases continue, failed-case gold claims become false negatives, and the run is
marked `partial` unless every case failed.
