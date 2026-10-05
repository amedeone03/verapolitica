from enum import StrEnum

from backend.app.ai import StructuredExtractionRequest
from backend.app.schemas import StructuredExtractionResult
from backend.app.schemas.ai_evaluation import GoldExtractionCase


class EvaluationFakeProfile(StrEnum):
    PERFECT = "perfect"
    NOISY = "noisy"
    WRONG_EVIDENCE = "wrong_evidence"
    WRONG_TYPE = "wrong_type"
    ABSTENTION = "abstention"


class DatasetFakeExtractionProvider:
    def __init__(
        self,
        cases: tuple[GoldExtractionCase, ...],
        profile: EvaluationFakeProfile,
    ) -> None:
        self.profile = profile
        self._cases = {case.source_url: case for case in cases}
        self.requests: list[StructuredExtractionRequest] = []

    @property
    def provider_name(self) -> str:
        return "evaluation_fake"

    @property
    def model_name(self) -> str:
        return f"evaluation-{self.profile.value}-v1"

    def extract(
        self, request: StructuredExtractionRequest
    ) -> StructuredExtractionResult:
        self.requests.append(request)
        case = self._cases[request.source_url]
        candidates = self._candidates(case)
        return StructuredExtractionResult.model_validate(
            {
                "output": {"candidates": candidates},
                "usage": {
                    "request_count": 1,
                    "input_tokens": sum(len(chunk.text.split()) for chunk in request.chunks),
                    "output_tokens": sum(
                        len(str(candidate).split()) for candidate in candidates
                    ),
                },
            }
        )

    def _candidates(self, case: GoldExtractionCase) -> list[dict]:
        if self.profile is EvaluationFakeProfile.ABSTENTION:
            return [{"abstention_reason": "insufficient_evidence"}]
        if case.expects_abstention:
            return [
                {
                    "abstention_reason": (
                        case.abstention_reason.value
                        if case.abstention_reason
                        else "insufficient_evidence"
                    )
                }
            ]
        claims = list(case.claims)
        if self.profile is EvaluationFakeProfile.NOISY and case.case_id == "two_claims":
            claims = claims[:1]
        candidates = [self._claim_payload(claim) for claim in claims]
        if self.profile is EvaluationFakeProfile.NOISY and case.case_id == "clear_proposal":
            candidates.append(
                {
                    "claim_type": "proposal",
                    "exact_statement": "The programme proposes a national tax reduction.",
                    "normalized_title": "Reduce national taxes",
                    "summary": None,
                    "topic": "economy",
                    "actor_mentions": [],
                    "announced_at": None,
                    "target_date": None,
                    "evidence": [
                        {
                            "chunk_index": 0,
                            "page": None,
                            "supporting_text": case.claims[0].evidence[0].supporting_text,
                        }
                    ],
                    "confidence": "low",
                    "abstention_reason": None,
                }
            )
        return candidates

    def _claim_payload(self, claim) -> dict:
        claim_type = claim.claim_type.value
        if (
            self.profile is EvaluationFakeProfile.WRONG_TYPE
            and claim_type == "explicit_promise"
        ):
            claim_type = "proposal"
        evidence = [
            {
                "chunk_index": (
                    999
                    if self.profile is EvaluationFakeProfile.WRONG_EVIDENCE
                    else item.chunk_index
                ),
                "page": item.page,
                "supporting_text": item.supporting_text,
            }
            for item in claim.evidence
        ]
        return {
            "claim_type": claim_type,
            "exact_statement": claim.exact_statement,
            "normalized_title": claim.normalized_title,
            "summary": None,
            "topic": claim.topic.value if claim.topic else None,
            "actor_mentions": [
                {"name": actor.name, "role": actor.role.value}
                for actor in claim.actors
            ],
            "announced_at": (
                claim.announced_at.isoformat() if claim.announced_at else None
            ),
            "target_date": claim.target_date.isoformat() if claim.target_date else None,
            "evidence": evidence,
            "confidence": "high",
            "abstention_reason": None,
        }
