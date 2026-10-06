# Citizen search

VeraPolitica exposes one public, read-only search across published politicians,
published proposals, published referendums, municipalities, regions, parliamentary
groups, source-backed political parties, and civic glossary terms.

There is no Elasticsearch, vector index, LLM ranking, autocomplete, analytics, or
personalization in this milestone.

## Endpoint

```http
GET /search?q=meloni
GET /search?q=milano&type=municipality
GET /search?q=universita&type=proposal
```

Parameters:

- `q` required, 1–200 characters after the client sends the string
- `type` optional: `politician`, `proposal`, `referendum`, `municipality`, `region`,
  `parliamentary_group`, `political_party`, `glossary_term`
- `offset` ≥ 0
- `limit` 1–50 (default 20)

Empty, whitespace-only, oversized, or unknown-type queries return `422`.

Thin public detail reads exist for click-through:

- `GET /parliamentary-groups/{id}`
- `GET /political-parties/{id}`

Politicians, proposals, regions, and municipalities keep their existing public
detail routes.

## Publication filters

Search never inspects identity-resolution cases, profile/proposal drafts,
reviews, AI extraction runs, job history, or reviewer notes.

- Politicians: `current_version_id` points at a version with `published_at`
- Proposals and referendums: `published_at` is set
- Glossary terms: `published_at` is set
- Territories, groups, and parties: official reference rows, not editorial drafts

Luca Bianchi and Carlo Verdi remain hidden in the deterministic demo until a
human publishes or resolves them.

## Searchable fields

| Type | Fields |
| --- | --- |
| Politician | normalized full name, given/family name, office, institution, election area, territorial office names |
| Proposal | published title, summary, exact statement, proposal type, public actor display names |
| Referendum | published title, official question, referendum type |
| Municipality | name, `Comune di …` convention, province abbreviation |
| Region | name |
| Parliamentary group | canonical name, abbreviation, institution, legislature |
| Political party | canonical name, abbreviation |
| Glossary term | term, slug, short definition |

Proposal topic is not a published column yet; `proposal_type` is the public
stand-in. Internal evidence excerpts are not searchable.

## Normalization

Queries are trimmed, Unicode-normalized (NFKD), accent-stripped, case-folded,
and collapsed to alphanumeric tokens. Person-name search reuses
`normalize_person_name`. Names are not stemmed.

## Ranking

Cross-entity scores are not treated as perfectly comparable. Each hit gets a
tier, then results merge deterministically:

1. exact normalized primary match (name or title)
2. prefix match
3. token / document match
4. conservative PostgreSQL trigram match (`similarity >= 0.42`, query length ≥ 4)

Ties break by title, then entity type order (politician, proposal, referendum,
municipality, region, parliamentary group, political party, glossary term), then
id. There is no popularity or ideological boost.

PostgreSQL may use `pg_trgm` so `Giorga Meloni` can still find Giorgia Meloni.
Fuzzy hits never outrank exact or prefix hits. SQLite has no fuzzy tier.

## SQLite vs PostgreSQL

Tests and the demo stay on SQLite and use indexed `LIKE`/`prefix` matching on
`search_primary` / `search_document`.

PostgreSQL adds `CREATE EXTENSION IF NOT EXISTS pg_trgm` and GIN trigram
indexes on municipality, politician, proposal, region, referendum, and glossary
search keys. The public JSON contract is the same on both dialects.

Municipality queries are SQL-filtered and limited. The service does not load
the full ~7,894-row table into Python.

## Citizen UI

`/app/` has a header search box. Results live at
`/app/?view=search&q=…&type=…`. Titles, subtitles, and snippets are escaped
before optional client-side highlighting. Click-through uses the existing
public detail URLs.

Search queries are not stored.
