"""Gold dataset for Ask VeraPolitica evaluation. Display/eval only."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.app.evaluation.dataset import EvaluationDatasetError
from backend.app.schemas.ask import MAX_ASK_QUESTION_LENGTH


class AskGoldCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    category: str
    question: str = ""
    question_length: int | None = Field(default=None, ge=1)
    expected_intent: str | None = None
    expected_politician_key: str | None = None
    expected_politician_name: str | None = None
    expected_pledge_keys: tuple[str, ...] | None = None
    expected_verdict: str | None = None
    expected_topic: str | None = None
    expected_source_url: str | None = None
    expected_source_host: str | None = None
    expected_count: int | None = Field(default=None, ge=0)
    should_abstain: bool = False
    should_require_clarification: bool = False
    expect_unrated: bool = False
    expect_invalid: bool = False
    expect_zero_results: bool = False
    forbidden_claims: tuple[str, ...] = ()
    forbidden_verdicts: tuple[str, ...] = ()
    forbidden_titles: tuple[str, ...] = ()
    notes: str = ""

    @model_validator(mode="after")
    def _question_or_invalid(self) -> AskGoldCase:
        if self.expect_invalid:
            return self
        if self.question_length is not None:
            return self
        if not self.question.strip():
            raise ValueError(f"{self.id}: question must not be blank")
        return self

    def resolved_question(self) -> str:
        if self.question_length is not None:
            filler = self.question or "x"
            if len(filler) >= self.question_length:
                return filler[: self.question_length]
            extra = self.question_length - len(filler)
            return filler + ("x" * extra)
        return self.question


class AskGoldDataset(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_version: str
    description: str = ""
    cases: tuple[AskGoldCase, ...]


SYNTHETIC_V1_ALIAS = "synthetic-v1"
REAL_V1_ALIAS = "real-v1"
DATASET_ALIASES = {
    SYNTHETIC_V1_ALIAS: "v1",
    "v1": "v1",
    REAL_V1_ALIAS: "real_v1",
    "real_v1": "real_v1",
}


def ask_evaluation_root() -> Path:
    return Path(__file__).resolve().parents[3] / "evaluation" / "ask_verapolitica"


def resolve_ask_dataset_root(spec: str | Path | None = None) -> Path:
    if spec is None:
        return default_ask_gold_root()
    raw = Path(spec)
    alias = DATASET_ALIASES.get(str(spec).strip())
    if alias is not None:
        return ask_evaluation_root() / alias
    if raw.exists():
        return raw.expanduser().resolve()
    raise EvaluationDatasetError(
        f"unknown Ask dataset {spec!r}; use {SYNTHETIC_V1_ALIAS}, {REAL_V1_ALIAS}, "
        "or a gold directory path"
    )


def is_real_ask_dataset(dataset: AskGoldDataset) -> bool:
    return "real" in dataset.dataset_version.casefold()


def load_ask_gold_dataset(root: Path | None = None) -> AskGoldDataset:
    dataset_root = (root or default_ask_gold_root()).expanduser().resolve()
    path = dataset_root / "cases.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        dataset = AskGoldDataset.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise EvaluationDatasetError(f"invalid Ask gold dataset: {exc}") from exc
    ids = [case.id for case in dataset.cases]
    if len(ids) != len(set(ids)):
        raise EvaluationDatasetError("Ask gold dataset has duplicate case ids")
    return dataset


def default_ask_gold_root() -> Path:
    return ask_evaluation_root() / "v1"


def default_real_ask_gold_root() -> Path:
    return ask_evaluation_root() / "real_v1"


def oversized_question() -> str:
    return "x" * (MAX_ASK_QUESTION_LENGTH + 1)
