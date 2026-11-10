"""The public app: logo and profile in the header, Feed / Politica / Archivio / Cerca in a bottom bar."""

from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "frontend" / "app"


def test_bottom_bar_and_header():
    html = (APP / "index.html").read_text(encoding="utf-8")
    header = html.split('<header class="site-header">')[1].split("</header>")[0]
    bottom = html.split('<nav class="bottom-nav"')[1].split("</nav>")[0]
    assert 'class="brand"' in header and 'href="./?view=profile" data-section="profile"' in header
    for section, href in (("home", "./"), ("politics", "./?view=politics"), ("history", "./?view=history"), ("search", "./?view=search")):
        assert html.count(f'href="{href}" data-section="{section}"') == 1
        assert f'href="{href}" data-section="{section}"' in bottom
    assert 'aria-label="Cerca"' in bottom and "<span>Cerca</span>" not in bottom  # magnifier only
    assert "mobile-menu" not in html and "menu-toggle" not in html
    for view in ("home-view", "politics-view", "compare-view", "history-view", "legislature-view",
                 "parliamentarians-view", "provinces-view", "territory-history-view", "profile-view", "post-view"):
        assert f'id="{view}"' in html
    assert '<section id="archive-view" aria-labelledby="archive-title" hidden>' in html
    # The home is only the redazione's timeline.
    assert 'id="feed-choice"' in html and 'class="feed-timeline"' in html
    # No side column: the feed is one timeline.
    assert 'class="feed-rail"' not in html and "Come si scrive" not in html
    choice = html.split('id="feed-choice"')[1].split("</div>\n        </div>")[0]
    labels = [part.split(">", 1)[1].split("<", 1)[0] for part in choice.split('<button type="button" data-feed=')[1:]]
    assert labels == ["Per te", "Nazionale", "Regionale", "Provinciale"]
    assert 'data-feed="saved"' not in html and 'data-feed="local"' not in html
    home = html.split('id="home-view"')[1].split("</section>")[0]
    assert "shortcut-grid" not in home and "home-hero" not in home
    assert "Il tuo profilo." in html
    # Guest consult is read-only; registration/login build the reader's Per te.
    assert 'id="profile-demo"' in html and 'href="./?view=registrati"' in html
    assert 'href="./?view=accedi"' in html
    assert "trust-line" not in html


def test_routes_and_privacy_of_the_reader_profile():
    script = (APP / "app.js").read_text(encoding="utf-8")
    for route in ('view === "politics"', 'view === "history"', 'view === "profile"', 'view === "compare"',
                  "showLegislature(api", "showTerritoryHistory(api", "showArchiveTimeline(api", "showParty(api", "showPost(api"):
        assert route in script
    assert "showHome(api);" in script and "start();" in script
    # Zone and favourites stay in browser storage, wrapped so private mode still works.
    assert 'const PROFILE_KEY = "verapolitica.profile.v1"' in script
    assert "storage?.setItem(PROFILE_KEY" in script
    assert "fetchImpl(path" in script and "PROFILE_KEY" not in script.split("function createPublicApiClient")[1].split("\n}\n")[0]
    # No public scoring method; comparisons stay same-role only.
    assert "non è una media dei punteggi dei suoi esponenti" not in script
    assert "non è distinguibile" in script


def test_cambridge_classic_tokens_fonts_and_accessibility():
    styles = (APP / "styles.css").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    html = (APP / "index.html").read_text(encoding="utf-8")
    for token in ("--color-primary: #0F2747", "--color-secondary: #003C71", "--color-accent: #85B09A",
                  "--color-accent-light: #DCEBE5", "--color-background: #F4EFE6", "--color-border: #D9D0C4",
                  "--color-surface: #FFFCF7", "--color-text: #1A1F24"):
        assert token in styles
    # Self-hosted fonts only: no @import, no third-party font host.
    assert "@import" not in styles and "fonts.googleapis" not in html
    assert (APP / "fonts" / "inter-latin-var.woff2").exists()
    assert (APP / "fonts" / "source-serif-4-latin-var.woff2").exists()
    # Inter for UI and body; Source Serif 4 for display titles (H1, wordmark).
    assert "Source Serif 4" in styles and "source-serif-4-latin-var.woff2" in html
    assert '--font-heading: "Inter"' in styles
    assert '--font-display: "Source Serif 4"' in styles
    assert html.count('rel="preload"') == 2
    # No glow. Translucency only on the floating bottom bar,
    # with a solid fallback when the reader asks for less transparency.
    assert "radial-gradient" not in styles
    assert styles.count(" backdrop-filter: blur") == 1 and "prefers-reduced-transparency: reduce" in styles
    # Feed switcher shows its options directly; every button responds on press.
    assert 'class="feed-segments"' in html and "<select" not in html.split('id="feed-choice"')[1][:200]
    assert ".button:active" in styles
    assert "will-reveal" not in styles and "is-new" not in script
    assert "@media (prefers-reduced-motion: reduce)" in styles
    # Navigation is a bottom bar on every page; no hamburger menu to trap focus in.
    assert ".bottom-nav {" in styles and "bindMobileMenu" not in script
    assert 'class="skip-link"' in html
    # SEO essentials.
    assert 'property="og:image"' in html and "application/ld+json" in html
    assert 'link.rel = "canonical"' in script


