from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.ai.base import ExtractionProviderError
from backend.app.ai.text_completion import FakeTextCompleter
from backend.app.core.config import AppEnvironment, Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import PledgeAssessment, PledgeAssessmentDraft
from backend.app.scoring import EvidenceLabel, FulfillmentVerdict, VERDICT_VALUE
from backend.app.scoring.scorecard import METHODOLOGY_VERSION
from backend.app.services.pledge_explanation_service import (
    UNRATED_MESSAGE,
    clear_explanation_cache,
    explanation_contradicts_verdict,
)
from backend.app.services.pledge_service import PledgeService
from tests.services.pledge_seed import seed
from tests.services.test_pledge_service import classification, editor_draft


EXCERPT = "approvato in via definitiva la legge che aumenta le pensioni minime"


def _settings(url, tmp_path, **overrides):
    values = {
        "env": AppEnvironment.TEST,
        "database_url": url,
        "raw_storage_path": tmp_path / "raw",
        "admin_api_key": "test-admin-secret",
        "trusted_hosts": "localhost,127.0.0.1,testserver",
        "enable_demo_ui": False,
    }
    values.update(overrides)
    return Settings(**values)


def _client(tmp_path, **overrides):
    url = f"sqlite:///{tmp_path / 'explain.db'}"
    engine = create_db_engine(url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    data = seed(factory)
    engine.dispose()
    app = create_app(_settings(url, tmp_path, **overrides))
    return TestClient(app), data, factory


def _publish(factory, data, verdict=FulfillmentVerdict.IN_PROGRESS, label=EvidenceLabel.SUPPORTS):
    service = PledgeService(factory)
    service.classify(data.pledge_id, classification(), classified_by="ed")
    draft, _ = editor_draft(service, data, data.pledge_id, verdict, label)
    reviewers = ("rev-1", "rev-2") if verdict is FulfillmentVerdict.BROKEN else ("rev",)
    published = None
    for reviewer in reviewers:
        _, published = service.approve(draft.id, reviewer=reviewer)
    return published


def setup_function():
    clear_explanation_cache()


def test_scoring_constants_unchanged_by_explanation_feature():
    assert METHODOLOGY_VERSION == "pledge-score/v1"
    assert VERDICT_VALUE[FulfillmentVerdict.KEPT] == 1.0
    assert VERDICT_VALUE[FulfillmentVerdict.PARTIALLY_KEPT] == 0.5
    assert VERDICT_VALUE[FulfillmentVerdict.BROKEN] == 0.0
    assert [item.value for item in FulfillmentVerdict] == [
        "not_yet_rated",
        "in_progress",
        "stalled",
        "kept",
        "partially_kept",
        "broken",
    ]


def test_contradiction_guard_rejects_wrong_public_labels():
    assert explanation_contradicts_verdict(
        FulfillmentVerdict.IN_PROGRESS, "La promessa è Mantenuta."
    )
    assert explanation_contradicts_verdict(
        FulfillmentVerdict.BROKEN, "L'obiettivo è ancora In corso."
    )
    assert not explanation_contradicts_verdict(
        FulfillmentVerdict.IN_PROGRESS,
        "VeraPolitica la classifica come 'In corso' perché l'atto è stato avviato.",
    )


def test_unrated_pledge_returns_deterministic_message(tmp_path):
    client, data, factory = _client(tmp_path)
    PledgeService(factory).classify(data.pledge_id, classification(), classified_by="ed")
    with client:
        response = client.get(f"/proposals/{data.pledge_id}/explanation")
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "not_yet_rated"
    assert body["public_verdict_label"] == "Non ancora valutata"
    assert body["explanation"] == UNRATED_MESSAGE
    assert body["generated_by_ai"] is False
    assert body["fallback"] is False
    assert body["sources"] == []
    assert "Mantenuta" not in body["explanation"]


def test_unpublished_and_non_promise_are_not_public(tmp_path):
    client, data, _factory = _client(tmp_path)
    with client:
        missing = client.get(f"/proposals/{data.unpublished_id}/explanation")
        bill = client.get(f"/proposals/{data.bill_id}/explanation")
    assert missing.status_code == 404
    assert bill.status_code == 404


def test_ai_disabled_uses_deterministic_fallback(tmp_path):
    client, data, factory = _client(tmp_path)
    _publish(factory, data)
    with client:
        response = client.get(f"/proposals/{data.pledge_id}/explanation")
    body = response.json()
    assert response.status_code == 200
    assert body["verdict"] == "in_progress"
    assert body["public_verdict_label"] == "In corso"
    assert body["generated_by_ai"] is False
    assert body["fallback"] is True
    assert body["model"] is None
    assert "In corso" in body["explanation"]
    assert body["sources"][0]["url"] == "https://www.senato.it/legge/1"
    assert EXCERPT in body["sources"][0]["excerpt"]
    assert "https://evil.example" not in response.text


def test_fake_provider_returns_ai_explanation(tmp_path, monkeypatch):
    text = (
        "Questa promessa riguarda le pensioni minime. VeraPolitica la classifica "
        "come 'In corso' perché è stato avviato un atto ufficiale. La valutazione "
        "si basa sull'estratto pubblicato. Non è ancora conclusa."
    )
    fake = FakeTextCompleter(text)
    monkeypatch.setattr(
        "backend.app.services.pledge_explanation_service.completer_from_settings",
        lambda settings: fake,
    )
    client, data, factory = _client(tmp_path)
    _publish(factory, data)
    with client:
        response = client.get(f"/proposals/{data.pledge_id}/explanation")
    body = response.json()
    assert body["generated_by_ai"] is True
    assert body["fallback"] is False
    assert body["model"] == "fake-explainer"
    assert body["explanation"] == text
    assert fake.requests
    assert "PUBLISHED_VERDICT: in_progress" in fake.requests[0][1]
    assert "do not alter the verdict" in fake.requests[0][0].casefold() or "immutable" in fake.requests[0][0].casefold()


def test_provider_failure_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.app.services.pledge_explanation_service.completer_from_settings",
        lambda settings: FakeTextCompleter(
            "unused", error=ExtractionProviderError("down")
        ),
    )
    client, data, factory = _client(tmp_path)
    _publish(factory, data)
    with client:
        response = client.get(f"/proposals/{data.pledge_id}/explanation")
    body = response.json()
    assert body["generated_by_ai"] is False
    assert body["fallback"] is True
    assert "In corso" in body["explanation"]
    assert "down" not in response.text
    assert "Traceback" not in response.text


