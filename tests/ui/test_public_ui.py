from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from scripts.prepare_demo import DEMO_ADMIN_KEY, prepare_demo


def public_demo_client(tmp_path):
    summary = prepare_demo(workspace_root=tmp_path / "workspace")
    app = create_app(
        Settings(
            database_url=f"sqlite:///{summary.database_path}",
            raw_storage_path=summary.raw_storage_path,
            admin_api_key=DEMO_ADMIN_KEY,
            admin_reviewer_identity="demo-presenter",
        )
    )
    return TestClient(app)


def test_public_ui_assets_and_query_string_detail_route_are_served(tmp_path):
    with public_demo_client(tmp_path) as client:
        archive = client.get("/app/")
        detail = client.get("/app/?politician=1")
        styles = client.get("/app/styles.css")
        script = client.get("/app/app.js")

    assert archive.status_code == 200
    assert detail.status_code == 200
    assert "Know who represents you" in archive.text
    assert "Loading verified profiles" in archive.text
    assert styles.status_code == 200
    assert ".politician-grid" in styles.text
    assert ".source-block" in styles.text
    assert script.status_code == 200
    assert "renderPoliticianCard" in script.text
    assert "renderPoliticianDetail" in script.text
    assert "groupCitations" in script.text
    assert "renderParliamentaryGroups" in script.text
    assert "Parliamentary groups" in script.text
    assert ".group-membership" in styles.text
    assert "renderPoliticalParties" in script.text
    assert "Political party" in script.text
    assert ".party-affiliation" in styles.text
    assert "renderProposalCard" in script.text
    assert "renderProposalTimeline" in script.text
    assert "Proposals / commitments" in script.text
    assert ".proposal-timeline" in styles.text
    assert "renderRegionCard" in script.text
    assert "renderMunicipalityCard" in script.text
    assert "renderTerritorialOffices" in script.text
    assert "Territorial offices" in script.text
    assert "/regions?offset=0&limit=50" in script.text
    assert "/municipalities?" in script.text


def test_public_ui_distinguishes_current_and_historical_groups(tmp_path):
    with public_demo_client(tmp_path) as client:
        script = client.get("/app/app.js").text

    assert "Previous groups" in script
    assert "Since" in script
    assert "not the same as political parties" in script


def test_public_ui_keeps_parties_separate_and_displays_party_history(tmp_path):
    with public_demo_client(tmp_path) as client:
        script = client.get("/app/app.js").text

    assert "Previous parties" in script
    assert "political_parties" in script
    assert "distinct institutional concepts" in script
    assert "parliamentary_groups" in script


def test_public_ui_has_separate_proposal_archive_and_detail_timeline(tmp_path):
    with public_demo_client(tmp_path) as client:
        page = client.get("/app/?view=proposals")
        script = client.get("/app/app.js").text
        proposals = client.get("/proposals")
        detail = client.get("/proposals/1")

    assert page.status_code == 200
    assert "Proposal tracker" in page.text
    assert proposals.status_code == 200
    assert proposals.json()["total"] == 1
    assert detail.json()["status_history"][0]["status"] == "introduced"
    assert "Explicit promise" in script
    assert "legislative_proposal" not in page.text


def test_public_ui_assets_are_strictly_public(tmp_path):
    with public_demo_client(tmp_path) as client:
        assets = "\n".join(
            (
                client.get("/app/").text,
                client.get("/app/app.js").text,
                client.get("/app/styles.css").text,
            )
        )

    assert "/politicians?offset=0&limit=50" in assets
    assert "getPolitician" in assets
    assert "/admin/" not in assets
    assert "verapolitica-demo-admin" not in assets
    assert "Authorization" not in assets
    assert "start-review" not in assets
    assert "approve" not in assets.casefold()
    assert "reject" not in assets.casefold()
    assert "reviewer" not in assets.casefold()
    assert "Anna Rossi" not in assets
    assert "Luca Bianchi" not in assets


def test_initial_archive_contains_only_published_api_data(tmp_path):
    with public_demo_client(tmp_path) as client:
        listing = client.get("/politicians?offset=0&limit=50")
        anna = client.get("/politicians/1")
        luca = client.get("/politicians/2")

    assert listing.status_code == 200
    payload = listing.json()
    assert payload["total"] == 2
    assert [person["id"] for person in payload["items"]] == [3, 1]
    assert payload["items"][1]["given_name"] == "Anna"
    assert payload["items"][0]["given_name"] == "Giulia"
    assert payload["items"][1]["citation_count"] == 14
    assert anna.status_code == 200
    assert anna.json()["parliamentary_groups"][0]["name"] == "Fratelli d'Italia"
    assert luca.status_code == 404


def test_real_approval_makes_profile_and_groupable_citations_public(tmp_path):
    headers = {"Authorization": f"Bearer {DEMO_ADMIN_KEY}"}
    with public_demo_client(tmp_path) as client:
        assert client.get("/politicians/2").status_code == 404
        started = client.post("/admin/drafts/2/start-review", headers=headers)
        approved = client.post(
            "/admin/drafts/2/approve",
            headers=headers,
            json={"note": "Official evidence verified during demo"},
        )
        listing = client.get("/politicians?offset=0&limit=50")
        detail = client.get("/politicians/2")

    assert started.status_code == 200
    assert approved.status_code == 200
    assert [person["id"] for person in listing.json()["items"]] == [2, 3, 1]
    payload = detail.json()
    assert payload["given_name"] == "Luca"
    assert payload["current_version_number"] == 1
    assert payload["profile"]["profession"]
    assert payload["profile"]["mandates"]
    assert payload["citation_count"] == 14
    assert len(payload["citations"]) == 14
    assert {
        (citation["source_name"], citation["source_url"])
        for citation in payload["citations"]
    } == {("Senato della Repubblica", "https://dati.senato.it/sparql")}
