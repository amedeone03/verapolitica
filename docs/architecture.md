# Architecture

The implemented multi-source path is deterministic:

```text
official source (Senato, Camera, or Governo)
  -> source-specific collector
  -> persisted RawDocument
  -> source-specific parser
  -> canonical normalized hash and change detection
  -> source-specific mapper
  -> transient CandidateProfiles when changed
  -> generic matching, diff, Evidence, review, publication, and public API
```

Camera, Senato, and Governo share no source-specific domain fields. Each adapter translates
official bindings to CandidateProfile identity and versioned profile fields while
retaining exact document, record, and field provenance. `Source` registration and
`PoliticianSourceIdentifier` allow one Politician to carry opaque identifiers from
several institutions without adding provider-specific columns.

Senato and Camera collect structured official data. Governo currently has no
equivalent structured people feed, so its adapter collects the official current
office-holder index plus every linked official profile page into one deterministic
JSON envelope containing the original HTML. The parser relies on semantic metadata,
CSS classes, canonical links, and official appointment links rather than positional
selectors. It prefers the official Drupal node shortlink as the person identifier
and falls back to the canonical profile URL.

Governo pages can represent one person more than once when that person holds several
offices. The MVP parser groups exact normalized display names, retains every official
identifier, and emits distinct mandates. This is deterministic but not a general
identity algorithm. Its simple first-token/rest displayed-name split and exact-name
grouping are explicit adapter limitations. Birth data is mapped only from an exact
biographical statement, and profession is left null rather than inferred from prose.

Matching remains deterministic and read-only. A new provider identifier is checked
first; if it is not yet linked, normalized full name plus exact birth date may match
an existing Politician. Multiple matches remain uncertain and are never merged.
Attaching a newly resolved provider identifier is an explicit write outside
MatchingService:

```text
CandidateProfile
  -> MatchingService (read-only)
  -> unique deterministic MatchedResult
  -> CandidateIdentityCoordinator
  -> PoliticianIdentityService transaction
  -> PoliticianSourceIdentifier
  -> DraftService may continue with the same Politician
```

The coordinator writes only for exact source-identifier or normalized-name plus
exact-birth-date matches. `new` and `uncertain` results return without calling the
write service. The write transaction rechecks the match, source authority,
Politician, and current identifier ownership. An identifier already linked to the
same Politician is an idempotent success. Ownership by a different Politician is a
typed conflict, and database integrity failures roll back the entire attachment.
The existing schema permits several identifier values from the same Source for one
Politician; the service preserves that capability and never overwrites a value.

Normal ingestion stops there. It never creates or changes Politicians.

Initial identity population is an explicit operator path:

```text
selected successfully parsed RawDocument
  -> rebuild CandidateProfiles from stored structured records
  -> validate and classify every record with MatchingService
  -> detailed dry-run report
  -> if every record is safe, one transaction creates new Politicians
     and PoliticianSourceIdentifiers
```

The rebuild operation does not weaken normal ingestion's changed-only rule. It is a
separate service used only when an operator asks to remap a stored document. Mapping
failures are captured per stored record so the report can identify invalid input.
Candidates without a birth date and without an already linked official identifier
cannot safely be distinguished from an existing person. Bootstrap therefore reports
the MatchingService's `insufficient_fallback_identity` result as invalid and blocks
the batch instead of creating a possible duplicate Politician.

Planning and applying are intentionally separate. Planning uses a read-only session
and performs all matching before any write. Matched records are skipped, new records
are retained in an in-memory plan, and uncertain or invalid records make the plan
unsafe. Apply opens a fresh session and creates the complete safe batch in one
transaction. A uniqueness conflict or any other creation failure rolls back the
whole batch. The unique `(source_id, value)` database constraint is the final guard
against concurrent or stale plans.

The JSON report includes counts and concise per-record details for new, matched,
uncertain, and invalid classifications. It records both proposed and actual creation
counts. A second run after a successful apply classifies the same official IDs as
matched and proposes no writes.

Matched candidates can enter a separate explicit draft path:

```text
matched CandidateProfile
  -> safe official-identifier attachment when newly discovered
  -> pure CandidateProfile-to-PoliticianVersionProfile conversion
  -> deterministic DiffService against Politician.current_version
  -> complete field-provenance validation
  -> supersede unresolved older drafts
  -> one transaction inserts ProfileDraft + Evidence
```

DiffService does not use a database session and never mutates its inputs. With no
current version it produces an initial proposal. With a current version it validates
the stored snapshot and reports only meaningful changes. Scalar and birth-place
fields are compared explicitly; mandates are sorted and compared as a collection so
record order alone is not a change.

DraftService requires a typed deterministic match. A no-change result writes
nothing and does not supersede an existing draft. For a meaningful change, it first
verifies the referenced RawDocument and complete Evidence coverage. Only then does
it supersede every `pending` or `in_review` draft and insert the replacement draft
and its Evidence in the same transaction. Any failure rolls back both insertion and
supersession.

