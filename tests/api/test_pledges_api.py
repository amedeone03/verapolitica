from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from tests.services.pledge_seed import add_extra_pledges, seed

ADMIN = {"Authorization": "Bearer pledge-admin"}
EXCERPT = "approvato in via definitiva la legge che aumenta le pensioni minime"


def _client(tmp_path, *, publish_politician=True):
    url = f"sqlite:///{tmp_path / 'pledges-api.db'}"
    engine = create_db_engine(url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    data = seed(factory, publish_politician=publish_politician)
    extra = add_extra_pledges(factory, data, 8)
    engine.dispose()
    settings = Settings(
        database_url=url, raw_storage_path=tmp_path / "raw", admin_api_key="pledge-admin"
    )
    return TestClient(create_app(settings)), data, extra


CLASSIFICATION = {
    "specificity": "high",
    "commitment_type": "action",
    "holder_role": "government_coalition",
    "cap_topic_code": "13",
    "mandate_start": "2022-10-13",
    "mandate_end": "2027-10-13",
}


def _draft(client, data, proposal_id, verdict="kept", label="supports"):
    response = client.post(
        f"/admin/pledges/{proposal_id}/assessment-drafts",
        headers=ADMIN,
        json={
            "verdict": verdict,
            "evidence_label": label,
            "rationale": "Atto approvato.",
            "quoted_excerpt": EXCERPT,
            "raw_document_id": data.raw_document_id,
            "document_chunk_id": data.chunk_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_admin_pledge_workflow_and_public_scorecard(tmp_path):
    test_client, data, extra = _client(tmp_path)
    with test_client as client:
        _run_workflow(client, data, extra)


def _run_workflow(client, data, extra):

    assert client.put(f"/admin/pledges/{data.pledge_id}/classification", json=CLASSIFICATION).status_code == 401
    assert client.put(
        f"/admin/pledges/{data.bill_id}/classification", headers=ADMIN, json=CLASSIFICATION
    ).status_code == 404

    for proposal_id in (data.pledge_id, *extra):
        response = client.put(
            f"/admin/pledges/{proposal_id}/classification", headers=ADMIN, json=CLASSIFICATION
        )
        assert response.status_code == 200, response.text

    bad = client.post(
        f"/admin/pledges/{data.pledge_id}/assessment-drafts",
        headers=ADMIN,
        json={
            "verdict": "kept",
            "evidence_label": "refutes",
            "rationale": "x",
            "quoted_excerpt": EXCERPT,
            "raw_document_id": data.raw_document_id,
        },
    )
    assert bad.status_code == 422

    # The shared admin credential proposed it, so it must approve under another name.
    draft = _draft(client, data, data.pledge_id)
    self_approval = client.post(
        f"/admin/pledges/assessment-drafts/{draft['id']}/approve", headers=ADMIN, json={}
    )
    assert self_approval.status_code == 409
    approved = client.post(
        f"/admin/pledges/assessment-drafts/{draft['id']}/approve",
        headers=ADMIN,
        json={"reviewer": "caporedattore"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["published"]["verdict"] == "kept"

    broken = _draft(client, data, extra[0], verdict="broken", label="refutes")
    first = client.post(
        f"/admin/pledges/assessment-drafts/{broken['id']}/approve",
        headers=ADMIN,
        json={"reviewer": "rev-1"},
    ).json()
    assert first["draft"]["status"] == "awaiting_second_approval"
    assert first["published"] is None
    second = client.post(
        f"/admin/pledges/assessment-drafts/{broken['id']}/approve",
        headers=ADMIN,
        json={"reviewer": "rev-2"},
    ).json()
    assert second["published"]["verdict"] == "broken"

    for proposal_id in extra[1:]:
        item = _draft(client, data, proposal_id)
        client.post(
            f"/admin/pledges/assessment-drafts/{item['id']}/approve",
            headers=ADMIN,
            json={"reviewer": "caporedattore"},
        )

    scorecard = client.get(f"/politicians/{data.politician_id}/scorecard?as_of=2026-10-07")
    assert scorecard.status_code == 200, scorecard.text
    body = scorecard.json()
    assert list(body)[:5] == ["politician_id", "methodology_version", "methodology_url", "as_of", "pledges"]
    assert body["methodology_version"] == "pledge-score/v1"
    assert body["unclassified_pledges"] == 1  # the outcome pledge was never classified
    (stratum,) = body["strata"]
    assert stratum["closed_pledges"] == 9
    assert stratum["rate"] == round(8 / 9, 4)
    assert stratum["credible_interval"][0] < stratum["rate"] < stratum["credible_interval"][1]
    composition = {entry["verdict"]: entry["count"] for entry in stratum["composition"]}
    assert composition["kept"] == 8 and composition["broken"] == 1

    methodology = client.get("/methodology/scoring").json()
    assert methodology["version"] == "pledge-score/v1"
    assert methodology["min_closed_for_rate"] == 8

    sample = client.post(
        "/admin/pledges/audit-samples",
        headers=ADMIN,
        json={"sample_key": "q4", "size": 3, "seed": 5},
    )
    assert sample.status_code == 201, sample.text
    items = sample.json()["items"]
    assert len(items) == 3 and "verdict" not in items[0]
    coded = client.post(
        f"/admin/pledges/audit-samples/q4/codings/{items[0]['assessment_id']}",
        headers=ADMIN,
        json={"verdict": "kept", "coder": "auditor"},
    )
    assert coded.status_code == 204, coded.text
    quality = client.get("/admin/pledges/audit-samples/q4/quality", headers=ADMIN)
    assert quality.status_code == 200 and quality.json()["coded_items"] == 1
    assert client.get("/admin/pledges/bias-audit", headers=ADMIN).status_code == 200
    drafts = client.get("/admin/pledges/assessment-drafts?status=approved", headers=ADMIN)
    assert len(drafts.json()) == 9


def test_public_scorecard_requires_published_politician(tmp_path):
    test_client, data, _extra = _client(tmp_path, publish_politician=False)
    with test_client as client:
        assert client.get(f"/politicians/{data.politician_id}/scorecard").status_code == 404
        assert client.get("/politicians/999999/scorecard").status_code == 404


def test_admin_draft_shows_commitment_versus_evidence_and_matching_does_not_publish(tmp_path):
    test_client, data, _extra = _client(tmp_path)
    with test_client as client:
        client.put(
            f"/admin/pledges/{data.pledge_id}/classification",
            headers=ADMIN,
            json=CLASSIFICATION,
        )
        draft = _draft(client, data, data.pledge_id)
        detail = client.get(f"/admin/pledges/assessment-drafts/{draft['id']}", headers=ADMIN)
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["commitment_title"]
        assert body["quoted_excerpt"]
        assert body["source_url"]
        assert body["status"] == "pending"
        before = client.get(f"/politicians/{data.politician_id}/scorecard").json()
        assert before["pledges"][0]["latest_assessment"] is None
        matching = client.post(
            f"/admin/pledges/{data.pledge_id}/evidence-matching?dry_run=true&judge=abstaining",
            headers=ADMIN,
        )
        assert matching.status_code == 200, matching.text
        assert matching.json()["published"] is False
        candidates = client.get(
            f"/admin/pledges/{data.pledge_id}/evidence-candidates", headers=ADMIN
        )
        assert candidates.status_code == 200
        after = client.get(f"/politicians/{data.politician_id}/scorecard").json()
        assert after["pledges"][0]["latest_assessment"] is None
        assert after["methodology_version"] == "pledge-score/v1"
