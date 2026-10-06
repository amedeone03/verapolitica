# Civic features

VeraPolitica publishes editorially reviewed civic facts: referendum questions and
dates, how-to-vote guidance, a civic glossary, and an internal reminder foundation.

This milestone does not send email, SMS, or push. It does not recommend how to vote.
It does not scrape Eligendo’s undocumented browser API.

## Official sources researched

Used for canonical facts:

- Ministero dell’Interno news and electoral pages (`interno.gov.it`)
- DAIT election area and FAQ (`dait.interno.gov.it/elezioni`)
- DAIT FAQ. Referendum 2026 (17 March 2026)
- Senate Constitution pages, especially Articles 49, 60, 64, 70, 71, 75, 77, 138

Not used as canonical sources: Wikipedia, newspapers, party campaign pages, social
media, or undocumented `eleapi.interno.gov.it` JSON.

Eligendo Archivio / Eligendo results exist as official *presentation* systems. They
are HTML-first. Third-party tools reverse-engineer an undocumented JSON API. That is
not a stable live collector for VeraPolitica.

## Referendum source selected

Editorial/manual JSON fixture mapped by `map_referendum_fixture`.

- Historical official sample: March 2026 constitutional referendum, curated from the
  DAIT FAQ (question, dates, hours, no participation quorum).
- Demo upcoming record: clearly synthetic (`is_synthetic=true`).

Live HTML collection is not implemented.

## Domain

`Referendum` is the stable row. Identity is `ReferendumSourceIdentifier`
`(source_id, official_identifier)`, never title. Geographic scope is
`national` / `region` / `municipality` with optional Region/Municipality FKs.

`ReferendumDraft` + `ReferendumEvidence` + `ReferendumReview` follow the proposal
review shape. Ingestion never sets `published_at`. Approval copies official fields
onto the public row.

`VotingGuide` stores structured sections (`eligibility`, `date_and_hours`,
`required_documents`, `ballot_instructions`, `quorum`, `accessibility`,
`official_links`) with guide-level and section-level official URLs.

`GlossaryTerm` is manually curated, slug-keyed, alphabetically listed.

`NotificationSubscription` is an internal placeholder (`channel=internal`, opaque
`destination_token`, no email). `NotificationReminderCandidate` is the idempotent
reminder row produced by the `civic-reminders` job.

## Neutrality

No party positions, campaign arguments, recommendations, popularity ranking, or
news. Synthetic records must remain labelled as demo-only in public JSON and UI.
