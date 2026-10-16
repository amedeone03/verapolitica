import json
from pathlib import Path

import pytest

from backend.app.evaluation.ask_dataset import (
    AskGoldCase,
    load_ask_gold_dataset,
    resolve_ask_dataset_root,
)
from backend.app.evaluation.ask_fixture import AskEvalCatalog
from backend.app.evaluation.ask_metrics import score_ask_case
from backend.app.evaluation.ask_runner import run_ask_evaluation
from backend.app.evaluation.dataset import EvaluationDatasetError
from backend.app.schemas.ask import AskResponse, AskResultItem, AskSource
from backend.app.scoring.types import FulfillmentVerdict
from backend.app.services.ask_verapolitica_service import UNSUPPORTED_ANSWER
from evaluation.eval_ask_verapolitica import build_parser, main


GOLD_ROOT = Path(__file__).resolve().parents[2] / "evaluation" / "ask_verapolitica" / "v1"
REQUIRED_CATEGORIES = {
    "politician",
    "verdict",
    "topic",
    "explanation",
    "sources",
    "no_assessment",
    "unsupported",
    "injection",
    "ambiguous",
    "variants",
    "invalid",
    "contradiction",
}


def _catalog() -> AskEvalCatalog:
    return AskEvalCatalog(
        politician_ids={
            "giorgia-meloni": 1,
            "mario-rossi": 2,
            "anna-rossi": 3,
        },
        politician_names={
            "giorgia-meloni": "Giorgia Meloni",
            "mario-rossi": "Mario Rossi",
            "anna-rossi": "Anna Rossi",
        },
        pledge_ids={"autonomia": 10, "tasse": 11},
        pledge_titles={
            "autonomia": "Autonomia differenziata",
            "tasse": "Taglio del cuneo fiscale",
        },
        source_urls={
            "autonomia": "https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg",
        },
        published_source_urls=(
            "https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg",
        ),
        unpublished_titles=("Bozza",),
    )


def _response(**overrides) -> AskResponse:
    payload = {
        "answer": "Risposta deterministica sui dati pubblicati.",
        "intent": "politician_pledges",
        "entities": {"politician": "Giorgia Meloni"},
        "results": (
            AskResultItem(
                type="pledge",
                id=10,
                title="Autonomia differenziata",
                verdict=FulfillmentVerdict.IN_PROGRESS,
                public_verdict_label="In corso",
            ),
        ),
        "sources": (
            AskSource(
                title="Gazzetta",
                url="https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg",
                excerpt="legge sull'autonomia",
            ),
        ),
        "generated_by_ai": False,
        "fallback": False,
        "prompt_version": "ask-verapolitica/v1",
    }
    payload.update(overrides)
    return AskResponse(**payload)


def test_gold_dataset_covers_required_categories():
    dataset = load_ask_gold_dataset(GOLD_ROOT)
    categories = {case.category for case in dataset.cases}
    assert 40 <= len(dataset.cases) <= 60
    assert REQUIRED_CATEGORIES <= categories
    assert len({case.id for case in dataset.cases}) == len(dataset.cases)


def test_score_detects_bad_retrieval():
    case = AskGoldCase(
        id="bad-retrieval",
        category="politician",
        question="Quali promesse sull'autonomia?",
        expected_pledge_keys=("autonomia",),
    )
    response = _response(
        results=(
            AskResultItem(
                type="pledge",
                id=11,
                title="Taglio del cuneo fiscale",
                verdict=FulfillmentVerdict.KEPT,
            ),
        )
    )
    score = score_ask_case(case, _catalog(), response=response)
    assert not score.passed
    assert score.pledge_fp == 1
    assert score.pledge_fn == 1


def test_score_detects_invented_urls():
    case = AskGoldCase(
        id="invented-url",
        category="sources",
        question="Qual è la fonte sull'autonomia?",
        expected_source_url="https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg",
    )
    response = _response(
        answer="Vedi https://en.wikipedia.org/wiki/Giorgia_Meloni",
        sources=(
            AskSource(
                title="Wikipedia",
                url="https://en.wikipedia.org/wiki/Giorgia_Meloni",
                excerpt="invented",
            ),
        ),
    )
    score = score_ask_case(case, _catalog(), response=response)
    assert not score.passed
    assert score.invented_url_hits >= 1
    assert any("invented URL" in reason for reason in score.reasons)