def test_politics_section_layout() -> None:
    html = (APP / "index.html").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    view = html.split('id="politics-view"')[1].split('id="compare-view"')[0]
    # Search, government row, parties with logos, tools and topics; no empty tile grid.
    for marker in ('class="politics-search"', 'id="government-row"', 'id="party-list"', 'id="topic-list"', 'id="dossier-list"'):
        assert marker in view
    assert "shortcut-grid" not in view
    assert "api.listParties({ all: true })" in script and "partyLogo(party, 40)" in script
    assert "export function shortRole" in script and "GOVERNMENT_RANK" in script
    assert "export function cabinetMandate" in script and "export function governmentOfficeRank" in script
    assert 'listPoliticians({ role: "governo", limit: 100 })' in script
    assert "export function collectFeaturedPoliticianIds" in script
    assert "export function renderPersonBubble" in script
    assert "export function paintPoliticsFaces" in script
    assert "Profili pubblicati" in script
    assert "listAllMunicipalities" in script
    assert "export async function listAllPoliticians" in script
    assert "renderCurrentLegislatureWalk" in script


def test_proposals_section_layout() -> None:
    html = (APP / "index.html").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    css = (APP / "styles.css").read_text(encoding="utf-8")
    view = html.split('id="proposals-view"')[1].split('id="referendums-view"')[0]
    # Type tabs, topic chips, verdict summary, one grouped list (no card grid).
    for marker in ('class="proposals-tabs', 'data-type="explicit_promise"', 'id="proposal-topics"', 'id="proposal-summary"', 'class="row-list proposal-rows"'):
        assert marker in view
    assert "proposal-grid" not in view
    # A promise row shows its verdict, a bill its institutional status; one tap target per row.
    assert 'renderVerdictChip(proposal.verdict || "not_yet_rated")' in script
    assert "export function renderPromiseSummary" in script and "renderCompositionBar(entries)" in script
    assert "Fonte ufficiale ${icon" not in script.split("export function renderProposalCard")[1].split("export function renderPromiseSummary")[0]
    # Record: verdict panel, exact words, people, timeline, sources.
    detail = script.split("export function renderProposalDetail")[1].split("export function renderPoliticianProposals")[0]
    for marker in ("renderProposalState(proposal)", "Le parole esatte", "Chi l'ha promesso", "Cronologia", "Fonti ufficiali"):
        assert marker in detail
    assert 'bindExplainPledges(byId("proposal-detail"), api)' in script
    assert ".proposals-tabs a:active { transform: scale(.97); }" in css


def test_government_cloud_sizes_by_institutional_role() -> None:
    html = (APP / "index.html").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    css = (APP / "styles.css").read_text(encoding="utf-8")
    assert 'id="government-row" class="authority-cloud"' in html
    assert "Non è un giudizio." in html
    assert "export const AUTHORITY_WEIGHT = [1, 0.78, 0.62, 0.52, 0.42];" in script
    # Portrait, then the party logo (only from a current affiliation), then the name.
    node = script.split("function authorityNode")[1].split("export function packAuthority")[0]
    assert node.index("authority-photo") < node.index("authority-party") < node.index("authority-name")
    assert "person.current_party" in node
    assert "new ResizeObserver" in script and ".authority-cloud.is-static" in css
    assert "@media (prefers-reduced-motion: reduce) { .authority-node" in css
    # Without a cabinet, the same slot shows published profiles (party members, promise actors).
    assert "className = \"people-row\"" in script
    assert "current_members" in script.split("export function collectFeaturedPoliticianIds")[1].split("export function renderPersonBubble")[0]
    assert 'id="government-note"' in html


