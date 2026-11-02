"""Home feed, newsroom posts, proposal tags and the historical archive."""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import (
    EditorialPost,
    GeographicScopeType,
    ImmutableEditorialPostError,
    Legislature,
    Municipality,
    PoliticianSourceIdentifier,
    Proposal,
    ProposalSourceIdentifier,
    ProposalStatus,
    ProposalStatusEvent,
    Referendum,
    ReferendumStatus,
    ReferendumType,
    Region,
    Source,
    TerritoryStatus,
)
from backend.app.pipeline.collectors.camera_history import encode_history_bundle, mandates_query
from backend.app.pipeline.parsers.base import ParserError
from backend.app.pipeline.parsers.camera_history import CameraHistoryParser
from backend.app.services.archive_service import ArchiveService, roman
from tests.services.pledge_seed import NOW, seed

ADMIN = {"Authorization": "Bearer feed-admin"}
CITATION = [{"title": "Gazzetta Ufficiale", "url": "https://www.gazzettaufficiale.it/atto/1"}]


def _territories(factory, data):
    with factory() as session:
        lombardia = Region(
            istat_code="03", canonical_name="Lombardia", status=TerritoryStatus.ACTIVE,
            source_id=data.source_id, raw_document_id=data.raw_document_id,
            source_url="https://www.istat.it",
        )
        lazio = Region(
            istat_code="12", canonical_name="Lazio", status=TerritoryStatus.ACTIVE,
            source_id=data.source_id, raw_document_id=data.raw_document_id,
            source_url="https://www.istat.it",
        )
        session.add_all([lombardia, lazio])
        session.flush()
        towns = [
            Municipality(
                istat_code=code, region_id=region.id, canonical_name=name,
                province_abbreviation=province, province_name=province_name,
                status=TerritoryStatus.ACTIVE, source_id=data.source_id,
                raw_document_id=data.raw_document_id, source_url="https://www.istat.it",
            )
            for code, region, name, province, province_name in (
                ("015146", lombardia, "Milano", "MI", "Milano"),
                ("015002", lombardia, "Abbiategrasso", "MI", "Milano"),
                ("016024", lombardia, "Bergamo", "BG", "Bergamo"),
                ("058091", lazio, "Roma", "RM", "Roma"),
            )
        ]
        session.add_all(towns)
        session.commit()
        return lombardia.id, lazio.id, {town.canonical_name: town.id for town in towns}


def _referendum(factory, title, *, scope, region_id=None, municipality_id=None, vote=date(2027, 3, 1), published=NOW):
    with factory() as session:
        session.add(
            Referendum(
                title=title,
                official_question="Volete voi…?",
                referendum_type=ReferendumType.NATIONAL_ABROGATIVE,
                status=ReferendumStatus.SCHEDULED,
                vote_date=vote,
                scope_type=scope,
                region_id=region_id,
                municipality_id=municipality_id,
                official_source_url="https://dait.interno.gov.it/elezioni",
                published_at=published,
            )
        )
        session.commit()


