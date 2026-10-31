# Redazione console (`/redazione`)

The redazione decides what the citizen sees. The console is the only editorial
path for the demo: profiles, promises and their status (which drive the
score), news and withdrawals are written there, verified by a second person
and logged.

## Access

Each member signs in with their own token, configured as
`VERAPOLITICA_REDAZIONE_MEMBERS="Nome Cognome=token;Nome Cognome=token"`.
On a local demo with nothing configured, three demo members are offered on the
sign-in page:

| Member | Token |
| --- | --- |
| Redattore demo | `demo-redattore` |
| Verificatore demo | `demo-verificatore` |
| Caporedattore demo | `demo-caporedattore` |

Production refuses demo tokens and tokens shorter than 24 characters. The
console is not linked from the public site and is `noindex`.

## Sections

| Section | What it does |
| --- | --- |
| Da verificare | Everything waiting for a second person: profile blocks, promises, proposals, promise statuses, news, withdrawals and re-classifications. The verifier ticks the final checklist of the writing models, then approves or rejects (a rejection needs a note). |
| Politici | The "Modello Politico" in blocks 0–6: scheda rapida (from the official import), Chi è, Cosa ha fatto, Posizioni, Promesse (with status and classification), Procedimenti, Notizie collegate e fonti. |
| Notizie | The "Modello Notizia" in nine blocks with live checks: word counts, right/left balance, sources from both sides plus an institutional or agency source. |
| Registro modifiche | The append-only log: who, when, what, with before/after details. |
| Regole | The eight rules, the conventions and the checklist. |

## Rules enforced by code

Blocking (the item cannot be approved):

- the author approves their own work;
- open `[square brackets]` in the text;
- a missing source, or a source that is a home or section page;
- a position without a date, a career entry without a start date;
- a news item without at least three sources, one institutional or agency,
  one centre-right and one centre-left outlet, or with an empty "Il fatto",
  "Cosa cambia", "Destra" or "Sinistra" block;
- "Non mantenuta" without a reason (deadline passed, mandate ended, explicit
  renunciation), or with a declared deadline that is not before the fact.

Warnings (the verifier decides): lengths outside the guide, right/left
imbalance in words or points, loaded title words, judgements, unattributed
opinions, short dates such as «16/9».

## What reaches the citizen

- Published profile blocks, promises, statuses and news appear at once in the
  public app (`/app`). The profile shows «Aggiornato al … · Redattore … ·
  Verificatore …» and «Notizie collegate».
- A news item written in the console is shown in its nine blocks, with sources
  and the names of writer and verifier.
- The scorecard counts only promises that are published, classified and have
  an approved status (see `docs/scoring-methodology.md`, section 2.1).
- Published content is never rewritten: a correction is a new version that is
  verified again; a withdrawal is a change request approved by another member.

## API

`/redazione/api/*`, bearer token of a member. Main routes: `GET /coda`,
`POST /coda/{kind}/{id}/approva|rifiuta`, `GET /politici/{id}`,
`POST /politici/{id}/blocchi/{kind}`, `POST /politici/{id}/promesse`,
`POST /promesse/{id}/stato`, `POST /promesse/{id}/classificazione`,
`POST /contenuti/{kind}/{id}/ritira`, `GET|POST /notizie`, `PUT /notizie/{id}`,
`GET /registro`.

## What was removed

The English walkthrough at `/demo/` (Luca Bianchi), `/demo/video`,
`/demo/pledge-review` and `/demo/profile-review` are replaced by the console;
`/demo/` redirects to `/redazione/`. The AI draft tool (`/demo/ai-upload`)
stays, in the same colours; its approvals are written to the same log.
