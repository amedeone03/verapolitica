from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app.models import (
    Politician,
    PoliticianSourceIdentifier,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalDraft,
    ProposalDraftKind,
    ProposalDraftStatus,
    ProposalReview,
    ProposalStatusEvent,
    ProposalType,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.schemas import (
    ObservedActorType,
    ProposalActorObservation,
    ProposalEvidenceObservation,
    ProposalObservation,
)
from backend.app.services import (
    ProposalReviewService,
    ProposalService,
    ProposalValidationError,
    normalize_person_name,
)


NOW = datetime(2026, 1, 11, 12, tzinfo=timezone.utc)


def setup_context(session_factory, source):
    with session_factory() as session:
        proposal_source = Source(
            key="senato-ddl",
            name="Senato della Repubblica — Disegni di legge",
            base_url="https://dati.senato.it",
        )
        politician = Politician(
            canonical_given_name="Anna",
            canonical_family_name="Rossi",
            normalized_name=normalize_person_name("Anna", "Rossi"),
            birth_date=date(1970, 1, 1),
        )
        session.add_all((proposal_source, politician))
        session.flush()
        session.add(
            PoliticianSourceIdentifier(
                politician_id=politician.id,
                source_id=source.id,
                value="https://dati.senato.it/senatore/synthetic-anna",
            )
        )
        session.commit()
        return proposal_source.id, politician.id


def add_document(session_factory, source_id, marker: str) -> int:
    with session_factory() as session:
        document = RawDocument(
            source_id=source_id,
            retrieved_at=NOW,
            source_url="https://dati.senato.it/sparql",
            content_type="application/json",
            storage_key=f"senato-ddl/{marker}.json",
            raw_sha256=marker[0] * 64,
            normalized_sha256=marker[-1] * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="fixture_v1",
            parser_version="fixture_v1",
        )
        session.add(document)
        session.commit()
        return document.id


def observation(
    raw_document_id: int,
    *,
    identifier: str = "https://dati.senato.it/ddl/synthetic-100",
    title: str = "Synthetic housing reform proposal",
    source_status: str = "da assegn. a commis.",
    normalized_status="introduced",
    effective_at: date = date(2026, 1, 10),
    actor_identifier: str = "https://dati.senato.it/senatore/synthetic-anna",
) -> ProposalObservation:
    return ProposalObservation(
        source_key="senato-ddl",
        raw_document_id=raw_document_id,
        proposal_identifier=identifier,
        title=title,
        proposal_type=ProposalType.LEGISLATIVE_PROPOSAL,
        introduced_at=date(2026, 1, 10),
        source_status_label=source_status,
        normalized_status=normalized_status,
        status_effective_at=effective_at,
        status_source_identifier=f"{identifier}#{effective_at}-{normalized_status}",
        official_url=identifier,
        source_field="osr:statoDdl",
        observed_at=NOW,
        actors=(
            ProposalActorObservation(
                actor_type=ObservedActorType.POLITICIAN,
                role=ProposalActorRole.PROPOSER,
                display_name="Sen. Anna Rossi",
                authority_key="senato-repubblica",
                source_identifier=actor_identifier,
                source_field="osr:senatore",
            ),
        ),
        evidence=(
            ProposalEvidenceObservation(
                field_path="title",
                source_url=identifier,
                source_field="osr:titolo",
                source_value=title,
            ),
            ProposalEvidenceObservation(
                field_path="proposal_type",
                source_url=identifier,
                source_field="rdf:type",
                source_value="osr:Ddl",
            ),
            ProposalEvidenceObservation(
                field_path="introduced_at",
                source_url=identifier,
                source_field="osr:dataPresentazione",
                source_value="2026-01-10",
            ),
            ProposalEvidenceObservation(
                field_path="current_status",
                source_url=identifier,
                source_field="osr:statoDdl",
                source_value=source_status,
            ),
            ProposalEvidenceObservation(
                field_path="actors[0]",
                source_url=identifier,
                source_field="osr:senatore",
                source_value=actor_identifier,
            ),
        ),
    )


def test_sync_is_internal_idempotent_and_resolves_actors(session_factory, source):
    proposal_source_id, politician_id = setup_context(session_factory, source)
    first_document = add_document(session_factory, proposal_source_id, "ab")
    first = ProposalService(session_factory).sync((observation(first_document),))

    assert first.proposals_created == 1
    assert first.drafts_created == 1
    assert first.resolved_actors == 1
    with session_factory() as session:
        proposal = session.scalar(select(Proposal))
        draft = session.scalar(select(ProposalDraft))
        assert proposal.published_at is None
        assert proposal.current_status is None
        assert draft.status is ProposalDraftStatus.PENDING
        assert session.scalar(select(func.count()).select_from(ProposalActor)) == 0
        assert session.scalar(select(func.count()).select_from(ProposalStatusEvent)) == 0

    second_document = add_document(session_factory, proposal_source_id, "cd")
    replay = ProposalService(session_factory).sync((observation(second_document),))
    assert replay.unchanged == 1
    assert replay.drafts_created == 0
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Proposal)) == 1
        assert session.scalar(select(func.count()).select_from(ProposalDraft)) == 1
        assert session.scalar(select(Politician.id).where(Politician.id == politician_id))


