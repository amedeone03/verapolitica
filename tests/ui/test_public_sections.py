"""The public app is organised in four sections: Home, Politica, Archivio, Profilo."""

from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "frontend" / "app"


def test_four_sections_in_header_and_mobile_menu():
    html = (APP / "index.html").read_text(encoding="utf-8")
    for section, href in (("home", "./"), ("politics", "./?view=politics"), ("history", "./?view=history"), ("profile", "./?view=profile")):
        assert html.count(f'href="{href}" data-section="{section}"') == 2  # header + mobile menu
    assert 'aria-controls="mobile-menu"' in html and 'role="dialog" aria-modal="true"' in html
    assert "tab-bar" not in html
    for view in ("home-view", "politics-view", "compare-view", "history-view", "legislature-view",
                 "parliamentarians-view", "provinces-view", "territory-history-view", "profile-view", "post-view"):
        assert f'id="{view}"' in html
    assert '<section id="archive-view" aria-labelledby="archive-title" hidden>' in html
    # The home is only the redazione's timeline.
    assert 'id="feed-choice"' in html and 'class="feed-timeline"' in html
    home = html.split('id="home-view"')[1].split("</section>")[0]
    assert "shortcut-grid" not in home and "home-hero" not in home
    assert "Salvato solo su questo dispositivo, senza account." in html
    assert "trust-line" not in html


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
    # No glass, glow or entrance animation.
    assert "backdrop-filter" not in styles and "radial-gradient" not in styles
    assert "will-reveal" not in styles and "is-new" not in script
    assert "@media (prefers-reduced-motion: reduce)" in styles
    # Accessible mobile menu: Escape, focus trap, focus return, scroll lock.
    assert 'event.key === "Escape"' in script and 'classList.toggle("menu-open", open)' in script
    assert 'class="skip-link"' in html
    # SEO essentials.
    assert 'property="og:image"' in html and "application/ld+json" in html
    assert 'link.rel = "canonical"' in script
