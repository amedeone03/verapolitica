# HTTP API contract

## Public proposal API

`GET /proposals` returns only reviewed, published proposals. Filters are `status`,
`proposal_type`, `politician`, `source`, `offset`, and `limit`. Results include the
title, explicit type, accurate actor roles, current status, date, and one official
source. `GET /proposals/{proposal_id}` adds the complete approved timeline and all
official proposal identities.

```json
{
  "id": 1,
  "title": "Synthetic housing reform proposal",
  "proposal_type": "legislative_proposal",
  "summary": null,
  "exact_statement": null,
  "introduced_at": "2026-01-10",
  "current_status": "under_review",
  "actors": [
    {
      "actor_type": "politician",
      "role": "proposer",
      "display_name": "Sen. Anna Rossi",
      "politician_id": 1
    }
  ],
  "status_history": [
    {
      "status": "introduced",
      "source_status_label": "da assegn. a commis.",
      "effective_at": "2026-01-10",
      "source": {
        "name": "Senato della Repubblica — Disegni di legge",
        "url": "https://dati.senato.it/ddl/example"
      }
    }
  ]
}
```

Unpublished or rejected proposals return 404 and never appear in lists. Payloads
exclude drafts, unresolved actors, reviewer data, notes, hashes, RawDocument IDs,
storage paths, and internal event identities. A politician link is emitted only if
that politician has a public profile. Politician detail adds a compact `proposals`
collection containing role, so co-sponsorship is not implied authorship.

## Public territorial API

`GET /regions` and `GET /municipalities` are unauthenticated, paginated
(`offset`, `limit` 1–100), and ordered by official name. Municipalities also accept
`region` as a public region id filter.

`GET /search` is the public unified search. See `docs/search.md`. It accepts `q`
(required, max 200 characters), optional `type`, `offset`, and `limit` (1–50).
Only published politicians/proposals, official reference rows, published
referendums, and glossary terms are searchable. `GET /parliamentary-groups/{id}`
and `GET /political-parties/{id}` are thin public detail reads for search
click-through.

Civic citizen endpoints:

```http
GET /referendums
GET /referendums/{referendum_id}
GET /voting-guides
GET /voting-guides/{guide_id}
GET /glossary
GET /glossary/{slug}
```

`GET /referendums` is paginated (`offset`, `limit` 1–100) and accepts `status`,
`scope`, and `upcoming=true`. Only rows with `published_at` are returned. Drafts,
reviews, identity keys, and reminder candidates are never exposed. Voting guides
and glossary terms are likewise published-only. Glossary is alphabetical by term.
Admin referendum review lives under `/admin/referendums/{id}/...` and is not a
citizen contract. There is no public notification-subscription write API.

`GET /regions/{region_id}` includes ISTAT code, status, municipality count, official
source, and `current_president` when a linked mandate exists. This milestone does
not import regional presidents, so the field is typically null.

`GET /municipalities/{municipality_id}` includes ISTAT code, region, province/UTS
metadata, official source, and `current_mayor` when a politician could be linked
conservatively. `politician_id` is present only if that person also has a published
profile.

Published politician detail adds historical `territorial_offices` with office type,
territory, dates, and official source. Identity keys, RawDocument IDs, and
resolution-case metadata stay private.

DAIT coverage is incomplete. Missing mayors must not be interpreted as vacant
municipalities.

## Proposal editorial API

All proposal editorial routes use the existing router-level `/admin/*` bearer
authentication:

- `GET /admin/proposals/drafts`
- `GET /admin/proposals/drafts/{draft_id}`
- `POST /admin/proposals/drafts/{draft_id}/start-review`
- `POST /admin/proposals/drafts/{draft_id}/approve`
- `POST /admin/proposals/drafts/{draft_id}/reject`

