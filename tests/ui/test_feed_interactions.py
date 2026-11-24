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
    # Entrance: the first screenful fades in together, once per session; no stagger.
    assert "options.index < 3" in card and "--vp-delay" not in card and "--vp-delay" not in css
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



def test_motion_system_is_one_shared_layer():
    """Crisp feel: shared tokens, press on press-in, exits ~70% of entrances, nothing moves by itself."""
    motion = (APP / "motion.css").read_text(encoding="utf-8")
    motion_js = (APP / "motion.js").read_text(encoding="utf-8")
    styles = (APP / "styles.css").read_text(encoding="utf-8")
    cards = (APP / "feed-card.css").read_text(encoding="utf-8")
    html = (APP / "index.html").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    territory = (APP / "territory-map.js").read_text(encoding="utf-8")
    # Loaded last, so its tokens win; the redazione shares it.
    assert html.index("./feed-card.css") < html.index("./motion.css")
    assert "/app/motion.css" in (APP.parent / "redazione" / "index.html").read_text(encoding="utf-8")
    for token in ("--dur-press: 120ms", "--dur-enter: 220ms", "--dur-exit: 150ms", "--dur-page: 300ms", "--dur-page-exit: 210ms", "--press-scale: .97"):
        assert token in motion
    # Press feedback reads the shared tokens everywhere, never a private timing.
    for css in (styles, cards):
        assert "transform 100ms ease-out" not in css and "transform .12s ease" not in css
        assert "ease-in;" not in css and "ease-in " not in css.replace("ease-in-out", "")
    assert styles.count("scale(var(--press-scale") >= 20
    # Toast: live region present before any message, readable duration, swipe to dismiss.
    assert 'id="toast-live" class="visually-hidden" role="status" aria-live="polite"' in html
    assert "Math.max(4000" in motion_js and "attachVerticalDrag(root" in motion_js
    assert "demo-notice" not in script and 'import { toast } from "./motion.js";' in script
    # Page transitions carry a direction; tabs crossfade.
    for kind in ("push", "pop", "sheet-open", "sheet-close", "tab"):
        assert f"active-view-transition-type({kind})" in motion
    assert "export function pageTransitionType" in script
    # Sheet: finger-driven position, rubber band, release velocity into a spring.
    assert "attachVerticalDrag(sheetBox" in territory and "rubberband(" in territory and "project(velocity)" in territory
    assert "touchend" not in territory
    # Nothing animates without the reader: no breathing art, pulses, shimmer or count-ups.
    for gone in ("italy-breath", "sk-pulse", "search-shimmer", "animation-delay: calc(var(--i"):
        assert gone not in styles
    assert "IntersectionObserver" not in script.split("function bindProfileMotion")[1].split("\nfunction ")[0]
