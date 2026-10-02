# MVP ingestion data model

The implemented slices persist the official source and every collected response,
then map changed Senato records to transient CandidateProfiles. Stable politician
identities can be explicitly bootstrapped from a selected parsed document. The
implementation can persist reviewable profile drafts and field-level Evidence, but
only an explicit final Review can reject a draft or publish a new version.

## Source

`Source` identifies one configured official provider.

- `id`: internal primary key
- `key`: stable application key (`senato-repubblica`)
- `name`: human-readable institution name
- `base_url`: official provider URL
- `is_enabled`: whether collection is enabled
- `created_at`: creation timestamp

One Source has many RawDocuments.

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
a RawDocument's normalized data changed and is never persisted.

It separates:

- identity-like matching inputs: name, birth data, and generic source identifiers;
- versioned profile data: gender, profession, URLs, and political mandates;
- provenance: the RawDocument snapshot plus a deterministic source mapping for each
  populated candidate field.

Senato-specific record keys, RDF terms, person URIs, and mandate URIs remain in the
Senato mapper, generic source identifiers, or provenance. They are not domain field
names. Field provenance retains the parsed source value and source binding name so a
later slice can create Evidence records backed by the persisted RawDocument.

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
Politicians. Future Camera identifiers can use the same structure as Senato URIs.

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

## Matching lifecycle

MatchingService is read-only and applies these rules in order:

1. exact Source key and official identifier value;
2. exact normalized name and birth date;
3. uncertain when either method resolves to multiple Politicians;
4. new when nothing matches or birth date is unavailable for fallback.

Matching never creates Politicians, attaches identifiers, creates versions, or
commits a transaction.

## Bootstrap lifecycle

`RawDocumentCandidateRebuilder` reconstructs CandidateProfiles from the persisted
structured records of an explicitly selected, successfully parsed RawDocument (or
the latest successful one for a selected source). The rebuilt objects stay
transient. Per-record mapping failures become invalid report entries.

`PoliticianBootstrapService` first validates and matches the entire candidate set
without writing. Its report contains aggregate counts and per-record entries for
new, matched, uncertain, and invalid cases. Missing source identifiers, unknown
source authorities, invalid canonical names, and duplicate identifiers within the
input batch are invalid. Any invalid or uncertain entry prevents apply.

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
`given_name` and `profession`. Senato field names remain source metadata rather than
domain field names. A mandate collection change can have several Evidence rows,
one for each source-backed mandate field.

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
Review creation, version insertion, current-pointer update, and the approved draft
status share one transaction. Rejection similarly commits its Review and rejected
status together but never creates a version or changes the current pointer.
