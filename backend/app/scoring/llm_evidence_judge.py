"""Optional local LLM judge for pledge evidence. Never publishes.

The model may only classify a commitment against a passage that deterministic
retrieval already selected. Invalid or incomplete JSON is treated as
``not_enough_info``. Python does not rewrite an invalid verdict into a valid one.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.scoring.evidence_matching import EvidenceJudgment
from backend.app.scoring.types import CommitmentType, EvidenceLabel, FulfillmentVerdict


PROMPT_VERSION = "pledge_evidence_judge_v1"


def load_pledge_evidence_judge_prompt() -> str:
    return (
        files("backend.app.pipeline.prompts")
        .joinpath(f"{PROMPT_VERSION}.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


class PledgeEvidenceJudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_label: EvidenceLabel
    proposed_verdict: FulfillmentVerdict | None = None
    quoted_excerpt: str = Field(default="", max_length=4000)
    rationale: str = Field(default="", max_length=4000)


def _abstain() -> EvidenceJudgment:
    return EvidenceJudgment(EvidenceLabel.NOT_ENOUGH_INFO, None, "", "")


def parse_judge_output(payload: Any) -> EvidenceJudgment:
    """Validate model JSON. Do not coerce incompatible verdicts."""

    try:
        parsed = PledgeEvidenceJudgeOutput.model_validate(payload)
    except ValidationError:
        return _abstain()
    if parsed.evidence_label is EvidenceLabel.NOT_ENOUGH_INFO:
        return EvidenceJudgment(EvidenceLabel.NOT_ENOUGH_INFO, None, "", "")
    return EvidenceJudgment(
        parsed.evidence_label,
        parsed.proposed_verdict,
        parsed.quoted_excerpt.strip(),
        parsed.rationale.strip(),
    )


class OllamaEvidenceJudge:
    name = "ollama-pledge-evidence"
    version = PROMPT_VERSION

    def __init__(
        self,
        *,
        model_name: str,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 180.0,
    ) -> None:
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._prompt = load_pledge_evidence_judge_prompt()

    def judge(
        self,
        *,
        pledge_text: str,
        commitment_type: CommitmentType,
        passage_text: str,
        **_temporal: object,
    ) -> EvidenceJudgment:
        del _temporal
        user = (
            f"{self._prompt}\n\nCOMMITMENT ({commitment_type.value}):\n{pledge_text}\n\n"
            f"OFFICIAL EVIDENCE PASSAGE:\n{passage_text}\n"
        )
        body = {
            "model": self.model_name,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": "Return only valid JSON."},
                {"role": "user", "content": user},
            ],
        }
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=body,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content") or ""
            return parse_judge_output(json.loads(content))
        except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError):
            return _abstain()
