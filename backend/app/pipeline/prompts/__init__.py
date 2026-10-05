from importlib.resources import files


PROPOSAL_EXTRACTION_PROMPT_VERSION = "proposal_extraction_v1"


def load_proposal_extraction_prompt() -> str:
    return (
        files("backend.app.pipeline.prompts")
        .joinpath(f"{PROPOSAL_EXTRACTION_PROMPT_VERSION}.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


__all__ = ["PROPOSAL_EXTRACTION_PROMPT_VERSION", "load_proposal_extraction_prompt"]