def test_search_is_grouped_instant_and_keeps_the_lens() -> None:
    html = (APP / "index.html").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    css = (APP / "styles.css").read_text(encoding="utf-8")
    view = html.split('id="search-view"')[1].split('id="organization-detail-view"')[0]
    # The lens stays in the field and in the navigation; no type dropdown.
    assert '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>' in view
    assert 'data-section="search" aria-label="Cerca"' in html
    assert "<select" not in view and 'id="search-clear"' in view and 'id="search-scopes"' in view
    show = script.split("async function showSearch")[1].split("async function showOrganization")[0]
    # Instant (debounced) search, stale answers dropped, grouped by kind with a best match.
    assert "window.setTimeout(() => run(), 220)" in show and "seq !== state.seq" in show and "controller?.abort()" in show
    assert "limit: SEARCH_GROUP_SIZE" in show and "renderSearchGroups(all.groups, query)" in show
    assert "export function bestSearchMatch" in script and "Risultato migliore" in script
    # Recent searches stay on this device and can be removed.
    assert 'SEARCH_RECENT_KEY = "verapolitica.search.recent.v1"' in script
    assert "Restano solo su questo dispositivo." in script and "data-remove-recent" in script
    assert "@keyframes search-shimmer" in css and ".skeleton-line { animation: none; }" in css


def test_region_and_comune_pages_show_their_local_news():
    from pathlib import Path

    script = Path("frontend/app/app.js").read_text(encoding="utf-8")
    assert "async function renderLocalNews(api, container, zone, placeName, { title = false } = {})" in script
    assert 'item.scope !== "national"' in script
    # With a scheda, news fill its «Notizie» block; without, the older page keeps them.
    assert 'renderLocalNews(api, byId("t-notizie"), { region_id: region.id }, scheda.news_title, { title: true })' in script
    assert 'renderLocalNews(api, byId("t-notizie"), { municipality_id: municipality.id }, scheda.news_title, { title: true })' in script
    assert 'renderLocalNews(api, byId("t-notizie"), { province: base.key }, scheda.news_title, { title: true })' in script
    assert '<div id="region-news"></div>' in script


def test_territorio_is_a_main_tab_with_the_map():
    html = (APP / "index.html").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    nav = html.split('class="bottom-nav"')[1].split("</nav>")[0]
    # Feed, Politica, Territorio, Archivio, Cerca — in this order.
    order = [nav.index(f'data-section="{name}"') for name in ("home", "politics", "territory", "history", "search")]
    assert order == sorted(order)
    view = html.split('id="territory-view"')[1].split('id="compare-view"')[0]
    for marker in ('id="tmap-canvas"', 'role="combobox"', 'id="tmap-results"', 'id="tmap-back"', 'id="tmap-zone"', 'id="tmap-sheet"', "ISTAT", "OpenStreetMap"):
        assert marker in view
    # Politica no longer carries the territory block; lists and schede belong to Territorio.
    politics = html.split('id="politics-view"')[1].split('id="territory-view"')[0]
    assert 'id="territories-title"' not in politics and "?view=regions" not in politics
    assert 'territory: "territory", provinces: "territory", regions: "territory", municipalities: "territory"' in script
    assert 'if (params.get("province") || params.get("region") || params.get("municipality")) return "territory";' in script
    assert 'import("./territory-map.js")' in script and "export function renderTownFilter(towns)" in script


def test_territory_schede_go_back_to_the_map():
    html = (APP / "index.html").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    assert 'id="province-detail-view"' in html and 'showProvinceDetail(api, provinceCode.toUpperCase())' in script
    assert 'showTerritoryHistory(api, { province: params.get("history_province").toUpperCase() })' in script
    for view in ("region-detail-view", "municipality-detail-view", "province-detail-view", "regions-view", "provinces-view", "municipalities-view"):
        block = html.split(f'id="{view}"')[1].split("</section>")[0]
        assert "./?view=territory" in block and "Archivio" not in block
    # Back lands on the same place on the map.
    assert "./?view=territory&regione=${encodeURIComponent(region.istat_code)}" in script
    assert "./?view=territory&provincia=${encodeURIComponent(base.key)}" in script
    assert "export function renderTerritoryScheda(t" in script and "export function renderTerritoryFacts(t)" in script


