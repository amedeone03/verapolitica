from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import event, func, select

from backend.app.db.base import Base
from backend.app.models import (
    Evidence,
    Politician,
    PoliticianSourceIdentifier,
    PoliticianVersion,
    ProfileDraft,
    ProfileDraftKind,
    ProfileDraftStatus,
    RawDocument,
    RawDocumentStatus,
)
from backend.app.pipeline.mappers import SenatoCandidateProfileMapper
from backend.app.schemas import (
    DraftCreatedResult,
    MatchedResult,
    MatchingMethod,
    NoChangesResult,
    SourceDocumentProvenance,
)
from backend.app.services import (
    DraftEvidenceError,
    DraftPersistenceError,
    DraftService,
    candidate_to_version_profile,
    normalize_person_name,
)


def parsed_record(
    *,
    identifier: str = "100",
    profession: str | None = "Avvocata",
    homepage: str | None = "https://example.test/profile",
    election_region: str | None = "Lazio",
) -> dict[str, str | None]:
    return {
        "senator_uri": f"https://dati.senato.it/senatore/{identifier}",
        "first_name": "Maria",
        "last_name": "Rossi",
        "gender": "F",
        "birth_date": "1970-01-02",
        "birth_city": "Roma",
        "birth_province": "RM",
        "birth_country": "Italia",
        "profession": profession,
        "photo_url": None,
        "homepage": homepage,
        "mandate_uri": f"https://dati.senato.it/mandato/{identifier}",
        "mandate_type": "elettivo",
        "mandate_start": "2022-10-13",
        "legislature": "19",
        "election_region": election_region,
    }


def add_candidate(session_factory, source, record, *, sequence: int = 1):
    raw_hash = f"{sequence:064x}"
    normalized_hash = f"{sequence + 100:064x}"
    retrieved_at = datetime(2026, 10, 2, tzinfo=timezone.utc) + timedelta(
        seconds=sequence
    )
    with session_factory() as session:
        document = RawDocument(
            source_id=source.id,
            retrieved_at=retrieved_at,
            source_url="https://dati.senato.it/sparql",
            content_type="application/json",
            storage_key=f"senato/{sequence}.json",
            raw_sha256=raw_hash,
            normalized_sha256=normalized_hash,
            structured_records=[record],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="senato_collector_v1",
            parser_version="senato_parser_v1",
        )
        session.add(document)
        session.commit()
        document_id = document.id

    provenance = SourceDocumentProvenance(
        source_key=source.key,
        raw_document_id=document_id,
        source_url="https://dati.senato.it/sparql",
        retrieved_at=retrieved_at,
        raw_sha256=raw_hash,
        normalized_sha256=normalized_hash,
        collector_version="senato_collector_v1",
        parser_version="senato_parser_v1",
    )
    candidate = SenatoCandidateProfileMapper().map_records(
        (record,), document=provenance
    )[0]
    return candidate, document_id


def add_politician(session_factory, source, candidate) -> int:
    identity = candidate.identity
    with session_factory() as session:
        politician = Politician(
            canonical_given_name=identity.given_name,
            canonical_family_name=identity.family_name,
            normalized_name=normalize_person_name(
                identity.given_name, identity.family_name
            ),
            birth_date=identity.birth_date,
        )
        politician.source_identifiers.append(
            PoliticianSourceIdentifier(
                source_id=source.id,
                value=identity.source_identifiers[0].value,
            )
        )
        session.add(politician)
        session.commit()
        return politician.id


