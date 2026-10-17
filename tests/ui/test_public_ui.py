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
    assert 'lang="it"' in archive.text
    assert "Sai chi ti rappresenta" in archive.text
    assert "Caricamento dei profili verificati" in archive.text
    assert styles.status_code == 200
    assert ".politician-grid" in styles.text
    assert ".source-block" in styles.text
    assert "scroll-padding-top: 5.5rem" in styles.text
    assert "scroll-padding-top: 11rem" in styles.text
    assert ".public-nav { display: flex; flex-wrap: wrap" in styles.text
    assert script.status_code == 200
    assert "renderPoliticianCard" in script.text
    assert "renderPoliticianDetail" in script.text
    assert "groupCitations" in script.text
    assert "renderParliamentaryGroups" in script.text
    assert "Gruppi parlamentari" in script.text
    assert ".group-membership" in styles.text
    assert "renderPoliticalParties" in script.text
    assert "Partito politico" in script.text
    assert ".party-affiliation" in styles.text
    assert "renderProposalCard" in script.text
    assert "renderProposalTimeline" in script.text
    assert "Proposte e promesse" in script.text
    assert ".proposal-timeline" in styles.text
    assert "renderRegionCard" in script.text
    assert "renderMunicipalityCard" in script.text
    assert "renderTerritorialOffices" in script.text
    assert "renderCareerTimeline" in script.text
    assert "territorial_offices" in script.text
    assert "/regions?offset=0&limit=50" in script.text
    assert "/municipalities?" in script.text
    assert "renderSearchCard" in script.text
    assert "/search?" in script.text
    assert "view=search" in archive.text
    assert "Cerca nell'archivio pubblico" in archive.text
    assert "Referendum" in archive.text
    assert "Guide al voto" in archive.text
    assert "Glossario" in archive.text
    assert "renderReferendumCard" in script.text
    assert "renderVotingGuide" in script.text
    assert "renderGlossaryTerm" in script.text
    assert "renderScorecard" in script.text
    assert "renderCompositionBar" in script.text
    assert "renderVerdictLegend" in script.text
    assert "countPledgeVerdicts" in script.text
    assert "renderPledgeStatusSummary" in script.text
    assert "renderPledgeDistribution" in script.text
    assert "promesse monitorate" in script.text
    assert "Nessuna promessa pubblicata con questo stato." in script.text
    assert "Distribuzione degli stati pubblicati" in script.text
    assert 'kept: "Mantenute"' in script.text
    assert 'not_yet_rated: "Non ancora valutate"' in script.text
    assert "Spiegami questa promessa" in script.text
    assert "/explanation" in script.text
    assert "explainPledge" in script.text
    assert ".explain-pledge" in styles.text
    assert "/scorecard" in script.text
    assert "Scheda delle promesse" in script.text
    assert "Tasso di mantenimento" in script.text
    assert "Chi è" in script.text
    assert "Data di nascita" in script.text
    assert "In carica dal" in script.text
    assert "Cosa ha fatto" in script.text
    assert 'DateTimeFormat("it-IT"' in script.text
    assert "Nessun risultato trovato" in script.text
    assert "Caricamento delle promesse" in script.text
    assert "Presentata" in script.text
    assert "Come funziona il punteggio delle promesse" in script.text
    assert "Know who represents you" not in archive.text
    assert "Loading verified profiles" not in archive.text
    assert "Current office" not in script.text
    assert "Biography" not in script.text
    assert "Mantenuta parzialmente" in script.text
    assert "In corso" in script.text
    assert "Iter bloccato" in script.text
    assert "Non mantenuta" in script.text
    assert "Non ancora valutata" in script.text
    assert 'tone: "partial"' in script.text
    assert 'tone: "stalled"' in script.text
    assert 'tone: "progress"' in script.text
    assert ".composition-bar" in styles.text
    assert ".pledge-item" in styles.text
    assert ".verdict-legend" in styles.text
    assert ".pledge-status-summary" in styles.text
    assert ".pledge-summary-grid" in styles.text
    assert ".pledge-distribution" in styles.text
    assert ".pledge-item .verdict-chip" in styles.text
    assert "view=methodology" in archive.text
    assert "view=ask" in archive.text
    assert "Chiedi a VeraPolitica" in archive.text
    assert "Es. Quali promesse di Giorgia Meloni sono ancora in corso?" in archive.text
    assert "dati pubblicati e fonti verificate" in archive.text
    assert "ask:" in script.text
    assert "/ask" in script.text
    assert ".ask-form" in styles.text
    assert ".ask-result" in styles.text


