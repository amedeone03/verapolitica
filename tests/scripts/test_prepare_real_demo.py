from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.pipeline.collectors import GovernoCollector
from backend.app.pipeline.collectors.base import CollectedDocument
from backend.app.pipeline.pledge_candidates import select_pledge_candidates
from scripts.prepare_real_demo import PROGRAMME_URL, prepare_real_demo

FIXTURE = Path("data/fixtures/governo/governo_office_holders.json")

PROGRAMME_HTML = """<html><body><article>
<h1>Le dichiarazioni programmatiche (fixture)</h1>
<p>Signor Presidente, onorevoli colleghi, è un onore essere qui oggi davanti a voi.</p>
<p>Intendiamo ridurre il cuneo fiscale di cinque punti a favore dei lavoratori nel corso della legislatura. Vogliamo una Nazione orgogliosa del proprio futuro e del proprio destino.</p>
<p>Ci impegneremo a introdurre una riforma della giustizia civile che dimezzi i tempi dei processi.</p>
<p>Porteremo la banda ultralarga in tutti i comuni con un piano di investimenti da 3 miliardi di euro.</p>
<p>Introdurremo un assegno unico rafforzato per le famiglie con figli e una legge sulla natalità.</p>
<p>Siete d'accordo con noi su questo percorso?</p>
</article></body></html>"""


class FixtureGovernoCollector:
    def collect(self) -> CollectedDocument:
        return CollectedDocument(
            content=FIXTURE.read_bytes(),
            source_url="https://www.governo.it/it/ministri-e-sottosegretari",
            content_type=GovernoCollector.response_media_type,
            retrieved_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
            collector_version="fixture",
        )


def fetch(url):
    assert url == PROGRAMME_URL
    return PROGRAMME_HTML.encode("utf-8"), "text/html"


def test_candidate_selection_is_verbatim_and_skips_rhetoric():
    text = PROGRAMME_HTML
    picked = select_pledge_candidates(
        "Intendiamo ridurre il cuneo fiscale di cinque punti a favore dei lavoratori nel corso della legislatura. "
        "Vogliamo una Nazione orgogliosa del proprio futuro e del proprio destino."
    )
    assert [c.sentence for c in picked] == [
        "Intendiamo ridurre il cuneo fiscale di cinque punti a favore dei lavoratori nel corso della legislatura."
    ]
    assert picked[0].topic_code == "5"
    assert all(c.sentence in text for c in select_pledge_candidates(text))


def test_real_demo_publishes_official_profiles_and_unrated_commitments(tmp_path):
    report = prepare_real_demo(
        workspace_root=tmp_path, collector=FixtureGovernoCollector(), fetch=fetch
    )
    assert report.politicians_collected == 4
    assert len(report.profiles_published) == 2  # PM and minister; undersecretaries stay drafts
    assert report.profiles_pending_review == 1  # the other one has no birth date to bootstrap safely
    assert any("Carlo Verdi" in warning for warning in report.warnings)
    assert report.commitment_owner == "Mario Rossi"
    assert len(report.commitments_published) == 4
    assert (tmp_path / "data/demo/real_demo_report.json").is_file()

    settings = Settings(
        database_url=f"sqlite:///{report.database_path}",
        raw_storage_path=tmp_path / "data/demo/raw",
    )
    with TestClient(create_app(settings)) as client:
        people = client.get("/politicians").json()
        names = {f"{p['given_name']} {p['family_name']}" for p in people["items"]}
        assert names == {"Mario Rossi", "Lucia Bianchi"}
        pm = next(p for p in people["items"] if p["family_name"] == "Rossi")
        card = client.get(f"/politicians/{pm['id']}/scorecard").json()
    assert card["tracked_pledges"] == 4
    assert {p["verdict"] for p in card["pledges"]} == {"not_yet_rated"}
    (stratum,) = card["strata"]
    assert stratum["role"] == "government_coalition"
    assert stratum["rate"] is None and stratum["rate_withheld_reason"] == "no_closed_pledges"
    assert all(p["exact_statement"] in PROGRAMME_HTML for p in card["pledges"])
