# Architecture

## Evidence-grounded AI extraction sidecar

```text
operator-approved official HTML or text PDF
  -> immutable RawDocument + raw SHA-256
  -> deterministic text extraction (no OCR)
  -> deterministic DocumentChunk rows
  -> StructuredExtractionProvider
  -> strict Pydantic schema
  -> excerpt/chunk/page validation
  -> transient ProposalObservation
  -> existing ProposalService
  -> pending ProposalDraft
  -> existing human review and publication boundary
```

Provider-specific behavior is isolated behind `StructuredExtractionProvider`.
`OpenAIExtractionProvider` uses strict structured output; tests and the demo use
`FakeExtractionProvider`. Prompts, output schemas, provider/model identity, usage,
failures, candidates, validation outcomes, and short evidence excerpts are versioned
and auditable. The provider receives only selected source chunks and never receives
database credentials, admin secrets, review notes, or identity IDs.

The model cannot supply source URLs or database identities. VeraPolitica injects the
trusted RawDocument URL, validates every excerpt against the referenced chunk, and
keeps actor names unresolved unless the existing exact official-identifier logic can
resolve them. Explicit promises additionally require deterministic commitment
language and a commitment-owner mention. Confidence is metadata only.

Completed-run idempotency is based on source, raw SHA-256, provider, model, prompt
version, and schema version. Candidate deduplication is conservative and
deterministic. Prompt/model/schema changes permit a new audited run; unchanged
observations remain protected by ProposalService replay identity. Failures and
abstentions create no draft and are not publication failures.

There are no embeddings, vector indexes, retrievers, RAG framework, chatbot, OCR,
or automatic publication in this milestone. The chunk/evidence model is reusable by
a future retrieval layer without changing the current review boundary.

## AI evaluation boundary

Evaluation is a separate, non-publishing path:

```text
versioned gold manifest + local document
  -> deterministic in-memory extraction and chunks
  -> StructuredExtractionProvider
  -> deterministic one-to-one matcher
  -> case metrics + aggregate metrics
  -> AIExtractionEvaluationRun + JSON/Markdown reports
```

The evaluator never constructs `ProposalObservation`, calls `ProposalService`, or
touches review/publication state. Matching uses unique normalized exact statements,
then unique title + actor/role + claim type. Ambiguity remains unmatched. Evidence,
actors, topic, dates, numeric commitments, abstention, and hallucination are scored
by frozen deterministic rules documented in `docs/ai-evaluation.md`; no LLM judge,
embedding, or semantic similarity is used.

## Proposal-tracker vertical slice

```text
Senato DDL SPARQL (dedicated senato-ddl stream)
  -> SenatoProposalCollector
  -> RawDocument + raw SHA-256
  -> SenatoProposalParser
  -> canonical JSON + normalized SHA-256
  -> SenatoProposalMapper
  -> transient ProposalObservation
  -> ProposalService (exact identities and actor resolution)
  -> pending ProposalDraft + ProposalEvidence
  -> ProposalReviewService
  -> approved ProposalStatusEvent + ProposalActor + public Proposal
  -> /proposals API + citizen timeline
```

The feed is separate from the `senato-repubblica` person stream, so a DDL status
change cannot make unchanged politician profiles appear changed. Actor observations
still name that person authority and resolve through exact existing
`PoliticianSourceIdentifier` rows. Missing or ambiguous identities remain unresolved
draft metadata; proposal ingestion never creates a Politician or matches by name.

Parsers and mappers are write-free. `ProposalService.sync` validates Source,
RawDocument, chronology, evidence, and actor-resolution input before superseding an
active draft. Proposal identity is `(Source, official_identifier)`. Replay identity
excludes retrieval time and RawDocument ID, so the same assertion is idempotent
across snapshots.

The internal Proposal may exist before approval, but public queries require
`published_at`. `ProposalStatusEvent` rows are created only during approval and are
immutable. A later observation produces a reviewable update; the public status and
timeline remain unchanged until approval. Approval verifies that the baseline event
is still latest, then writes the event, actors, cached status, final review, and
draft state atomically.

`ProposalType` preserves `legislative_proposal`, `government_initiative`, and
`explicit_promise`. The Senato DDL adapter emits only `legislative_proposal`:
initiative ownership does not turn a bill into a promise. Explicit promises are
fixture-only and require exact text, a commitment owner, and official evidence.
The Senato DDL adapter itself remains deterministic and does not use AI, free-text
classification, fulfillment scoring, or promise extraction. The separate AI
sidecar described above can produce reviewable observations from approved official
unstructured documents without changing this adapter.