def test_score_detects_verdict_contradiction():
    case = AskGoldCase(
        id="verdict-contradiction",
        category="contradiction",
        question="La promessa sull'autonomia è In corso?",
        expected_pledge_keys=("autonomia",),
        expected_verdict="in_progress",
        forbidden_verdicts=("kept",),
    )
    response = _response(
        results=(
            AskResultItem(
                type="pledge",
                id=10,
                title="Autonomia differenziata",
                verdict=FulfillmentVerdict.KEPT,
                public_verdict_label="Mantenuta",
            ),
        )
    )
    score = score_ask_case(case, _catalog(), response=response)
    assert not score.passed
    assert score.verdict_ok is False
    assert any("forbidden result verdict" in reason for reason in score.reasons)


def test_score_correct_abstention_passes():
    case = AskGoldCase(
        id="abstain",
        category="unsupported",
        question="Chi è il miglior politico italiano?",
        expected_intent="unsupported",
        expected_pledge_keys=(),
        should_abstain=True,
    )
    response = _response(
        answer=UNSUPPORTED_ANSWER,
        intent="unsupported",
        entities={},
        results=(),
        sources=(),
    )
    score = score_ask_case(case, _catalog(), response=response)
    assert score.passed
    assert score.abstention_ok is True


def test_score_clarification_expectation_passes():
    case = AskGoldCase(
        id="clarify",
        category="ambiguous",
        question="Quali promesse ha Rossi?",
        should_require_clarification=True,
        expected_pledge_keys=(),
    )
    response = _response(
        answer="Più profili pubblici corrispondono. Precisa quale intendi: Mario Rossi; Anna Rossi.",
        intent="politician_pledges",
        entities={},
        results=(
            AskResultItem(type="politician", id=2, title="Mario Rossi"),
            AskResultItem(type="politician", id=3, title="Anna Rossi"),
        ),
        sources=(),
    )
    score = score_ask_case(case, _catalog(), response=response)
    assert score.passed
    assert score.clarification_ok is True


def test_score_clarification_fails_when_guessing():
    case = AskGoldCase(
        id="guess",
        category="ambiguous",
        question="Quali promesse ha Rossi?",
        should_require_clarification=True,
        expected_pledge_keys=(),
    )
    score = score_ask_case(case, _catalog(), response=_response())
    assert not score.passed
    assert score.clarification_ok is False


def test_runner_known_good_cases_pass():
    report = run_ask_evaluation(case_id="unsupported-miglior")
    assert report.total == 1
    assert report.passed == 1
    report = run_ask_evaluation(case_id="ambig-rossi")
    assert report.passed == 1
    report = run_ask_evaluation(case_id="pol-meloni-in-corso")
    assert report.passed == 1


def test_score_zero_result_precision():
    empty = AskGoldCase(
        id="zero",
        category="verdict",
        question="Quali risultano Non mantenute?",
        expected_pledge_keys=(),
        expect_zero_results=True,
    )
    ok = score_ask_case(
        empty,
        _catalog(),
        response=_response(results=(), sources=(), entities={"verdict": "broken"}),
    )
    assert ok.passed
    assert ok.zero_result_ok is True
    invented = score_ask_case(empty, _catalog(), response=_response())
    assert not invented.passed
    assert invented.zero_result_ok is False


def test_dataset_selector_keeps_synthetic_default():
    root = resolve_ask_dataset_root("synthetic-v1")
    assert root == GOLD_ROOT
    report = run_ask_evaluation(dataset_name="synthetic-v1", case_id="unsupported-miglior")
    assert report.dataset_version == "ask-verapolitica-gold/v1"
    assert report.passed == 1


def test_runner_rejects_unknown_filter():
    with pytest.raises(EvaluationDatasetError, match="no gold cases"):
        run_ask_evaluation(case_id="does-not-exist")


def test_cli_case_id_and_json_output(tmp_path, capsys):
    output = tmp_path / "ask-eval.json"
    args = build_parser().parse_args(
        ["--case-id", "unsupported-miglior", "--json-output", str(output)]
    )
    assert args.case_id == "unsupported-miglior"
    exit_code = main(
        ["--case-id", "unsupported-miglior", "--json-output", str(output)]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "passed=1" in captured.out
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["failed"] == 0
    assert "curated gold set" in payload["disclaimer"]
