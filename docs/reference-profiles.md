# Schede della redazione

The redazione writes politician sheets (Word documents). Each sheet becomes a
fixture in `data/fixtures/reference_profiles/`, loaded as **pending drafts**:
nothing is published by the import.

| Slug | Fixture | Source document |
| --- | --- | --- |
| `giorgia-meloni` | `giorgia_meloni_v1.json` | Giorgia_Meloni (15 ottobre 2026) |
| `giuseppe-conte` | `giuseppe_conte_v1.json` | Giuseppe_Conte.docx (16 ottobre 2026) |
| `elly-schlein` | `elly_schlein_v1.json` | Elly_Schlein.docx (17 ottobre 2026) |

## Rules for turning a sheet into a fixture

- Text is copied as written. Only tracking parameters (`utm_*`) are removed from links.
- Every fixture lists `editorial_issues` (what the redazione must fix) and
  `not_imported` (sections with no place in the data model, and why).
- Verdict labels map to `pledge-score/v1`. Labels that do not exist there
  (for example "obiettivo realizzato dopo il mandato") get `suggested_verdict: null`.
- No pledge assessment is created: a verdict needs a verbatim excerpt from a
  stored official document (see `docs/scoring-methodology.md`).

## Loading

The politician must already exist from the official Camera/Senato/Governo import.
The match uses family name, birth date and the fixture's given-name aliases
(the Camera registers Schlein as "Elly", the sheet says "Elena Ethel").

```bash
python -m scripts.prepare_reference_profile --slug giuseppe-conte --dry-run
python -m scripts.prepare_reference_profile --slug giuseppe-conte --apply
python -m scripts.audit_reference_profile giuseppe-conte
python -m scripts.approve_reference_profile giuseppe-conte --apply
```

`prepare` creates drafts for biography, career, positions, proceedings, pledges
and proposals. Positions without a dated, verifiable statement are reported as
blocked and not created.

`approve` publishes only biography, career and position rows the audit marks
`READY_FOR_EDITORIAL_REVIEW`. Proceedings, pledges and proposals go through the
normal review queues (`/admin/proposals/drafts`, profile content review).

## What counts as a source

A source must point at the document that backs the claim. Home and section
pages (`https://www.partitodemocratico.it/`, `ansa.it/.../politica/politica.shtml`,
`europarl.europa.eu/meps/it/home`, `camera.it/deputati/elenco`) are not
citations: the audit marks them `MISSING_SOURCE_URL` and the row stays unpublished.
