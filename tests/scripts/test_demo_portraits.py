import json

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from scripts.demo_portraits import COMMONS_API, WIKIDATA_API, build_portraits


def entity(qid, *, human=True, italian=True, politician=True, image="Ritratto.jpg", description="politico italiano"):
    def claim(prop, value):
        return {prop: [{"mainsnak": {"datavalue": {"value": value}}}]}
    claims = {}
    if human:
        claims |= claim("P31", {"id": "Q5"})
    if italian:
        claims |= claim("P27", {"id": "Q38"})
    if politician:
        claims |= claim("P106", {"id": "Q82955"})
    if image:
        claims |= claim("P18", image)
    return {"id": qid, "claims": claims, "descriptions": {"it": {"value": description}}}


def fake(search_results, entities):
    calls = []

    def get_json(url, params):
        calls.append((url, params.get("action")))
        if url == WIKIDATA_API and params["action"] == "wbsearchentities":
            return {"search": search_results.get(params["search"], [])}
        if url == WIKIDATA_API and params["action"] == "wbgetentities":
            return {"entities": {i: entities[i] for i in params["ids"].split("|") if i in entities}}
        if url == COMMONS_API:
            return {"query": {"pages": {"1": {"imageinfo": [{
                "url": "https://upload.wikimedia.org/full.jpg",
                "thumburl": "https://upload.wikimedia.org/thumb.jpg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Ritratto.jpg",
                "extmetadata": {
                    "Artist": {"value": "<a href='x'>Ufficio Stampa</a>"},
                    "LicenseShortName": {"value": "CC BY 3.0 IT"},
                },
            }]}}}}
        raise AssertionError(url)
    return get_json, calls


PEOPLE = [
    {"id": 1, "name": "Giorgia Meloni", "given_name": "Giorgia", "family_name": "Meloni",
     "image_url": "https://www.governo.it/meloni.jpg", "source_name": "Governo Italiano",
     "source_url": "https://www.governo.it/meloni"},
    {"id": 2, "name": "Guido Crosetto", "given_name": "Guido", "family_name": "Crosetto", "image_url": None},
    {"id": 3, "name": "Mario Bianchi", "given_name": "Mario", "family_name": "Bianchi", "image_url": None},
    {"id": 4, "name": "Eugenia Maria Roccella", "given_name": "Eugenia Maria", "family_name": "Roccella", "image_url": None},
]


def test_portraits_prefer_official_then_unambiguous_commons():
    get_json, calls = fake(
        {
            "Guido Crosetto": [{"id": "Q1", "label": "Guido Crosetto"}],
            # Two Italian politicians with the same name: ambiguous, no photo.
            "Mario Bianchi": [{"id": "Q2", "label": "Mario Bianchi"}, {"id": "Q3", "label": "Mario Bianchi"}],
            # Full name unknown, short name matches.
            "Eugenia Roccella": [{"id": "Q4", "label": "Eugenia Roccella"}],
        },
        {"Q1": entity("Q1"), "Q2": entity("Q2"), "Q3": entity("Q3"), "Q4": entity("Q4")},
    )
    portraits = build_portraits(PEOPLE, get_json=get_json)
    assert portraits["1"]["origin"] == "Governo Italiano"
    assert portraits["2"] == {
        "url": "https://upload.wikimedia.org/thumb.jpg",
        "credit": "Ufficio Stampa",
        "license": "CC BY 3.0 IT",
        "source_url": "https://commons.wikimedia.org/wiki/File:Ritratto.jpg",
        "origin": "Wikimedia Commons",
    }
    assert "3" not in portraits
    assert "4" in portraits
    assert not any(url for url, _ in calls if "governo" in url)


def test_portraits_reject_non_politicians_and_foreign_namesakes():
    get_json, _ = fake(
        {"Guido Crosetto": [{"id": "Q9", "label": "Guido Crosetto"}]},
        {"Q9": entity("Q9", italian=False)},
    )
    assert build_portraits(PEOPLE[1:2], get_json=get_json) == {}
    get_json, _ = fake(
        {"Guido Crosetto": [{"id": "Q9", "label": "Guido Crosetto"}]},
        {"Q9": entity("Q9", politician=False, description="calciatore italiano")},
    )
    assert build_portraits(PEOPLE[1:2], get_json=get_json) == {}


