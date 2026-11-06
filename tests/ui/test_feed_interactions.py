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