def test_archivio_lists_city_timelines_and_opens_verona():
    html = (APP / "index.html").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    console = (APP.parent / "redazione" / "app.js").read_text(encoding="utf-8")
    history = html.split('id="history-view"')[1].split('id="legislature-view"')[0]
    assert 'id="city-archive"' in history and "Cerca Verona, Milano, Veneto" in history
    assert 'data-archive-tab="cities"' in history and 'class="archive-dir"' in history
    assert "export function renderArchiveTimeline(timeline" in script
    assert "showArchiveTimeline(api, timelineSlug)" in script
    assert 'listArchiveTimelines:' in script
    assert "export function renderArchiveTimelineChip(item)" in script and "archive-dir-item" in script
    assert "if (item.municipality_id) return `./?municipality=${encodeURIComponent(item.municipality_id)}`;" in script
    assert 'window.location.replace(`./?municipality=${encodeURIComponent(timeline.municipality_id)}`)' in script
    assert "Apri in Archivio" not in script
    assert "I capoluoghi (Verona, Milano, …) stanno in elenco" in console
    assert 'accept="image/*' in console
    assert "Prima il file" in console
    assert "export function askFollowUps(payload)" in script
    assert "Nessuna promessa pubblicata corrisponde" in script
    assert "Imposta la zona" in script


def test_government_chart_shows_the_parties_and_the_ranks():
    html = (APP / "index.html").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    styles = (APP / "styles.css").read_text(encoding="utf-8")
    assert 'id="government-chart"' in html
    assert "export function governmentComposition(people)" in script and "export function renderGovernmentComposition(people)" in script
    for tier in ("Presidente del Consiglio", "Vicepresidenti del Consiglio", "Ministri con portafoglio", "Ministri senza portafoglio"):
        assert tier in script
    # Colours follow the party (assigned by name), counts are in the legend, not on the bar.
    assert "String(a.party.name).localeCompare(String(b.party.name)" in script
    assert 'role="img" aria-label="Componenti del Governo per partito' in script
    assert ".gov-bar { display: flex; gap: 2px;" in styles


def test_politica_opens_with_regioni_camera_senato():
    html = (APP / "index.html").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    view = html.split('id="politics-view"')[1].split('id="compare-view"')[0]
    # Il quadro holds only Governo (default), Camera and Senato.
    quadro = view.split('id="quadro-title"')[1].split('id="parties-title"')[0]
    for tab in ("governo", "camera", "senato"):
        assert f'data-quadro="{tab}"' in quadro
    assert 'data-quadro="regioni"' not in quadro
    assert quadro.index('data-quadro="governo"') < quadro.index('data-quadro="camera"')
    assert 'id="government-row"' in quadro and 'id="government-chart"' in quadro
    assert 'id="quadro-governo"' in quadro and 'show("governo");' in script
    # Regions are coloured only by the coalition the redazione published; the rest is «Da compilare».
    assert 'const COALITION_ORDER = ["centrosinistra", "altro", "da_compilare", "centrodestra"];' in script
    assert "export function hemicycle(count" in script and "export function renderChamberQuadro(chamber)" in script
    assert 'getParliament: () => request("/parliament/composition")' in script
    assert 'getRegionsOverview: () => request("/territories/regions")' in script


def test_territory_map_is_accessible_light_and_self_hosted():
    module = (APP / "territory-map.js").read_text(encoding="utf-8")
    css = (APP / "styles.css").read_text(encoding="utf-8")
    # Opens on the URL state, else the reader's zone (region + province), else Italy.
    assert "fromUrl.regione || fromUrl.provincia ? fromUrl : { regione: zoneIstat" in module
    assert 'history.pushState({ territory: true }, "", territoryHref(state))' in module and 'window.addEventListener("popstate"' in module
    # Faces and pins are buttons; Escape goes up a level; keyboard activation moves focus.
    assert 'document.createElement("button")' in module and 'event.key === "Escape"' in module and "event.detail === 0" in module
    assert 'aria-activedescendant' in module and "Elenco ${" in module
    # MapLibre is self-hosted (script-src 'self'); shapes appear even without basemap tiles.
    assert './vendor/maplibre/maplibre-gl-csp.js' in module and 'map.once("style.load"' in module
    assert (APP / "vendor" / "maplibre" / "maplibre-gl-csp-worker.js").exists()
    for name in ("regioni", "province", "regioni-centri", "province-centri"):
        assert (APP / "geo" / f"{name}.geojson").exists()
    assert "prefers-reduced-motion: reduce" in css and ".tmap-sheet-body.is-in > *, .tmap-results { animation: none; }" in css
    assert "if (q.length < 2) return;" in module


