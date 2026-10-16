import json
import re
from pathlib import Path

from backend.app.scoring.public_presentation import (
    PUBLIC_VERDICT_LEGEND_ORDER,
    PUBLIC_VERDICT_STYLES,
    is_closed_verdict,
    is_open_verdict,
    public_verdict_chip_html,
    public_verdict_label,
    public_verdict_tone,
)
from backend.app.scoring.scorecard import METHODOLOGY_VERSION
from backend.app.scoring.types import (
    CLOSED_VERDICTS,
    FulfillmentVerdict,
    OPEN_VERDICTS,
    VERDICT_VALUE,
)


ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "kept": ("Mantenuta", "kept", "green"),
    "partially_kept": ("Mantenuta parzialmente", "partial", "yellow"),
    "in_progress": ("In corso", "progress", "blue"),
    "stalled": ("Iter bloccato", "stalled", "black"),
    "broken": ("Non mantenuta", "broken", "red"),
    "not_yet_rated": ("Non ancora valutata", "unrated", "grey"),
}


def test_internal_verdict_values_are_unchanged():
    assert [item.value for item in FulfillmentVerdict] == [
        "not_yet_rated",
        "in_progress",
        "stalled",
        "kept",
        "partially_kept",
        "broken",
    ]
    assert {item.value for item in CLOSED_VERDICTS} == {
        "kept",
        "partially_kept",
        "broken",
    }
    assert {item.value for item in OPEN_VERDICTS} == {
        "not_yet_rated",
        "in_progress",
        "stalled",
    }
    assert VERDICT_VALUE[FulfillmentVerdict.KEPT] == 1.0
    assert VERDICT_VALUE[FulfillmentVerdict.PARTIALLY_KEPT] == 0.5
    assert VERDICT_VALUE[FulfillmentVerdict.BROKEN] == 0.0
    assert METHODOLOGY_VERSION == "pledge-score/v1"


def test_public_labels_and_tones():
    for value, (label, tone, color) in EXPECTED.items():
        verdict = FulfillmentVerdict(value)
        style = PUBLIC_VERDICT_STYLES[verdict]
        assert public_verdict_label(value) == label
        assert public_verdict_tone(verdict) == tone
        assert style.color_name == color
        chip = public_verdict_chip_html(verdict)
        assert f'class="verdict-chip tone-{tone}"' in chip
        assert f">{label}</span>" in chip
    assert [item.value for item in PUBLIC_VERDICT_LEGEND_ORDER] == list(EXPECTED)
    assert is_open_verdict("in_progress") and is_open_verdict("stalled")
    assert is_open_verdict("not_yet_rated")
    assert is_closed_verdict("kept") and is_closed_verdict("partially_kept")
    assert is_closed_verdict("broken")


def test_frontend_mapping_matches_python_helper():
    script = (ROOT / "frontend" / "app" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "app" / "styles.css").read_text(encoding="utf-8")
    for value, (label, tone, _color) in EXPECTED.items():
        pattern = (
            rf'{re.escape(value)}:\s*\{{\s*label:\s*"{re.escape(label)}",'
            rf'\s*tone:\s*"{re.escape(tone)}"'
        )
        assert re.search(pattern, script), value
        assert f".tone-{tone}" in styles
    assert "--kept:" in styles
    assert "--partial:" in styles
    assert "--progress:" in styles
    assert "--stalled: #0e0e10" in styles
    assert "--unrated: #a8a29e" in styles
    assert "--broken:" in styles
    assert "verdict-chip.tone-partial" in styles
    assert "verdict-chip.tone-stalled" in styles
    assert "Partly kept" not in script
    assert "Not kept" not in script
    assert "Not yet rated" not in script


def test_autonomia_gold_still_treats_follow_through_as_in_progress():
    manifest = json.loads(
        (ROOT / "data" / "fixtures" / "pledge_evidence" / "gold" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    case = next(item for item in manifest["cases"] if item["case_id"] == "pos-autonomia-law86")
    assert case["actor"] == "Giorgia Meloni"
    assert "autonomia differenziata" in case["commitment_title"].casefold()
    assert "in_progress" in case["acceptable_verdicts"]
    assert "kept" in case["unacceptable_verdicts"]
