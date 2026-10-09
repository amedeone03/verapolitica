"""Official-evidence matching for open pledges.

For every published, classified, non-vague *action* pledge whose current
verdict is still open:

1. derive a deterministic retrieval profile
2. keep only later official passages (never the pledge's own programme text)
3. persist unpublished ``PledgeEvidenceCandidate`` rows
4. ask an ``EvidenceJudge`` only after candidates exist
5. create a ``PledgeAssessmentDraft`` only when fail-closed validation passes

Outcome pledges are skipped on purpose. The default judge abstains. Matching
never publishes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    DocumentChunk,
    PledgeAssessmentOrigin,
    PledgeClassification,
    PledgeEvidenceCandidate,
    PledgeEvidenceCandidateStatus,
    Proposal,
    ProposalActor,
    ProposalSourceIdentifier,
    ProposalType,
    RawDocument,
    Source,
)
from backend.app.schemas.pledge import (
    PledgeAssessmentProposal,
    PledgeEvidenceCandidateResponse,
)
from backend.app.scoring.conservative_evidence_judge import ConservativeOfficialActJudge
from backend.app.scoring.evidence_matching import (
    MATCHER_VERSION,
    AbstainingJudge,
    Embedder,
    EvidenceJudge,
    Passage,
)
from backend.app.scoring.official_evidence import (
    OfficialPassage,
    retrieve_official_candidates,
    validate_official_judgment,
)
from backend.app.scoring.official_sources import classify_source_url
from backend.app.scoring.retrieval_profile import RetrievalProfile, build_retrieval_profile
from backend.app.scoring.types import (
    CommitmentType,
    EvidenceLabel,
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
    candidates_stored: int = 0
    unofficial_excluded: int = 0
    origin_excluded: int = 0
    no_candidate_abstentions: int = 0
    rejections: dict[str, int] = field(default_factory=dict)
    dry_run: bool = False


def _published_at_from_document(document: RawDocument) -> date | None:
    records = document.structured_records or []
    for record in records:
        if not isinstance(record, dict):
            continue
        value = record.get("official_published_at")
        if isinstance(value, str) and value:
            try:
                return date.fromisoformat(value)
            except ValueError:
                continue
    return None


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

    def _load_passages(self, session: Session) -> list[OfficialPassage]:
        rows = session.execute(
            select(DocumentChunk, RawDocument, Source)
            .join(RawDocument, RawDocument.id == DocumentChunk.raw_document_id)
            .join(Source, Source.id == RawDocument.source_id)
            .order_by(DocumentChunk.id)
        ).all()
        passages: list[OfficialPassage] = []
        for chunk, document, source in rows:
            passages.append(
                OfficialPassage(
                    passage=Passage(
                        passage_id=chunk.id,
                        raw_document_id=document.id,
                        text=chunk.text,
                        source_url=document.source_url,
                        retrieved_at=document.retrieved_at,
                        source_key=source.key,
                        source_name=source.name,
                        published_at=_published_at_from_document(document),
                    ),
                    source_id=source.id,
                    source_key=source.key,
                    source_name=source.name,
                    retrieved_at=document.retrieved_at,
                    published_at=_published_at_from_document(document),
                )
            )
        return passages

    def _profile(
        self,
        session: Session,
        proposal: Proposal,
        classification: PledgeClassification,
    ) -> RetrievalProfile:
        actors = session.scalars(
            select(ProposalActor).where(ProposalActor.proposal_id == proposal.id)
        )
        identifiers = session.scalars(
            select(ProposalSourceIdentifier).where(
                ProposalSourceIdentifier.proposal_id == proposal.id
            )
        )
        announcement = proposal.introduced_at or classification.mandate_start
        return build_retrieval_profile(
            proposal_id=proposal.id,
            title=proposal.canonical_title,
            commitment_text=proposal.exact_statement or proposal.canonical_title,
            actor_names=tuple(actor.display_name for actor in actors if actor.display_name),
            topic_code=classification.cap_topic_code,
            specificity=classification.specificity,
            commitment_type=classification.commitment_type,
            announcement_date=announcement,
            mandate_start=classification.mandate_start,
            mandate_end=classification.mandate_end,
            origin_urls=tuple(item.source_url for item in identifiers),
        )

    def _open_pledges(
        self, session: Session, proposal_ids: list[int] | None
    ) -> tuple[list[tuple[Proposal, PledgeClassification]], EvidenceMatchingReport]:
        report = EvidenceMatchingReport()
        query = (
            select(Proposal, PledgeClassification)
            .join(PledgeClassification, PledgeClassification.proposal_id == Proposal.id)
            .where(
                Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
                Proposal.published_at.is_not(None),
                PledgeClassification.specificity != PledgeSpecificity.VAGUE,
            )
            .order_by(Proposal.id)
        )
        if proposal_ids:
            query = query.where(Proposal.id.in_(proposal_ids))
        rows = session.execute(query).all()
        latest = PledgeService._latest_assessments(session, [proposal.id for proposal, _ in rows])
        work: list[tuple[Proposal, PledgeClassification]] = []
        for proposal, classification in rows:
            current = latest.get(proposal.id)
            verdict = current.verdict if current else FulfillmentVerdict.NOT_YET_RATED
            if verdict not in OPEN_VERDICTS:
                continue
            if classification.commitment_type is CommitmentType.OUTCOME:
                report.skipped_outcome_pledges += 1
                continue
            work.append((proposal, classification))
        return work, report

    def _store_candidates(
        self,
        session: Session,
        profile: RetrievalProfile,
        candidates,
        *,
        dry_run: bool,
    ) -> list[PledgeEvidenceCandidate]:
        stored: list[PledgeEvidenceCandidate] = []
        for candidate in candidates:
            existing = session.scalar(
                select(PledgeEvidenceCandidate).where(
                    PledgeEvidenceCandidate.proposal_id == profile.proposal_id,
                    PledgeEvidenceCandidate.document_chunk_id == candidate.document_chunk_id,
                )
            )
            payload = {
                "matcher_version": MATCHER_VERSION,
                "query": profile.query,
                "instrument_phrases": list(profile.instrument_phrases),
                "instrument_hits": list(candidate.instrument_hits),
                "topic_hits": list(candidate.topic_hits),
                "lexical_rank": candidate.lexical_rank,
                "retrieval_reason": candidate.retrieval_reason,
            }
            if existing is None:
                existing = PledgeEvidenceCandidate(
                    proposal_id=profile.proposal_id,
                    source_id=candidate.source_id,
                    raw_document_id=candidate.raw_document_id,
                    document_chunk_id=candidate.document_chunk_id,
                    source_url=candidate.source_url,
                    source_title=candidate.source_title,
                    published_at=candidate.published_at,
                    retrieved_at=candidate.retrieved_at,
                    exact_excerpt=candidate.exact_excerpt,
                    retrieval_reason=candidate.retrieval_reason,
                    deterministic_score=candidate.deterministic_score,
                    status=PledgeEvidenceCandidateStatus.RETRIEVED,
                    retrieval=payload,
                )
                if not dry_run:
                    session.add(existing)
                    session.flush()
            else:
                existing.deterministic_score = candidate.deterministic_score
                existing.exact_excerpt = candidate.exact_excerpt
                existing.retrieval = payload
                existing.updated_at = datetime.now(timezone.utc)
            stored.append(existing)
        if not dry_run:
            session.commit()
        return stored

    def _mark(
        self,
        candidate: PledgeEvidenceCandidate,
        *,
        status: PledgeEvidenceCandidateStatus,
        label: EvidenceLabel | None,
        excerpt: str | None = None,
        extra: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> None:
        candidate.status = status
        candidate.evidence_label_candidate = label
        if excerpt:
            candidate.exact_excerpt = excerpt
        retrieval = dict(candidate.retrieval or {})
        if extra:
            retrieval.update(extra)
        candidate.retrieval = retrieval
        candidate.updated_at = datetime.now(timezone.utc)
        if dry_run:
            return

    def list_candidates(
        self, proposal_id: int | None = None, *, limit: int = 50
    ) -> list[PledgeEvidenceCandidateResponse]:
        with self.session_factory() as session:
            query = select(PledgeEvidenceCandidate).order_by(
                PledgeEvidenceCandidate.proposal_id,
                PledgeEvidenceCandidate.deterministic_score.desc(),
            )
            if proposal_id is not None:
                query = query.where(PledgeEvidenceCandidate.proposal_id == proposal_id)
            return [
                PledgeEvidenceCandidateResponse(
                    id=row.id,
                    proposal_id=row.proposal_id,
                    source_url=row.source_url,
                    source_title=row.source_title,
                    published_at=row.published_at,
                    exact_excerpt=row.exact_excerpt,
                    retrieval_reason=row.retrieval_reason,
                    deterministic_score=row.deterministic_score,
                    evidence_label_candidate=row.evidence_label_candidate,
                    status=row.status.value,
                    raw_document_id=row.raw_document_id,
                    document_chunk_id=row.document_chunk_id,
                )
                for row in session.scalars(query.limit(limit))
            ]

    def run(
        self,
        *,
        proposal_ids: list[int] | None = None,
        dry_run: bool = False,
    ) -> EvidenceMatchingReport:
        with self.session_factory() as session:
            work, report = self._open_pledges(session, proposal_ids)
            report.dry_run = dry_run
            passages = self._load_passages(session)
            jobs: list[tuple[RetrievalProfile, list]] = []
            for proposal, classification in work:
                profile = self._profile(session, proposal, classification)
                candidates, reasons = retrieve_official_candidates(
                    profile, passages, limit=self.passages_per_pledge
                )
                report.unofficial_excluded += sum(
                    count
                    for key, count in reasons.items()
                    if key in {"unofficial_host", "blocked_non_official_host", "source_not_https"}
                )
                report.origin_excluded += reasons.get("origin_document", 0)
                report.rejections.update(
                    {key: report.rejections.get(key, 0) + value for key, value in reasons.items()}
                )
                stored = self._store_candidates(session, profile, candidates, dry_run=dry_run)
                report.candidates_stored += len(stored)
                jobs.append((profile, stored))

        for profile, stored in jobs:
            report.pledges_considered += 1
            if not stored:
                report.no_candidate_abstentions += 1
                continue
            for candidate in stored:
                report.passages_judged += 1
                with self.session_factory() as session:
                    row = session.get(PledgeEvidenceCandidate, candidate.id) if candidate.id else candidate
                    chunk = session.get(DocumentChunk, candidate.document_chunk_id)
                    passage_text = chunk.text if chunk is not None else candidate.exact_excerpt
                    judgment = self.judge.judge(
                        pledge_text=profile.query,
                        commitment_type=profile.commitment_type,
                        passage_text=passage_text,
                    )
                    reason = validate_official_judgment(
                        judgment,
                        passage_text,
                        source_url=candidate.source_url,
                        profile=profile,
                        published_at=candidate.published_at or profile.earliest_evidence_date,
                        is_origin=False,
                    )
                    extra = {
                        "judge_name": self.judge.name,
                        "judge_version": self.judge.version,
                        "prompt_version": getattr(self.judge, "version", None),
                        "validation_result": reason or "accepted",
                    }
                    if reason is not None:
                        report.rejections[reason] = report.rejections.get(reason, 0) + 1
                        status = (
                            PledgeEvidenceCandidateStatus.ABSTAINED
                            if reason == "not_enough_info"
                            else PledgeEvidenceCandidateStatus.REJECTED
                        )
                        if row is not None and getattr(row, "id", None):
                            self._mark(
                                row,
                                status=status,
                                label=judgment.label,
                                extra=extra,
                                dry_run=dry_run,
                            )
                            if not dry_run:
                                session.commit()
                        continue
                    if dry_run:
                        report.drafts_created += 1
                        continue
                    retrieval_meta = dict(candidate.retrieval or {})
                    draft, created = self.pledges.propose(
                        NewAssessmentDraft(
                            proposal_id=profile.proposal_id,
                            proposal=PledgeAssessmentProposal(
                                verdict=judgment.proposed_verdict,
                                evidence_label=judgment.label,
                                rationale=judgment.rationale,
                                quoted_excerpt=judgment.quoted_excerpt,
                                raw_document_id=candidate.raw_document_id,
                                document_chunk_id=candidate.document_chunk_id,
                                effective_at=candidate.published_at,
                            ),
                            origin=PledgeAssessmentOrigin.EVIDENCE_MATCHER,
                            created_by=MATCHER_IDENTITY,
                            retrieval={
                                "matcher_version": MATCHER_VERSION,
                                "candidate_id": candidate.id,
                                "score": candidate.deterministic_score,
                                "lexical_rank": retrieval_meta.get("lexical_rank"),
                                "instrument_hits": retrieval_meta.get("instrument_hits"),
                                "query": profile.query,
                                "validation_result": "accepted",
                            },
                            judge_name=self.judge.name,
                            judge_version=self.judge.version,
                        )
                    )
                    if row is not None:
                        self._mark(
                            row,
                            status=PledgeEvidenceCandidateStatus.DRAFTED,
                            label=judgment.label,
                            excerpt=judgment.quoted_excerpt,
                            extra={**extra, "draft_id": draft.id},
                            dry_run=False,
                        )
                        session.commit()
                    if created:
                        report.drafts_created += 1
                    else:
                        report.drafts_replayed += 1
        return report


def judge_from_name(name: str, *, model_name: str | None = None, base_url: str | None = None):
    if name in {"", "abstaining"}:
        return AbstainingJudge()
    if name in {"conservative", "conservative-official-act"}:
        return ConservativeOfficialActJudge()
    if name in {"llm", "ollama"}:
        from backend.app.scoring.llm_evidence_judge import OllamaEvidenceJudge

        if not model_name:
            raise ValueError("LLM judge requires a model name")
        return OllamaEvidenceJudge(
            model_name=model_name,
            base_url=base_url or "http://127.0.0.1:11434",
        )
    raise ValueError(f"unknown pledge evidence judge {name!r}")
