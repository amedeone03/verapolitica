from scripts.prepare_demo import DEMO_ADMIN_KEY, prepare_demo

from backend.app.core.config import Settings
from backend.app.main import create_app
from fastapi.testclient import TestClient


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


def test_profile_information_architecture_uses_published_fields_only(tmp_path):
    with public_demo_client(tmp_path) as client:
        script = client.get("/app/app.js").text
        styles = client.get("/app/styles.css").text
        person = client.get("/politicians/1").json()
        scorecard = client.get("/politicians/1/scorecard").json()

    assert person["given_name"] == "Anna"
    assert person["birth_date"]
    assert person["profile"]["mandates"]
    assert person["citations"]
    assert "reviewer_identity" not in person
    assert "admin_notes" not in person
    assert "draft" not in person

    assert "renderPoliticianDetail" in script
    assert "renderCareerTimeline" in script
    assert "renderWhoIs" in script
    assert "renderSourceCard" in script
    assert "suggestedAskQuestions" in script
    assert "Chi è" in script
    assert "Cosa ha fatto" in script
    assert "Posizioni su temi chiave" in script
    assert "Procedimenti e controversie" in script
    assert "Scheda delle promesse" in script
    assert "countPledgeVerdicts" in script
    assert "renderPledgeStatusSummary" in script
    assert "Nessuna promessa pubblicata con questo stato." in script
    assert "Ultimo aggiornamento" in script
    assert "In carica dal" in script
    assert "Data di nascita" in script
    assert "Luogo di nascita" in script
    assert "Chiedi a VeraPolitica su" in script
    assert "Come vengono verificati questi dati?" in script
    assert "Le valutazioni delle promesse vengono pubblicate solo dopo revisione." in script
    assert "Non sono ancora disponibili posizioni verificate per questo profilo." in script
    assert "Questa sezione non contiene ancora elementi pubblicati." in script
    assert "Nessun incarico istituzionale pubblicato è ancora disponibile per questo profilo." in script
    assert "Non ancora valutata" in script
    assert "Apri la fonte" in script
    assert "view=ask" in script
    assert "sono ancora in corso?" in script
    assert "non sono ancora valutate?" in script
    assert "fonti delle valutazioni pubblicate" in script
    assert "Consigliera della Provincia di Roma" not in script
    assert "Biography" not in script
    assert "Current office" not in script
    assert "no controversies" not in script.casefold()
    assert "nessuna controversia" not in script.casefold()
    assert "Giorgia Meloni è nata" not in script
    assert 'family_name === "Meloni"' not in script
    assert "giorgia-meloni" not in script
    assert "renderKeyPositions(person)" in script
    assert "renderProceedings(person)" in script
    assert "Fonte giornalistica" in script
    assert "Procedimento giudiziario" in script
    assert "Controversia politica" in script

    assert ".profile-section-nav" in styles
    assert "flex-wrap: wrap" in styles
    assert ".career-timeline" in styles
    assert ".source-card" in styles
    assert ".ask-suggestions" in styles
    assert "scroll-padding-top: var(--profile-scroll-pad, 5.5rem)" in styles
    assert "scroll-padding-top: var(--profile-scroll-pad, 11rem)" in styles
    assert ".career-entry" in styles
    assert ".career-marker" in styles
    assert ".will-reveal" in styles
    assert ".pledge-details" in styles
    assert "--profile-nav-top" in styles
    assert "prefers-reduced-motion: reduce" in styles

    assert scorecard["methodology_version"] == "pledge-score/v1"
    assert "Tasso di mantenimento" in script
    assert "Spiegami questa promessa" in script
    assert "/explanation" in script


