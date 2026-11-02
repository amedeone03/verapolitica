from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "frontend" / "app"


def test_welcome_and_registration_flow() -> None:
    script = (APP / "app.js").read_text(encoding="utf-8")
    onboarding = (APP / "onboarding.js").read_text(encoding="utf-8")
    styles = (APP / "styles.css").read_text(encoding="utf-8")
    # The root opens on the welcome screen: logo, Registrati and Accedi alla demo.
    assert 'import { renderWelcome, runOnboarding } from "./onboarding.js";' in script
    assert "Registrati" in onboarding and "Accedi alla demo" in onboarding
    assert 'view === "registrati"' in script and "firstVisit" in script
    # Sign-up asks for politicians, parties, region and province, then shows the summary.
    assert onboarding.count('const STEPS = ["name", "politicians", "parties", "zone", "summary"]') == 1
    assert "api.listPoliticians()" in onboarding and "api.listParties(" in onboarding
    assert "api.listRegions()" in onboarding and "api.listProvinces(" in onboarding
    # Neutral: no voting advice, nothing leaves the device.
    assert "non dà indicazioni di voto" in onboarding
    assert "fetch(" not in onboarding and "localStorage" not in onboarding
    # The demo cannot save; the "Per te" sends follows to the feed.
    assert script.count("if (!isMember())") >= 3 and "demoNotice()" in script
    assert 'params.set("politicians"' in script and 'params.set("parties"' in script
    # Motion respects the reader's settings.
    assert ".ob-screen.is-entering, .ob-stat { animation: none; }" in styles


def test_logos_reach_every_view() -> None:
    root = APP.parent
    card = (APP / "feed-card.js").read_text(encoding="utf-8")
    console = (root / "redazione" / "app.js").read_text(encoding="utf-8")
    onboarding = (APP / "onboarding.js").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    # Only logos served by VeraPolitica itself (/media/{id}) are drawn.
    assert "export function partyLogo" in card and "/^\\/media\\/\\d+$/" in card
    assert "/^\\/media\\/\\d+$/" in onboarding and "listParties({ all: true })" in onboarding
    assert 'section === "simboli"' in console and "partyLogo(party)" in console
    assert 'api("/simboli", { method: "POST"' in console
    assert "syncFollows(api)" in script