List/detail expose normalized status, original official label, the source-independent
observation, Evidence, unresolved-actor count, baseline, supersession, and final
decision. For an AI-assisted draft, detail also includes an optional admin-only
`ai_assistance` object with source document, provider/model, prompt/schema versions,
controlled confidence/topic metadata, and short excerpts already verified against
document chunks. Deterministic drafts return `null` for this field. Reviewer identity
comes only from authenticated server context.
Start-review creates no final review. Approval is the only path that can append a
public status event; rejection and repeated terminal actions cannot.

AI run/candidate creation is an operator CLI concern in this milestone; there is no
public or admin HTTP endpoint that triggers paid provider calls. Public proposal
responses never expose `ai_assistance`, model names, prompt versions, confidence,
abstention data, raw chunks, or internal extraction outcomes.

## Public politician API

Public endpoints are read-only and require no authentication. Their only source of
profile data is the immutable PoliticianVersion explicitly referenced by
`Politician.current_version_id`. A row with no current pointer, a missing referenced
version, or a version without publication metadata is not public.

### `GET /politicians`

Query parameters:

- `offset`: non-negative integer, default 0
- `limit`: 1–100, default 50

Returns a deterministic, paginated list of current published profiles:

```json
{
  "items": [
    {
      "id": 1,
      "given_name": "Maria",
      "family_name": "Rossi",
      "birth_date": "1970-01-02",
      "current_version_number": 2,
      "profile_schema_version": 1,
      "published_at": "2026-10-02T10:00:00Z",
      "profile": {
        "given_name": "Maria",
        "family_name": "Rossi",
        "birth_date": "1970-01-02",
        "birth_place": null,
        "gender": null,
        "profession": "Avvocata",
        "image_url": null,
        "official_homepage_url": null,
        "mandates": []
      },
      "citation_count": 2
    }
  ],
  "total": 1,
  "offset": 0,
  "limit": 50
}
```

### `GET /politicians/{politician_id}`

Returns the current published projection in the same item shape used by the list.
It never selects `MAX(version_number)`. A nonexistent Politician or one without a
valid current published version returns:

```json
{
  "error": {
    "code": "not_found",
    "message": "published politician not found",
    "details": null
  }
}
```

The detail response additionally returns the immutable public citation snapshot:

```json
{
  "citation_count": 2,
  "citations": [
    {
      "field_path": "birth_date",
      "source_name": "Senato della Repubblica",
      "source_url": "https://dati.senato.it/sparql",
      "source_field": "birthDate"
    }
  ]
}
```

It also returns source-backed parliamentary-group history, ordered current first:

```json
{
  "parliamentary_groups": [
    {
      "name": "Fratelli d'Italia",
      "abbreviation": "FdI",
      "institution": "Senato della Repubblica",
      "legislature": "19",
      "start_date": "2022-10-18",
      "end_date": null,
      "role": "Membro",
      "source": {
        "name": "Senato della Repubblica",
        "url": "https://dati.senato.it/senatore/12345"
      }
    }
  ]
}
```

The public projection omits internal group and membership IDs, deterministic keys,
raw-document references, and RDF identifiers. An empty history is returned as
`"parliamentary_groups": []`. Parliamentary groups are institutional chamber
memberships and must not be interpreted as political-party affiliations.

Party affiliations are a separate collection and are also ordered current first:

```json
{
  "political_parties": [
    {
      "name": "Example Party",
      "abbreviation": "EP",
      "official_website_url": "https://example-party.it",
      "start_date": "2023-01-01",
      "end_date": null,
      "affiliation_type": "member",
      "source": {
        "name": "Explicit official source",
        "url": "https://official.example/member/123"
      }
    }
  ]
}
```

When no supported explicit assertion exists the value is
`"political_parties": []`. This collection is never derived from
`parliamentary_groups`, election lists, or coalitions, and does not expose internal
party/affiliation IDs or provenance storage keys.

Citations are deduplicated and sorted by field path, source name, source URL, and
source field. Versions published before citation snapshot support return
`"citation_count": 0` and `"citations": []`; citations are never inferred from a
later draft.

For a newly approved update, citations for unchanged fields are inherited from the
baseline version and citations for changed fields are replaced by the approved
draft's Evidence. The response may therefore contain separate entries naming
Senato della Repubblica and Camera dei Deputati when both support the current
version; source names are never collapsed.

