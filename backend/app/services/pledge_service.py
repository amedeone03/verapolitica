"""Pledge classification, fulfilment review, scorecard and audit.

Rules enforced here (see docs/scoring-methodology.md):

* Only published ``explicit_promise`` proposals can be classified and assessed.
* A verdict is first a draft with a verbatim cited excerpt; publishing needs a
  human approval, and "broken" needs two distinct reviewers. An editor cannot
  be the only approver of a draft they proposed.
* Published assessments are append-only; the current verdict is the latest.
* Audit coders never see the published verdict and cannot audit an assessment
  they approved.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from backend.app.models import (
    DocumentChunk,
    PledgeAssessment,
    PledgeAssessmentApproval,
    PledgeAssessmentDraft,
    PledgeAssessmentDraftStatus,
    PledgeAssessmentOrigin,
    PledgeAuditCoding,
    PledgeAuditSample,
    PledgeClassification,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalActorType,
    ProposalType,
    RawDocument,
)
from backend.app.schemas.pledge import (
    AgreementResponse,
    AuditQualityReport,
    AuditSampleResponse,
    BiasAuditResponse,
    BlindAuditItem,
    BlocComparisonResponse,
    CompositionEntry,
    CorrectedRateResponse,
    MandateProgressResponse,
    PledgeAssessmentDraftResponse,
    PledgeAssessmentProposal,
    PledgeAssessmentResponse,
    PledgeClassificationRequest,
    PledgeClassificationResponse,
    PublicScorecard,
    PublicScorecardPledge,
    ScorecardStratumResponse,
    TopicEntry,
)
from backend.app.scoring import (
    AlphaMetric,
    BiasObservation,
    CLOSED_VERDICTS,
    DEFAULT_METHODOLOGY,
    DUAL_APPROVAL_VERDICTS,
    FulfillmentVerdict,
    HolderRole,
    MandateProgress,
    PledgeOutcome,
    PledgeSpecificity,
    ScoringMethodology,
    VERDICT_VALUE,
    compute_scorecard,
    design_based_mean,
    draw_audit_sample,
    krippendorff_alpha,
    partisan_skew_audit,
)
from backend.app.scoring.evidence_matching import excerpt_is_verbatim
from backend.app.scoring.types import CLOSED_VERDICT_ORDER, VERDICTS_BY_EVIDENCE_LABEL

METHODOLOGY_URL = "/methodology/scoring"


class PledgeServiceError(RuntimeError):
    pass


class PledgeNotFoundError(PledgeServiceError):
    pass


class PledgeValidationError(PledgeServiceError):
    pass


class PledgeConflictError(PledgeServiceError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def draft_identity_key(
    *,
    verdict: FulfillmentVerdict,
    label: str,
    excerpt: str,
    raw_document_id: int,
    effective_at: date | None,
) -> str:
    payload = json.dumps(
        [verdict.value, label, " ".join(excerpt.split()), raw_document_id,
         effective_at.isoformat() if effective_at else None],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def approvals_required(verdict: FulfillmentVerdict) -> int:
    return 2 if verdict in DUAL_APPROVAL_VERDICTS else 1


@dataclass(frozen=True, slots=True)
class NewAssessmentDraft:
    """Service-level input shared by editors and the evidence matcher."""

    proposal_id: int
    proposal: PledgeAssessmentProposal
    origin: PledgeAssessmentOrigin
    created_by: str
    retrieval: dict | None = None
    judge_name: str | None = None
    judge_version: str | None = None


class PledgeService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        methodology: ScoringMethodology = DEFAULT_METHODOLOGY,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.session_factory = session_factory
        self.methodology = methodology
        self.clock = clock

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _load_pledge(session: Session, proposal_id: int) -> Proposal:
        proposal = session.get(Proposal, proposal_id)
        if (
            proposal is None
            or proposal.published_at is None
            or proposal.proposal_type is not ProposalType.EXPLICIT_PROMISE
        ):
            raise PledgeNotFoundError("published explicit promise not found")
        return proposal

    @staticmethod
    def _classification(session: Session, proposal_id: int) -> PledgeClassification | None:
        return session.scalar(
            select(PledgeClassification).where(PledgeClassification.proposal_id == proposal_id)
        )

    @staticmethod
    def _latest_assessments(
        session: Session, proposal_ids: Iterable[int] | None = None
    ) -> dict[int, PledgeAssessment]:
        query = select(PledgeAssessment).order_by(
            PledgeAssessment.proposal_id, PledgeAssessment.created_at, PledgeAssessment.id
        )
        if proposal_ids is not None:
            ids = list(proposal_ids)
            if not ids:
                return {}
            query = query.where(PledgeAssessment.proposal_id.in_(ids))
        latest: dict[int, PledgeAssessment] = {}
        for assessment in session.scalars(query):
            latest[assessment.proposal_id] = assessment
        return latest

    @staticmethod
    def _classification_response(row: PledgeClassification) -> PledgeClassificationResponse:
        return PledgeClassificationResponse(
            proposal_id=row.proposal_id,
            specificity=row.specificity,
            commitment_type=row.commitment_type,
            holder_role=row.holder_role,
            cap_topic_code=row.cap_topic_code,
            mandate_start=row.mandate_start,
            mandate_end=row.mandate_end,
            included_in_score=row.specificity is not PledgeSpecificity.VAGUE,
            classified_by=row.classified_by,
            updated_at=row.updated_at,
        )

    @staticmethod
    def draft_response(draft: PledgeAssessmentDraft) -> PledgeAssessmentDraftResponse:
        proposal = getattr(draft, "proposal", None)
        return PledgeAssessmentDraftResponse(
            id=draft.id,
            proposal_id=draft.proposal_id,
            origin=draft.origin.value,
            status=draft.status.value,
            proposed_verdict=draft.proposed_verdict,
            evidence_label=draft.evidence_label,
            rationale=draft.rationale,
            quoted_excerpt=draft.quoted_excerpt,
            source_url=draft.source_url,
            raw_document_id=draft.raw_document_id,
            document_chunk_id=draft.document_chunk_id,
            effective_at=draft.effective_at,
            approvals=tuple(approval.reviewer for approval in draft.approvals),
            approvals_required=approvals_required(draft.proposed_verdict),
            judge_name=draft.judge_name,
            judge_version=draft.judge_version,
            created_by=draft.created_by,
            created_at=draft.created_at,
            commitment_title=proposal.canonical_title if proposal is not None else None,
            commitment_statement=proposal.exact_statement if proposal is not None else None,
            source_title=None,
        )

    @staticmethod
    def assessment_response(row: PledgeAssessment) -> PledgeAssessmentResponse:
        return PledgeAssessmentResponse(
            id=row.id,
            proposal_id=row.proposal_id,
            verdict=row.verdict,
            rationale=row.rationale,
            quoted_excerpt=row.quoted_excerpt,
            source_url=row.source_url,
            effective_at=row.effective_at,
            methodology_version=row.methodology_version,
            created_at=row.created_at,
        )

    # ----------------------------------------------------------- classification
    def classify(
        self, proposal_id: int, request: PledgeClassificationRequest, *, classified_by: str
    ) -> PledgeClassificationResponse:
        if (
            request.mandate_start is not None
            and request.mandate_end is not None
            and request.mandate_end < request.mandate_start
        ):
            raise PledgeValidationError("mandate_end precedes mandate_start")
        with self.session_factory.begin() as session:
            self._load_pledge(session, proposal_id)
            row = self._classification(session, proposal_id)
            if row is None:
                row = PledgeClassification(proposal_id=proposal_id)
                session.add(row)
            row.specificity = request.specificity
            row.commitment_type = request.commitment_type
            row.holder_role = request.holder_role
            row.cap_topic_code = request.cap_topic_code
            row.mandate_start = request.mandate_start
            row.mandate_end = request.mandate_end
            row.note = request.note
            row.classified_by = classified_by
            row.updated_at = self.clock()
            session.flush()
            return self._classification_response(row)

    # ------------------------------------------------------------------- drafts
    def propose(self, new: NewAssessmentDraft) -> tuple[PledgeAssessmentDraftResponse, bool]:
        """Create a draft. Returns ``(draft, created)``; replays are idempotent."""

        proposal = new.proposal
        allowed = VERDICTS_BY_EVIDENCE_LABEL[proposal.evidence_label]
        if proposal.verdict not in allowed:
            raise PledgeValidationError(
                f"verdict {proposal.verdict.value} is incompatible with evidence "
                f"label {proposal.evidence_label.value}"
            )
        with self.session_factory.begin() as session:
            self._load_pledge(session, new.proposal_id)
            if self._classification(session, new.proposal_id) is None:
                raise PledgeValidationError("classify the pledge before assessing it")
            document = session.get(RawDocument, proposal.raw_document_id)
            if document is None:
                raise PledgeValidationError("raw document not found")
            if proposal.document_chunk_id is not None:
                chunk = session.get(DocumentChunk, proposal.document_chunk_id)
                if chunk is None or chunk.raw_document_id != document.id:
                    raise PledgeValidationError("chunk does not belong to the raw document")
                haystack = chunk.text
            else:
                haystack = document.normalized_text or ""
            if not excerpt_is_verbatim(haystack, proposal.quoted_excerpt):
                raise PledgeValidationError("quoted excerpt is not verbatim in the source")
            key = draft_identity_key(
                verdict=proposal.verdict,
                label=proposal.evidence_label.value,
                excerpt=proposal.quoted_excerpt,
                raw_document_id=document.id,
                effective_at=proposal.effective_at,
            )
            existing = session.scalar(
                select(PledgeAssessmentDraft)
                .options(
                    selectinload(PledgeAssessmentDraft.approvals),
                    selectinload(PledgeAssessmentDraft.proposal),
                )
                .where(
                    PledgeAssessmentDraft.proposal_id == new.proposal_id,
                    PledgeAssessmentDraft.identity_key == key,
                )
            )
            if existing is not None:
                return self.draft_response(existing), False
            now = self.clock()
            draft = PledgeAssessmentDraft(
                proposal_id=new.proposal_id,
                origin=new.origin,
                status=PledgeAssessmentDraftStatus.PENDING,
                proposed_verdict=proposal.verdict,
                evidence_label=proposal.evidence_label,
                rationale=proposal.rationale,
                quoted_excerpt=proposal.quoted_excerpt,
                source_url=document.source_url,
                raw_document_id=document.id,
                document_chunk_id=proposal.document_chunk_id,
                effective_at=proposal.effective_at,
                retrieval=new.retrieval,
                judge_name=new.judge_name,
                judge_version=new.judge_version,
                created_by=new.created_by,
                identity_key=key,
                created_at=now,
                updated_at=now,
            )
            session.add(draft)
            session.flush()
            session.refresh(draft, ["approvals", "proposal"])
            return self.draft_response(draft), True

    def list_drafts(
        self,
        *,
        status: PledgeAssessmentDraftStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[PledgeAssessmentDraftResponse]:
        with self.session_factory() as session:
            query = select(PledgeAssessmentDraft).options(
                selectinload(PledgeAssessmentDraft.approvals),
                selectinload(PledgeAssessmentDraft.proposal),
            )
            if status is not None:
                query = query.where(PledgeAssessmentDraft.status == status)
            rows = session.scalars(
                query.order_by(PledgeAssessmentDraft.created_at, PledgeAssessmentDraft.id)
                .offset(offset)
                .limit(limit)
            )
            return [self.draft_response(row) for row in rows]

    def get_draft(self, draft_id: int) -> PledgeAssessmentDraftResponse:
        with self.session_factory() as session:
            draft = session.scalar(
                select(PledgeAssessmentDraft)
                .options(
                    selectinload(PledgeAssessmentDraft.approvals),
                    selectinload(PledgeAssessmentDraft.proposal),
                )
                .where(PledgeAssessmentDraft.id == draft_id)
            )
            if draft is None:
                raise PledgeNotFoundError("assessment draft not found")
            return self.draft_response(draft)

    def approve(
        self, draft_id: int, *, reviewer: str, note: str | None = None
    ) -> tuple[PledgeAssessmentDraftResponse, PledgeAssessmentResponse | None]:
        with self.session_factory.begin() as session:
            draft = session.scalar(
                select(PledgeAssessmentDraft)
                .options(
                    selectinload(PledgeAssessmentDraft.approvals),
                    selectinload(PledgeAssessmentDraft.proposal),
                )
                .where(PledgeAssessmentDraft.id == draft_id)
                .with_for_update()
            )
            if draft is None:
                raise PledgeNotFoundError("assessment draft not found")
            if draft.status not in (
                PledgeAssessmentDraftStatus.PENDING,
                PledgeAssessmentDraftStatus.AWAITING_SECOND_APPROVAL,
            ):
                raise PledgeConflictError(f"draft is {draft.status.value}")
            reviewers = {approval.reviewer for approval in draft.approvals}
            if reviewer in reviewers:
                raise PledgeConflictError("this reviewer already approved the draft")
            required = approvals_required(draft.proposed_verdict)
            if draft.origin is PledgeAssessmentOrigin.EDITOR and draft.created_by == reviewer:
                if required == 1 or not reviewers:
                    raise PledgeConflictError(
                        "the proposing editor cannot be the only approver"
                    )
            latest = self._latest_assessments(session, [draft.proposal_id]).get(
                draft.proposal_id
            )
            if (
                latest is not None
                and latest.effective_at is not None
                and draft.effective_at is not None
                and draft.effective_at < latest.effective_at
            ):
                raise PledgeConflictError("draft is older than the published verdict")

            now = self.clock()
            session.add(
                PledgeAssessmentApproval(
                    draft_id=draft.id, reviewer=reviewer, note=note, created_at=now
                )
            )
            session.flush()
            session.refresh(draft, ["approvals"])
            approvers = [approval.reviewer for approval in draft.approvals]
            if len(approvers) < required:
                draft.status = PledgeAssessmentDraftStatus.AWAITING_SECOND_APPROVAL
                draft.updated_at = now
                session.flush()
                return self.draft_response(draft), None

            assessment = PledgeAssessment(
                proposal_id=draft.proposal_id,
                draft_id=draft.id,
                verdict=draft.proposed_verdict,
                rationale=draft.rationale,
                quoted_excerpt=draft.quoted_excerpt,
                source_url=draft.source_url,
                raw_document_id=draft.raw_document_id,
                effective_at=draft.effective_at,
                approved_by=approvers,
                methodology_version=self.methodology.version,
                created_at=now,
            )
            session.add(assessment)
            draft.status = PledgeAssessmentDraftStatus.APPROVED
            draft.updated_at = now
            session.flush()
            return self.draft_response(draft), self.assessment_response(assessment)

    def reject(self, draft_id: int, *, reviewer: str, note: str) -> PledgeAssessmentDraftResponse:
        with self.session_factory.begin() as session:
            draft = session.scalar(
                select(PledgeAssessmentDraft)
                .options(
                    selectinload(PledgeAssessmentDraft.approvals),
                    selectinload(PledgeAssessmentDraft.proposal),
                )
                .where(PledgeAssessmentDraft.id == draft_id)
            )
            if draft is None:
                raise PledgeNotFoundError("assessment draft not found")
            if draft.status not in (
                PledgeAssessmentDraftStatus.PENDING,
                PledgeAssessmentDraftStatus.AWAITING_SECOND_APPROVAL,
            ):
                raise PledgeConflictError(f"draft is {draft.status.value}")
            draft.status = PledgeAssessmentDraftStatus.REJECTED
            draft.rejection_note = f"{reviewer}: {note.strip()}"
            draft.updated_at = self.clock()
            session.flush()
            return self.draft_response(draft)

    # ---------------------------------------------------------------- scorecard
    @staticmethod
    def _politician_pledges(session: Session, politician_id: int) -> list[Proposal]:
        return list(
            session.scalars(
                select(Proposal)
                .join(ProposalActor, ProposalActor.proposal_id == Proposal.id)
                .where(
                    ProposalActor.politician_id == politician_id,
                    ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
                    Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
                    Proposal.published_at.is_not(None),
                )
                .order_by(Proposal.id)
                .distinct()
            )
        )

    def scorecard_for_politician(
        self, politician_id: int, *, as_of: date | None = None
    ) -> PublicScorecard:
        as_of = as_of or self.clock().date()
        with self.session_factory() as session:
            pledges = self._politician_pledges(session, politician_id)
            ids = [pledge.id for pledge in pledges]
            classifications = {
                row.proposal_id: row
                for row in session.scalars(
                    select(PledgeClassification).where(PledgeClassification.proposal_id.in_(ids))
                )
            } if ids else {}
            latest = self._latest_assessments(session, ids)

            outcomes: list[PledgeOutcome] = []
            items: list[PublicScorecardPledge] = []
            for pledge in pledges:
                classification = classifications.get(pledge.id)
                if classification is None:
                    continue
                assessment = latest.get(pledge.id)
                verdict = assessment.verdict if assessment else FulfillmentVerdict.NOT_YET_RATED
                outcomes.append(
                    PledgeOutcome(
                        pledge_id=pledge.id,
                        verdict=verdict,
                        role=classification.holder_role,
                        specificity=classification.specificity,
                        commitment_type=classification.commitment_type,
                        topic_code=classification.cap_topic_code,
                    )
                )
                items.append(
                    PublicScorecardPledge(
                        proposal_id=pledge.id,
                        title=pledge.canonical_title,
                        exact_statement=pledge.exact_statement,
                        verdict=verdict,
                        role=classification.holder_role,
                        specificity=classification.specificity,
                        commitment_type=classification.commitment_type,
                        cap_topic_code=classification.cap_topic_code,
                        included_in_score=classification.specificity
                        is not PledgeSpecificity.VAGUE,
                        latest_assessment=(
                            self.assessment_response(assessment) if assessment else None
                        ),
                    )
                )

            windows = [
                row
                for row in classifications.values()
                if row.mandate_start is not None and row.mandate_end is not None
            ]
            progress = None
            if windows:
                current = max(windows, key=lambda row: (row.mandate_start, row.mandate_end))
                progress = MandateProgress(current.mandate_start, current.mandate_end, as_of)

        scorecard = compute_scorecard(
            outcomes, methodology=self.methodology, mandate_progress=progress
        )
        return PublicScorecard(
            politician_id=politician_id,
            methodology_version=scorecard.methodology_version,
            methodology_url=METHODOLOGY_URL,
            as_of=as_of,
            pledges=tuple(items),
            tracked_pledges=scorecard.tracked_pledges,
            unclassified_pledges=len(pledges) - len(items),
            excluded_vague_pledges=scorecard.excluded_vague_pledges,
            credible_level=scorecard.credible_level,
            min_closed_for_rate=scorecard.min_closed_for_rate,
            mandate_progress=(
                MandateProgressResponse(
                    start=progress.start,
                    end=progress.end,
                    as_of=progress.as_of,
                    elapsed_fraction=progress.elapsed_fraction,
                )
                if progress
                else None
            ),
            strata=tuple(
                ScorecardStratumResponse(
                    role=stratum.role,
                    composition=tuple(
                        CompositionEntry(verdict=verdict, count=count)
                        for verdict, count in stratum.composition
                    ),
                    scored_pledges=stratum.scored_pledges,
                    closed_pledges=stratum.closed_pledges,
                    open_pledges=stratum.open_pledges,
                    kept_equivalent=stratum.kept_equivalent,
                    rate=stratum.rate,
                    credible_interval=stratum.credible_interval,
                    rate_withheld_reason=stratum.rate_withheld_reason,
                    topics=tuple(
                        TopicEntry(cap_topic_code=code, count=count)
                        for code, count in stratum.topics
                    ),
                )
                for stratum in scorecard.strata
            ),
        )

    # -------------------------------------------------------------------- audit
    def _closed_current(
        self, session: Session
    ) -> list[tuple[PledgeAssessment, PledgeClassification]]:
        latest = self._latest_assessments(session)
        if not latest:
            return []
        classifications = {
            row.proposal_id: row
            for row in session.scalars(
                select(PledgeClassification).where(
                    PledgeClassification.proposal_id.in_(list(latest))
                )
            )
        }
        result = []
        for proposal_id, assessment in latest.items():
            classification = classifications.get(proposal_id)
            if (
                classification is None
                or classification.specificity is PledgeSpecificity.VAGUE
                or assessment.verdict not in CLOSED_VERDICTS
            ):
                continue
            result.append((assessment, classification))
        return result

    def _blind_items(
        self, session: Session, assessment_ids: Iterable[int]
    ) -> tuple[BlindAuditItem, ...]:
        ids = list(assessment_ids)
        if not ids:
            return ()
        rows = session.execute(
            select(PledgeAssessment, Proposal, PledgeClassification)
            .join(Proposal, Proposal.id == PledgeAssessment.proposal_id)
            .join(PledgeClassification, PledgeClassification.proposal_id == Proposal.id)
            .where(PledgeAssessment.id.in_(ids))
            .order_by(PledgeAssessment.id)
        ).all()
        return tuple(
            BlindAuditItem(
                assessment_id=assessment.id,
                proposal_id=proposal.id,
                title=proposal.canonical_title,
                exact_statement=proposal.exact_statement,
                commitment_type=classification.commitment_type,
                quoted_excerpt=assessment.quoted_excerpt,
                source_url=assessment.source_url,
            )
            for assessment, proposal, classification in rows
        )

    def draw_audit_sample(
        self, *, sample_key: str, size: int, seed: int, created_by: str
    ) -> AuditSampleResponse:
        with self.session_factory.begin() as session:
            if session.scalar(
                select(PledgeAuditSample.id).where(PledgeAuditSample.sample_key == sample_key)
            ):
                raise PledgeConflictError("sample key already exists")
            population = [assessment.id for assessment, _ in self._closed_current(session)]
            sample = draw_audit_sample(population, size=size, seed=seed, sample_key=sample_key)
            row = PledgeAuditSample(
                sample_key=sample_key,
                seed=seed,
                population_size=sample.population_size,
                inclusion_probability=sample.inclusion_probability,
                population_ids=sorted(set(population)),
                assessment_ids=list(sample.selected_ids),
                created_by=created_by,
                created_at=self.clock(),
            )
            session.add(row)
            session.flush()
            return AuditSampleResponse(
                sample_key=sample_key,
                seed=seed,
                population_size=sample.population_size,
                inclusion_probability=round(sample.inclusion_probability, 6),
                items=self._blind_items(session, sample.selected_ids),
            )

    def get_audit_sample(self, sample_key: str) -> AuditSampleResponse:
        with self.session_factory() as session:
            row = session.scalar(
                select(PledgeAuditSample).where(PledgeAuditSample.sample_key == sample_key)
            )
            if row is None:
                raise PledgeNotFoundError("audit sample not found")
            return AuditSampleResponse(
                sample_key=row.sample_key,
                seed=row.seed,
                population_size=row.population_size,
                inclusion_probability=round(row.inclusion_probability, 6),
                items=self._blind_items(session, row.assessment_ids),
            )

    def record_audit_coding(
        self,
        sample_key: str,
        assessment_id: int,
        *,
        coder: str,
        verdict: FulfillmentVerdict,
        note: str | None = None,
    ) -> None:
        if verdict not in CLOSED_VERDICTS:
            raise PledgeValidationError("audit codes must be kept, partially_kept or broken")
        with self.session_factory.begin() as session:
            sample = session.scalar(
                select(PledgeAuditSample).where(PledgeAuditSample.sample_key == sample_key)
            )
            if sample is None:
                raise PledgeNotFoundError("audit sample not found")
            if assessment_id not in sample.assessment_ids:
                raise PledgeValidationError("assessment is not part of this sample")
            assessment = session.get(PledgeAssessment, assessment_id)
            if assessment is None:
                raise PledgeNotFoundError("assessment not found")
            if coder in assessment.approved_by:
                raise PledgeConflictError("an approver cannot blind-audit their own verdict")
            exists = session.scalar(
                select(PledgeAuditCoding.id).where(
                    PledgeAuditCoding.sample_id == sample.id,
                    PledgeAuditCoding.assessment_id == assessment_id,
                    PledgeAuditCoding.coder == coder,
                )
            )
            if exists:
                raise PledgeConflictError("this coder already coded this assessment")
            session.add(
                PledgeAuditCoding(
                    sample_id=sample.id,
                    assessment_id=assessment_id,
                    coder=coder,
                    verdict=verdict,
                    note=note,
                    created_at=self.clock(),
                )
            )

    def audit_quality(self, sample_key: str) -> AuditQualityReport:
        with self.session_factory() as session:
            sample = session.scalar(
                select(PledgeAuditSample)
                .options(selectinload(PledgeAuditSample.codings))
                .where(PledgeAuditSample.sample_key == sample_key)
            )
            if sample is None:
                raise PledgeNotFoundError("audit sample not found")
            population_rows = session.execute(
                select(PledgeAssessment, PledgeClassification)
                .join(
                    PledgeClassification,
                    PledgeClassification.proposal_id == PledgeAssessment.proposal_id,
                )
                .where(PledgeAssessment.id.in_(sample.population_ids or [-1]))
            ).all()
            assessments = {assessment.id: assessment for assessment, _ in population_rows}
            # Agreement: published verdict as coder "published", plus each auditor.
            coders = sorted({coding.coder for coding in sample.codings})
            by_item: dict[int, dict[str, FulfillmentVerdict]] = {}
            for coding in sample.codings:
                by_item.setdefault(coding.assessment_id, {})[coding.coder] = coding.verdict
            units = [
                [assessments[item_id].verdict, *(codes.get(coder) for coder in coders)]
                for item_id, codes in sorted(by_item.items())
                if item_id in assessments
            ]
            nominal = krippendorff_alpha(units, metric=AlphaMetric.NOMINAL)
            ordinal = krippendorff_alpha(
                units, metric=AlphaMetric.ORDINAL, order=CLOSED_VERDICT_ORDER
            )

            # Design-based correction per role, over the population frozen at draw time.
            # The audit value of an item is the mean of its auditors' codes.
            audit_values = {
                item_id: sum(VERDICT_VALUE[v] for v in codes.values()) / len(codes)
                for item_id, codes in by_item.items()
            }
            population = population_rows
            corrected: list[CorrectedRateResponse] = []
            for role in HolderRole:
                members = {
                    assessment.id: VERDICT_VALUE[assessment.verdict]
                    for assessment, classification in population
                    if classification.holder_role is role
                }
                if not members:
                    continue
                audited = {
                    item_id: value
                    for item_id, value in audit_values.items()
                    if item_id in members
                }
                estimate = design_based_mean(
                    members,
                    audited,
                    inclusion_probability=sample.inclusion_probability or 1.0,
                )
                corrected.append(
                    CorrectedRateResponse(
                        role=role,
                        naive_rate=estimate.naive_estimate,
                        corrected_rate=estimate.corrected_estimate,
                        standard_error=estimate.standard_error,
                        confidence_interval=estimate.confidence_interval,
                        population_size=estimate.population_size,
                        audited=estimate.audited,
                        disagreement_rate=estimate.disagreement_rate,
                    )
                )
            return AuditQualityReport(
                sample_key=sample_key,
                coded_items=len(units),
                nominal_agreement=AgreementResponse(
                    metric=nominal.metric.value,
                    alpha=nominal.alpha,
                    pairable_units=nominal.pairable_units,
                ),
                ordinal_agreement=AgreementResponse(
                    metric=ordinal.metric.value,
                    alpha=ordinal.alpha,
                    pairable_units=ordinal.pairable_units,
                ),
                corrected_rates=tuple(corrected),
            )

    # --------------------------------------------------------------- bias audit
    def bias_audit(
        self, *, min_per_group: int = 5, flag_threshold: float = 0.15
    ) -> BiasAuditResponse:
        with self.session_factory() as session:
            population = self._closed_current(session)
            proposal_ids = [assessment.proposal_id for assessment, _ in population]
            blocs: dict[int, str] = {}
            if proposal_ids:
                for actor in session.scalars(
                    select(ProposalActor)
                    .where(
                        ProposalActor.proposal_id.in_(proposal_ids),
                        ProposalActor.actor_type == ProposalActorType.POLITICAL_PARTY,
                        ProposalActor.role.in_(
                            (ProposalActorRole.COMMITMENT_OWNER, ProposalActorRole.PROPOSER)
                        ),
                    )
                    .order_by(ProposalActor.id)
                ):
                    blocs.setdefault(actor.proposal_id, f"party:{actor.political_party_id}")
            observations = [
                BiasObservation(
                    bloc=blocs.get(assessment.proposal_id, "unattributed"),
                    role=classification.holder_role.value,
                    period=(
                        str(classification.mandate_start.year)
                        if classification.mandate_start
                        else "unknown"
                    ),
                    value=VERDICT_VALUE[assessment.verdict],
                )
                for assessment, classification in population
            ]
        report = partisan_skew_audit(
            observations, min_per_group=min_per_group, flag_threshold=flag_threshold
        )
        return BiasAuditResponse(
            methodology_version=self.methodology.version,
            min_per_group=report.min_per_group,
            flag_threshold=report.flag_threshold,
            skipped_strata=report.skipped_strata,
            comparisons=tuple(
                BlocComparisonResponse(
                    bloc=item.bloc,
                    stratum_count=item.stratum_count,
                    bloc_pledges=item.bloc_pledges,
                    other_pledges=item.other_pledges,
                    weighted_difference=item.weighted_difference,
                    confidence_interval=item.confidence_interval,
                    flagged=item.flagged,
                )
                for item in report.comparisons
            ),
        )
