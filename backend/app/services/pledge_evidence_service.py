"""Monthly evidence matching for open pledges.

For every published, classified, non-vague *action* pledge whose current
verdict is still open, retrieve candidate passages from stored official
document chunks, ask an :class:`EvidenceJudge` for a FEVER-style judgment, and
turn only verified judgments into ``PledgeAssessmentDraft`` rows for review.

Outcome pledges are skipped on purpose: an official act cannot prove that
unemployment fell. They need a separate statistical-data matcher (ISTAT/MEF),
which is not implemented yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    DocumentChunk,
    PledgeAssessmentOrigin,
    PledgeClassification,
    Proposal,
    ProposalType,
    RawDocument,
)
from backend.app.schemas.pledge import PledgeAssessmentProposal
from backend.app.scoring.evidence_matching import (
    MATCHER_VERSION,
    AbstainingJudge,
    Embedder,
    EvidenceJudge,
    Passage,
    retrieve,
    validate_judgment,
)
from backend.app.scoring.types import (
    CommitmentType,
    FulfillmentVerdict,
    OPEN_VERDICTS,
    PledgeSpecificity,
)
from backend.app.services.pledge_service import NewAssessmentDraft, PledgeService

MATCHER_IDENTITY = "system:pledge-evidence-matcher"


@dataclass(slots=True)
class EvidenceMatchingReport:
    pledges_considered: int = 0
    skipped_outcome_pledges: int = 0
    passages_judged: int = 0
    drafts_created: int = 0
    drafts_replayed: int = 0
    rejections: dict[str, int] = field(default_factory=dict)


class PledgeEvidenceService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        judge: EvidenceJudge | None = None,
        embedder: Embedder | None = None,
        passages_per_pledge: int = 5,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.session_factory = session_factory
        self.judge = judge or AbstainingJudge()
        self.embedder = embedder
        self.passages_per_pledge = passages_per_pledge
        self.pledges = PledgeService(session_factory, clock=clock)

    @staticmethod
    def _load(
        session: Session,
    ) -> tuple[list[tuple[Proposal, PledgeClassification]], list[Passage]]:
        rows = session.execute(
            select(Proposal, PledgeClassification)
            .join(PledgeClassification, PledgeClassification.proposal_id == Proposal.id)
            .where(
                Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
                Proposal.published_at.is_not(None),
                PledgeClassification.specificity != PledgeSpecificity.VAGUE,
            )
            .order_by(Proposal.id)
        ).all()
        chunks = session.execute(
            select(DocumentChunk, RawDocument)
            .join(RawDocument, RawDocument.id == DocumentChunk.raw_document_id)
            .order_by(DocumentChunk.id)
        ).all()
        passages = [
            Passage(
                passage_id=chunk.id,
                raw_document_id=document.id,
                text=chunk.text,
                source_url=document.source_url,
            )
            for chunk, document in chunks
        ]
        return [(proposal, classification) for proposal, classification in rows], passages

    def run(self) -> EvidenceMatchingReport:
        report = EvidenceMatchingReport()
        with self.session_factory() as session:
            pledges, passages = self._load(session)
            latest = PledgeService._latest_assessments(session, [p.id for p, _ in pledges])
            work = []
            for proposal, classification in pledges:
                current = latest.get(proposal.id)
                verdict = current.verdict if current else FulfillmentVerdict.NOT_YET_RATED
                if verdict not in OPEN_VERDICTS:
                    continue
                if classification.commitment_type is CommitmentType.OUTCOME:
                    report.skipped_outcome_pledges += 1
                    continue
                query = " ".join(
                    part for part in (proposal.exact_statement, proposal.canonical_title) if part
                )
                work.append((proposal.id, query, classification.commitment_type))

        for proposal_id, query, commitment_type in work:
            report.pledges_considered += 1
            for ranked in retrieve(
                query,
                passages,
                limit=self.passages_per_pledge,
                embedder=self.embedder,
            ):
                report.passages_judged += 1
                judgment = self.judge.judge(
                    pledge_text=query,
                    commitment_type=commitment_type,
                    passage_text=ranked.passage.text,
                )
                reason = validate_judgment(judgment, ranked.passage.text)
                if reason is not None:
                    report.rejections[reason] = report.rejections.get(reason, 0) + 1
                    continue
                _draft, created = self.pledges.propose(
                    NewAssessmentDraft(
                        proposal_id=proposal_id,
                        proposal=PledgeAssessmentProposal(
                            verdict=judgment.proposed_verdict,
                            evidence_label=judgment.label,
                            rationale=judgment.rationale,
                            quoted_excerpt=judgment.quoted_excerpt,
                            raw_document_id=ranked.passage.raw_document_id,
                            document_chunk_id=ranked.passage.passage_id,
                        ),
                        origin=PledgeAssessmentOrigin.EVIDENCE_MATCHER,
                        created_by=MATCHER_IDENTITY,
                        retrieval={
                            "matcher_version": MATCHER_VERSION,
                            "score": ranked.score,
                            "lexical_rank": ranked.lexical_rank,
                            "semantic_rank": ranked.semantic_rank,
                        },
                        judge_name=self.judge.name,
                        judge_version=self.judge.version,
                    )
                )
                if created:
                    report.drafts_created += 1
                else:
                    report.drafts_replayed += 1
        return report