Public responses deliberately omit ProfileDrafts, IdentityResolutionCases, internal
Evidence, Reviews, reviewer identity, review notes, hashes, storage paths, and
supersession data. A curated
public citation exposes only field path, readable source name, public source URL,
and source field.

**Invariant:** No public politician profile exists unless it points to an explicitly
approved immutable version.

## Public scorecard API

`GET /politicians/{politician_id}/scorecard?as_of=YYYY-MM-DD` returns 404 unless
the politician has a published current version. The body lists, in this order,
the pledges with their current verdicts, then per-role strata with composition,
closed/open counts, `kept_equivalent`, `rate` (null below 8 closed pledges, with
`rate_withheld_reason`) and `credible_interval`, plus `mandate_progress`.
Strata are never combined. `GET /methodology/scoring` returns the machine-readable
parameters of the current methodology.

## Pledge editorial API

All routes require the admin bearer token.

* `PUT /admin/pledges/{proposal_id}/classification`
* `POST /admin/pledges/{proposal_id}/assessment-drafts` (422 when the excerpt is
  not verbatim or the verdict does not match the evidence label)
* `GET /admin/pledges/assessment-drafts?status=`
* `POST /admin/pledges/assessment-drafts/{draft_id}/approve` with optional
  `{"reviewer": "...", "note": "..."}`; returns the draft and, once enough
  approvals exist, the published assessment. 409 for self-approval, repeated
  reviewer, terminal or stale drafts.
* `POST /admin/pledges/assessment-drafts/{draft_id}/reject` with `{"note": "..."}`
* `POST /admin/pledges/audit-samples` with `{"sample_key", "size", "seed"}`
* `GET /admin/pledges/audit-samples/{sample_key}` (blind items, no verdicts)
* `POST /admin/pledges/audit-samples/{sample_key}/codings/{assessment_id}`
* `GET /admin/pledges/audit-samples/{sample_key}/quality`
* `GET /admin/pledges/bias-audit?min_per_group=&flag_threshold=`

## Admin API

The Admin API is the authenticated HTTP adapter for the existing editorial service
layer. It does not contain review or publication transactions.

## Authentication

All `/admin/*` routes require:

```http
Authorization: Bearer <VERAPOLITICA_ADMIN_API_KEY>
```

The secret comes from `VERAPOLITICA_ADMIN_API_KEY`. The reviewer recorded in final
Reviews comes from `VERAPOLITICA_ADMIN_REVIEWER_IDENTITY`, never from request JSON.
Missing or invalid credentials return 401. If no key is configured, the admin router
fails closed with 503.

## Error envelope

```json
{
  "error": {
    "code": "draft_not_reviewable",
    "message": "draft 1 cannot be approved from status 'approved'",
    "details": null
  }
}
```

- 401: missing or invalid credentials
- 404: missing draft/resource
- 409: stale draft, terminal transition, supersession, or publication conflict
- 422: request body, query, filter, or review-input validation
- 500: sanitized internal persistence/unexpected failure
- 503: admin authentication is not configured

## `GET /health`

Compatibility health check. Includes database ping and schema revision fields.
It does not expose DSNs or secrets.

## `GET /health/live`

Process liveness. Does not check the database or official sources.

```json
{"status": "ok"}
```

## `GET /health/ready`

Readiness. Returns 503 when the database is unreachable or, when Alembic is in
use, the schema revision is not head.

The current public and admin paths are the V1 HTTP contract. This milestone does
not rename them under `/v1`.

OpenAPI (`/docs`, `/redoc`, `/openapi.json`) is disabled when
`VERAPOLITICA_ENV=production` unless `VERAPOLITICA_ENABLE_API_DOCS=true`.

## `GET /admin/drafts`

Supported query parameters:

- `status`: `pending`, `in_review`, `approved`, `rejected`, `superseded`, `failed`
- `kind`: `initial`, `update`
- `politician_id`: positive integer
- `source_key`: official source key
- `created_after`, `created_before`: ISO-8601 datetimes
- `offset`: non-negative integer, default 0
- `limit`: 1–100, default 50

