from pathlib import Path

import pytest

from backend.app.core.config import Settings
from backend.app.schemas import EvaluationComparison, EvaluationReport
from scripts.evaluate_ai_extraction import build_parser, run


DATASET_ROOT = Path(__file__).resolve().parents[2] / "evaluation" / "gold" / "v1"


def test_evaluation_cli_fake_profile_writes_reports(tmp_path):
    output = tmp_path / "reports"
    args = build_parser().parse_args(
        [
            "--dataset",
            str(DATASET_ROOT),
            "--profile",
            "perfect",
            "--output-dir",
            str(output),
        ]
    )
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'evaluation.db'}",
        raw_storage_path=tmp_path / "raw",
    )

    report = run(args, settings=settings)

    assert isinstance(report, EvaluationReport)
    assert report.metrics.f1 == 1
    assert (output / "report.json").is_file()
    assert (output / "report.md").is_file()


def test_evaluation_cli_real_provider_requires_explicit_configuration(tmp_path):
    args = build_parser().parse_args(
        [
            "--dataset",
            str(DATASET_ROOT),
            "--provider",
            "openai",
            "--model",
            "configured-model",
            "--output-dir",
            str(tmp_path / "reports"),
        ]
    )
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'evaluation.db'}",
        raw_storage_path=tmp_path / "raw",
        llm_api_key=None,
    )

    with pytest.raises(ValueError, match="VERAPOLITICA_LLM_API_KEY"):
        run(args, settings=settings)


def test_evaluation_cli_compares_two_reports(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'evaluation.db'}",
        raw_storage_path=tmp_path / "raw",
    )
    paths = []
    for profile in ("perfect", "noisy"):
        output = tmp_path / profile
        args = build_parser().parse_args(
            [
                "--dataset",
                str(DATASET_ROOT),
                "--profile",
                profile,
                "--output-dir",
                str(output),
            ]
        )
        run(args, settings=settings)
        paths.append(output / "report.json")
    compare_args = build_parser().parse_args(
        ["--compare", str(paths[0]), str(paths[1])]
    )

    comparison = run(compare_args, settings=settings)

    assert isinstance(comparison, EvaluationComparison)
    assert comparison.metric_deltas["f1"] < 0
