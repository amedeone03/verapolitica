import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from backend.app.ai import (
    ExtractionChunk,
    ExtractionProviderError,
    ExtractionProviderOutputError,
    StructuredExtractionProvider,
    StructuredExtractionRequest,
)
from backend.app.models import (
    AIExtractionCandidate,
    AIExtractionCandidateEvidence,
    AIExtractionCandidateStatus,
    AIExtractionRun,
    AIExtractionRunStatus,
    DocumentChunk,
    ProposalActorRole,
    ProposalStatus,
    ProposalType,
    RawDocument,
    RawDocumentStatus,
)
from backend.app.pipeline.prompts import (
    PROPOSAL_EXTRACTION_PROMPT_VERSION,
    load_proposal_extraction_prompt,
)
from backend.app.pipeline.chunk_selection import (
    CHUNK_SELECTION_VERSION,
    DEFAULT_DOCUMENT_TOKEN_BUDGET,
    select_relevant_chunks,
)
from backend.app.schemas import (
    AI_EXTRACTION_SCHEMA_VERSION,
    ExtractedClaimType,
    ExtractedPoliticalClaim,
    ObservedActorType,
    ProposalActorObservation,
    ProposalEvidenceObservation,
    ProposalObservation,
)
from backend.app.services.proposal_service import ProposalService, ProposalServiceError


class ProposalExtractionError(RuntimeError):
    pass


class ProposalExtractionInputError(ProposalExtractionError):
    pass


class ProposalExtractionProviderFailure(ProposalExtractionError):
    def __init__(self, message: str, *, run_id: int) -> None:
        super().__init__(message)
        self.run_id = run_id


@dataclass(frozen=True, slots=True)
class ProposalExtractionSummary:
    run_id: int
    raw_document_id: int
    reused_completed_run: bool
    candidate_count: int
    accepted_count: int
    rejected_count: int
    abstained_count: int
    duplicate_count: int
    draft_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ActorIdentityHint:
    display_name: str
    actor_type: ObservedActorType
    authority_key: str
    source_identifier: str

    def __post_init__(self) -> None:
        if self.actor_type not in {
            ObservedActorType.POLITICIAN,
            ObservedActorType.POLITICAL_PARTY,
        }:
            raise ValueError("actor identity hints support politicians and parties only")


@dataclass(frozen=True, slots=True)
class _ValidatedEvidence:
    chunk: DocumentChunk
    page: int | None
    supporting_text: str


class ProposalExtractionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        provider: StructuredExtractionProvider,
        *,
        max_chunks_per_run: int,
        max_evidence_excerpt_chars: int,
        max_selected_chunks: int | None = None,
        max_document_tokens: int | None = None,
        prompt_version: str = PROPOSAL_EXTRACTION_PROMPT_VERSION,
        schema_version: str = AI_EXTRACTION_SCHEMA_VERSION,
        actor_identity_hints: tuple[ActorIdentityHint, ...] = (),
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.max_chunks_per_run = max_chunks_per_run
        self.max_evidence_excerpt_chars = max_evidence_excerpt_chars
        self.max_selected_chunks = max_selected_chunks or min(16, max_chunks_per_run)
        self.max_document_tokens = (
            DEFAULT_DOCUMENT_TOKEN_BUDGET
            if max_document_tokens is None
            else max_document_tokens
        )
        self.prompt_version = prompt_version
        self.schema_version = schema_version
        self.actor_identity_hints = {
            self._normalized_evidence(item.display_name): item
            for item in actor_identity_hints
        }

    def extract(self, raw_document_id: int) -> ProposalExtractionSummary:
        with self.session_factory() as session:
            document = session.scalar(
                select(RawDocument)
                .where(RawDocument.id == raw_document_id)
                .options(
                    selectinload(RawDocument.source),
                    selectinload(RawDocument.document_chunks),
                )
            )
            if document is None:
                raise ProposalExtractionInputError(
                    f"RawDocument {raw_document_id} does not exist"
                )
            if document.process_status is not RawDocumentStatus.PARSED:
                raise ProposalExtractionInputError(
                    "AI extraction requires a successfully parsed RawDocument"
                )
            chunks = tuple(
                sorted(document.document_chunks, key=lambda item: item.chunk_index)
            )
            if not chunks:
                raise ProposalExtractionInputError(
                    "AI extraction requires persisted document chunks"
                )
            selection = select_relevant_chunks(
                chunks,
                max_selected=min(self.max_selected_chunks, self.max_chunks_per_run),
                max_document_tokens=self.max_document_tokens,
            )
            if not selection.chunks:
                raise ProposalExtractionInputError(
                    "no relevant evidence sections could be selected from this document"
                )
            idempotency_key = self._idempotency_key(document)
            completed = session.scalar(
                select(AIExtractionRun)
                .where(
                    AIExtractionRun.completed_idempotency_key == idempotency_key,
                    AIExtractionRun.status == AIExtractionRunStatus.COMPLETED,
                )
                .options(selectinload(AIExtractionRun.candidates))
            )
            if completed is not None:
                return self._summary(completed, reused=True)
            source_key = document.source.key
            source_url = document.source_url
            observed_at = document.retrieved_at
            raw_sha256 = document.raw_sha256
            run = AIExtractionRun(
                raw_document_id=document.id,
                provider=self.provider.provider_name,
                model=self.provider.model_name,
                prompt_version=self.prompt_version,
                schema_version=self.schema_version,
                status=AIExtractionRunStatus.RUNNING,
                idempotency_key=idempotency_key,
                input_chunk_count=len(selection.chunks),
                provider_response={"chunk_selection": selection.as_dict()},
            )
            session.add(run)
            session.commit()
            run_id = run.id

        request = StructuredExtractionRequest(
            source_url=source_url,
            prompt=load_proposal_extraction_prompt(),
            chunks=tuple(
                ExtractionChunk(
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                )
                for chunk in selection.chunks
            ),
        )
        try:
            result = self.provider.extract(request)
        except ExtractionProviderError as exc:
            raw_output = (
                exc.raw_output
                if isinstance(exc, ExtractionProviderOutputError)
                else None
            )
            self._fail_run(
                run_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
                provider_response=self._safe_provider_response(raw_output),
            )
            raise ProposalExtractionProviderFailure(str(exc), run_id=run_id) from exc
        except Exception as exc:
            self._fail_run(
                run_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise ProposalExtractionProviderFailure(
                "extraction provider failed", run_id=run_id
            ) from exc

        chunk_by_index = {chunk.chunk_index: chunk for chunk in selection.chunks}
        accepted: list[tuple[int, ProposalObservation]] = []
        seen_deduplication_keys: set[str] = set()
        with self.session_factory() as session:
            run = session.get(AIExtractionRun, run_id)
            if run is None:
                raise ProposalExtractionError("AI extraction run disappeared")
            run.provider_response = {
                "output": result.output.model_dump(mode="json"),
                "provider_response_id": result.provider_response_id,
                "chunk_selection": selection.as_dict(),
            }
            diagnostics = getattr(self.provider, "last_diagnostics", None)
            dumped = getattr(diagnostics, "as_dict", None)
            if callable(dumped):
                run.provider_response = {
                    **run.provider_response,
                    "ollama_diagnostics": dumped(),
                }
            run.request_count = result.usage.request_count
            run.input_tokens = result.usage.input_tokens
            run.output_tokens = result.usage.output_tokens
            run.output_candidate_count = len(result.output.candidates)

            for index, claim in enumerate(result.output.candidates):
                candidate = AIExtractionCandidate(
                    run_id=run.id,
                    candidate_index=index,
                    status=AIExtractionCandidateStatus.REJECTED,
                    model_output=claim.model_dump(mode="json"),
                )
                session.add(candidate)
                session.flush()
                if claim.abstention_reason is not None:
                    candidate.status = AIExtractionCandidateStatus.ABSTAINED
                    candidate.validation_message = claim.abstention_reason.value
                    continue
                try:
                    self._validate_promise_language(claim)
                    validated_evidence = self._validate_evidence(
                        claim, chunk_by_index
                    )
                    self._validate_actor_evidence(claim, validated_evidence)
                    deduplication_key = self._claim_deduplication_key(claim)
                    candidate.deduplication_key = deduplication_key
                    if deduplication_key in seen_deduplication_keys:
                        candidate.status = AIExtractionCandidateStatus.DUPLICATE
                        candidate.validation_message = (
                            "deterministic duplicate within extraction run"
                        )
                        continue
                    seen_deduplication_keys.add(deduplication_key)
                    observation = self._build_observation(
                        claim=claim,
                        evidence=validated_evidence,
                        source_key=source_key,
                        raw_document_id=raw_document_id,
                        raw_sha256=raw_sha256,
                        source_url=source_url,
                        observed_at=observed_at,
                        deduplication_key=deduplication_key,
                        actor_identity_hints=self.actor_identity_hints,
                    )
                except (ValueError, ProposalExtractionInputError) as exc:
                    candidate.validation_message = str(exc)
                    continue
                candidate.status = AIExtractionCandidateStatus.ACCEPTED
                candidate.observation_data = observation.model_dump(mode="json")
                session.add_all(
                    AIExtractionCandidateEvidence(
                        candidate_id=candidate.id,
                        document_chunk_id=item.chunk.id,
                        page=item.page,
                        supporting_text=item.supporting_text,
                        source_url=source_url,
                    )
                    for item in validated_evidence
                )
                accepted.append((candidate.id, observation))
            session.commit()

        try:
            sync = ProposalService(self.session_factory).sync(
                tuple(observation for _, observation in accepted)
            )
        except ProposalServiceError as exc:
            with self.session_factory() as session:
                candidates = tuple(
                    session.scalars(
                        select(AIExtractionCandidate).where(
                            AIExtractionCandidate.run_id == run_id,
                            AIExtractionCandidate.status
                            == AIExtractionCandidateStatus.ACCEPTED,
                        )
                    )
                )
                for candidate in candidates:
                    candidate.status = AIExtractionCandidateStatus.REJECTED
                    candidate.validation_message = (
                        f"proposal integration rejected candidate: {exc}"
                    )
                session.commit()
            self._fail_run(
                run_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise ProposalExtractionError(
                f"proposal integration failed for extraction run {run_id}: {exc}"
            ) from exc

        with self.session_factory() as session:
            for (candidate_id, _), detail in zip(accepted, sync.details, strict=True):
                candidate = session.get(AIExtractionCandidate, candidate_id)
                if candidate is not None:
                    candidate.proposal_draft_id = detail.draft_id
            run = session.get(AIExtractionRun, run_id)
            if run is None:
                raise ProposalExtractionError("AI extraction run disappeared")
            counts = self._candidate_counts(session, run_id)
            run.rejected_candidate_count = counts[AIExtractionCandidateStatus.REJECTED]
            run.abstained_candidate_count = counts[AIExtractionCandidateStatus.ABSTAINED]
            run.duplicate_candidate_count = counts[AIExtractionCandidateStatus.DUPLICATE]
            run.status = AIExtractionRunStatus.COMPLETED
            run.completed_idempotency_key = run.idempotency_key
            run.completed_at = datetime.now(timezone.utc)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                completed = session.scalar(
                    select(AIExtractionRun)
                    .where(
                        AIExtractionRun.completed_idempotency_key == idempotency_key
                    )
                    .options(selectinload(AIExtractionRun.candidates))
                )
                if completed is None:
                    raise
                return self._summary(completed, reused=True)
            session.refresh(run)
            _ = run.candidates
            return self._summary(run, reused=False)

    def _idempotency_key(self, document: RawDocument) -> str:
        canonical = json.dumps(
            [
                document.source_id,
                document.raw_sha256,
                self.provider.provider_name,
                self.provider.model_name,
                self.prompt_version,
                self.schema_version,
                CHUNK_SELECTION_VERSION,
                min(self.max_selected_chunks, self.max_chunks_per_run),
                self.max_document_tokens,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    def _validate_evidence(
        self,
        claim: ExtractedPoliticalClaim,
        chunks: dict[int, DocumentChunk],
    ) -> tuple[_ValidatedEvidence, ...]:
        validated: list[_ValidatedEvidence] = []
        for item in claim.evidence:
            chunk = chunks.get(item.chunk_index)
            if chunk is None:
                raise ProposalExtractionInputError(
                    f"evidence references missing chunk {item.chunk_index}"
                )
            if item.page is not None:
                if chunk.page_start is None or chunk.page_end is None:
                    raise ProposalExtractionInputError(
                        "evidence page supplied for a chunk without page metadata"
                    )
                if not chunk.page_start <= item.page <= chunk.page_end:
                    raise ProposalExtractionInputError(
                        f"evidence page {item.page} does not belong to chunk "
                        f"{item.chunk_index}"
                    )
            excerpt = item.supporting_text.strip()
            if len(excerpt) > self.max_evidence_excerpt_chars:
                raise ProposalExtractionInputError(
                    "supporting evidence exceeds the configured excerpt limit"
                )
            if self._normalized_evidence(excerpt) not in self._normalized_evidence(
                chunk.text
            ):
                raise ProposalExtractionInputError(
                    f"supporting evidence does not occur in chunk {item.chunk_index}"
                )
            validated.append(
                _ValidatedEvidence(
                    chunk=chunk,
                    page=item.page,
                    supporting_text=excerpt,
                )
            )
        if not validated:
            raise ProposalExtractionInputError("claim has no validated evidence")
        return tuple(validated)

    @staticmethod
    def _validate_promise_language(claim: ExtractedPoliticalClaim) -> None:
        if claim.claim_type is not ExtractedClaimType.EXPLICIT_PROMISE:
            return
        statement = (claim.exact_statement or "").casefold()
        commitment = re.search(
            r"\b("
            r"we will|shall|commit(?:s|ted)? to|pledge(?:s|d)? to|"
            r"promise(?:s|d)? to|ci impegniamo a|si impegna a|"
            r"promettiamo di|promette di|provvederemo a|realizzeremo|"
            r"costruiremo|introdurremo|aboliremo|garantiremo"
            r")\b",
            statement,
        )
        if commitment is None:
            raise ProposalExtractionInputError(
                "explicit promise lacks deterministic commitment language"
            )

    @staticmethod
    def _validate_actor_evidence(
        claim: ExtractedPoliticalClaim,
        evidence: tuple[_ValidatedEvidence, ...],
    ) -> None:
        excerpts = " ".join(
            ProposalExtractionService._normalized_evidence(item.supporting_text)
            for item in evidence
        )
        for actor in claim.actor_mentions:
            if (
                ProposalExtractionService._normalized_evidence(actor.name)
                not in excerpts
            ):
                raise ProposalExtractionInputError(
                    f"actor mention {actor.name!r} is not supported by cited evidence"
                )

    @staticmethod
    def _normalized_evidence(value: str) -> str:
        normalized = unicodedata.normalize("NFC", value)
        return re.sub(r"\s+", " ", normalized).strip().casefold()

    @staticmethod
    def _claim_deduplication_key(claim: ExtractedPoliticalClaim) -> str:
        canonical = json.dumps(
            [
                ProposalExtractionService._normalized_evidence(
                    claim.exact_statement or ""
                ),
                sorted(
                    ProposalExtractionService._normalized_evidence(actor.name)
                    for actor in claim.actor_mentions
                ),
                claim.target_date.isoformat() if claim.target_date else None,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _build_observation(
        *,
        claim: ExtractedPoliticalClaim,
        evidence: tuple[_ValidatedEvidence, ...],
        source_key: str,
        raw_document_id: int,
        raw_sha256: str,
        source_url: str,
        observed_at: datetime,
        deduplication_key: str,
        actor_identity_hints: dict[str, ActorIdentityHint],
    ) -> ProposalObservation:
        if claim.claim_type is None or claim.normalized_title is None:
            raise ValueError("validated claim is missing required fields")
        proposal_type = (
            ProposalType.EXPLICIT_PROMISE
            if claim.claim_type is ExtractedClaimType.EXPLICIT_PROMISE
            else ProposalType.PROPOSAL
        )
        identifier = (
            f"urn:verapolitica:official-claim:{raw_sha256}:{deduplication_key}"
        )
        actors = []
        for actor in claim.actor_mentions:
            hint = actor_identity_hints.get(
                ProposalExtractionService._normalized_evidence(actor.name)
            )
            actors.append(
                ProposalActorObservation(
                    actor_type=(
                        hint.actor_type if hint else ObservedActorType.UNRESOLVED
                    ),
                    role=actor.role,
                    display_name=actor.name,
                    authority_key=hint.authority_key if hint else None,
                    source_identifier=hint.source_identifier if hint else None,
                    source_field=f"chunk:{evidence[0].chunk.chunk_index}",
                )
            )
        first = evidence[0]
        required_paths = ["title", "proposal_type", "current_status"]
        if claim.announced_at is not None:
            required_paths.append("introduced_at")
        if proposal_type is ProposalType.EXPLICIT_PROMISE:
            required_paths.append("exact_statement")
        observation_evidence = tuple(
            ProposalEvidenceObservation(
                field_path=path,
                source_url=source_url,
                source_field=f"chunk:{first.chunk.chunk_index}",
                source_value=first.supporting_text,
            )
            for path in required_paths
        ) + tuple(
            ProposalEvidenceObservation(
                field_path=f"supporting_evidence[{index}]",
                source_url=source_url,
                source_field=f"chunk:{item.chunk.chunk_index}",
                source_value=item.supporting_text,
            )
            for index, item in enumerate(evidence[1:], start=1)
        )
        return ProposalObservation(
            source_key=source_key,
            raw_document_id=raw_document_id,
            proposal_identifier=identifier,
            title=claim.normalized_title,
            summary=claim.summary,
            exact_statement=claim.exact_statement,
            proposal_type=proposal_type,
            introduced_at=claim.announced_at,
            source_status_label="announced in official document",
            normalized_status=ProposalStatus.ANNOUNCED,
            status_effective_at=claim.announced_at,
            status_source_identifier=f"{identifier}#announced",
            official_url=source_url,
            status_url=source_url,
            source_field=f"chunk:{first.chunk.chunk_index}",
            observed_at=observed_at,
            actors=tuple(actors),
            evidence=observation_evidence,
            metadata={
                "_ai_assisted": True,
                "topic": claim.topic.value if claim.topic else None,
                "target_date": (
                    claim.target_date.isoformat() if claim.target_date else None
                ),
            },
        )

    def _fail_run(
        self,
        run_id: int,
        *,
        error_type: str,
        error_message: str,
        provider_response: dict[str, Any] | list[Any] | None = None,
    ) -> None:
        with self.session_factory() as session:
            run = session.get(AIExtractionRun, run_id)
            if run is None:
                return
            run.status = AIExtractionRunStatus.FAILED
            run.error_type = error_type[:200]
            run.error_message = error_message[:4_000]
            current = run.provider_response if isinstance(run.provider_response, dict) else {}
            if provider_response is not None:
                current = {**current, "provider_output": provider_response}
            diagnostics = getattr(self.provider, "last_diagnostics", None)
            dumped = getattr(diagnostics, "as_dict", None)
            if callable(dumped):
                current = {**current, "ollama_diagnostics": dumped()}
            if current:
                run.provider_response = current
            run.completed_at = datetime.now(timezone.utc)
            session.commit()

    @staticmethod
    def _safe_provider_response(value: object | None):
        if value is None:
            return None
        try:
            encoded = json.dumps(value, ensure_ascii=False)
            if len(encoded) > 100_000:
                return {"truncated": True, "preview": encoded[:10_000]}
            decoded = json.loads(encoded)
            return decoded if isinstance(decoded, (dict, list)) else {"value": decoded}
        except (TypeError, ValueError):
            return {"unserializable_type": type(value).__name__}

    @staticmethod
    def _candidate_counts(
        session: Session, run_id: int
    ) -> dict[AIExtractionCandidateStatus, int]:
        candidates = tuple(
            session.scalars(
                select(AIExtractionCandidate).where(
                    AIExtractionCandidate.run_id == run_id
                )
            )
        )
        return {
            status: sum(candidate.status is status for candidate in candidates)
            for status in AIExtractionCandidateStatus
        }

    @staticmethod
    def _summary(
        run: AIExtractionRun, *, reused: bool
    ) -> ProposalExtractionSummary:
        candidates = tuple(run.candidates)
        return ProposalExtractionSummary(
            run_id=run.id,
            raw_document_id=run.raw_document_id,
            reused_completed_run=reused,
            candidate_count=len(candidates),
            accepted_count=sum(
                item.status is AIExtractionCandidateStatus.ACCEPTED
                for item in candidates
            ),
            rejected_count=sum(
                item.status is AIExtractionCandidateStatus.REJECTED
                for item in candidates
            ),
            abstained_count=sum(
                item.status is AIExtractionCandidateStatus.ABSTAINED
                for item in candidates
            ),
            duplicate_count=sum(
                item.status is AIExtractionCandidateStatus.DUPLICATE
                for item in candidates
            ),
            draft_ids=tuple(
                item.proposal_draft_id
                for item in candidates
                if item.proposal_draft_id is not None
            ),
        )
