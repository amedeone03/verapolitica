import json
from datetime import datetime, timezone

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.services.redazione.service import RedazioneService
from scripts import seed_government_parties as seed_module, sync_symbols
from test_sync_symbols import PNG, _binding


def test_government_parties_go_through_the_redazione_flow(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'gov.db'}")
    Base.metadata.create_all(engine)
    service = RedazioneService(create_session_factory(engine), clock=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
    rows = [
        _binding(item="http://www.wikidata.org/entity/Q1", label="Partito Uno", short="P1", site="https://uno.example.org",
                 logo="http://commons.wikimedia.org/wiki/Special:FilePath/Uno.svg"),
        _binding(item="http://www.wikidata.org/entity/Q2", label="Partito Due",
                 logo="http://commons.wikimedia.org/wiki/Special:FilePath/Due.png"),
    ]

    def get(url: str) -> bytes:
        if url.startswith(sync_symbols.WIKIDATA_SPARQL):
            return json.dumps({"results": {"bindings": rows}}).encode()
        if url.startswith(sync_symbols.COMMONS_API):
            free = "Uno.svg" in url
            info = {
                "url": "https://upload.wikimedia.org/x.png", "descriptionurl": "https://commons.wikimedia.org/wiki/File:x",
                "extmetadata": {"LicenseShortName": {"value": "Public domain" if free else "Fair use"}},
            }
            return json.dumps({"query": {"pages": {"1": {"imageinfo": [info]}}}}).encode()
        return PNG

    report = seed_module.seed(service, get, approver="Direzione", names=("Partito Uno", "Partito Due", "Partito Tre"))
    assert report.proposed == ["partito: Partito Uno", "logo: Partito Uno [pubblico-dominio]", "partito: Partito Due"]
    assert any("Partito Tre" in line for line in report.unmatched)
    assert any("logo: Partito Due" in line and "Fair use" in line for line in report.unmatched)
    parties = {item["name"]: item for item in service.symbols()["party"]}
    assert parties["Partito Uno"]["abbreviation"] == "P1" and parties["Partito Uno"]["symbol"]["approved_by"] == "Direzione"
    assert parties["Partito Due"]["symbol"] is None
    log = [entry["summary"] for entry in service.log_entries()["items"]]
    assert any("Aggiunto all'elenco: Partito Uno" in line for line in log)
    # Idempotent: a second run changes nothing.
    again = seed_module.seed(service, get, approver="Direzione", names=("Partito Uno",))
    assert again.proposed == [] and "partito: Partito Uno (già nell'elenco)" in again.skipped
    engine.dispose()


def test_parliament_seed_includes_opposition_and_electoral_lists():
    assert "Partito Democratico" in seed_module.PARLIAMENT_PARTIES
    assert "Movimento 5 Stelle" in seed_module.PARLIAMENT_PARTIES
    assert "Alleanza Verdi e Sinistra" in seed_module.OPPOSITION_PARTIES
    assert "wd:Q388602" in seed_module.QUERY
