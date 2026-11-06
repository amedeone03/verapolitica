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
                  "showLegislature(api", "showTerritoryHistory(api", "showParty(api", "showPost(api"):
        assert route in script
    assert "showHome(api);" in script and "start();" in script
    # Zone and favourites stay in browser storage, wrapped so private mode still works.
    assert 'const PROFILE_KEY = "verapolitica.profile.v1"' in script
    assert "storage?.setItem(PROFILE_KEY" in script
    assert "fetchImpl(path" in script and "PROFILE_KEY" not in script.split("function createPublicApiClient")[1].split("\n}\n")[0]
    # Party scores are explained as pooled counts, comparisons as same-role only.
    assert "non è una media dei punteggi dei suoi esponenti" in script
    assert "non è distinguibile" in script


def test_cambridge_classic_tokens_fonts_and_accessibility():
    styles = (APP / "styles.css").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    html = (APP / "index.html").read_text(encoding="utf-8")
    for token in ("--color-primary: #0F2747", "--color-secondary: #003C71", "--color-accent: #85B09A",
                  "--color-accent-light: #DCEBE5", "--color-background: #F8FAF9", "--color-border: #DFE6E3"):
        assert token in styles
    # Self-hosted fonts only: no @import, no third-party font host.
    assert "@import" not in styles and "fonts.googleapis" not in html
    assert (APP / "fonts" / "inter-latin-var.woff2").exists()
    # One family, as on House of the People: Inter for text and headings.
    assert "Source Serif" not in styles and "source-serif" not in html
    assert '--font-heading: "Inter"' in styles
    assert html.count('rel="preload"') == 1
    # No glow or entrance animation. Translucency only on the floating bottom bar,
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
    assert ".proposals-tabs a:active { transform: scale(.95); }" in css


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


def test_politica_holds_regions_provinces_and_comuni():
    html = (APP / "index.html").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    view = html.split('id="politics-view"')[1].split('id="compare-view"')[0]
    for marker in ('id="territories-title"', 'id="my-zone"', 'id="territory-q"', 'href="./?view=regions"',
                   'href="./?view=provinces"', 'href="./?view=municipalities"'):
        assert marker in view
    # The zone card reads the on-device profile; the comune search uses the public search.
    assert "export function renderZoneCard(zone" in script
    assert "const zone = loadReaderProfile().zone;" in script
    assert 'api.search({ q, type: "municipality", limit: 6' in script
    assert 'provinces: "politics", regions: "politics", municipalities: "politics"' in script
    archive = html.split('id="history-view"')[1].split("</section>\n      </section>")[0]
    assert "?view=regions" not in archive and "?view=provinces" not in archive


def test_territory_schede_live_in_politica():
    html = (APP / "index.html").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    # A province opens its own scheda in Politica; its history stays in the Archivio.
    assert 'id="province-detail-view"' in html and 'showProvinceDetail(api, provinceCode.toUpperCase())' in script
    assert 'showTerritoryHistory(api, { province: params.get("history_province").toUpperCase() })' in script
    # Region and comune pages go back to Politica, never to the Archivio.
    for view in ("region-detail-view", "municipality-detail-view", "province-detail-view"):
        block = html.split(f'id="{view}"')[1].split("</section>")[0]
        assert "./?view=politics" in block and "Archivio" not in block
    # The scheda shows the official base first, then the model's blocks, news and sources.
    assert "export function renderTerritoryScheda(t" in script and "export function renderTerritoryFacts(t)" in script
    assert 'getTerritory: (kind, key) => request(`/territories/' in script


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
    # Three tabs above the Governo block, one panel.
    assert view.index('id="quadro-title"') < view.index('id="government-title"')
    for tab in ("regioni", "camera", "senato"):
        assert f'data-quadro="{tab}"' in view
    # Regions are coloured only by the coalition the redazione published; the rest is «Da compilare».
    assert 'const COALITION_ORDER = ["centrosinistra", "altro", "da_compilare", "centrodestra"];' in script
    assert "export function hemicycle(count" in script and "export function renderChamberQuadro(chamber)" in script
    assert 'getParliament: () => request("/parliament/composition")' in script
    assert 'getRegionsOverview: () => request("/territories/regions")' in script
