"""Heuristic assistant that may only propose an open ``in_progress`` draft.

This is not the public methodology and never proposes a closed verdict
(``kept``, ``partially_kept``, ``broken``). It exists so an official act that
names the same policy instrument can be sent to a human reviewer. Keyword
matches are not treated as fulfilment.
"""

from __future__ import annotations

import re

from backend.app.scoring.evidence_matching import EvidenceJudgment, excerpt_is_verbatim
from backend.app.scoring.retrieval_profile import extract_instrument_phrases
from backend.app.scoring.types import CommitmentType, EvidenceLabel, FulfillmentVerdict

ENACTMENT = re.compile(
    r"\b("
    r"legge(?:\s+\d|\s+n\.)|decreto-legge|d\.lgs|d\.l\.|"
    r"approvat[aoe]\s+in\s+via\s+definitiva|"
    r"pubblicat[ao]\s+nella\s+gazzetta|gazzetta\s+ufficiale|"
    r"entrata\s+in\s+vigore|promulga|"
    r"disposizioni\s+per\s+l.attuazione|"
    r"disegno\s+di\s+legge"
    r")\b",
    re.IGNORECASE,
)


def _excerpt(passage_text: str, phrases: tuple[str, ...]) -> str:
    lowered = passage_text.lower()
    for phrase in phrases:
        token = phrase.split()[0]
        index = lowered.find(token.lower())
        if index < 0:
            continue
        start = max(0, index - 40)
        snippet = passage_text[start : index + 220].strip()
        if excerpt_is_verbatim(passage_text, snippet):
            return snippet
    fallback = " ".join(passage_text.split())[:240].strip()
    return fallback if excerpt_is_verbatim(passage_text, fallback) else ""


class ConservativeOfficialActJudge:
    """Propose ``in_progress`` only when an official act names the instrument."""

    name = "conservative-official-act"
    version = "v1"

    def judge(
        self, *, pledge_text: str, commitment_type: CommitmentType, passage_text: str
    ) -> EvidenceJudgment:
        del commitment_type
        phrases = extract_instrument_phrases(pledge_text)
        if not phrases or not ENACTMENT.search(passage_text):
            return EvidenceJudgment(EvidenceLabel.NOT_ENOUGH_INFO, None, "", "")
        if not any(phrase.lower() in passage_text.lower() for phrase in phrases):
            return EvidenceJudgment(EvidenceLabel.NOT_ENOUGH_INFO, None, "", "")
        excerpt = _excerpt(passage_text, phrases)
        if not excerpt_is_verbatim(passage_text, excerpt) and not excerpt_is_verbatim(
            " ".join(passage_text.split()), excerpt
        ):
            return EvidenceJudgment(EvidenceLabel.NOT_ENOUGH_INFO, None, "", "")
        return EvidenceJudgment(
            EvidenceLabel.SUPPORTS,
            FulfillmentVerdict.IN_PROGRESS,
            excerpt,
            (
                "Official act language names the same policy instrument as the "
                "commitment. This is proposed as in_progress for human review, "
                "not as a closed fulfilment verdict."
            ),
        )
