"""The public app is organised in four sections: Home, Politica, Archivio, Profilo."""

from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "frontend" / "app"


def test_four_sections_in_header_and_mobile_tab_bar():
    html = (APP / "index.html").read_text(encoding="utf-8")
    for section, href in (("home", "./"), ("politics", "./?view=politics"), ("history", "./?view=history"), ("profile", "./?view=profile")):
        assert html.count(f'href="{href}" data-section="{section}"') == 2  # header + tab bar
    for view in ("home-view", "politics-view", "compare-view", "history-view", "legislature-view",
                 "parliamentarians-view", "provinces-view", "territory-history-view", "profile-view", "post-view"):
        assert f'id="{view}"' in html
    # The politician list is no longer the landing page.
    assert '<section id="archive-view" aria-labelledby="archive-title" hidden>' in html
    assert "dossier=legge_bilancio" in html
    assert "nessun account, niente viene inviato" in html


def test_routes_and_privacy_of_the_reader_profile():
    script = (APP / "app.js").read_text(encoding="utf-8")
    for route in ('view === "politics"', 'view === "history"', 'view === "profile"', 'view === "compare"',
                  "showLegislature(api", "showTerritoryHistory(api", "showParty(api", "showPost(api"):
        assert route in script
    assert "showHome(api);\n}" in script
    # Zone and favourites stay in browser storage, wrapped so private mode still works.
    assert 'const PROFILE_KEY = "verapolitica.profile.v1"' in script
    assert "storage?.setItem(PROFILE_KEY" in script
    assert "fetchImpl(path" in script and "PROFILE_KEY" not in script.split("function createPublicApiClient")[1].split("\n}\n")[0]
    # Party scores are explained as pooled counts, comparisons as same-role only.
    assert "non è una media dei punteggi dei suoi esponenti" in script
    assert "non è distinguibile" in script


def test_tab_bar_only_on_small_screens():
    styles = (APP / "styles.css").read_text(encoding="utf-8")
    assert ".tab-bar { display: none; }" in styles
    assert "@media (max-width: 760px)" in styles
