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

Future, unimplemented stages remain:

```text
CandidateProfile -> MatchingService -> DiffService
  -> ProfileDraft + Evidence -> Admin review -> Review
  -> immutable PoliticianVersion -> Public API
```

No LLM, version creation, draft, review, publishing, or API behavior is part of the
bootstrap path.
