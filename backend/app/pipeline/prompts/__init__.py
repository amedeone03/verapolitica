from importlib.resources import files


PROPOSAL_EXTRACTION_PROMPT_VERSION = "proposal_extraction_v1"
PLEDGE_EVIDENCE_JUDGE_PROMPT_VERSION = "pledge_evidence_judge_v1"
PLEDGE_EXPLANATION_PROMPT_VERSION = "pledge_explanation_v1"
ASK_VERAPOLITICA_PROMPT_VERSION = "ask-verapolitica/v1"


def load_proposal_extraction_prompt() -> str:
    return (
        files("backend.app.pipeline.prompts")
        .joinpath(f"{PROPOSAL_EXTRACTION_PROMPT_VERSION}.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def load_pledge_evidence_judge_prompt() -> str:
    return (
        files("backend.app.pipeline.prompts")
        .joinpath(f"{PLEDGE_EVIDENCE_JUDGE_PROMPT_VERSION}.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def load_pledge_explanation_prompt() -> str:
    return (
        files("backend.app.pipeline.prompts")
        .joinpath(f"{PLEDGE_EXPLANATION_PROMPT_VERSION}.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def load_ask_verapolitica_prompt() -> str:
    return (
        files("backend.app.pipeline.prompts")
        .joinpath("ask_verapolitica_v1.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


__all__ = [
    "PROPOSAL_EXTRACTION_PROMPT_VERSION",
    "PLEDGE_EVIDENCE_JUDGE_PROMPT_VERSION",
    "PLEDGE_EXPLANATION_PROMPT_VERSION",
    "ASK_VERAPOLITICA_PROMPT_VERSION",
    "load_proposal_extraction_prompt",
    "load_pledge_evidence_judge_prompt",
    "load_pledge_explanation_prompt",
    "load_ask_verapolitica_prompt",
]
