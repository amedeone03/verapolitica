# MVP ingestion data model

The implemented slices persist the official source and every collected response,
then map changed Senato, Camera, or Governo records to transient CandidateProfiles. Stable politician
identities can be explicitly bootstrapped from a selected parsed document. The
implementation can persist identity-resolution cases, reviewable profile drafts,
and field-level Evidence, but
only an explicit final Review can reject a draft or publish a new version.

## Source

`Source` identifies one configured official provider.

- `id`: internal primary key
- `key`: stable application key (`senato-repubblica`, `camera-deputati`, or
  `governo-italiano`)
- `name`: human-readable institution name
- `base_url`: official provider URL
- `is_enabled`: whether collection is enabled
- `created_at`: creation timestamp

One Source has many RawDocuments.

Senato and Camera RawDocuments preserve their structured endpoint responses. A
Governo RawDocument preserves a deterministic JSON bundle containing the official
office-holder index HTML and all linked profile-page HTML, so parsing remains
repeatable even though the upstream representation is HTML.

## RawDocument

`RawDocument` records one collection attempt. Duplicate responses still receive
separate database records for auditability, while their raw bytes share the same
content-addressed storage object.

- source and retrieval metadata
- raw storage key and raw SHA-256
- canonical normalized SHA-256 after successful parsing
- structured parser records
- normalized human-readable text
- `collected`, `parsed`, or `failed` process status
- change-detection result
- collector and parser versions
- parser error text when parsing fails

The raw SHA-256 identifies exact response bytes. Semantic change detection compares
the normalized SHA-256, which is computed from canonical JSON with normalized strings,
stable record order, stable key order, and explicit JSON null values.

## CandidateProfile

`CandidateProfile` is a source-independent Pydantic object. It is returned only when
a RawDocument's normalized data changed and remains transient in the ingestion and
matching pipeline. When human identity review is required, a validated JSON snapshot
of that object is embedded in an IdentityResolutionCase for auditability.

It separates:

- identity-like matching inputs: exact official display name, structured name,
  birth data, and generic source identifiers;
- versioned profile data: gender, profession, URLs, and political mandates;
- provenance: the RawDocument snapshot plus a deterministic source mapping for each
  populated candidate field.

Provider-specific record keys, RDF terms, person URIs, and mandate URIs remain in
the appropriate mapper, generic source identifiers, or provenance. They are not domain field
names. Field provenance retains the parsed source value and source binding name so a
later slice can create Evidence records backed by the persisted RawDocument. It may
also carry the exact official page URL for that field; Evidence prefers this URL to
the enclosing document index URL.

The Governo mapper can emit several official identifiers and mandates for one
candidate when the same person has several official pages. It maps only explicit
structured or semantic page facts. Missing birth data and profession remain null;
free-form biography text is not interpreted as a domain claim.

## Politician

`Politician` is the stable canonical identity of one person. It stores an internal
ID, canonical given and family names, a deterministic normalized-name key, birth
date, and an optional pointer to the current PoliticianVersion.

The canonical name and birth date support identity matching before a public version
exists. Mutable public-profile fields do not live directly on Politician.

## PoliticianSourceIdentifier

Official identifiers use a generic link table rather than source-specific columns.
Each row links a Politician to a Source and an opaque identifier value. The pair of
Source and value is unique, so one official identifier cannot identify multiple
Politicians. The same Politician can hold separate Senato, Camera, and Governo
identifier rows.
The model deliberately does not constrain `(politician_id, source_id)`, so historical
or otherwise legitimate multiple identifiers from one authority remain possible.
Identifiers are appended, never silently replaced.

## PoliticianVersion

`PoliticianVersion` is an immutable, ordered snapshot belonging to one Politician.
It stores a positive version number, profile schema version, source-independent JSON
profile data, creation time, and optional publication time. A uniqueness constraint
prevents duplicate version numbers for one Politician.

Normal SQLAlchemy updates to an existing version raise an immutable-version error.
The Politician's nullable `current_version_id` identifies the active version. New
versions are created only by PublishService after approval.

The JSON snapshot is validated at application boundaries with the
`PoliticianVersionProfile` schema. It contains public identity and profile fields but
excludes source identifiers and CandidateProfile provenance.

## PoliticianVersionCitation

