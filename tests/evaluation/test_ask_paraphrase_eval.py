import json
from pathlib import Path

from backend.app.evaluation.ask_dataset import (
    load_ask_gold_dataset,
    resolve_ask_dataset_root,
)
from backend.app.evaluation.ask_metrics import compare_retrieve_reports
from backend.app.evaluation.ask_runner import run_ask_evaluation
from backend.app.services.ask_query_planner import AskRetrieveMode
from evaluation.eval_ask_verapolitica import build_parser, main


GOLD_ROOT = (
    Path(__file__).resolve().parents[2]
    / "evaluation"
    / "ask_verapolitica"
    / "paraphrase_v1"
)
COMPARE_PATH = GOLD_ROOT / "compare.json"


def test_paraphrase_dataset_loads():
    root = resolve_ask_dataset_root("paraphrase-v1")
    dataset = load_ask_gold_dataset(root)
    assert root == GOLD_ROOT
    assert dataset.dataset_version == "ask-verapolitica-gold/paraphrase-v1"
    assert 28 <= len(dataset.cases) <= 40
    categories = {case.category for case in dataset.cases}
    assert {"control", "paraphrase", "unsupported", "injection"} <= categories
    assert any(case.category == "paraphrase" for case in dataset.cases)
    assert all(case.id for case in dataset.cases)


def test_keyword_misses_irpef_hybrid_retrieves():
    keyword = run_ask_evaluation(
        dataset_name="paraphrase-v1",
        case_id="para-irpef",
        retrieve_mode=AskRetrieveMode.KEYWORD,
    )
    hybrid = run_ask_evaluation(
        dataset_name="paraphrase-v1",
        case_id="para-irpef",
        retrieve_mode=AskRetrieveMode.HYBRID,
    )
    assert keyword.case_scores[0].pledge_tp == 0
    assert keyword.case_scores[0].pledge_fn == 1
    assert hybrid.passed == 1
    assert hybrid.case_scores[0].pledge_tp == 1
    assert hybrid.metrics["invented_url_rate"] == 0


def test_paraphrase_hybrid_beats_keyword_recall():
    keyword = run_ask_evaluation(
        dataset_name="paraphrase-v1",
        retrieve_mode=AskRetrieveMode.KEYWORD,
    )
    hybrid = run_ask_evaluation(
        dataset_name="paraphrase-v1",
        retrieve_mode=AskRetrieveMode.HYBRID,
    )
    dataset = load_ask_gold_dataset(GOLD_ROOT)
    payload = compare_retrieve_reports(
        keyword=keyword, hybrid=hybrid, gold_cases=dataset.cases
    )
    assert payload["labeled_queries"] >= 20
    assert hybrid.metrics["recall_at_12"] > keyword.metrics["recall_at_12"]
    assert hybrid.metrics["invented_url_rate"] == 0
    assert hybrid.metrics["forbidden_claim_rate"] == 0
    assert hybrid.failed == 0
    frozen = json.loads(COMPARE_PATH.read_text(encoding="utf-8"))
    assert frozen["hybrid"]["recall_at_12"] == payload["hybrid"]["recall_at_12"]
    assert frozen["keyword"]["recall_at_12"] == payload["keyword"]["recall_at_12"]
    assert frozen["labeled_queries"] == payload["labeled_queries"]


def test_compare_retrieve_cli(capsys):
    args = build_parser().parse_args(
        ["--dataset", "paraphrase-v1", "--compare-retrieve", "--case-id", "para-ssn"]
    )
    assert args.compare_retrieve is True
    exit_code = main(
        ["--dataset", "paraphrase-v1", "--compare-retrieve", "--case-id", "para-ssn"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "hybrid Recall@12" in captured.out
    assert "keyword-only Recall@12" in captured.out
