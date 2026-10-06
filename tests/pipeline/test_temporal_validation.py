from datetime import date

import pytest

from backend.app.pipeline.temporal_validation import (
    SemanticValidationError,
    validate_claim_temporal,
    validate_temporal_semantics,
)
from backend.app.schemas import ExtractedPoliticalClaim, PoliticalClaimExtraction


ANNOUNCEMENT = "annunciato nella seduta n. 459 del 29 settembre 2026"
SCADENZA = (
    "Conversione in legge del decreto-legge 7 agosto 2026, n. 144, "
    "scadenza il 6 ottobre 2026"
)
COMMITMENT = (
    "Il Governo si impegna a completare la digitalizzazione degli archivi "
    "entro il 31 dicembre 2027"
)


def _claim(
    *,
    announced_at: str | None = None,
    target_date: str | None = None,
    evidence_text: str,
    statement: str | None = None,
) -> ExtractedPoliticalClaim:
    return ExtractedPoliticalClaim.model_validate(
        {
            "claim_type": "proposal",
            "exact_statement": statement or evidence_text,
            "normalized_title": "Test proposal",
            "summary": None,
            "topic": "public_administration",
            "actor_mentions": [],
            "announced_at": announced_at,
            "target_date": target_date,
            "evidence": [
                {
                    "chunk_index": 0,
                    "page": 5,
                    "supporting_text": evidence_text,
                }
            ],
            "confidence": "high",
            "abstention_reason": None,
        }
    )


def test_announced_at_from_explicit_parliamentary_announcement_is_valid():
    claim = _claim(announced_at="2026-09-29", evidence_text=ANNOUNCEMENT)
    assert validate_claim_temporal(claim) == ()
    validate_temporal_semantics(claim)


def test_target_date_from_decreto_legge_scadenza_is_invalid():
    claim = _claim(target_date="2026-10-06", evidence_text=SCADENZA)
    issues = validate_claim_temporal(claim)
    assert len(issues) == 1
    assert issues[0].field == "target_date"
    assert issues[0].reason == "procedural_deadline_not_proposal_target"
    assert issues[0].value == "2026-10-06"
    assert claim.target_date == date(2026, 10, 6)
    with pytest.raises(SemanticValidationError, match="procedural_deadline_not_proposal_target"):
        validate_temporal_semantics(claim)


def test_target_date_from_explicit_commitment_deadline_is_valid():
    claim = _claim(target_date="2027-12-31", evidence_text=COMMITMENT)
    assert validate_claim_temporal(claim) == ()
    validate_temporal_semantics(claim)


def test_uncertain_target_date_without_commitment_language_is_unsupported():
    claim = _claim(
        target_date="2026-10-06",
        evidence_text="Il provvedimento è datato 6 ottobre 2026.",
    )
    issues = validate_claim_temporal(claim)
    assert issues[0].reason == "unsupported_target_date"


def test_empty_candidates_and_abstentions_skip_temporal_validation():
    payload = PoliticalClaimExtraction.model_validate(
        {
            "candidates": [
                {"abstention_reason": "insufficient_evidence"},
            ]
        }
    )
    validate_temporal_semantics(payload)
    validate_temporal_semantics(PoliticalClaimExtraction.model_validate({"candidates": []}))
