"""Feed card: reactions, re-share and save are for registered readers; motion follows the reader's settings."""

from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "frontend" / "app"


def test_reactions_are_the_four_system_emoji_with_long_press():
    card = (APP / "feed-card.js").read_text(encoding="utf-8")
    for code, emoji in (("heart", "❤️"), ("angry", "😡"), ("party", "🎉"), ("tears", "😢")):
        assert f'code: "{code}", emoji: "{emoji}"' in card
    # Tap is the heart; press and hold, right click or ArrowUp opens the picker.
    assert "LONG_PRESS_MS" in card and '"contextmenu"' in card and 'event.key === "ArrowUp"' in card
    assert 'react(reactButton, reactButton.dataset.mine ? null : "heart")' in card
    assert 'setAttribute("role", "menu")' in card and 'role="menuitemradio"' in card
    # Re-share and save live in the reader's profile.
    assert "data-card-repost" in card and "data-card-save" in card and "data-card-share" in card


def test_only_registered_readers_can_react_reshare_or_save():
    script = (APP / "app.js").read_text(encoding="utf-8")
    handlers = script.split("function cardHandlers(api")[1].split("\n}\n")[0]
    assert handlers.count("if (!isMember()) { demoNotice();") == 3
    assert "api.react(postId, reaction)" in handlers
    assert 'listReactions: (postIds) => request(`/reactions?posts=' in script
    assert "export function toggleSharedPost" in script
    # The profile shows saved and re-shared posts in tabs.
    html = (APP / "index.html").read_text(encoding="utf-8")
    for tab in ("saved", "shared", "follows"):
        assert f'data-tab="{tab}"' in html and f'id="profile-panel-{tab}"' in html


def test_motion_is_short_and_respects_reduced_motion():
    css = (APP / "feed-card.css").read_text(encoding="utf-8")
    styles = (APP / "styles.css").read_text(encoding="utf-8")
    assert "cubic-bezier(0.23, 1, 0.32, 1)" in css
    assert "transition: all" not in css and "scale(0)" not in css and "ease-in;" not in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (hover: hover) and (pointer: fine)" in css
    # Segmented control: a clipped copy of the labels slides, Kowalski's tab technique.
    assert ".feed-segments-active" in styles and "clip-path: inset(0 calc(" in styles


def test_category_band_and_session_entrance():
    card = (APP / "feed-card.js").read_text(encoding="utf-8")
    css = (APP / "feed-card.css").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    # One coloured band per kind of news, coloured by the redazione's tone.
    assert '<header class="vp-band">' in card
    for tone in ("tone-ink", "tone-red", "tone-green"):
        assert f".vp-card.{tone}" in css
    # Entrance: three cards, non-uniform delays, once per session, never on tab switches.
    assert "const ENTER = [[0, 10], [60, 6], [100, 6]];" in card
    assert "load(false, { animate: firstFeedOpen() })" in script
    # Signature strip: fact → proof → sources.
    assert 'class="vp-prova"' in card and "Fatto verificato" in card
    assert ".vp-prova" in css
    # Dark theme: title/people use surface text, not the near-black ink used on bands.
    assert ".vp-title a { color: inherit;" in css or "color: inherit" in css.split(".vp-title a")[1][:80]
    assert "color: var(--vp-text)" in css.split(".vp-person-text a")[1][:120]


def test_frontend_standout_surfaces_are_wired():
    script = (APP / "app.js").read_text(encoding="utf-8")
    css = (APP / "styles.css").read_text(encoding="utf-8")
    assert "renderPledgeScoreboard" in script and "pledge-scoreboard" in css
    assert "news-sides" in script and ".news-sides" in css
    assert "ask-proof-chip" in script and "Non ancora verificato" in script
    assert "share-strip" in script and "Condividi la prova" in script

