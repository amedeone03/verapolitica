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

You need **at least two named people**. One person cannot approve their own
work, so a single token leaves every draft stuck in **Da verificare**.

### Admin

`VERAPOLITICA_REDAZIONE_ADMINS="Nome Cognome;Altro Nome"` names the admins
(names must match `VERAPOLITICA_REDAZIONE_MEMBERS`; unknown names are ignored;
`VERAPOLITICA_REDAZIONE_LEADS` is the old name and still works).

- An admin writes and publishes at once: politicians, scheda blocks, promises,
  news, parties, photos. The log records `self_verified: true`.
- Everyone else saves and the item waits in **Da fare** until an admin
  publishes or rejects it (with a note the author sees on their home).
- With no admin named, any second member publishes (the old four-eyes rule).
- The state of a promise moves the public score and still needs a second person.

On a local demo, **Caporedattore demo** is the admin.

### Foto e loghi

The photo of a new politician goes in the «Nuovo politico» form, the logo of a
new party in the «Nuovo partito» form: file, credit (e.g. «Camera dei
deputati»), optional source link. An existing scheda has «Aggiungi/Cambia la
foto» in its first block. Nothing is fetched from Camera, Senato or Governo.

### Notizie locali

A news item is national, regional, provincial or about one comune: pick the
region from the list or search the comune by name.

### Procedimenti giudiziari e controversie

Two separate boxes on the scheda:

- **Procedimenti giudiziari**: only investigations and trials *against the
  politician* (types «Indagine a suo carico», «Processo a suo carico»);
- **Controversie**: matters of public interest that do not necessarily put the
  politician under investigation — a statement, a bust, a relative or
  collaborator under investigation («Indagine su una persona vicina»).

The console refuses an investigation of the politician among the controversies
and a controversy among the proceedings. Existing rows were sorted by the
migration `f3a7c9d21b48`: anything with an investigation or trial against the
politician stays a proceeding.

### Territori (Regione, Provincia, Comune)

**Territori** in the console opens one scheda per regione, provincia and comune,
written with the «Modelli di scrittura»:

- **Regione** (Modello Regione): Scheda rapida, Il presidente, La giunta,
  Il consiglio regionale, Promesse del mandato, Elezioni, then Notizie regionali
  and Fonti.
- **Comune** (Modello Città): Scheda rapida, Il sindaco, La giunta, Consiglio e
  opposizione, Promesse del mandato, Elezioni (storico e prossime), then Notizie
  locali and Fonti.
- **Provincia** (the same rules, with the blocks a province has): Scheda rapida,
  Il presidente, Il consiglio provinciale, Elezioni, then Notizie and Fonti.

The **official base** (ISTAT names and counts, presidents and mayors from the
DAIT registry) sits at the top of every scheda and is read-only: it is the
reference every block is written against. Every block can always be rewritten,
also after publication: each save is a new version (`territory_blocks`, migration
`b4e1d7c93a52`), an admin publishes it at once or publishes another member's
version, and the new version replaces the published one. Open `[parentesi]`, a
missing source, a population without its year, a promise without a source or a
«Non mantenuta» without the fact are errors that block publication.

On the public site the schede live in **Politica** (`?region=`, `?province=`,
`?municipality=`); the history of a region or province stays in the Archivio
(`?history_region=`, `?history_province=`). The public API is
`GET /territories/{region|province|municipality}/{id or sigla}`.

### Production VPS

On the server, generate one token per editor (do not reuse the admin key):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the names and tokens in `/opt/verapolitica/repo/.env.production` (mode
`0600`, never commit the file):

```bash
VERAPOLITICA_REDAZIONE_MEMBERS="Nome Cognome=<token1>;Altro Nome=<token2>"
```

Recreate **only** `web` so Compose reloads the env file. Do not
`docker compose down -v` and do not start the scheduler:

```bash
cd /opt/verapolitica/repo
./scripts/run_production_compose.sh up -d web --force-recreate
```

Each editor opens `https://verapolitica.com/redazione/`, pastes their own
codice, writes a notizia, and the other person approves it. Published news
then appears on the public home at `/app/`. Give tokens out of band.

## Sections

| Section | What it does |
| --- | --- |
| Da verificare | Everything waiting for a second person: profile blocks, promises, proposals, promise statuses, news, withdrawals and re-classifications. The verifier ticks the final checklist of the writing models, then approves or rejects (a rejection needs a note). A pending or rejected news draft can be deleted by any member (`Elimina la notizia`); a published news item cannot. |
| Politici | The "Modello Politico" in blocks 0–6: scheda rapida (from the official import), Chi è, Cosa ha fatto, Posizioni, Promesse (with status and classification), Procedimenti, Notizie collegate e fonti. **Aggiungi un politico** proposes a new public identity (name, official https source, optional Governo office); another member must approve it. |
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
  "Cosa cambia", "Destra" or "Sinistra" block. A card typed
  **Pubblicazione ufficiale** is the exception: it only announces an official
  list (governo.it, Camera, Senato) and needs that institutional page, not
  newspaper sources;
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
- Published content is never rewritten or deleted: a correction is a new
  version that is verified again; a withdrawal is a change request approved
  by another member. Pending or rejected news drafts can be removed from the
  queue (`DELETE /notizie/{id}`); the action is logged.

## API