def test_public_ui_distinguishes_current_and_historical_groups(tmp_path):
    with public_demo_client(tmp_path) as client:
        script = client.get("/app/app.js").text

    assert "Gruppi precedenti" in script
    assert "Dal " in script
    assert "non coincidono con i partiti politici" in script


def test_public_ui_keeps_parties_separate_and_displays_party_history(tmp_path):
    with public_demo_client(tmp_path) as client:
        script = client.get("/app/app.js").text

    assert "Partiti precedenti" in script
    assert "political_parties" in script
    assert "concetti istituzionali distinti" in script
    assert "parliamentary_groups" in script


def test_public_ui_has_separate_proposal_archive_and_detail_timeline(tmp_path):
    with public_demo_client(tmp_path) as client:
        page = client.get("/app/?view=proposals")
        script = client.get("/app/app.js").text
        proposals = client.get("/proposals")
        detail = client.get("/proposals/1")

    assert page.status_code == 200
    assert "Proposte e promesse esplicite" in page.text
    assert proposals.status_code == 200
    assert proposals.json()["total"] == 1
    assert detail.json()["status_history"][0]["status"] == "introduced"
    assert "Promessa esplicita" in script
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
    assert "/admin/drafts" not in assets
    assert "reviewer_identity" not in assets
    assert "admin_api_key" not in assets
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


def test_public_ui_search_and_click_through(tmp_path):
    with public_demo_client(tmp_path) as client:
        page = client.get("/app/?view=search&q=Anna")
        script = client.get("/app/app.js").text
        anna = client.get("/search", params={"q": "Anna"})
        luca = client.get("/search", params={"q": "Luca", "type": "politician"})
        milano = client.get("/search", params={"q": "Milano", "type": "municipality"})
        lombardia = client.get("/search", params={"q": "Lombardia", "type": "region"})
        proposal = client.get("/search", params={"q": "housing", "type": "proposal"})
        group = client.get("/search", params={"q": "Fratelli", "type": "parliamentary_group"})
        party = client.get("/search", params={"q": "Demo Civic Alliance", "type": "political_party"})
        unpublished = client.get(
            "/search",
            params={"q": "sottoposta all'esame della commissione"},
        )
        carlo = client.get("/search", params={"q": "Carlo Verdi"})
        referendum = client.get("/search", params={"q": "synthetic civic", "type": "referendum"})
        glossary = client.get("/search", params={"q": "quorum", "type": "glossary_term"})
        referendums_page = client.get("/app/?view=referendums")
        guide_page = client.get("/app/?view=voting-guide")
        glossary_page = client.get("/app/?view=glossary")
        unpublished_referendum = client.get("/search", params={"q": "Unpublished synthetic civic"})

    assert page.status_code == 200
    assert "Cerca nell'archivio" in page.text
    assert "renderSearchCard" in script
    assert anna.json()["items"][0]["url"] == "/app/?politician=1"
    assert luca.json()["total"] == 0
    assert milano.json()["items"][0]["title"] == "Milano"
    assert lombardia.json()["items"][0]["title"] == "Lombardia"
    assert proposal.json()["items"][0]["title"].startswith("Synthetic housing")
    assert group.json()["items"][0]["subtitle"].startswith("Gruppo parlamentare")
    assert party.json()["items"][0]["subtitle"].startswith("Partito politico")
    assert unpublished.json()["total"] == 0
    assert carlo.json()["total"] == 0
    assert referendum.json()["items"][0]["entity_type"] == "referendum"
    assert glossary.json()["items"][0]["title"] == "Quorum"
    assert "Referendum e consultazioni" in referendums_page.text
    assert "Guide al voto" in guide_page.text
    assert "Termini chiave" in glossary_page.text
    assert unpublished_referendum.json()["total"] == 0