def test_portraits_endpoint_serves_only_valid_https_entries(tmp_path):
    path = tmp_path / "portraits.json"
    path.write_text(json.dumps({
        "2": {"url": "https://upload.wikimedia.org/thumb.jpg", "credit": "A", "license": "CC BY 4.0",
              "source_url": "https://commons.wikimedia.org/x", "origin": "Wikimedia Commons"},
        "3": {"url": "javascript:alert(1)", "credit": "A", "license": "x", "source_url": "x", "origin": "x"},
        "bad": {"url": "https://x"},
    }), "utf-8")
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'p.db'}", portraits_path=path)
    with TestClient(create_app(settings)) as client:
        body = client.get("/portraits").json()
    assert list(body) == ["2"]
    with TestClient(create_app(Settings(database_url=f"sqlite:///{tmp_path / 'q.db'}"))) as client:
        assert client.get("/portraits").json() == {}


def test_portrait_cache_skips_known_names_and_retries_failures():
    get_json, calls = fake(
        {"Guido Crosetto": [{"id": "Q1", "label": "Guido Crosetto"}]},
        {"Q1": entity("Q1")},
    )
    cache = {"Mario Bianchi": None}
    first = build_portraits(PEOPLE[1:3], get_json=get_json, cache=cache)
    assert "2" in first and "3" not in first
    assert cache["Guido Crosetto"]["origin"] == "Wikimedia Commons"
    before = len(calls)
    again = build_portraits(PEOPLE[1:3], get_json=get_json, cache=cache)
    assert again == first and len(calls) == before  # served from cache

    def failing(url, params):
        import httpx
        raise httpx.HTTPError("429 Too Many Requests")
    warnings = []
    assert build_portraits(PEOPLE[3:4], get_json=failing, cache=cache, warnings=warnings) == {}
    assert "Eugenia Maria Roccella" not in cache and warnings


def test_portrait_files_are_stored_and_served_locally(tmp_path):
    from scripts.demo_portraits import store_portrait_files, write_portraits

    portraits = {"2": {"url": "https://upload.wikimedia.org/thumb.jpg", "credit": "A", "license": "CC BY 4.0",
                       "source_url": "https://commons.wikimedia.org/x", "origin": "Wikimedia Commons"},
                 "3": {"url": "https://upload.wikimedia.org/page.html", "credit": "B", "license": "CC0",
                       "source_url": "https://commons.wikimedia.org/y", "origin": "Wikimedia Commons"}}
    fetched = []

    def fetch_bytes(url):
        fetched.append(url)
        return (b"\xff\xd8\xff" + b"0" * 100, "image/jpeg") if url.endswith(".jpg") else (b"<html>", "text/html")

    warnings = []
    store_portrait_files(portraits, tmp_path / "portraits", fetch_bytes=fetch_bytes, warnings=warnings)
    assert portraits["2"]["file"].endswith(".jpg") and "file" not in portraits["3"] and warnings
    store_portrait_files(portraits, tmp_path / "portraits", fetch_bytes=fetch_bytes)
    assert fetched.count("https://upload.wikimedia.org/thumb.jpg") == 1  # reused on the next run
    write_portraits(tmp_path / "portraits.json", portraits)

    settings = Settings(database_url=f"sqlite:///{tmp_path / 'p.db'}", portraits_path=tmp_path / "portraits.json")
    with TestClient(create_app(settings)) as client:
        listing = client.get("/portraits").json()
        image = client.get("/portraits/2/image")
        missing = client.get("/portraits/3/image")
    assert listing["2"]["url"] == "/portraits/2/image"
    assert listing["3"]["url"] == "https://upload.wikimedia.org/page.html"
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert missing.status_code == 404