`PoliticianVersionCitation` is the immutable, public-safe citation snapshot for one
PoliticianVersion. PublishService creates it from the approved draft's Evidence in
the same transaction as the version. Each row contains only:

- source-independent profile field path;
- readable Source name;
- public source URL;
- source field name.

It deliberately excludes draft and RawDocument IDs, storage keys, hashes, source
record identifiers, source values, extraction/debug metadata, reviewer identity,
and review notes. A uniqueness constraint prevents duplicate public projections for
one version, while service-level sorting makes output deterministic. Updates and
deletes through the ORM raise an immutability error.

Existing PoliticianVersions need no backfill. If a legacy version has no citation
rows, the public API returns an empty list and never infers citations from newer
Evidence.

When publishing an update, unchanged-field citations are copied from the baseline
version. Citations whose field path is changed by the draft are replaced with the
new Evidence projection. Consequently one immutable version may cite multiple
official Sources without merging their names or silently selecting an authority.

## Matching lifecycle

MatchingService is read-only and applies these rules in order:

1. exact Source key and official identifier value;
2. exact normalized name and birth date;
3. uncertain when either method resolves to multiple Politicians;
4. new when nothing matches or birth date is unavailable for fallback.

Matching never creates Politicians, attaches identifiers, creates versions, or
commits a transaction.

## Identity attachment lifecycle

`CandidateIdentityCoordinator` composes matching with the separate
`PoliticianIdentityService`. It invokes the write service only for one unique
`MatchedResult` produced by exact official identifier matching or normalized full
name plus exact birth date. New and uncertain results produce no writes.

The identity service transaction validates that the Politician and Source exist,
that every identifier authority matches the CandidateProfile's source document,
that the candidate still resolves to the same Politician, and that no identifier is
owned by another Politician. Existing ownership by the same Politician returns
`already_exists`; a new row returns `attached`. Conflicts and database integrity
errors roll back the whole operation and expose a typed service error.

The explicit profile-draft orchestration uses this coordinator before DraftService.
This means a Camera record that first matches a Senato-created identity by name and
birth date gains its Camera identifier before the draft proceeds. Future Camera
matching then uses the exact identifier. MatchingService remains write-free;
orchestration may append the safely resolved identifier.

## IdentityResolutionCase

`IdentityResolutionCase` is the durable manual boundary for candidates that cannot
be linked safely. It is created for an `uncertain` match or for
`insufficient_fallback_identity`; a complete `no_match` candidate remains eligible
for the existing explicit bootstrap flow.

Each case stores:

- the supporting RawDocument and Source;
- a primary official source identifier;
- the exact official display name;
- the complete validated CandidateProfile JSON snapshot;
- the original typed MatchingResult JSON;
- status, creation/update timestamps, and terminal resolution audit fields;
- an optional resolved Politician.

The case statuses are `pending`, `resolved_existing`, `resolved_new`, and `ignored`.
Only `pending` may transition, and every terminal status records the trusted reviewer
and resolution time. Existing/new resolutions require a Politician; ignored cases
must not reference one. Database checks enforce those combinations.

Snapshot fields are immutable after insertion. Status and terminal audit fields are
the only values changed by resolution. The unique `(source_id, source_identifier)`
constraint is the idempotency guard. For a candidate with several identifiers, the
lexically first distinct identifier belonging to the document Source is the case
key; the snapshot retains all identifiers and a resolution attaches all of them.

Same-normalized-name Politicians are exposed as editorial suggestions only. The
query may also retain IDs from the original uncertain result and annotate exact
birth/identifier signals. It performs no mutation and never feeds a name-only result
back into MatchingService.

`resolve_to_existing` and `resolve_as_new` call the same source, ownership, and
conflict validation primitive used by PoliticianIdentityService. The caller-owned
transaction includes every identifier attachment, any new Politician, and the case
transition. An integrity or ownership conflict rolls everything back and leaves the
case pending. `ignored` attaches nothing and creates no Politician.

## Bootstrap lifecycle

`RawDocumentCandidateRebuilder` reconstructs CandidateProfiles from the persisted
structured records of an explicitly selected, successfully parsed RawDocument (or
the latest successful one for a selected source). The rebuilt objects stay
transient. Per-record mapping failures become invalid report entries.

