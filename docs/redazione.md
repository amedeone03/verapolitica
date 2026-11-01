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

## The feed (Home)

The public Home is now only the redazione's timeline: published news, newest
first, one card each. The editor composes the card in the news editor
("La card nel feed"), with a live preview:

| Card part | Field in the editor |
| --- | --- |
| Coloured band | Tipo: Notizia, Disegno di legge del Governo, Proposta di legge, Decreto-legge, Votazione in Aula, Interrogazione, Referendum (red), Promessa (green), Elezioni |
| Badge · date | Etichetta (suggestions: Nuova pubblicazione, Approvato, Respinto, Scade oggi…), colour, date |
| Text on the right | Testo a destra (e.g. «Aperto il 1 aprile 2026») |
| Politicians with a round photo | Up to three, picked from the profiles in the archive (search by name): name and current party come from the profile, free names are not accepted. The photo is uploaded from the computer, cropped to a circle in the console and saved as a 320×320 JPEG (max 400 KB, credit required), or the profile's portrait is used |
| Parties involved | Chips: the politicians' parties are included automatically; other parties are picked from the list |
| Institution | Ente o istituzione |
| Title, summary | Titolo and Sommario of block 0 |
| Iter strip | Optional: first chamber, current step (Camera/Senato, Senato/Camera, Navetta, Gazzetta Ufficiale), state, step text, date |
| External button | Optional label and link (e.g. «Leggi su senato.it») |

Readers filter the timeline with «Per te / Nazionale / La tua zona / Salvati»;
the bookmark saves a post in their browser only. «Info» opens the post with
its nine blocks, «Fonti» lists the sources, «Chiedi» opens Ask VeraPolitica.
There are no support/oppose buttons: VeraPolitica does not collect opinions.

Images are stored in `editorial_images` (migration `c2f4e8a17b93`) and served
at `/media/{id}`; each upload is logged.

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

## Partiti e territori (loghi e stemmi)

Sezione **Partiti e territori** della console (`#/simboli`):

- **Partiti**: l'elenco viene dai dati parlamentari e da quello che aggiunge la redazione. «Aggiungi un partito» chiede nome ufficiale, sigla, sito e una fonte https (statuto, registro dei partiti, sito); il partito entra nell'elenco solo dopo l'approvazione di un'altra persona. La registrazione del cittadino mostra tutti i partiti dell'elenco (`/political-parties?all=true`).
- **Regioni e province**: vengono da ISTAT (`scripts/run_territorial_ingestion.py territories --live`). Le province sono le sigle presenti nell'elenco dei comuni.
- **Loghi e stemmi**: si caricano dalla console (PNG, JPEG o WebP, adattati senza ritaglio in un quadrato trasparente) con titolare, licenza (pubblico dominio, CC0, CC BY, CC BY-SA, uso autorizzato, stemma istituzionale) e pagina di provenienza. Ogni logo è una proposta nella coda: diventa pubblico solo quando lo approva un'altra persona (tabella `editorial_symbols`), e tutto finisce nel registro.
- **Sincronizzazione**: `scripts/sync_reference_data.cmd` (Windows, serve internet) carica tutte le regioni, province e comuni da ISTAT, poi `scripts/sync_symbols.py` cerca su Wikidata il logo (P154) o lo stemma (P94) di ogni partito, regione e provincia e lo scarica da Wikimedia Commons **solo se la licenza è libera**. I loghi arrivano in coda firmati «Sincronizzazione Wikidata»: nessuno è pubblico finché la redazione non li approva. Con `--dry-run` mostra le corrispondenze senza scrivere nulla.
- **Dove compaiono**: chip dei partiti e delle zone nella registrazione, riepilogo «La tua scheda», card del feed (accanto al partito della persona e nella riga «Anche»), composer della card in console, Profilo. I partiti seguiti dal lettore si riallineano all'elenco della redazione a ogni apertura (nome, sigla, logo; un partito rimosso sparisce).