def test_in_progress_cannot_become_mantenuta(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.app.services.pledge_explanation_service.completer_from_settings",
        lambda settings: FakeTextCompleter(
            "VeraPolitica ritiene che la promessa sia Mantenuta in ogni sua parte."
        ),
    )
    client, data, factory = _client(tmp_path)
    _publish(factory, data)
    with client:
        body = client.get(f"/proposals/{data.pledge_id}/explanation").json()
    assert body["verdict"] == "in_progress"
    assert body["generated_by_ai"] is False
    assert body["fallback"] is True
    assert "Mantenuta" not in body["explanation"]
    assert "In corso" in body["explanation"]


def test_broken_cannot_become_in_corso(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.app.services.pledge_explanation_service.completer_from_settings",
        lambda settings: FakeTextCompleter(
            "L'obiettivo è ancora In corso e verrà completato presto."
        ),
    )
    client, data, factory = _client(tmp_path)
    _publish(factory, data, FulfillmentVerdict.BROKEN, EvidenceLabel.REFUTES)
    with client:
        body = client.get(f"/proposals/{data.pledge_id}/explanation").json()
    assert body["verdict"] == "broken"
    assert body["public_verdict_label"] == "Non mantenuta"
    assert body["generated_by_ai"] is False
    assert "In corso" not in body["explanation"]


def test_sources_are_only_approved_and_endpoint_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.app.services.pledge_explanation_service.completer_from_settings",
        lambda settings: FakeTextCompleter(
            "Questa promessa riguarda le pensioni. VeraPolitica la classifica come "
            "'In corso' secondo https://evil.example/secret. La valutazione si basa "
            "sull'atto ufficiale già pubblicato e non è conclusa."
        ),
    )
    client, data, factory = _client(tmp_path)
    _publish(factory, data)
    with factory() as session:
        assessments = session.scalar(select(func.count()).select_from(PledgeAssessment))
        drafts = session.scalar(select(func.count()).select_from(PledgeAssessmentDraft))
    with client:
        body = client.get(f"/proposals/{data.pledge_id}/explanation").json()
    assert [item["url"] for item in body["sources"]] == ["https://www.senato.it/legge/1"]
    assert "evil.example" not in body["explanation"]
    assert "evil.example" not in "".join(item["url"] for item in body["sources"])
    assert body["generated_by_ai"] is False
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PledgeAssessment)) == assessments
        assert session.scalar(select(func.count()).select_from(PledgeAssessmentDraft)) == drafts


def test_pending_draft_is_not_treated_as_published_truth(tmp_path):
    client, data, factory = _client(tmp_path)
    service = PledgeService(factory)
    service.classify(data.pledge_id, classification(), classified_by="ed")
    editor_draft(
        service, data, data.pledge_id, FulfillmentVerdict.KEPT, EvidenceLabel.SUPPORTS
    )
    with client:
        body = client.get(f"/proposals/{data.pledge_id}/explanation").json()
    assert body["verdict"] == "not_yet_rated"
    assert body["explanation"] == UNRATED_MESSAGE
    assert body["sources"] == []


def test_production_like_startup_without_llm(tmp_path):
    url = f"sqlite:///{tmp_path / 'prod-explain.db'}"
    engine = create_db_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    settings = Settings(
        env=AppEnvironment.TEST,
        database_url=url,
        raw_storage_path=tmp_path / "raw",
        admin_api_key="test-admin-secret",
        trusted_hosts="testserver",
        llm_provider=None,
        llm_model=None,
        enable_demo_ui=False,
    )
    assert settings.ai_extraction_enabled is False
    app = create_app(settings)
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
    assert live.status_code == 200
    assert ready.status_code == 200
    assert not hasattr(app.state, "ollama")
