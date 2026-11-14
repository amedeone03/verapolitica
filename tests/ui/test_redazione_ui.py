"""Static checks on the redazione console (frontend/redazione)."""

import re

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app


def _client(tmp_path, **extra):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'ui.db'}",
        raw_storage_path=tmp_path / "raw",
        **extra,
    )
    return TestClient(create_app(settings))


def test_console_is_self_contained_and_in_cambridge_colours(tmp_path):
    with _client(tmp_path) as client:
        page = client.get("/redazione/").text
        script = client.get("/redazione/app.js").text
        styles = client.get("/redazione/styles.css").text
        demo = client.get("/demo/", follow_redirects=False)
        access = client.get("/redazione/api/accesso").json()
        robots = client.get("/robots.txt").text

    assert '<html lang="it">' in page and 'name="robots" content="noindex, nofollow"' in page
    assert not re.search(r'<script[^>]+src="https?://', page)
    assert "--color-primary: #0F2747" in styles and "--color-accent: #85B09A" in styles
    # The writing models drive the console.
    for text in ("Cosa scrivere", "Da evitare", "Come si scrive", "Pubblica un admin",
                 "Come si assegna lo stato a una promessa", "Registro",
                 "Parentesi quadre: nessuna rimasta aperta nel testo.",
                 "Per chi inizia (Donatella e nuovi redattori)",
                 "docs/bachin-guida-pratica.md",
                 "Settimana notizie"):
        assert text in script or text in page
    # One «Pubblica» button for admins; no checklist to tick before publishing.
    assert 'data-action="approva">Pubblica<' in script and "data-check" not in script
    assert 'imageFields("pol", "Foto")' in script and 'imageFields("party", "Logo")' in script
    assert "bindTerritoryPicker" in script and "type=municipality" in script
    assert 'href="#/identita"' in page and "Identità da risolvere" in script
    assert 'data-action="collega"' in script and "pending_identities" in script
    assert "Elimina la notizia" in script and "data-discard" in script
    assert "Aggiungi un politico" in script and 'api("/politici", { method: "POST"' in script
    assert "Presidente della Repubblica" in script and "Europarlamentare" in script
    assert "Consigliere comunale" in script and "POLITICAL_OFFICE_GROUPS" in script
    assert "career-role-suggestions" in script
    assert 'method: "DELETE"' in script
    assert demo.status_code == 307 and demo.headers["location"] == "/redazione/"
    assert [m["name"] for m in access["demo_members"]] == ["Redattore demo", "Verificatore demo", "Caporedattore demo"]
    assert "Disallow: /redazione/" in robots


def test_configured_members_hide_demo_tokens(tmp_path):
    with _client(tmp_path, redazione_members="Anna=token-anna-lungo-abbastanza-123") as client:
        access = client.get("/redazione/api/accesso").json()
        assert access == {"configured": True, "demo_members": []}
        assert client.get("/redazione/api/me", headers={"Authorization": "Bearer demo-redattore"}).status_code == 401
