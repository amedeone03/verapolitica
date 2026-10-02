import httpx

from backend.app.pipeline.collectors import SenatoCollector


def test_collector_gets_versioned_sparql_request():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["accept"] == "application/sparql-results+json"
        assert "FILTER(?legislature = 19)" in request.url.params["query"]
        assert request.url.params["format"] == "application/sparql-results+json"
        return httpx.Response(
            200,
            headers={"content-type": "application/sparql-results+json"},
            json={"head": {"vars": []}, "results": {"bindings": []}},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = SenatoCollector(
            "https://dati.senato.it/sparql", legislature=19, client=client
        )
        document = collector.collect()

    assert document.collector_version == "senato_collector_v1"
    assert document.source_url == "https://dati.senato.it/sparql"
    assert document.content_type == "application/sparql-results+json"
    assert document.content
