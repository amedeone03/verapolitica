# Architecture

The implemented path is deterministic:

```text
Senato official source
  -> collector
  -> persisted RawDocument
  -> parser
  -> canonical normalized hash and change detection
  -> transient CandidateProfiles when changed
```

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
  Review + new PoliticianVersion + current-version pointer + status
  committed in one transaction
```

A Review is the immutable final decision, so each draft has at most one Review.
PublishService is the only approval and version-creation path. Before any writes it
locks the draft and Politician where supported, validates the proposed profile, and
checks the baseline. An initial draft is current only while the Politician has no
version. An update draft is current only while its baseline ID exactly matches the
Politician's current-version ID.

Version numbers are assigned per Politician as the existing maximum plus one. The
database uniqueness constraint on `(politician_id, version_number)` and the unique
Review per draft are final conflict guards. Any approval failure rolls back the
Review, version, pointer, and draft status together.

Future, unimplemented stages remain:

```text
immutable PoliticianVersion -> Admin API -> Public API
```

No API, authentication UI, LLM, scheduling, or background-worker behavior is part
of the review and publication path.