def add_current_version(session_factory, politician_id, candidate) -> int:
    with session_factory() as session:
        politician = session.get(Politician, politician_id)
        version = PoliticianVersion(
            politician_id=politician_id,
            version_number=1,
            profile_schema_version=1,
            profile_data=candidate_to_version_profile(candidate).model_dump(mode="json"),
            published_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        session.add(version)
        session.flush()
        assert politician is not None
        politician.current_version = version
        session.commit()
        return version.id


def matched(politician_id: int) -> MatchedResult:
    return MatchedResult(
        politician_id=politician_id,
        method=MatchingMethod.OFFICIAL_SOURCE_IDENTIFIER,
    )


def database_counts(session_factory) -> tuple[int, int, int]:
    with session_factory() as session:
        return (
            session.scalar(select(func.count()).select_from(ProfileDraft)),
            session.scalar(select(func.count()).select_from(Evidence)),
            session.scalar(select(func.count()).select_from(PoliticianVersion)),
        )


def add_existing_draft(
    session_factory,
    politician_id,
    raw_document_id,
    status,
    *,
    baseline_version_id=None,
) -> int:
    with session_factory() as session:
        draft = ProfileDraft(
            politician_id=politician_id,
            baseline_version_id=baseline_version_id,
            raw_document_id=raw_document_id,
            kind=(
                ProfileDraftKind.UPDATE
                if baseline_version_id
                else ProfileDraftKind.INITIAL
            ),
            status=status,
            proposed_profile_data={},
            diff_data={},
        )
        session.add(draft)
        session.commit()
        return draft.id


def test_initial_draft_has_no_baseline_and_persists_field_evidence(
    session_factory, source
):
    candidate, _ = add_candidate(session_factory, source, parsed_record())
    politician_id = add_politician(session_factory, source, candidate)

    result = DraftService(session_factory).create(candidate, matched(politician_id))

    assert isinstance(result, DraftCreatedResult)
    assert result.kind.value == "initial"
    assert result.baseline_version_id is None
    assert result.evidence_count > 0
    with session_factory() as session:
        draft = session.get(ProfileDraft, result.draft_id)
        assert draft is not None
        assert draft.status is ProfileDraftStatus.PENDING
        assert draft.baseline_version_id is None
        assert draft.proposed_profile_data["profession"] == "Avvocata"
        evidence_paths = {item.field_path for item in draft.evidence}
        for change in result.diff.changes:
            if change.field_path == "mandates":
                assert any(path.startswith("mandates[") for path in evidence_paths)
            else:
                assert change.field_path in evidence_paths


def test_no_draft_is_created_when_candidate_equals_current_version(
    session_factory, source
):
    candidate, _ = add_candidate(session_factory, source, parsed_record())
    politician_id = add_politician(session_factory, source, candidate)
    version_id = add_current_version(session_factory, politician_id, candidate)

    result = DraftService(session_factory).create(candidate, matched(politician_id))

    assert isinstance(result, NoChangesResult)
    assert result.baseline_version_id == version_id
    assert database_counts(session_factory) == (0, 0, 1)


def test_update_draft_references_current_version_and_changed_field_evidence(
    session_factory, source
):
    baseline_candidate, _ = add_candidate(
        session_factory, source, parsed_record(profession="Avvocata"), sequence=1
    )
    changed_candidate, _ = add_candidate(
        session_factory, source, parsed_record(profession="Magistrata"), sequence=2
    )
    politician_id = add_politician(session_factory, source, baseline_candidate)
    version_id = add_current_version(
        session_factory, politician_id, baseline_candidate
    )

    result = DraftService(session_factory).create(
        changed_candidate, matched(politician_id)
    )

    assert isinstance(result, DraftCreatedResult)
    assert result.kind.value == "update"
    assert result.baseline_version_id == version_id
    assert [item.field_path for item in result.diff.changes] == ["profession"]
    with session_factory() as session:
        draft = session.get(ProfileDraft, result.draft_id)
        assert draft is not None
        assert [item.field_path for item in draft.evidence] == ["profession"]
        assert draft.evidence[0].source_field_name == "profession"
        assert draft.evidence[0].source_value == "Magistrata"


def test_missing_required_provenance_blocks_creation_safely(session_factory, source):
    candidate, _ = add_candidate(session_factory, source, parsed_record())
    politician_id = add_politician(session_factory, source, candidate)
    incomplete = candidate.model_copy(
        update={
            "provenance": candidate.provenance.model_copy(
                update={
                    "fields": tuple(
                        field
                        for field in candidate.provenance.fields
                        if field.target_path != "profile.profession"
                    )
                }
            )
        }
    )

    with pytest.raises(DraftEvidenceError, match="profession"):
        DraftService(session_factory).create(incomplete, matched(politician_id))

    assert database_counts(session_factory) == (0, 0, 0)


def test_removal_without_absence_provenance_is_rejected(session_factory, source):
    baseline_candidate, _ = add_candidate(
        session_factory, source, parsed_record(profession="Avvocata"), sequence=1
    )
    removed_candidate, _ = add_candidate(
        session_factory, source, parsed_record(profession=None), sequence=2
    )
    politician_id = add_politician(session_factory, source, baseline_candidate)
    add_current_version(session_factory, politician_id, baseline_candidate)

    with pytest.raises(DraftEvidenceError, match="profession"):
        DraftService(session_factory).create(
            removed_candidate, matched(politician_id)
        )

    assert database_counts(session_factory) == (0, 0, 1)


def test_new_meaningful_draft_supersedes_all_active_drafts(session_factory, source):
    candidate, raw_document_id = add_candidate(
        session_factory, source, parsed_record()
    )
    politician_id = add_politician(session_factory, source, candidate)
    pending_id = add_existing_draft(
        session_factory,
        politician_id,
        raw_document_id,
        ProfileDraftStatus.PENDING,
    )
    in_review_id = add_existing_draft(
        session_factory,
        politician_id,
        raw_document_id,
        ProfileDraftStatus.IN_REVIEW,
    )

    result = DraftService(session_factory).create(candidate, matched(politician_id))

    assert set(result.superseded_draft_ids) == {pending_id, in_review_id}
    with session_factory() as session:
        assert session.get(ProfileDraft, pending_id).status is ProfileDraftStatus.SUPERSEDED
        assert (
            session.get(ProfileDraft, in_review_id).status
            is ProfileDraftStatus.SUPERSEDED
        )
        new_draft = session.get(ProfileDraft, result.draft_id)
        assert new_draft is not None
        assert new_draft.supersedes_id in {pending_id, in_review_id}


def test_approved_and_rejected_drafts_are_not_superseded(session_factory, source):
    candidate, raw_document_id = add_candidate(
        session_factory, source, parsed_record()
    )
    politician_id = add_politician(session_factory, source, candidate)
    approved_id = add_existing_draft(
        session_factory,
        politician_id,
        raw_document_id,
        ProfileDraftStatus.APPROVED,
    )
    rejected_id = add_existing_draft(
        session_factory,
        politician_id,
        raw_document_id,
        ProfileDraftStatus.REJECTED,
    )

    DraftService(session_factory).create(candidate, matched(politician_id))

    with session_factory() as session:
        assert session.get(ProfileDraft, approved_id).status is ProfileDraftStatus.APPROVED
        assert session.get(ProfileDraft, rejected_id).status is ProfileDraftStatus.REJECTED


def test_evidence_failure_rolls_back_new_draft_and_supersession(
    session_factory, source
):
    candidate, raw_document_id = add_candidate(
        session_factory, source, parsed_record()
    )
    politician_id = add_politician(session_factory, source, candidate)
    pending_id = add_existing_draft(
        session_factory,
        politician_id,
        raw_document_id,
        ProfileDraftStatus.PENDING,
    )

    def fail_evidence_insert(mapper, connection, target):
        raise RuntimeError("injected evidence failure")

    event.listen(Evidence, "before_insert", fail_evidence_insert)
    try:
        with pytest.raises(DraftPersistenceError, match="rolled back"):
            DraftService(session_factory).create(candidate, matched(politician_id))
    finally:
        event.remove(Evidence, "before_insert", fail_evidence_insert)

    with session_factory() as session:
        drafts = list(session.scalars(select(ProfileDraft)))
        assert len(drafts) == 1
        assert drafts[0].id == pending_id
        assert drafts[0].status is ProfileDraftStatus.PENDING
        assert session.scalar(select(func.count()).select_from(Evidence)) == 0


def test_candidate_stays_transient_and_no_version_or_publication_is_created(
    session_factory, source
):
    candidate, _ = add_candidate(session_factory, source, parsed_record())
    politician_id = add_politician(session_factory, source, candidate)

    DraftService(session_factory).create(candidate, matched(politician_id))

    with session_factory() as session:
        politician = session.get(Politician, politician_id)
        assert politician is not None
        assert politician.current_version_id is None
        assert session.scalar(select(func.count()).select_from(PoliticianVersion)) == 0
        assert "candidate_profiles" not in Base.metadata.tables
