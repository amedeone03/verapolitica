from backend.app.services.official_source_display import (
    citizen_source_label,
    citizen_source_url,
    is_sparql_endpoint,
    senato_lodview_url,
)


def test_ddl_identifier_becomes_lodview_html():
    assert citizen_source_url("http://dati.senato.it/ddl/60491") == (
        "https://dati.senato.it/ddl/60491.html"
    )
    assert citizen_source_url("https://dati.senato.it/ddl/60491.html") == (
        "https://dati.senato.it/ddl/60491.html"
    )


def test_sparql_uses_numeric_senator_hint_and_keeps_unknown_hints():
    assert is_sparql_endpoint("https://dati.senato.it/sparql")
    assert citizen_source_url(
        "https://dati.senato.it/sparql",
        "http://dati.senato.it/senatore/25402",
    ) == "https://dati.senato.it/senatore/25402.html"
    assert (
        citizen_source_url("https://dati.senato.it/sparql", "senato-record")
        == "https://dati.senato.it/sparql"
    )
    assert senato_lodview_url("https://dati.senato.it/senatore/demo-001") is None


def test_camera_sparql_is_not_invented():
    assert (
        citizen_source_url("https://dati.camera.it/sparql", "camera-record")
        == "https://dati.camera.it/sparql"
    )


def test_non_numeric_ddl_identifier_is_left_unchanged():
    url = "https://dati.senato.it/ddl/synthetic-e2e"
    assert citizen_source_url(url) == url


def test_senato_source_label_hides_raw_url():
    assert (
        citizen_source_label("Senato della Repubblica — Disegni di legge")
        == "Senato della Repubblica"
    )
    assert citizen_source_label("Camera dei Deputati") == "Camera dei Deputati"