def test_approval_and_status_update_append_immutable_history(session_factory, source):
    proposal_source_id, politician_id = setup_context(session_factory, source)
    first_document = add_document(session_factory, proposal_source_id, "ab")
    initial = ProposalService(session_factory).sync(
        (observation(first_document, effective_at=date(2026, 1, 15)),)
    )
    initial_draft_id = initial.details[0].draft_id
    approved = ProposalReviewService(session_factory).approve(
        initial_draft_id, reviewer="editor", note="Official record checked"
    )
    assert approved.created_status_event_id is not None

    update_document = add_document(session_factory, proposal_source_id, "ef")
    update_observation = observation(
        update_document,
        source_status="esame in comm.",
        normalized_status="under_review",
        effective_at=date(2026, 2, 3),
    )
    update = ProposalService(session_factory).sync((update_observation,))
    update_draft_id = update.details[0].draft_id
    with session_factory() as session:
        draft = session.get(ProposalDraft, update_draft_id)
        assert draft.kind is ProposalDraftKind.STATUS_UPDATE
        assert draft.baseline_status_event_id == approved.created_status_event_id
    ProposalReviewService(session_factory).start_review(update_draft_id)
    ProposalReviewService(session_factory).approve(
        update_draft_id, reviewer="editor"
    )

    with session_factory() as session:
        proposal = session.scalar(select(Proposal))
        events = list(
            session.scalars(
                select(ProposalStatusEvent).order_by(ProposalStatusEvent.effective_at)
            )
        )
        actors = list(session.scalars(select(ProposalActor)))
        assert proposal.current_status.value == "under_review"
        assert [event.normalized_status.value for event in events] == [
            "introduced",
            "under_review",
        ]
        assert len(actors) == 1
        assert actors[0].politician_id == politician_id
        assert session.scalar(select(func.count()).select_from(ProposalReview)) == 2


def test_unresolved_actor_is_reported_and_never_attached_by_name(
    session_factory, source
):
    proposal_source_id, _ = setup_context(session_factory, source)
    document_id = add_document(session_factory, proposal_source_id, "ab")
    result = ProposalService(session_factory).sync(
        (
            observation(
                document_id,
                actor_identifier="https://dati.senato.it/senatore/not-known",
            ),
        )
    )
    assert result.unresolved_actors == 1
    assert result.details[0].unresolved_actors == ("Sen. Anna Rossi",)
    ProposalReviewService(session_factory).approve(
        result.details[0].draft_id, reviewer="editor"
    )
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ProposalActor)) == 0


def test_invalid_chronology_rolls_back_new_draft(session_factory, source):
    proposal_source_id, _ = setup_context(session_factory, source)
    first_document = add_document(session_factory, proposal_source_id, "ab")
    initial = ProposalService(session_factory).sync(
        (observation(first_document, effective_at=date(2026, 1, 15)),)
    )
    ProposalReviewService(session_factory).approve(
        initial.details[0].draft_id, reviewer="editor"
    )
    older_document = add_document(session_factory, proposal_source_id, "gh")
    older = observation(
        older_document,
        source_status="esame in comm.",
        normalized_status="under_review",
        effective_at=date(2026, 1, 12),
    )
    with pytest.raises(ProposalValidationError):
        ProposalService(session_factory).sync((older,))
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ProposalDraft)) == 1
        assert session.scalar(select(func.count()).select_from(ProposalStatusEvent)) == 1


def test_rejection_never_publishes_and_is_terminal(session_factory, source):
    proposal_source_id, _ = setup_context(session_factory, source)
    document_id = add_document(session_factory, proposal_source_id, "ab")
    created = ProposalService(session_factory).sync((observation(document_id),))
    draft_id = created.details[0].draft_id
    ProposalReviewService(session_factory).reject(draft_id, reviewer="editor")
    with session_factory() as session:
        proposal = session.scalar(select(Proposal))
        assert proposal.published_at is None
        assert proposal.current_status is None
        assert session.scalar(select(func.count()).select_from(ProposalStatusEvent)) == 0
    with pytest.raises(Exception, match="cannot be approved"):
        ProposalReviewService(session_factory).approve(draft_id, reviewer="editor")


def test_explicit_promise_requires_statement_and_commitment_owner():
    base = {
        "source_key": "synthetic-official",
        "raw_document_id": 1,
        "proposal_identifier": "promise-1",
        "title": "Synthetic explicit commitment",
        "proposal_type": "explicit_promise",
        "source_status_label": "announced",
        "normalized_status": "announced",
        "official_url": "https://example.invalid/official/promise-1",
        "source_field": "commitment",
        "observed_at": NOW,
        "evidence": [
            {
                "field_path": "exact_statement",
                "source_url": "https://example.invalid/official/promise-1",
                "source_field": "statement",
                "source_value": "We commit to publish a report.",
            },
            {
                "field_path": "title",
                "source_url": "https://example.invalid/official/promise-1",
                "source_field": "title",
                "source_value": "Synthetic explicit commitment",
            },
            {
                "field_path": "proposal_type",
                "source_url": "https://example.invalid/official/promise-1",
                "source_field": "type",
                "source_value": "explicit_promise",
            },
            {
                "field_path": "current_status",
                "source_url": "https://example.invalid/official/promise-1",
                "source_field": "status",
                "source_value": "announced",
            },
        ],
    }
    with pytest.raises(ValidationError, match="exact statement"):
        ProposalObservation.model_validate(base)

    promise = ProposalObservation.model_validate(
        {
            **base,
            "exact_statement": "We commit to publish a report.",
            "actors": [
                {
                    "actor_type": "institution",
                    "role": "commitment_owner",
                    "display_name": "Synthetic Ministry",
                    "institution_name": "Synthetic Ministry",
                    "source_field": "speaker",
                }
            ],
        }
    )
    assert promise.proposal_type is ProposalType.EXPLICIT_PROMISE
    assert promise.proposal_type is not ProposalType.LEGISLATIVE_PROPOSAL
    assert promise.exact_statement == "We commit to publish a report."
