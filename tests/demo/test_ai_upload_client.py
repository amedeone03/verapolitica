from pathlib import Path


JS = Path(__file__).resolve().parents[2] / "frontend" / "demo" / "ai-upload.js"


def test_upload_client_clears_loading_on_error_timeout_and_success_redirect():
    source = JS.read_text(encoding="utf-8")
    assert "const CLIENT_TIMEOUT_MS = 200000;" in source
    assert "AbortController" in source
    assert "function stopLoading()" in source
    assert "function failStep(" in source
    assert "is-failed" in source
    assert "try {" in source
    assert "catch (err)" in source
    assert "finally {" in source
    assert "stopLoading();" in source
    assert "updateAnalyze();" in source
    assert "Local AI analysis did not complete in time. Please retry." in source
    assert "window.location = extracted.redirect;" in source
    assert "failStep(failedStep, message);" in source
    assert "inFlight = false;" in source
    assert "sections sent to local AI" in source
    assert "Evidence selected: " in source
    assert "evidence_summary" in source