`PoliticianBootstrapService` first validates and matches the entire candidate set
without writing. Its report contains aggregate counts and per-record entries for
new, matched, uncertain, and invalid cases. Missing source identifiers, unknown
source authorities, invalid canonical names, duplicate identifiers within the input
batch, and a `new` result caused by missing birth data are invalid. The last rule
prevents bootstrap from creating a duplicate when deterministic fallback identity
is incomplete. Any invalid or uncertain entry prevents apply.

For a safe plan, apply creates one Politician and its PoliticianSourceIdentifier
rows for every new candidate in one transaction. It creates no PoliticianVersion.
Matched candidates are skipped. The database uniqueness constraint on Source and
identifier value makes reruns idempotent and protects against a conflicting write
between planning and apply; any failure rolls back the full batch.

## ProfileDraft

`ProfileDraft` is a persisted proposal belonging to one Politician. It stores:

- `initial` or `update` kind;
- nullable baseline PoliticianVersion for initial proposals;
- the supporting RawDocument;
- the complete proposed `PoliticianVersionProfile` JSON;
- the deterministic typed diff JSON;
- an optional link to the newest draft it supersedes;
- status and timestamps.

The status enum is `pending`, `in_review`, `approved`, `rejected`, `superseded`, or
`failed`. DraftService creates `pending` drafts and supersedes unresolved proposals.
ReviewService can move a pending draft into review or reject a pending/in-review
draft. PublishService can approve only a pending/in-review draft. Failures roll back
instead of leaving partial `failed` rows.

If there is no current version, the proposal is initial and its baseline is null.
If there is a current version, that immutable snapshot is the update baseline. A
candidate equal to the baseline produces no draft. Approval creates a new version;
it never updates an existing version.

## Evidence

`Evidence` belongs to one ProfileDraft and records field-level provenance:

- source-independent proposal field path;
- RawDocument and source URL;
- official source record identifier;
- original source field name and value;
- extraction method (`deterministic` in this slice);
- creation time.

Candidate paths such as `identity.given_name` and `profile.profession` become
`given_name` and `profession`. Senato, Camera, and Governo field names remain source metadata rather than
domain field names. A mandate collection change can have several Evidence rows,
one for each source-backed mandate field.

If official sources disagree, the incoming value is represented normally in the
CandidateProfile and its difference from the current version is persisted only as a
reviewable draft with source-specific Evidence. No model or service assigns an
automatic priority between official sources.

DraftService validates complete evidence coverage before any database mutation.
It does not invent evidence for absent values, so a removal without explicit
absence provenance is rejected safely.

## Draft supersession and transaction

For a meaningful, fully supported proposal, every existing `pending` or `in_review`
draft for the Politician becomes superseded. The new draft points to the newest of
those older drafts. Approved, rejected, already superseded, and failed drafts are
untouched.

Supersession, new-draft insertion, and all Evidence inserts share one explicit
transaction. An insertion failure rolls the entire operation back. The service rule
prevents ordinary competing active drafts; a portable database constraint for
concurrent active-draft creation remains future work.

## Review

`Review` is the immutable final human/editor decision for one ProfileDraft. It
stores a unique draft reference, opaque reviewer identity, `approved` or `rejected`
decision, optional note, and creation time. A unique constraint permits at most one
final Review per draft.

Entering `in_review` is temporary workflow state and does not create a Review row.
The allowed transitions are:

- `pending` to `in_review`;
- `pending` or `in_review` to `rejected` through ReviewService;
- `pending` or `in_review` to `approved` through PublishService.

Approved, rejected, superseded, and failed drafts are terminal for this workflow.
Repeating or contradicting a final decision creates no additional record.

## Publication and stale drafts

PublishService validates the complete proposed profile and creates a new immutable
PoliticianVersion. An initial draft can be approved only while
`Politician.current_version_id` remains null. An update draft can be approved only
while that pointer exactly equals its `baseline_version_id`. Stale drafts remain
unmodified and receive no successful Review.

The next version number is `MAX(version_number) + 1` for that Politician. The unique
per-politician version constraint protects the sequence from duplicate numbers.
Review creation, version and citation insertion, current-pointer update, and the
approved draft status share one transaction. A citation failure rolls back every
publication write. Rejection similarly commits its Review and rejected status
together but never creates a version or changes the current pointer.