Evidence uses source-independent profile paths while retaining the official source
record identifier, source field name, source value, RawDocument, source URL, and
deterministic extraction method. Missing provenance is never synthesized. A removal
without explicit source evidence of absence is therefore blocked conservatively.

Final decisions use two service boundaries:

```text
ReviewService
  pending -> in_review                 (no Review row)
  pending/in_review -> rejected        (Review + status transaction)

PublishService
  pending/in_review -> approved
  Evidence -> immutable public citation snapshot
  Review + new PoliticianVersion + citations + current-version pointer + status
  committed in one transaction
```

A Review is the immutable final decision, so each draft has at most one Review.
PublishService is the only approval and version-creation path. Before any writes it
locks the draft and Politician where supported, validates the proposed profile, and
checks the baseline. An initial draft is current only while the Politician has no
version. An update draft is current only while its baseline ID exactly matches the
Politician's current-version ID.

Before publication, PublishService projects the approved draft's Evidence into a
minimal public form: field path, Source name, source URL, and source field. It drops
record identifiers, raw-document IDs, values, extraction metadata, hashes, storage
keys, and all reviewer data. Identical projections are deduplicated and sorted,
then inserted as immutable PoliticianVersionCitation rows belonging to the new
version. For updates, unchanged field citations are inherited from the immutable
baseline snapshot; citations at changed field paths are replaced by the new draft's
Evidence. This preserves independent Senato and Camera citations on one version.

Conflicting official values are not resolved by source priority. The new candidate
is compared normally with the published baseline; a discrepancy becomes a typed
diff supported by Evidence from the new source and waits for human review.

Version numbers are assigned per Politician as the existing maximum plus one. The
database uniqueness constraint on `(politician_id, version_number)` and the unique
Review per draft are final conflict guards. Any approval failure rolls back the
Review, version, citations, pointer, and draft status together.

The implemented HTTP projections are separate:

```text
Admin:
official data -> ProfileDraft -> Review -> PublishService approval

Public:
Politician.current_version_id -> immutable PoliticianVersion -> Public API
```

No authentication UI, LLM, scheduling, or background-worker behavior is part of
the review and publication path.

## Admin API boundary

FastAPI exposes the editorial workflow under `/admin`. Authentication is attached
to the parent admin router, so new routes inherit protection by default. A configured
bearer token authenticates one MVP admin principal, and its configured reviewer
identity is passed to the domain services. Request bodies cannot supply reviewer
identity.

Read endpoints use a request-scoped SQLAlchemy Session and return explicit Pydantic
responses. They expose proposals, typed diffs, Evidence, source metadata, version
context, supersession, and final Review data without exposing ORM objects or raw
stored payloads.

Write endpoints remain thin:

```text
POST start-review -> ReviewService.start_review
POST reject       -> ReviewService.reject
POST approve      -> PublishService.approve
```

They receive the configured session factory through dependency injection. Services
open and own their established transactions, so the API does not introduce an outer
transaction or duplicate state-transition and publication rules.

Controlled domain errors use a stable JSON envelope: missing resources become 404,
stale or terminal decisions become 409, request validation becomes 422, and
persistence failures become sanitized 500 responses. The health endpoint is public;
admin authentication remains independent from the public router.

## Public API boundary

The public router is unauthenticated and read-only. Its query service joins a
Politician directly to the PoliticianVersion named by `current_version_id`; it does
not inspect drafts or select the greatest version number. The join also confirms
that the selected version belongs to that Politician and has publication metadata.

Responses validate stored JSON through the existing PoliticianVersionProfile and
serialize it through dedicated public Pydantic schemas. ORM models are never
returned. Detail responses query the immutable citation rows for that exact version;
list responses expose only a citation count. Internal drafts, Review data, Evidence,
hashes, storage paths, and admin workflow state are absent from the projection.
Legacy versions without citation rows remain public with an empty citation list.

The central visibility invariant is:

> No public politician profile exists unless it points to an explicitly approved
> immutable version.

## End-to-end regression boundary

The E2E suite verifies the complete MVP through production service and HTTP
boundaries, using a mocked Senato HTTP response, real parser and mapper, temporary
raw storage, and a temporary SQLite database:

```text
Senato collector response
  -> IngestionPipeline
  -> CandidateProfile
  -> PoliticianBootstrapService + MatchingService
  -> DraftService + Evidence
  -> Admin API review and approval
  -> PublishService transaction + immutable citations
  -> Public API
```

The happy path asserts that pending and in-review data remains invisible, then
becomes public only after explicit approval. Safety scenarios cover rejection,
double approval, stale baselines, citation-insert rollback, and internal identities
without a published current-version pointer. No E2E test contacts the live Senato
service or depends on developer configuration or test ordering.