`/redazione/api/*`, bearer token of a member. Main routes: `GET /coda`,
`POST /coda/{kind}/{id}/approva|rifiuta`, `GET /politici/{id}`,
`POST /politici` (new identity, second-person approval), `POST /politici/{id}/blocchi/{kind}`, `POST /politici/{id}/promesse`,
`POST /promesse/{id}/stato`, `POST /promesse/{id}/classificazione`,
`POST /contenuti/{kind}/{id}/ritira`, `GET|POST /notizie`, `PUT /notizie/{id}`,
`DELETE /notizie/{id}` (pending or rejected drafts only), `GET /registro`.

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
- **Partiti del Parlamento**: con `--parties` (incluso in `sync_reference_data.cmd`) lo script propone come nuovi partiti quelli dei deputati in carica nella XIX legislatura secondo Wikidata (fonte: la scheda Wikidata). Restano proposte finché la redazione non le approva; i loghi di questi partiti arrivano rilanciando lo script dopo l'approvazione.
- **Scheda Meloni e una promessa**: `python -m scripts.seed_meloni_showcase --author "Amedeo" --approver "Verificatore"` pubblica «Chi è», un incarico del curriculum ufficiale e la promessa sul reddito di cittadinanza dalle dichiarazioni programmatiche. Non assegna uno stato di adempimento senza stralcio ufficiale. Chi scrive e chi approva devono essere due persone diverse.
- **Stato della promessa RDC**: `python -m scripts.seed_rdc_verdict --author "Amedeo" --approver "Verificatore"` assegna «mantenuta» copiando lo stralcio della legge 85/2023 già in `data/fixtures/pledge_evidence/legge_85_2023_assegno_inclusione.html`.
- **Schede Schlein e Conte**: `python -m scripts.seed_opposition_showcase --author "Amedeo" --approver "Verificatore"` pubblica solo URL completi già in archivio (A.C. 1741 per Schlein; Treccani e scheda Senato per Conte).
- **Partito sulla scheda**: `python -m scripts.seed_party_affiliations` scrive l'affiliazione esplicita (Meloni→FdI, Schlein→PD, Conte→M5S) se la persona e il partito sono già pubblici. I gruppi parlamentari non bastano.
- **Una notizia a quattro occhi**: `python -m scripts.seed_official_notizia --author "Amedeo" --approver "Verificatore"` pubblica un Modello Notizia con tre fonti già in archivio (resoconto Senato, Sky TG24, Il Fatto Quotidiano).
- **Coda identità**: sezione **Identità** della console (`#/identita`). I casi Governo e DAIT senza data di nascita arrivano qui. Chi decide è il membro della redazione, non la chiave admin.
- **Gruppi parlamentari**: dopo l'ingest Camera/Senato, `python -m scripts.reprocess_parliamentary_groups --apply` riallaccia i gruppi dal bundle SPARQL già in archivio, senza scaricare di nuovo.
- **Foto dei politici**: le carica la redazione in **Partiti, territori e foto → Foto dei politici** (`#/simboli/politician`), con autore, licenza e pagina di provenienza; diventano pubbliche solo dopo l'approvazione di un secondo membro. Il sito non prende né collega foto da Camera, Senato o Governo, nemmeno se l'indirizzo è sulla scheda. Le foto già salvate in `data/…/portraits` restano finché la redazione non le sostituisce.
- **Zona sotto Roma**: con i territori ISTAT importati, la scheda della regione Lazio elenca tutti i comuni (Roma in testa). `attach_territorial_identities --apply` collega i sindaci DAIT già in archivio; `publish_territorial_profiles --region Lazio` pubblica le bozze. Il presidente regionale compare solo se esiste un mandato ufficiale: non viene inventato.
- **Demo live (senza reset)**: `python -m scripts.prepare_live_demo --author "Amedeo" --approver "Verificatore"` esegue partiti, gruppi, attacco Governo/DAIT, schede Meloni/Schlein/Conte, affiliazioni, stato RDC, feed ufficiale, notizia a tre fonti e bozze territoriali del Lazio. Non cancella il database.
- **Registrazione senza elenchi**: se partiti o regioni non sono ancora caricati, la registrazione lo dice e lascia proseguire; zona e partiti si impostano poi dal Profilo.
- **Partiti del Governo e dell'opposizione**: `scripts\seed_government_parties.cmd` inserisce Fratelli d'Italia, Lega per Salvini Premier, Forza Italia, Noi Moderati, Partito Democratico, Movimento 5 Stelle e Alleanza Verdi e Sinistra (dati Wikidata: nome, sigla, sito, logo). AVS è un'alleanza elettorale, non solo un partito Q7278. Passano dal flusso normale (proposta «Sincronizzazione Wikidata», approvazione «Direzione VeraPolitica»), quindi compaiono nel registro e in Registrati. Un logo senza licenza libera su Commons non viene scaricato: la redazione carica il file ufficiale dalla console.
- **Modifiche**: ogni partito ha «Modifica» (nome, sigla, sito, rimozione del logo, con il motivo) e «Sostituisci logo». Le modifiche si applicano quando le approva un'altra persona.
- **Dove compaiono**: chip dei partiti e delle zone nella registrazione, riepilogo «La tua scheda», card del feed (accanto al partito della persona e nella riga «Anche»), composer della card in console, Profilo. I partiti seguiti dal lettore si riallineano all'elenco della redazione a ogni apertura (nome, sigla, logo; un partito rimosso sparisce).