Active drafts are ordered first, followed by terminal drafts; each group is ordered
by newest creation timestamp and then descending draft ID.

```json
{
  "items": [
    {
      "id": 12,
      "politician_id": 4,
      "politician_name": "Maria Rossi",
      "kind": "update",
      "status": "pending",
      "baseline_version_id": 3,
      "created_at": "2026-10-02T10:00:00Z",
      "updated_at": "2026-10-02T10:00:00Z",
      "evidence_count": 1,
      "change_count": 1,
      "supersedes_id": null,
      "final_review_decision": null
    }
  ],
  "total": 1,
  "offset": 0,
  "limit": 50
}
```

## `GET /admin/drafts/{draft_id}`

Returns draft and politician metadata, the complete proposed profile, typed diff,
field-level Evidence, source/RawDocument metadata, baseline and current versions,
supersession context, and the final Review. Raw bytes are never returned.

## `POST /admin/drafts/{draft_id}/start-review`

No request body. Delegates to `ReviewService.start_review` and creates no Review row.

```json
{
  "status": "in_review",
  "draft_id": 12,
  "politician_id": 4,
  "final_draft_status": "in_review"
}
```

## `POST /admin/drafts/{draft_id}/approve`

Optional body:

```json
{"note": "Official evidence verified"}
```

Delegates exclusively to `PublishService.approve`.

```json
{
  "status": "reviewed",
  "review_id": 8,
  "decision": "approved",
  "draft_id": 12,
  "politician_id": 4,
  "created_version_id": 7,
  "version_number": 2,
  "current_version_id": 7,
  "final_draft_status": "approved"
}
```

## `POST /admin/drafts/{draft_id}/reject`

Optional body:

```json
{"note": "Evidence requires clarification"}
```

Delegates exclusively to `ReviewService.reject`. `created_version_id` and
`version_number` are null; the current-version pointer is unchanged.

## Identity-resolution Admin API

These endpoints use the same router-level bearer authentication as draft routes.
Reviewer identity comes only from `VERAPOLITICA_ADMIN_REVIEWER_IDENTITY`; request
bodies cannot provide or override it.

### `GET /admin/identity-resolution`

Supported query parameters:

- `status`: `pending`, `resolved_existing`, `resolved_new`, or `ignored`
- `source_key`: configured official Source key
- `offset`: non-negative integer, default 0
- `limit`: 1–100, default 50

Pending cases sort first. Each item includes its exact display name, Source,
primary official identifier, official profile URL, current role, available birth
date, status, timestamps, and resolved Politician ID when terminal.

### `GET /admin/identity-resolution/{case_id}`

Returns the complete validated CandidateProfile snapshot, original matching result,
Source and RawDocument references, official URL, terminal audit fields, and possible
existing Politicians. Possible matches are read-only same-name or original-ambiguity
suggestions; their presence never performs or authorizes a link. Raw HTML is omitted.

### `POST /admin/identity-resolution/{case_id}/resolve-existing`

```json
{
  "politician_id": 42,
  "note": "Official profiles compared"
}
```

The service verifies the pending state and target Politician, transactionally
attaches every candidate source identifier, and records `resolved_existing`.

### `POST /admin/identity-resolution/{case_id}/resolve-new`

Optional body:

```json
{"note": "Editor confirmed a distinct person"}
```

Creates one Politician from the available structured identity fields, attaches all
official identifiers, and records `resolved_new` in one transaction. This human
action is the authorization; missing birth data never triggers automatic creation.

### `POST /admin/identity-resolution/{case_id}/ignore`

Optional body:

```json
{"note": "Evidence is insufficient"}
```

Records a terminal `ignored` decision. It creates no Politician and attaches no
identifier. Every second terminal action returns 409. Missing cases return 404,
invalid input returns 422, ownership/concurrent conflicts return 409, and persistence
failures return a sanitized 500 response.
