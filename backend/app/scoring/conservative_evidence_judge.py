"""Heuristic assistant that may only propose an open ``in_progress`` draft.

This is not the public methodology and never proposes a closed verdict
(``kept``, ``partially_kept``, ``broken``). It exists so an official act that
names the same policy instrument can be sent to a human reviewer. Keyword
matches are not treated as fulfilment.
"""

from __future__ import annotations

import re
from datetime import date

from backend.app.scoring.evidence_matching import EvidenceJudgment, excerpt_is_verbatim
from backend.app.scoring.instrument_aliases import aliases_for
from backend.app.scoring.retrieval_profile import extract_instrument_phrases
from backend.app.scoring.types import CommitmentType, EvidenceLabel, FulfillmentVerdict

ENACTMENT = re.compile(
    r"\b("
    r"legge(?:\s+\d|\s+n\.)|decreto-legge|decreto\s+legislativo|d\.lgs|"
    r"approvat[aoe]\s+in\s+via\s+definitiva|"
    r"pubblicat[ao]\s+nella\s+gazzetta|"
    r"entrata\s+in\s+vigore|promulga"
    r")\b",
    re.IGNORECASE,
)
ANNOUNCEMENT = re.compile(
    r"\b(disegno\s+di\s+legge|comunicato\s+stampa|esame\s+preliminare)\b",
    re.IGNORECASE,
)
CONSTITUTIONAL_LIMIT = re.compile(
    r"illegittimit[aà']\s+costituzionale",
    re.IGNORECASE,
)
PURPOSE_INSTRUMENTS: tuple[str, ...] = ("logiche correntizie",)


def evidence_outside_temporal_window(
    *,
    published_at: date | None,
    announcement_date: date | None = None,
    mandate_start: date | None = None,
    mandate_end: date | None = None,
) -> bool:
    """Return True when supplied dates show the act cannot support this holder."""

    if published_at is None and announcement_date is None and mandate_start is None and mandate_end is None:
        return False
    if published_at is None:
        return True
    start = announcement_date or mandate_start
    if start is not None and published_at < start:
        return True
    if mandate_end is not None and published_at > mandate_end:
        return True
    return False


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
    version = "v1.2"

    def judge(
        self,
        *,
        pledge_text: str,
        commitment_type: CommitmentType,
        passage_text: str,
        published_at: date | None = None,
        announcement_date: date | None = None,
        mandate_start: date | None = None,
        mandate_end: date | None = None,
    ) -> EvidenceJudgment:
        del commitment_type
        if evidence_outside_temporal_window(
            published_at=published_at,
            announcement_date=announcement_date,
            mandate_start=mandate_start,
            mandate_end=mandate_end,
        ):
            return EvidenceJudgment(EvidenceLabel.NOT_ENOUGH_INFO, None, "", "")
        originals = extract_instrument_phrases(pledge_text)
        phrases = tuple(dict.fromkeys([*originals, *aliases_for(originals)]))
        if not originals or not ENACTMENT.search(passage_text):
            return EvidenceJudgment(EvidenceLabel.NOT_ENOUGH_INFO, None, "", "")
        if ANNOUNCEMENT.search(passage_text) and not re.search(
            r"\bpromulga\b", passage_text, re.IGNORECASE
        ):
            return EvidenceJudgment(EvidenceLabel.NOT_ENOUGH_INFO, None, "", "")
        if CONSTITUTIONAL_LIMIT.search(passage_text):
            return EvidenceJudgment(EvidenceLabel.NOT_ENOUGH_INFO, None, "", "")
        if not any(phrase.lower() in passage_text.lower() for phrase in phrases):
            return EvidenceJudgment(EvidenceLabel.NOT_ENOUGH_INFO, None, "", "")
        missing_purpose = [
            phrase
            for phrase in PURPOSE_INSTRUMENTS
            if phrase in originals and phrase.lower() not in passage_text.lower()
        ]
        if missing_purpose:
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
