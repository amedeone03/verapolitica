from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.scoring.types import EvidenceLabel, FulfillmentVerdict
from backend.app.services.pledge_service import PledgeService
from tests.services.pledge_seed import seed
from tests.services.test_pledge_service import classification, editor_draft


def _client(tmp_path):
    url = f"sqlite:///{tmp_path / 'pledge-review.db'}"
    engine = create_db_engine(url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    data = seed(factory)
    engine.dispose()
    settings = Settings(
        database_url=url,
        raw_storage_path=tmp_path / "raw",
        enable_demo_ui=True,
        admin_api_key="pledge-review-admin",
        admin_reviewer_identity="editor-reviewer",
    )
    return TestClient(create_app(settings)), data, factory


def test_pledge_review_page_shows_commitment_versus_official_evidence(tmp_path):
    client, data, factory = _client(tmp_path)
    service = PledgeService(factory)
    service.classify(data.pledge_id, classification(), classified_by="ed")
    editor_draft(
        service,
        data,
        data.pledge_id,
        FulfillmentVerdict.IN_PROGRESS,
        EvidenceLabel.SUPPORTS,
        by="system:pledge-evidence-matcher",
    )
    with client:
        page = client.get("/demo/pledge-review")
        assert page.status_code == 200
        assert "Commitment" in page.text
        assert "Official evidence" in page.text
        assert "Proposed FEVER label" in page.text
        assert "Proposed verdict" in page.text
        assert "Exact quote" in page.text
        assert "Official evidence" in page.text
        assert "Approve" in page.text
        assert "Reject" in page.text
        assert "Aumenteremo le pensioni minime" in page.text
        assert "https://www.senato.it/legge/1" in page.text


def test_demo_reject_does_not_publish(tmp_path):
    client, data, factory = _client(tmp_path)
    service = PledgeService(factory)
    service.classify(data.pledge_id, classification(), classified_by="ed")
    draft, _ = editor_draft(
        service,
        data,
        data.pledge_id,
        FulfillmentVerdict.IN_PROGRESS,
        EvidenceLabel.SUPPORTS,
        by="system:pledge-evidence-matcher",
    )
    with client:
        rejected = client.post(
            f"/demo/pledge-review/{draft.id}/reject",
            data={
                "note": (
                    "Retrieved official evidence concerns autonomia differenziata "
                    "and does not support the judicial-system commitment."
                )
            },
            follow_redirects=True,
        )
        assert rejected.status_code == 200
        assert "rejected" in rejected.text.lower()
        scorecard = service.scorecard_for_politician(data.politician_id)
        assert scorecard.pledges[0].latest_assessment is None
        assert scorecard.pledges[0].verdict is FulfillmentVerdict.NOT_YET_RATED
