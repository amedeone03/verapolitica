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
- **Gruppi parlamentari**: dopo l'ingest Camera/Senato, `python -m scripts.reprocess_parliamentary_groups --apply` riallaccia i gruppi dal bundle SPARQL già in archivio, senza scaricare di nuovo.
- **Ritratti del Governo**: `python -m scripts.seed_official_portraits` scrive i ritratti istituzionali già presenti sulle schede pubblicate (`image_url` di governo.it).
- **Zona sotto Roma**: con i territori ISTAT importati, la scheda della regione Lazio elenca tutti i comuni (Roma compresa). `publish_territorial_profiles --region Lazio` pubblica le bozze sindaco già in coda. La card ISTAT del Lazio entra nel feed locale.
- **Demo live (senza reset)**: `python -m scripts.prepare_live_demo --author "Amedeo" --approver "Verificatore"` esegue partiti, gruppi, scheda Meloni, ritratti, feed ufficiale e bozze territoriali del Lazio. Non cancella il database.
- **Registrazione senza elenchi**: se partiti o regioni non sono ancora caricati, la registrazione lo dice e lascia proseguire; zona e partiti si impostano poi dal Profilo.
- **Partiti del Governo e dell'opposizione**: `scripts\seed_government_parties.cmd` inserisce Fratelli d'Italia, Lega per Salvini Premier, Forza Italia, Noi Moderati, Partito Democratico, Movimento 5 Stelle e Alleanza Verdi e Sinistra (dati Wikidata: nome, sigla, sito, logo). AVS è un'alleanza elettorale, non solo un partito Q7278. Passano dal flusso normale (proposta «Sincronizzazione Wikidata», approvazione «Direzione VeraPolitica»), quindi compaiono nel registro e in Registrati. Un logo senza licenza libera su Commons non viene scaricato: la redazione carica il file ufficiale dalla console.
- **Modifiche**: ogni partito ha «Modifica» (nome, sigla, sito, rimozione del logo, con il motivo) e «Sostituisci logo». Le modifiche si applicano quando le approva un'altra persona.
- **Dove compaiono**: chip dei partiti e delle zone nella registrazione, riepilogo «La tua scheda», card del feed (accanto al partito della persona e nella riga «Anche»), composer della card in console, Profilo. I partiti seguiti dal lettore si riallineano all'elenco della redazione a ogni apertura (nome, sigla, logo; un partito rimosso sparisce).