@pytest.fixture
def world(tmp_path):
    url = f"sqlite:///{tmp_path / 'feed.db'}"
    engine = create_db_engine(url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    data = seed(factory)
    lombardia, lazio, towns = _territories(factory, data)
    with factory() as session:
        session.add(
            ProposalStatusEvent(
                proposal_id=data.bill_id,
                normalized_status=ProposalStatus.APPROVED,
                source_status_label="Approvato dal Senato",
                effective_at=date(2026, 10, 1),
                observed_at=NOW,
                source_id=data.source_id,
                raw_document_id=data.raw_document_id,
                source_url="https://www.senato.it/ddl/123",
                source_field="stato",
                identity_key="e" * 64,
            )
        )
        session.add(
            ProposalSourceIdentifier(
                proposal_id=data.bill_id, source_id=data.source_id,
                official_identifier="DDL 123", source_url="https://www.senato.it/ddl/123",
            )
        )
        bill = session.get(Proposal, data.bill_id)
        bill.current_status = ProposalStatus.APPROVED
        bill.introduced_at = date(2023, 2, 1)
        session.commit()
    _referendum(factory, "Referendum nazionale", scope=GeographicScopeType.NATIONAL)
    _referendum(factory, "Referendum lombardo", scope=GeographicScopeType.REGION, region_id=lombardia)
    _referendum(factory, "Referendum romano", scope=GeographicScopeType.MUNICIPALITY, municipality_id=towns["Roma"])
    _referendum(factory, "Referendum milanese", scope=GeographicScopeType.MUNICIPALITY, municipality_id=towns["Milano"])
    engine.dispose()
    settings = Settings(database_url=url, raw_storage_path=tmp_path / "raw", admin_api_key="feed-admin")
    with TestClient(create_app(settings)) as client:
        yield client, factory, data, lombardia, lazio, towns


def _titles(page):
    return [item["title"] for item in page["items"]]


def test_feed_filters_by_scope_and_reader_zone(world):
    client, factory, data, lombardia, _lazio, towns = world
    with factory() as session:
        # An undated status event is not a feed fact (it would show its import date).
        session.add(
            ProposalStatusEvent(
                proposal_id=data.bill_id, normalized_status=ProposalStatus.INTRODUCED,
                source_status_label="Presentata", effective_at=None, observed_at=NOW,
                source_id=data.source_id, raw_document_id=data.raw_document_id,
                source_url="https://www.senato.it/ddl/123", source_field="stato", identity_key="f" * 64,
            )
        )
        session.commit()

    everything = client.get("/feed").json()
    assert {"DDL 123", "Referendum nazionale", "Referendum lombardo", "Referendum romano"} <= set(_titles(everything))
    statuses = [item for item in everything["items"] if item["kind"] == "proposal_status"]
    assert len(statuses) == 1
    status = statuses[0]
    assert status["detail"].startswith("Proposta approvata")
    assert status["sources"][0]["url"] == "https://www.senato.it/ddl/123"

    mine = _titles(client.get(f"/feed?municipality={towns['Milano']}").json())
    assert "Referendum romano" not in mine  # another region's local item
    assert {"Referendum lombardo", "Referendum milanese", "Referendum nazionale", "DDL 123"} <= set(mine)

    national = _titles(client.get(f"/feed?scope=national&municipality={towns['Milano']}").json())
    assert "Referendum lombardo" not in national and "DDL 123" in national
    regional = _titles(client.get(f"/feed?scope=region&region={lombardia}").json())
    assert regional == ["Referendum lombardo"]
    municipal = _titles(client.get(f"/feed?scope=municipality&province=MI").json())
    assert municipal == ["Referendum milanese"]

    assert client.get("/feed?municipality=9999").status_code == 404
    assert client.get("/feed?province=mi").status_code == 422
    paged = client.get("/feed?limit=1").json()
    assert len(paged["items"]) == 1 and paged["has_more"] is True


def test_newsroom_needs_a_second_person_and_published_posts_are_frozen(world):
    client, factory, _data, _lombardia, _lazio, towns = world
    payload = {
        "title": "Nuovo orario dell'ufficio elettorale",
        "body": "Il Comune di Milano ha pubblicato i nuovi orari dell'ufficio elettorale.",
        "scope": "municipality",
        "municipality_id": towns["Milano"],
        "citations": CITATION,
        "author": "redattrice",
    }
    assert client.post("/admin/editorial/posts", json=payload).status_code == 401
    assert client.post(
        "/admin/editorial/posts", headers=ADMIN, json={**payload, "citations": []}
    ).status_code == 422
    assert client.post(
        "/admin/editorial/posts",
        headers=ADMIN,
        json={**payload, "citations": [{"title": "x", "url": "http://insecure.example"}]},
    ).status_code == 422
    assert client.post(
        "/admin/editorial/posts", headers=ADMIN, json={**payload, "scope": "province", "municipality_id": None}
    ).status_code == 422

    post = client.post("/admin/editorial/posts", headers=ADMIN, json=payload)
    assert post.status_code == 201, post.text
    post = post.json()
    assert post["province_abbreviation"] == "MI" and post["region_id"] is not None
    assert all(item["kind"] != "editorial" for item in client.get("/feed").json()["items"])

    own = client.post(
        f"/admin/editorial/posts/{post['id']}/publish", headers=ADMIN, json={"reviewer": "redattrice"}
    )
    assert own.status_code == 409
    published = client.post(
        f"/admin/editorial/posts/{post['id']}/publish", headers=ADMIN, json={"reviewer": "caporedattore"}
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    again = client.post(
        f"/admin/editorial/posts/{post['id']}/publish", headers=ADMIN, json={"reviewer": "altro"}
    )
    assert again.status_code == 409

    milan = client.get(f"/feed?municipality={towns['Milano']}").json()
    editorial = next(item for item in milan["items"] if item["kind"] == "editorial")
    assert editorial["municipality_name"] == "Milano"
    assert editorial["sources"] == CITATION
    rome = client.get(f"/feed?municipality={towns['Roma']}").json()
    assert all(item["kind"] != "editorial" for item in rome["items"])
    assert client.get(f"/feed/posts/{post['id']}").json()["title"] == payload["title"]

    with factory() as session:
        row = session.get(EditorialPost, post["id"])
        row.body = "Testo cambiato in silenzio, senza rettifica pubblica."
        with pytest.raises(ImmutableEditorialPostError):
            session.commit()

    correction = client.post(
        "/admin/editorial/posts", headers=ADMIN, json={**payload, "corrects_id": post["id"]}
    )
    assert correction.status_code == 201
    rejected = client.post(
        f"/admin/editorial/posts/{correction.json()['id']}/reject", headers=ADMIN, json={}
    )
    assert rejected.status_code == 422  # a rejection needs a note
    listing = client.get("/admin/editorial/posts?status=pending", headers=ADMIN).json()
    assert [item["id"] for item in listing["items"]] == [correction.json()["id"]]


def test_tags_are_controlled_and_filter_proposals(world):
    client, _factory, data, *_ = world
    vocabularies = client.get("/proposals/tags").json()
    assert {"value": "legge_bilancio", "label": "Legge di bilancio"} in vocabularies["dossiers"]

    bad = client.put(f"/admin/proposals/{data.bill_id}/tags", headers=ADMIN, json={"topics": ["11"]})
    assert bad.status_code == 422
    assert client.put("/admin/proposals/999/tags", headers=ADMIN, json={"topics": ["1"]}).status_code == 404
    tags = client.put(
        f"/admin/proposals/{data.bill_id}/tags",
        headers=ADMIN,
        json={"topics": ["1"], "dossiers": ["legge_bilancio"]},
    )
    assert tags.status_code == 200, tags.text
    assert [tag["label"] for tag in tags.json()] == ["Legge di bilancio", "Economia"]

    budget = client.get("/proposals?dossier=legge_bilancio").json()
    assert [item["id"] for item in budget["items"]] == [data.bill_id]
    assert budget["items"][0]["tags"][0]["value"] == "legge_bilancio"
    assert client.get("/proposals?topic=13").json()["total"] == 0
    assert client.get("/proposals?introduced_from=2023-01-01&introduced_to=2023-12-31").json()["total"] == 1

    client.put(f"/admin/proposals/{data.bill_id}/tags", headers=ADMIN, json={"topics": ["5"]})
    assert client.get("/proposals?dossier=legge_bilancio").json()["total"] == 0
    assert [tag["value"] for tag in client.get(f"/proposals/{data.bill_id}").json()["tags"]] == ["5"]


def _sparql(rows):
    return json.dumps({"head": {"vars": []}, "results": {"bindings": rows}}).encode()


def _literal(value):
    return {"type": "literal", "value": value}


HISTORY = encode_history_bundle(
    _sparql(
        [
            {"legislatureUri": {"type": "uri", "value": "http://dati.camera.it/ocd/legislatura.rdf/repubblica_1"},
             "startDate": _literal("19480508"), "endDate": _literal("19530624")},
            {"legislatureUri": {"type": "uri", "value": "http://dati.camera.it/ocd/legislatura.rdf/regno_25"},
             "startDate": _literal("19190601")},
        ]
    ),
    {
        1: _sparql(
            [
                {
                    "personUri": {"type": "uri", "value": "http://dati.camera.it/ocd/persona.rdf/p200"},
                    "deputyUri": {"type": "uri", "value": "http://dati.camera.it/ocd/deputato.rdf/d200_1"},
                    "mandateUri": {"type": "uri", "value": "http://dati.camera.it/ocd/mandatoCamera.rdf/mc200_1"},
                    "firstName": _literal("ALCIDE"),
                    "lastName": _literal("DE GASPERI"),
                    "mandateStart": _literal("19480508"),
                    "mandateEnd": _literal("19530624"),
                    "electionArea": _literal("TRENTO"),
                },
                {
                    "personUri": {"type": "uri", "value": "http://dati.camera.it/ocd/persona.rdf/p300"},
                    "mandateUri": {"type": "uri", "value": "http://dati.camera.it/ocd/mandatoCamera.rdf/mc300_1"},
                    "firstName": _literal("NILDE"),
                    "lastName": _literal("IOTTI"),
                    "mandateStart": _literal("19480508"),
                },
            ]
        )
    },
)


def test_camera_history_parser_and_archive_endpoints(world):
    client, factory, data, lombardia, *_ = world
    assert "repubblica_19" in mandates_query(19) and "endDate" in mandates_query(19)
    parsed = CameraHistoryParser().parse(HISTORY)
    kinds = [record["kind"] for record in parsed.structured_records]
    assert kinds == ["legislature", "mandate", "mandate"]  # Kingdom row ignored
    assert parsed.structured_records[1]["family_name"] == "De Gasperi"
    with pytest.raises(ParserError):
        CameraHistoryParser().parse(b'{"schema": "other"}')

    with factory() as session:
        camera = Source(key="camera-deputati", name="Camera", base_url="https://dati.camera.it")
        session.add(camera)
        session.flush()
        session.add(
            PoliticianSourceIdentifier(
                politician_id=data.politician_id,
                source_id=camera.id,
                value="http://dati.camera.it/ocd/deputato.rdf/d200_19",
            )
        )
        session.commit()
        camera_id = camera.id
    archive = ArchiveService(factory)
    assert archive.load_legislature_fixture() == 0  # the SQLite app start seeded them
    sync = archive.sync_camera_history(
        parsed.structured_records,
        source_id=data.source_id,
        profile_source_id=camera_id,
        raw_document_id=data.raw_document_id,
        source_url="https://dati.camera.it/sparql",
    )
    assert (sync.mandates_created, sync.mandates_linked) == (2, 1)
    again = archive.sync_camera_history(
        parsed.structured_records,
        source_id=data.source_id,
        profile_source_id=camera_id,
        raw_document_id=data.raw_document_id,
        source_url="https://dati.camera.it/sparql",
    )
    assert again.mandates_unchanged == 2
    with factory() as session:
        assert session.get(Legislature, 1).source_url.endswith("repubblica_1")

    eras = client.get("/archive/legislatures").json()["eras"]
    assert [era["era"] for era in eras] == ["costituente", "prima_repubblica", "seconda_repubblica"]
    first = eras[1]["legislatures"][0]
    assert (first["roman"], first["camera_mandates"]) == ("I", 2)
    assert eras[2]["legislatures"][0]["label"] == "XII legislatura"

    detail = client.get("/archive/legislatures/19").json()
    assert detail["previous"] == 18 and detail["next"] is None
    assert detail["published_proposals"] == 1
    assert "Referendum nazionale" in [item["title"] for item in detail["referendums"]]
    assert client.get("/archive/legislatures/42").status_code == 404

    roster = client.get("/archive/parliamentarians?legislature=1&q=gasp").json()
    assert roster["total"] == 1
    assert roster["items"][0]["politician_id"] == data.politician_id
    assert roster["items"][0]["election_area"] == "TRENTO"
    assert client.get("/archive/parliamentarians?chamber=senato").json()["total"] == 0

    provinces = client.get(f"/archive/provinces?region={lombardia}").json()
    assert [(item["abbreviation"], item["municipalities"]) for item in provinces["items"]] == [
        ("BG", 1),
        ("MI", 2),
    ]
    in_milan = client.get("/municipalities?province=MI").json()
    assert sorted(item["name"] for item in in_milan["items"]) == ["Abbiategrasso", "Milano"]
    milan = client.get("/archive/provinces/MI").json()
    assert milan["name"] == "Milano"
    assert [item["title"] for item in milan["referendums"]] == ["Referendum milanese"]
    region = client.get(f"/archive/regions/{lombardia}").json()
    assert {item["title"] for item in region["referendums"]} == {"Referendum lombardo", "Referendum milanese"}
    assert "56/2014" in region["coverage_note"]
    assert client.get("/archive/provinces/ZZ").status_code == 404


def test_roman_numerals():
    assert [roman(n) for n in (1, 4, 9, 11, 14, 19)] == ["I", "IV", "IX", "XI", "XIV", "XIX"]



def test_camera_history_collector_stores_every_response():
    import httpx

    from backend.app.pipeline.collectors.camera_history import CameraHistoryCollector

    seen = []

    def handler(request):
        query = request.url.params["query"]
        seen.append(query)
        legislatures = json.loads(base64_bundle()["legislatures"])
        body = legislatures if "ocd:legislatura ;" in query else json.loads(base64_bundle()["1"])
        return httpx.Response(200, json=body)

    collector = CameraHistoryCollector(
        "https://dati.camera.it/sparql", [1], client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    document = collector.collect()
    assert len(seen) == 2
    records = CameraHistoryParser().parse(document.content).structured_records
    assert [record["kind"] for record in records] == ["legislature", "mandate", "mandate"]
    with pytest.raises(ValueError):
        CameraHistoryCollector("https://dati.camera.it/sparql", [0])


def base64_bundle():
    import base64

    bundle = json.loads(HISTORY)
    return {
        "legislatures": base64.b64decode(bundle["legislatures_response_base64"]),
        **{key: base64.b64decode(value) for key, value in bundle["mandate_responses_base64"].items()},
    }


def test_robots_and_sitemap(world):
    client, *_ = world
    robots = client.get("/robots.txt").text
    assert "Disallow: /admin/" in robots and "Sitemap: http://testserver/sitemap.xml" in robots
    sitemap = client.get("/sitemap.xml")
    assert sitemap.headers["content-type"].startswith("application/xml")
    assert "http://testserver/app/?view=politics" in sitemap.text
    assert "?legislature=19" in sitemap.text
