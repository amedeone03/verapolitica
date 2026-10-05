from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    Evidence,
    EvidenceExtractionMethod,
    Politician,
    ProfileDraft,
    ProfileDraftKind,
    ProfileDraftStatus,
    RawDocument,
    RawDocumentStatus,
)
from backend.app.schemas import (
    CandidateProfile,
    DraftCreatedResult,
    DraftResult,
    MatchedResult,
    NoChangesResult,
    ProfileDiff,
)
from backend.app.services.diff_service import DiffService


class DraftServiceError(RuntimeError):
    """Base error for controlled draft creation failures."""


class DraftProvenanceError(DraftServiceError):
    """Candidate document provenance does not match persisted source data."""


class DraftEvidenceError(DraftServiceError):
    """A changed field lacks field-level source provenance."""


class DraftPersistenceError(DraftServiceError):
    """Draft creation failed and its transaction was rolled back."""


@dataclass(frozen=True)
class EvidenceSpec:
    field_path: str
    raw_document_id: int
    source_url: str
    source_record_identifier: str
    source_field_name: str
    source_value: str
    extraction_method: EvidenceExtractionMethod


class DraftService:
    active_statuses = (
        ProfileDraftStatus.PENDING,
        ProfileDraftStatus.IN_REVIEW,
    )

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        diff_service: DiffService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.diff_service = diff_service or DiffService()

    def create(
        self,
        candidate: CandidateProfile,
        match: MatchedResult,
    ) -> DraftResult:
        try:
            with self.session_factory() as session:
                with session.begin():
                    politician = session.get(Politician, match.politician_id)
                    if politician is None:
                        raise DraftServiceError(
                            f"matched Politician {match.politician_id} does not exist"
                        )

                    baseline = politician.current_version
                    if baseline is not None and baseline.politician_id != politician.id:
                        raise DraftServiceError(
                            "current PoliticianVersion belongs to a different politician"
                        )
                    diff = self.diff_service.compare(candidate, baseline)
                    if not diff.changes:
                        if baseline is None:
                            raise DraftServiceError(
                                "an initial profile unexpectedly produced no changes"
                            )
                        return NoChangesResult(
                            politician_id=politician.id,
                            baseline_version_id=baseline.id,
                        )

                    raw_document = session.get(
                        RawDocument,
                        candidate.provenance.document.raw_document_id,
                    )
                    self._validate_document(candidate, raw_document)
                    evidence_specs = self._build_evidence(candidate, diff)

                    active_drafts = list(
                        session.scalars(
                            select(ProfileDraft)
                            .where(
                                ProfileDraft.politician_id == politician.id,
                                ProfileDraft.status.in_(self.active_statuses),
                            )
                            .order_by(
                                ProfileDraft.created_at.desc(),
                                ProfileDraft.id.desc(),
                            )
                            .with_for_update()
                        )
                    )
                    superseded_ids = tuple(draft.id for draft in active_drafts)
                    for active_draft in active_drafts:
                        active_draft.status = ProfileDraftStatus.SUPERSEDED

                    draft = ProfileDraft(
                        politician_id=politician.id,
                        baseline_version_id=baseline.id if baseline else None,
                        raw_document_id=raw_document.id,
                        supersedes_id=active_drafts[0].id if active_drafts else None,
                        kind=ProfileDraftKind(diff.status.value),
                        status=ProfileDraftStatus.PENDING,
                        profile_schema_version=1,
                        proposed_profile_data=diff.proposed_profile.model_dump(
                            mode="json"
                        ),
                        diff_data=diff.model_dump(mode="json"),
                    )
                    session.add(draft)
                    session.flush()

                    for spec in evidence_specs:
                        session.add(
                            Evidence(
                                draft_id=draft.id,
                                field_path=spec.field_path,
                                raw_document_id=spec.raw_document_id,
                                source_url=spec.source_url,
                                source_record_identifier=(
                                    spec.source_record_identifier
                                ),
                                source_field_name=spec.source_field_name,
                                source_value=spec.source_value,
                                extraction_method=spec.extraction_method,
                            )
                        )
                    session.flush()
                    result = DraftCreatedResult(
                        draft_id=draft.id,
                        politician_id=politician.id,
                        baseline_version_id=baseline.id if baseline else None,
                        kind=diff.status,
                        evidence_count=len(evidence_specs),
                        superseded_draft_ids=superseded_ids,
                        diff=diff,
                    )
            return result
        except DraftServiceError:
            raise
        except Exception as exc:
            raise DraftPersistenceError(
                f"draft creation failed; transaction rolled back: {exc}"
            ) from exc

    @staticmethod
    def _validate_document(
        candidate: CandidateProfile,
        raw_document: RawDocument | None,
    ) -> None:
        document = candidate.provenance.document
        if raw_document is None:
            raise DraftProvenanceError(
                f"RawDocument {document.raw_document_id} does not exist"
            )
        if raw_document.process_status != RawDocumentStatus.PARSED:
            raise DraftProvenanceError(
                f"RawDocument {raw_document.id} is not successfully parsed"
            )
        if raw_document.source.key != document.source_key:
            raise DraftProvenanceError("candidate source does not match RawDocument")
        comparisons = (
            ("source URL", raw_document.source_url, str(document.source_url)),
            ("raw hash", raw_document.raw_sha256, document.raw_sha256),
            (
                "normalized hash",
                raw_document.normalized_sha256,
                document.normalized_sha256,
            ),
            (
                "collector version",
                raw_document.collector_version,
                document.collector_version,
            ),
            ("parser version", raw_document.parser_version, document.parser_version),
        )
        for label, stored, claimed in comparisons:
            if stored != claimed:
                raise DraftProvenanceError(
                    f"candidate {label} does not match RawDocument {raw_document.id}"
                )

    def _build_evidence(
        self,
        candidate: CandidateProfile,
        diff: ProfileDiff,
    ) -> tuple[EvidenceSpec, ...]:
        document = candidate.provenance.document
        normalized = []
        for field in candidate.provenance.fields:
            path = self._canonical_field_path(field.target_path)
            if path is None:
                continue
            normalized.append((path, field))

        evidence: list[EvidenceSpec] = []
        for change in diff.changes:
            if change.field_path == "mandates":
                supporting = [
                    item for item in normalized if item[0].startswith("mandates[")
                ]
            else:
                supporting = [
                    item for item in normalized if item[0] == change.field_path
                ]
            if not supporting:
                raise DraftEvidenceError(
                    f"changed field {change.field_path!r} has no supporting provenance"
                )
            for canonical_path, field in supporting:
                evidence.append(
                    EvidenceSpec(
                        field_path=canonical_path,
                        raw_document_id=document.raw_document_id,
                        source_url=str(field.source_url or document.source_url),
                        source_record_identifier=field.source_record_id,
                        source_field_name=field.source_field,
                        source_value=field.source_value,
                        extraction_method=EvidenceExtractionMethod(field.method),
                    )
                )
        return tuple(evidence)

    @staticmethod
    def _canonical_field_path(candidate_path: str) -> str | None:
        if candidate_path.startswith("identity.source_identifiers"):
            return None
        if candidate_path.startswith("identity."):
            return candidate_path.removeprefix("identity.")
        if candidate_path.startswith("profile."):
            return candidate_path.removeprefix("profile.")
        return None
