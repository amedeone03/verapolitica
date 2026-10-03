from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    Politician,
    PoliticianVersion,
    PoliticianVersionCitation,
    ProfileDraft,
    ProfileDraftKind,
    ProfileDraftStatus,
    Review,
    ReviewDecision,
    Evidence,
    RawDocument,
    Source,
)
from backend.app.schemas import (
    PoliticianVersionProfile,
    PublicCitation,
    ReviewDecisionResult,
)
from backend.app.services.review_service import (
    DraftNotFoundError,
    DraftNotReviewableError,
    ReviewInputError,
    normalize_review_input,
)


class PublishServiceError(RuntimeError):
    """Base error for controlled publication failures."""


class StaleDraftError(PublishServiceError):
    """The politician's current version no longer matches the draft baseline."""


class InvalidDraftError(PublishServiceError):
    """The draft is structurally invalid or contains invalid profile data."""


class PublishConflictError(PublishServiceError):
    """A concurrent final decision or version publication won the race."""


class PublishPersistenceError(PublishServiceError):
    """Approval failed and its transaction was rolled back."""


class PublishService:
    reviewable_statuses = (
        ProfileDraftStatus.PENDING,
        ProfileDraftStatus.IN_REVIEW,
    )

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def approve(
        self,
        draft_id: int,
        *,
        reviewer: str,
        note: str | None = None,
    ) -> ReviewDecisionResult:
        normalized_reviewer, normalized_note = normalize_review_input(reviewer, note)
        try:
            with self.session_factory() as session:
                with session.begin():
                    draft = self._load_draft(session, draft_id)
                    if draft.status not in self.reviewable_statuses:
                        raise DraftNotReviewableError(
                            f"draft {draft.id} cannot be approved from "
                            f"status {draft.status.value!r}"
                        )
                    if draft.review is not None:
                        raise DraftNotReviewableError(
                            f"draft {draft.id} already has a final Review"
                        )

                    politician = session.scalar(
                        select(Politician)
                        .where(Politician.id == draft.politician_id)
                        .with_for_update()
                    )
                    if politician is None:
                        raise InvalidDraftError(
                            f"draft {draft.id} references a missing Politician"
                        )
                    self._validate_baseline(session, draft, politician)
                    profile = self._validate_profile(draft)
                    citations = self._build_public_citations(session, draft)

                    next_version_number = (
                        session.scalar(
                            select(func.max(PoliticianVersion.version_number)).where(
                                PoliticianVersion.politician_id == politician.id
                            )
                        )
                        or 0
                    ) + 1
                    version = PoliticianVersion(
                        politician_id=politician.id,
                        version_number=next_version_number,
                        profile_schema_version=draft.profile_schema_version,
                        profile_data=profile.model_dump(mode="json"),
                        published_at=datetime.now(timezone.utc),
                    )
                    session.add(version)
                    session.flush()

                    session.add_all(
                        PoliticianVersionCitation(
                            politician_version_id=version.id,
                            field_path=citation.field_path,
                            source_name=citation.source_name,
                            source_url=str(citation.source_url),
                            source_field=citation.source_field or "",
                        )
                        for citation in citations
                    )
                    session.flush()

                    politician.current_version_id = version.id
                    draft.status = ProfileDraftStatus.APPROVED
                    review = Review(
                        draft_id=draft.id,
                        reviewer=normalized_reviewer,
                        decision=ReviewDecision.APPROVED,
                        note=normalized_note,
                    )
                    session.add(review)
                    session.flush()

                    result = ReviewDecisionResult(
                        review_id=review.id,
                        decision=review.decision,
                        draft_id=draft.id,
                        politician_id=politician.id,
                        created_version_id=version.id,
                        version_number=version.version_number,
                        current_version_id=politician.current_version_id,
                        final_draft_status=draft.status,
                    )
            return result
        except (
            PublishServiceError,
            DraftNotFoundError,
            DraftNotReviewableError,
            ReviewInputError,
        ):
            raise
        except IntegrityError as exc:
            raise PublishConflictError(
                "approval conflicted with another publication; transaction rolled back"
            ) from exc
        except Exception as exc:
            raise PublishPersistenceError(
                f"approval failed; transaction rolled back: {exc}"
            ) from exc

    @staticmethod
    def _load_draft(session: Session, draft_id: int) -> ProfileDraft:
        draft = session.scalar(
            select(ProfileDraft)
            .where(ProfileDraft.id == draft_id)
            .with_for_update()
        )
        if draft is None:
            raise DraftNotFoundError(f"ProfileDraft {draft_id} does not exist")
        return draft

    @staticmethod
    def _validate_baseline(
        session: Session,
        draft: ProfileDraft,
        politician: Politician,
    ) -> None:
        if draft.kind is ProfileDraftKind.INITIAL:
            if draft.baseline_version_id is not None:
                raise InvalidDraftError(
                    f"initial draft {draft.id} must not have a baseline version"
                )
            if politician.current_version_id is not None:
                raise StaleDraftError(
                    f"initial draft {draft.id} is stale because Politician "
                    f"{politician.id} now has version {politician.current_version_id}"
                )
            return

        if draft.kind is ProfileDraftKind.UPDATE:
            if draft.baseline_version_id is None:
                raise InvalidDraftError(
                    f"update draft {draft.id} must have a baseline version"
                )
            baseline = session.get(PoliticianVersion, draft.baseline_version_id)
            if baseline is None or baseline.politician_id != politician.id:
                raise InvalidDraftError(
                    f"draft {draft.id} baseline does not belong to Politician "
                    f"{politician.id}"
                )
            if politician.current_version_id != draft.baseline_version_id:
                raise StaleDraftError(
                    f"update draft {draft.id} is stale: expected current version "
                    f"{draft.baseline_version_id}, found {politician.current_version_id}"
                )
            return

        raise InvalidDraftError(f"draft {draft.id} has unsupported kind {draft.kind!r}")

    @staticmethod
    def _validate_profile(draft: ProfileDraft) -> PoliticianVersionProfile:
        try:
            return PoliticianVersionProfile.model_validate(
                draft.proposed_profile_data
            )
        except ValidationError as exc:
            raise InvalidDraftError(
                f"draft {draft.id} has invalid proposed profile data: {exc}"
            ) from exc

    @staticmethod
    def _build_public_citations(
        session: Session,
        draft: ProfileDraft,
    ) -> tuple[PublicCitation, ...]:
        rows = session.execute(
            select(
                Evidence.field_path,
                Source.name,
                Evidence.source_url,
                Evidence.source_field_name,
            )
            .join(RawDocument, RawDocument.id == Evidence.raw_document_id)
            .join(Source, Source.id == RawDocument.source_id)
            .where(Evidence.draft_id == draft.id)
        ).all()
        public_values = {
            (field_path, source_name, source_url, source_field_name)
            for field_path, source_name, source_url, source_field_name in rows
        }
        if draft.baseline_version_id is not None:
            changed_paths = {
                change.get("field_path")
                for change in draft.diff_data.get("changes", [])
                if isinstance(change, dict)
            }
            baseline_citations = session.scalars(
                select(PoliticianVersionCitation).where(
                    PoliticianVersionCitation.politician_version_id
                    == draft.baseline_version_id
                )
            )
            for citation in baseline_citations:
                if not any(
                    PublishService._citation_path_is_changed(
                        citation.field_path, changed_path
                    )
                    for changed_path in changed_paths
                    if isinstance(changed_path, str)
                ):
                    public_values.add(
                        (
                            citation.field_path,
                            citation.source_name,
                            citation.source_url,
                            citation.source_field,
                        )
                    )
        return tuple(
            PublicCitation(
                field_path=field_path,
                source_name=source_name,
                source_url=source_url,
                source_field=source_field,
            )
            for field_path, source_name, source_url, source_field in sorted(public_values)
        )

    @staticmethod
    def _citation_path_is_changed(citation_path: str, changed_path: str) -> bool:
        return (
            citation_path == changed_path
            or citation_path.startswith(f"{changed_path}[")
            or citation_path.startswith(f"{changed_path}.")
        )