def test_redazione_corrections_reach_the_politica_page():
    script = (APP / "app.js").read_text(encoding="utf-8")
    assert 'getPoliticsEdits: () => request("/parliament/edits")' in script
    # Governo: hide, change party/row/title, add people; texts and captions replaced.
    assert "export async function applyGovernmentEdits(people, edits, loadPerson)" in script
    assert "if (person.edited_tier !== undefined" in script and "if (person.edited_role) return person.edited_role;" in script
    assert 'texts["text:regions_caption"]' in script and 'live["text:government_note"]' in script
    # A corrected value says so, in words.
    assert script.count("editedMark(") >= 4


def test_redazione_has_a_politica_attuale_page():
    console = (APP.parent / "redazione" / "app.js").read_text(encoding="utf-8")
    html = (APP.parent / "redazione" / "index.html").read_text(encoding="utf-8")
    assert 'href="#/politica" data-section="politica"' in html and "Politica attuale" in html
    assert 'else if (section === "politica") await showPoliticaAttuale(' in console
    for tab in ("governo", "regioni", "parlamento", "testi"):
        assert f'["{tab}",' in console
    # Each row keeps the official value beside the correction, and can go back to it.
    assert "Dati ufficiali:" in console and "Torna al dato ufficiale" in console
    assert 'if (item.kind === "politica")' in console


def test_territory_schede_have_a_politician_style_hero_and_the_console_edits_images():
    script = (APP / "app.js").read_text(encoding="utf-8")
    css = (APP / "styles.css").read_text(encoding="utf-8")
    console = (APP.parent / "redazione" / "app.js").read_text(encoding="utf-8")
    html = (APP.parent / "redazione" / "index.html").read_text(encoding="utf-8")
    # Public: photo or coat of arms, the person who governs, credits, filterable comuni.
    assert "export function renderTerritoryHero(t" in script and "export function renderTerritoryHolder(holder" in script
    assert 't-hero-badge' in script and 't-hero-credit' in script and "images.photo" in script
    assert "export function renderTownDirectory(towns" in script and "bindTownDirectory(byId(\"province-detail\"))" in script
    assert ".t-hero { " in css and "aspect-ratio: 4 / 5" in css
    # Console: «Territorio» in the menu, a simple dashboard, coat of arms and photo per scheda.
    assert '<span class="nav-text">Territorio</span>' in html
    # Simple dashboard: what waits for verification first, no counters of logos or photos.
    assert "In attesa di verifica" in console and "function territoryWaiting(queue)" in console
    assert "Stemmi pubblicati" not in console and "Foto pubblicate" not in console
    assert '<span class="nav-text">Partiti</span>' in html and "Partiti e territori" not in html
    assert 'const SYMBOL_TABS = [["party", "Partiti"]];' in console
    assert 'api(`/territori/${kind}/${encodeURIComponent(base.key)}/immagini`)' in console
    assert 'purpose: slot.photo ? "photo" : "logo"' in console and "async function shrinkForUpload(img" in console
    assert "provinceTownsCard(base)" in console
    assert '<span class="nav-text">Archivio</span>' in html
    assert '<span class="nav-text">Lavori</span>' in html
    assert 'const QUEUE_KINDS =' in console and '["archivio", "Archivio"]' in console
    assert "async function showArchiveDesk" in console and "async function showJobs" in console
    assert "Wikipedia e Tuttitalia restano bozze" in console
    assert "Nessun cron è impostato" in console


def test_standout_public_surfaces_keep_gaps_visible_and_ask_threaded():
    script = (APP / "app.js").read_text(encoding="utf-8")
    css = (APP / "styles.css").read_text(encoding="utf-8")
    html = (APP / "index.html").read_text(encoding="utf-8")
    cards = (APP / "feed-card.js").read_text(encoding="utf-8")
    map_script = (APP / "territory-map.js").read_text(encoding="utf-8")
    assert 'class="vp-aside vp-place"' in cards
    assert "Il feed Per te è vuoto." in script
    assert 'href="./?view=profile&amp;tab=follows">Scegli chi seguire' in script
    assert "Scheda incompleta" in script and "Titolare non ancora collegato" in script
    assert "Cerca un comune, una provincia o una regione" in html
    assert 'api.search({ q, type: "municipality", limit: 12' in map_script
    assert "Leggi di questa legislatura" in script
    assert "thread.length < 3" in script and "pledge_ids: pin" in script
    assert ".ask-turn + .ask-turn" in css
    assert "@media (max-width: 767px)" in css and ".compare-card .rate-block" in css
