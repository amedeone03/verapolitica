import base64
import json
from datetime import datetime, timezone

from sqlalchemy import select

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import EditorialChangeRequest, PoliticalParty
from backend.app.services.redazione.service import RedazioneService
from scripts import sync_symbols

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _binding(**values):
    return {key: {"value": value} for key, value in values.items()}


def _fake_network(licences):
    party_rows = [
        _binding(item="http://www.wikidata.org/entity/Q1", label="Partito Esempio", short="PE",
                 image="http://commons.wikimedia.org/wiki/Special:FilePath/Logo%20PE.svg"),
        _binding(item="http://www.wikidata.org/entity/Q2", label="Partito Chiuso",
                 image="http://commons.wikimedia.org/wiki/Special:FilePath/Logo%20PC.png"),
    ]
    calls = []

    def get(url: str) -> bytes:
        calls.append(url)
        if url.startswith(sync_symbols.WIKIDATA_SPARQL):
            return json.dumps({"results": {"bindings": party_rows}}).encode()
        if url.startswith(sync_symbols.COMMONS_API):
            file = "Logo PE.svg" if "Logo+PE" in url else "Logo PC.png"
            info = {
                "url": f"https://upload.wikimedia.org/{file}",
                "thumburl": f"https://upload.wikimedia.org/thumb/{file}.png",
                "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{file}",
                "extmetadata": {"LicenseShortName": {"value": licences[file]}, "Artist": {"value": "<a href='x'>Partito</a>"}},
            }
            return json.dumps({"query": {"pages": {"1": {"imageinfo": [info]}}}}).encode()
        return PNG

    return get, calls


def test_sync_proposes_only_free_logos_and_waits_for_the_redazione(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'sync.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        session.add_all([
            PoliticalParty(canonical_name="Partito Esempio", abbreviation="PE"),
            PoliticalParty(canonical_name="Partito Chiuso", abbreviation="PC"),
            PoliticalParty(canonical_name="Partito Senza Wikidata"),
        ])
    service = RedazioneService(factory, clock=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
    get, _ = _fake_network({"Logo PE.svg": "CC BY-SA 4.0", "Logo PC.png": "Fair use"})

    dry = sync_symbols.sync(service, get, ("party",), dry_run=True)
    assert len(dry.proposed) == 1
    with factory() as session:
        assert session.scalar(select(EditorialChangeRequest)) is None

    report = sync_symbols.sync(service, get, ("party",))
    assert [line.split(" ←")[0] for line in report.proposed] == ["party: Partito Esempio"]
    assert any("licenza non libera: Fair use" in line for line in report.skipped)
    assert any("Partito Senza Wikidata" in line for line in report.unmatched)
    with factory() as session:
        request = session.scalar(select(EditorialChangeRequest))
        assert request.kind == "simbolo" and request.created_by == sync_symbols.AUTHOR
        assert request.payload["license"] == "cc-by-sa" and request.payload["credit"] == "Partito"
        assert request.payload["source_url"] == "https://commons.wikimedia.org/wiki/File:Logo PE.svg"
    # Nothing is public yet, and a second run does not propose the same logo twice.
    state = service.symbols()
    assert all(item["symbol"] is None for item in state["party"])
    assert sync_symbols.sync(service, get, ("party",)).proposed == []
    engine.dispose()


def test_regions_match_bilingual_istat_names():
    rows = [_binding(item="Q1", label="Trentino-Alto Adige", image="http://x/Stemma.svg")]
    found, missing = sync_symbols.match("region", rows, [{"key": "4", "name": "Trentino-Alto Adige/Südtirol"}])
    assert [(item.key, item.file) for item in found] == [("4", "Stemma.svg")] and not missing
    rows = [_binding(item="Q2", label="Provincia di Milano", code="MI", image="http://x/MI.svg")]
    found, _ = sync_symbols.match("province", rows, [{"key": "MI", "name": "Milano"}])
    assert found[0].file == "MI.svg"
    assert sync_symbols.licence_of({"LicenseShortName": {"value": "Public domain"}}) == "pubblico-dominio"
    assert sync_symbols.licence_of({"LicenseShortName": {"value": "CC BY-NC 4.0"}}) is None



def test_parties_in_parliament_become_proposals(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'parties.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        session.add(PoliticalParty(canonical_name="Partito Esempio", abbreviation="PE"))
    service = RedazioneService(factory, clock=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
    rows = [
        _binding(party="http://www.wikidata.org/entity/Q1", label="Partito Esempio"),
        _binding(party="http://www.wikidata.org/entity/Q3", label="Lista Nuova", short="LN", site="https://lista.example.org"),
        _binding(party="http://www.wikidata.org/entity/Q3", label="Lista Nuova", short="LN", site="https://lista.example.org"),
        _binding(party="http://www.wikidata.org/entity/Q4", label="Altro Gruppo", site="http://insecure.example.org"),
    ]

    def get(url: str) -> bytes:
        assert url.startswith(sync_symbols.WIKIDATA_SPARQL)
        return json.dumps({"results": {"bindings": rows}}).encode()

    report = sync_symbols.propose_parties(service, get)
    assert report.proposed == ["partito: Lista Nuova", "partito: Altro Gruppo"]
    with factory() as session:
        requests = {row.payload["name"]: row for row in session.scalars(select(EditorialChangeRequest))}
    assert requests["Lista Nuova"].payload == {
        "name": "Lista Nuova", "abbreviation": "LN", "website": "https://lista.example.org",
        "source_url": "https://www.wikidata.org/wiki/Q3",
    }
    assert requests["Altro Gruppo"].payload["website"] is None
    assert requests["Lista Nuova"].created_by == sync_symbols.AUTHOR
    # Pending proposals are not proposed twice; nothing is in the list until approved.
    assert sync_symbols.propose_parties(service, get).proposed == []
    assert [item["name"] for item in service.symbols()["party"]] == ["Partito Esempio"]
    engine.dispose()


def test_http_get_waits_on_rate_limit(monkeypatch):
    import io
    import urllib.error

    calls, waits = [], []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) < 3:
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {"Retry-After": "2"}, None)
        return Response(b"{}")

    monkeypatch.setattr(sync_symbols.urllib.request, "urlopen", fake_urlopen)
    assert sync_symbols.http_get(sync_symbols.WIKIDATA_SPARQL + "?q", sleep=waits.append) == b"{}"
    assert waits == [2, 2] and len(calls) == 3
