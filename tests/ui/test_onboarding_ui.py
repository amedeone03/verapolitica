from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "frontend" / "app"


def test_welcome_and_registration_flow() -> None:
    script = (APP / "app.js").read_text(encoding="utf-8")
    onboarding = (APP / "onboarding.js").read_text(encoding="utf-8")
    styles = (APP / "styles.css").read_text(encoding="utf-8")
    # The root opens on the welcome screen: logo, Registrati, Accedi, consult without an account.
    assert 'import { renderAccountForm, renderWelcome, runOnboarding } from "./onboarding.js";' in script
    assert "Registrati" in onboarding and "Accedi" in onboarding
    assert "Consulta senza account" in onboarding
    assert 'view === "registrati"' in script and 'view === "accedi"' in script and "firstVisit" in script
    assert "export function renderAccountForm" in onboarding
    assert 'request("/auth/register"' in script and 'request("/auth/login"' in script
    assert 'credentials: "include"' in script
    # Sign-up stays in the wrap: name, zone, follows, then email and password.
    assert 'const EDIT_STEPS = ["name", "zone", "politicians", "parties", "summary"]' in onboarding
    assert 'const REGISTER_STEPS = ["name", "zone", "politicians", "parties", "email", "password"]' in onboarding
    assert "collectAccount" in onboarding and "onCreateAccount" in onboarding
    assert "Qual è la tua email?" in onboarding and "Scegli una password" in onboarding
    assert "api.listPoliticians({ offset, limit: 100 })" in onboarding and "api.listParties(" in onboarding
    assert "api.listRegions()" in onboarding and "api.listProvinces(" in onboarding
    assert "Array.isArray(state.people) && !state.people.length" in onboarding
    assert "non dà indicazioni di voto" in onboarding
    assert "fetch(" not in onboarding and "localStorage" not in onboarding
    assert "collectAccount: true" in script
    # Accedi / Registrati sit in a centred panel; the name step is vertically centred.
    assert 'class="account-brand"' in onboarding and 'class="account-panel"' in onboarding
    assert 'id="account-title" class="account-title"' in onboarding
    assert "place-content:start" not in onboarding
    assert 'class="ob-title">Come ti chiami?' in onboarding
    assert "Come ti chiamiamo?" not in onboarding
    assert 'class="ob-faces-slot"' in onboarding and "function nameFaces" in onboarding
    assert "item.profile?.image_url" in onboarding
    assert 'class="ob-label" for="ob-name">Il tuo nome' in onboarding
    assert '["name", "email", "password"].includes(key) ? " is-centered"' in onboarding
    assert "Scrivi almeno due lettere" in onboarding
    assert ".account-gate" in styles and ".ob.is-centered .ob-body" in styles
    assert ".account-title" in styles and ".ob-faces" in styles and ".ob-avatar.is-face" in styles
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
