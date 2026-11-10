# Design system — Cambridge Classic v1.0

The public app (`frontend/app/`) is static HTML, one stylesheet and one ES module
served by FastAPI. The design system keeps that architecture: no framework, no
build step, no runtime dependency.

## Files

| File | Role |
| --- | --- |
| `frontend/app/styles.css` | Tokens (`:root`), base, components, responsive rules. Rewritten from scratch; no other stylesheet. |
| `frontend/app/fonts/` | Self-hosted variable WOFF2, Latin subset: Inter (~50 KB) for UI and body; Source Serif 4 (~120 KB) for display titles (H1, wordmark). Both OFL. |
| `frontend/app/LICENSE-lucide.txt` | Licence of the inlined Lucide icons (ISC). |
| `frontend/app/og-image.png` | 1200×630 social sharing image (wordmark and existing tagline only). |
| `frontend/app/index.html` | Header, accessible mobile menu, home hero, navy footer, metadata. |
| `frontend/app/app.js` | `icon()` helper, mobile menu, per-view description and canonical URL. |
| `backend/app/api/public/site.py` | `/robots.txt`, `/sitemap.xml` (uses `VERAPOLITICA_PUBLIC_BASE_URL`). |
| `backend/app/core/middleware.py`, `backend/app/main.py` | Gzip for text responses; one-year immutable cache for `/app/fonts/`. |

The redazione console (`frontend/redazione/`) and the AI draft pages
(`frontend/demo/styles.css`) use the same tokens and self-hosted fonts.

## Tokens

Colours, fonts, radii (4–16 px), spacing scale (4–128 px) and transitions are CSS
custom properties in `styles.css`. Additions to the specification:

| Token | Value | Why |
| --- | --- | --- |
| `--color-background` | `#F4EFE6` | Paper page, warmer than the original mint grey. Ink `#1A1F24` is 14.5:1 on it. |
| `--color-surface` | `#FFFCF7` | Cream cards. |
| `--color-border` | `#D9D0C4` | Warm hairline. |
| `--color-accent-strong` | `#2F6B4F` | Cambridge green dark enough for text and the active-navigation underline (6.0:1). `#85B09A` is 2.4:1 on white, so it is used only where it is decorative or on navy. |
| `--color-control-border` | `#7D8E8B` | Input, filter and toggle boundaries need 3:1 on cream. |
| `--color-danger` | `#A3261C` | Errors and "non mantenuta", separate from the accent. |
| `--font-display` | Source Serif 4 | H1, wordmark, quotes. Inter remains `--font-heading` and `--font-body`. |
| `--verdict-*` | | Six pledge states. Text on its tint ≥ 4.5:1, marks on white ≥ 3:1; each chip also carries its label, and "iter bloccato" uses an outline/hatch, so state never relies on colour alone. |

Every foreground/background pair in use was measured, not assumed.

## Components

Buttons (`.button-primary`, `.button-secondary`, text links with arrow), header
with underline navigation, modal mobile menu (focus trap, Escape, focus return,
scroll lock, closes when the window grows to desktop width), cards, chips,
filters, verdict chips, source lines, timelines, feed rows, footer.

The header is not sticky (as specified). The profile section navigation is the
only sticky element.

## Measured results

Lighthouse 12.8.2, mobile emulation with default throttling, local server, test
database:

| Page | Performance | Accessibility | Best practices | SEO | LCP | CLS |
| --- | --- | --- | --- | --- | --- | --- |
| Home | 100 | 100 | 100 | 100 | 1.7 s | 0 |
| Profilo politico | 97 | 100 | 100 | 100 | 2.1 s | 0 |
| Archivio | 99 | 100 | 100 | 100 | 1.9 s | 0 |
| Politica | 99 | 100 | 100 | 100 | 2.0 s | 0.03 |
| Profilo (lettore) | 100 | 100 | 100 | 100 | 1.8 s | 0 |

These are lab numbers on a local server, not field data at the 75th percentile.

## Limitations

- No name-hashed assets: `app.js` and `styles.css` are revalidated on every load
  (`Cache-Control: no-cache`) so a release is never served stale. A build step
  with hashed names would allow long caching.
- The canonical URL is set in the browser; crawlers that do not run JavaScript
  see none. `sitemap.xml` lists the canonical URLs.
- Footer placeholders (privacy policy, legal notes, contacts) are marked as such
  until the content exists.
- No font metric overrides: preloading both fonts kept CLS at 0 in the tests.

## Benvenuto, demo e registrazione

- `verapolitica.com/` reindirizza a `/app/`. Alla prima visita (nessun profilo, nessuna sessione, nessun link diretto) l'app mostra la schermata di benvenuto: sfondo navy, logo centrale, in basso **Registrati**, **Accedi** e **Consulta senza account**. Un link condiviso (post, politico…) si apre direttamente, in sola lettura.
- **Consulta senza account**: sola lettura per la sessione del browser. Preferiti, post salvati e zona non si salvano; un avviso invita a registrarsi.
- **Registrazione** (`?view=registrati`): una domanda per schermata — nome → regione e provincia → politici da seguire (si può saltare se l'elenco è vuoto) → partiti (facoltativi) → email → password — poi **Crea l'account**. **Accedi** (`?view=accedi`) è ancora email e password insieme. Chi ha già un account e modifica la scheda dal Profilo resta nel wrap fino a **La tua scheda**. Riferimenti: welcome e onboarding di Spotify (metadati Appllama).
- L'account salva segue, zona e post sul server (cookie HttpOnly). Una copia locale resta sul dispositivo come cache. La scheda descrive solo le scelte del lettore: non c'è classificazione ideologica né indicazione di voto.
- **Per te**: il feed riceve `politicians` e `parties` (massimo 24 id ciascuno) più la zona; mostra le notizie che coinvolgono quei politici (o i loro partiti) e quelle locali della zona. Se non c'è ancora nulla, mostra tutte le notizie e lo dice.