def test_profile_section_nav_omits_missing_optional_blocks(tmp_path):
    with public_demo_client(tmp_path) as client:
        script = client.get("/app/app.js").text

    assert 'who ? { href: "#profilo", label: "Chi è" }' in script
    assert 'hasCareer ? { href: "#carriera", label: "Cosa ha fatto" }' in script
    assert 'sourcesMarkup ? { href: "#fonti", label: "Fonti" }' in script
    assert 'href: "#posizioni"' in script
    assert 'href: "#promesse"' in script
    assert 'href: "#procedimenti"' in script
    assert '{ href: "#procedimenti", label: "Procedimenti e controversie" }' in script
    assert "bindProfileSectionNav" in script
    assert "IntersectionObserver" in script
    assert "bindProfileMotion" in script
    assert "bindProfileTabs" not in script
    assert 'aria-current="location"' in script
    assert 'class="career-entry' in script
    assert "career-marker" in script
    assert "Dettagli e fonti" in script
    assert 'class="pledge-details"' in script
    assert "data-count-to" in script
    assert "will-reveal" in script
    assert "prefersReducedMotion" in script
    assert "form.requestSubmit()" in script
    assert 'href="./?view=ask&amp;prefill=' in script
    assert 'class="profile-ask-cta" href="./?view=ask&amp;question=' not in script
    assert 'class="ask-suggestion" href="./?view=ask&amp;question=' in script


def test_suggested_questions_are_deterministic_and_ask_v1_safe(tmp_path):
    with public_demo_client(tmp_path) as client:
        script = client.get("/app/app.js").text

    assert "Quali promesse di ${name} sono ancora in corso?" in script
    assert "Quali promesse di ${name} non sono ancora valutate?" in script
    assert "Quali sono le fonti delle valutazioni pubblicate su ${name}?" in script
    assert "classifica" not in script.split("suggestedAskQuestions")[1].split("renderAskSuggestions")[0]
    assert "miglior" not in script.split("suggestedAskQuestions")[1].split("renderAskSuggestions")[0]


def test_public_profile_payload_has_career_inputs_not_positions_or_proceedings(tmp_path):
    with public_demo_client(tmp_path) as client:
        payload = client.get("/politicians/1").json()

    assert payload["profile"]["mandates"][0]["office"]
    assert payload["profile"]["mandates"][0]["start_date"]
    assert payload["biography"] is None
    assert payload["career_entries"] == []
    assert payload["positions"] == []
    assert payload["proceedings"] == []
    assert "controversies" not in payload
    assert "biography" not in payload["profile"]
    assert "reviewer_identity" not in payload
    assert "review_note" not in payload
    assert "status" not in payload


def test_career_in_carica_requires_explicit_is_current(tmp_path):
    with public_demo_client(tmp_path) as client:
        script = client.get("/app/app.js").text

    career = script.split("export function careerEntries")[1].split("export function renderCareerTimeline")[0]
    assert "function explicitlyCurrent(item)" in script
    assert "return item?.is_current === true;" in script
    assert "current: explicitlyCurrent(item)" in career
    assert "current: explicitlyCurrent(mandate)" in career
    assert "current: explicitlyCurrent(office)" in career
    assert "current: !mandate.end_date" not in career
    assert "current: !office.end_date" not in career
    assert "current: !item.end_date" not in career
    assert 'entry.current ? `<span class="career-current">In carica</span>`' in script


def test_ask_question_autosubmits_and_prefill_does_not(tmp_path):
    with public_demo_client(tmp_path) as client:
        script = client.get("/app/app.js").text

    show_ask = script.split("function showAsk")[1].split("export function renderSearchCard")[0]
    assert 'params.get("question")' in show_ask
    assert 'params.get("prefill")' in show_ask
    assert "if (preset) form.requestSubmit();" in show_ask
    assert "if (prefill) form.requestSubmit();" not in show_ask
    assert "if (preset && !field.value) field.value = preset;" in show_ask
    assert "else if (prefill && !field.value) field.value = prefill;" in show_ask
    assert 'class="profile-ask-cta" href="./?view=ask&amp;prefill=' in script
    assert 'class="ask-suggestion" href="./?view=ask&amp;question=' in script