Status normalization is an explicit allow-list. Examples: `da assegn. a commis.`
maps to `introduced`, `assegnato (no esame)` to `assigned`, `esame in comm.` to
`under_review`, `respinto` to `rejected`, and `appr. definit. Legge` to `enacted`.
The original label is retained. Unknown labels stop mapping instead of inventing a
political fact.

The implemented multi-source path is deterministic:

```text
official source (Senato, Camera, or Governo)
  -> source-specific collector
  -> persisted RawDocument
  -> source-specific parser
  -> canonical normalized hash and change detection
  -> source-specific mapper
  -> transient CandidateProfiles when changed
  -> generic automatic matching or human identity resolution
  -> diff, Evidence, review, publication, and public API
```

For Senato and Camera, each collector performs two queries against the official
[`dati.senato.it` SPARQL endpoint](https://dati.senato.it/sparql) or
[`dati.camera.it` SPARQL endpoint](https://dati.camera.it/sparql) and stores both
exact response bodies in one raw bundle. The parser includes people and
group records in the same canonical normalized hash, while CandidateProfile mapping
keeps its changed-only behavior. Group observations are safe to replay on unchanged
documents because persistence is idempotent:

```text
official chamber SPARQL
  -> people response + group-membership response
  -> one RawDocument bundle
  -> source-specific parser
  -> source-specific group mapper
  -> ParliamentaryGroupObservation (transient)
  -> exact PoliticianSourceIdentifier lookup
  -> ParliamentaryGroupService transaction
  -> ParliamentaryGroup + source identity + time-bounded membership
```

Parsers and mappers perform no database writes. `ParliamentaryGroupService` never
matches by name and never creates a Politician. The existing candidate identity
workflow runs first; an unresolved membership is returned as an explicit result and
can link on a later replay after bootstrap or human identity resolution.

Camera represents membership intervals with `ocd:startDate`, `ocd:endDate`, and
`ocd:rif_gruppoParlamentare`; abbreviations are `dcterms:alternative`, while the
display title contains a date suffix removed by the Camera mapper. Senato uses
`osr:inizio`, `osr:fine`, `osr:gruppo`, `osr:legislatura`, and exposes short names
plus `osr:carica`. Both membership resources are blank nodes, so their labels are
not treated as durable source IDs. Senato role intervals can overlap; they are
preserved and surfaced as warnings rather than corrected.

Group identity is `(Source, official group URI, legislature)`. The legislature is
required because Senato can reuse a group URI across legislatures. Membership
idempotency uses a deterministic internal SHA-256 over the source person identifier,
group URI, legislature, start date, optional official membership identifier, and
role. End date is excluded so a newly published end date updates the same row.
Historical memberships are never deleted.

> ParliamentaryGroup is not PoliticalParty. Chamber groups remain separate across
> institutions and no party identity or affiliation is inferred in this milestone.

## Political-party boundary

Party affiliations use an independent path:

```text
explicit official party-membership assertion
  -> source-specific parser (not available for current sources)
  -> PoliticalPartyObservation (transient)
  -> exact PoliticianSourceIdentifier lookup
  -> PoliticalPartyService transaction
  -> PoliticalParty + source identity + time-bounded affiliation
```

`PoliticalPartyService` is implemented for a future source with explicit membership
semantics, but it is not called by normal Senato, Camera, or Governo ingestion today.
The source audit found that the official
[Camera ontology](https://dati.camera.it/en/ontology-chamber-deputies) and
[Senato ontology](https://dati.senato.it/sito/21) model parliamentary groups and
election lists; the Interior Ministry's
[election-transparency data](https://dait.interno.gov.it/elezioni/trasparenza)
models submitted political organizations, lists, and candidates; the parliamentary
[national party register](https://www.parlamento.it/1063) identifies legal party
entities; and current [Governo profiles](https://www.governo.it/it/ministri-e-sottosegretari)
contain no consistent party-membership field. None provides a structured politician
membership history suitable for automatic affiliation creation.

The service never resolves a politician by name, never reads parliamentary-group
memberships, and never treats an electoral candidacy as party membership. It accepts
only an explicit observation carrying durable party identity, source relationship,
supporting RawDocument, and official URL. Party identity is `(Source, official party
identifier)`; similar names never merge entities. Affiliation identity is a stable
hash of source affiliation identifier, source person identifier, party identifier,
start date, and affiliation type. End date is excluded so a newly published end date
can close the existing interval without deleting history.

> PoliticalParty != ParliamentaryGroup != ElectoralList != Coalition. Only the first
> two are persisted domain entities, and they remain unrelated unless a future source
> explicitly supports a separate relationship.

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

Unsafe automatic results enter a separate generic human boundary:

```text
CandidateProfile
  -> MatchingService (unchanged and read-only)
  -> uncertain OR insufficient_fallback_identity
  -> HumanIdentityResolutionCoordinator
  -> create/reuse persistent IdentityResolutionCase
  -> authenticated editor chooses:
       link existing -> attach identifiers + resolve in one transaction
       create new    -> create Politician + identifiers + resolve in one transaction
       ignore        -> terminal audited case, no identity mutation
```

Complete candidates with no deterministic match retain the existing explicit
bootstrap path; they do not create a manual case merely because they are new.
Name-only lookup is used only to display conservative suggestions to an editor and
never changes MatchingService output or database state.

Case deduplication uses `(source_id, primary_source_identifier)`, where the primary
identifier is the lexically first distinct identifier belonging to the candidate's
document Source. The initial full CandidateProfile, matching result, exact official
display name, and RawDocument reference are persisted as an immutable audit snapshot.
Repeated ingestion reuses the case instead of replacing that snapshot.

Normal ingestion may append a safely matched source identifier or persist a manual
case. It never creates a Politician automatically, creates no profile version, and
does not publish anything. Manual link/create operations reuse the validation and
write primitive in PoliticianIdentityService while sharing the case service's outer
transaction. An identifier conflict rolls back both identity and case changes.

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

No authentication UI, scheduling, or background-worker behavior is part of the
review and publication path. AI extraction ends before that existing path.

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
POST identity-resolution/{id}/resolve-existing
                  -> IdentityResolutionService.resolve_to_existing
POST identity-resolution/{id}/resolve-new
                  -> IdentityResolutionService.resolve_as_new
POST identity-resolution/{id}/ignore
                  -> IdentityResolutionService.ignore
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
The detail projection separately joins the canonical Politician to its persisted
parliamentary-group memberships and exposes only citizen-safe group metadata and
official provenance. Current memberships sort before historical intervals. Group
data does not become part of immutable PoliticianVersion profile JSON and does not
bypass the version publication boundary for profile fields.
Explicit political-party affiliations are projected through a separate
`political_parties` field. They use the same current-first ordering convention but
are never populated from parliamentary-group data. Politician detail also projects
historical `territorial_offices`. Region and municipality pages expose current
holders from the latest open mandate and never invent missing end dates.

The central visibility invariant is:

> No public politician profile exists unless it points to an explicitly approved
> immutable version.

## Territorial foundation

```text
ISTAT XLSX
  -> collector/parser/mapper
  -> TerritoryService
  -> Region / Municipality

DAIT current-mayors CSV
  -> collector/parser/mapper
  -> existing identity coordinator
  -> TerritorialMandateService
```

Territorial ingestion is a dedicated CLI. ISTAT codes are identity. DAIT
municipality codes are not treated as ISTAT codes; linkage uses unique normalized
name + province abbreviation + region code. People are never created from names.
`--fixture` is the offline path; `--live`/`--url` is an explicit download. The
public API paginates regions and municipalities and projects current holders plus
politician `territorial_offices` without exposing identity keys or RawDocument IDs.

## Citizen search

`SearchService` normalizes the query, runs one indexed read per requested entity
type, assigns an exact/prefix/token/fuzzy tier, and merges results
deterministically. SQL stays in the service; routers only validate parameters.
PostgreSQL may use `pg_trgm` for conservative typos. SQLite uses the same
contract with LIKE/prefix matching. Search never reads drafts, identity cases,
reviews, AI runs, or job history. See `docs/search.md`.

## Database and scheduled jobs

SQLite remains the test and demo engine and may use `metadata.create_all`.
PostgreSQL is the persistent/dev engine and is evolved only with Alembic. App
startup never auto-upgrades PostgreSQL; it may warn if the revision is behind
head. See `docs/database-and-migrations.md`.

Ingestion can be driven by APScheduler or `python -m scripts.run_jobs`. Outcomes
are stored as `IngestionJobRun` rows. Overlap protection is a database unique
partial index on a running job name, not an in-memory lock. Schedules default to
disabled. See `docs/scheduled-jobs.md`.

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
