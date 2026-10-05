from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select

from backend.app.models import (
    IdentityResolutionCase,
    IdentityResolutionStatus,
    ImmutableIdentityResolutionSnapshotError,
    Politician,
    PoliticianSourceIdentifier,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.schemas import (
    CandidateIdentity,
    CandidateProfile,
    CandidateProfileData,
    CandidateProvenance,
    FieldProvenance,
    MatchedResult,
    MatchingMethod,
    PoliticalMandate,
    SourceDocumentProvenance,
    SourceIdentifier,
)
from backend.app.services import (
    HumanIdentityResolutionCoordinator,
    IdentityResolutionConflictError,
    IdentityResolutionService,
    IdentityResolutionStateError,
    MatchingService,
    normalize_person_name,
)


def setup_governo_source(session_factory) -> tuple[Source, RawDocument]:
    with session_factory() as session:
        source = Source(
            key="governo-italiano",
            name="Governo Italiano",
            base_url="https://www.governo.it",
        )
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
            source_url="https://www.governo.it/it/ministri-e-sottosegretari",
            content_type="application/vnd.verapolitica.governo-bundle+json",
            storage_key="governo/identity-resolution.json",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="governo_collector_v1",
            parser_version="governo_parser_v1",
        )
        session.add(document)
        session.commit()
        return source, document


def candidate(
    document: RawDocument,
    *,
    identifier: str = "https://www.governo.it/it/node/9001",
    given_name: str = "Antonio",
    family_name: str = "Example",
    display_name: str = "Antonio Example",
    birth_date: date | None = None,
) -> CandidateProfile:
    profile_url = "https://www.governo.it/it/governo/example/antonio-example"
    return CandidateProfile(
        identity=CandidateIdentity(
            display_name=display_name,
            given_name=given_name,
            family_name=family_name,
            birth_date=birth_date,
            source_identifiers=(
                SourceIdentifier(
                    authority="governo-italiano",
                    value=identifier,
                ),
            ),
        ),
        profile=CandidateProfileData(
            official_homepage_url=profile_url,
            mandates=(
                PoliticalMandate(
                    institution="Governo Italiano",
                    office="Sottosegretario",
                    legislature="Governo Meloni",
                    mandate_type="Sottosegretario di Stato",
                    start_date=date(2022, 10, 31),
                ),
            ),
        ),
        provenance=CandidateProvenance(
            document=SourceDocumentProvenance(
                source_key="governo-italiano",
                raw_document_id=document.id,
                source_url=document.source_url,
                retrieved_at=document.retrieved_at,
                raw_sha256=document.raw_sha256,
                normalized_sha256=document.normalized_sha256,
                collector_version=document.collector_version,
                parser_version=document.parser_version,
            ),
            fields=(
                FieldProvenance(
                    target_path="identity.given_name",
                    source_record_id=profile_url,
                    source_field="h1.title_small",
                    source_value=given_name,
                    source_url=profile_url,
                ),
            ),
        ),
    )


def add_politician(
    session_factory,
    *,
    source: Source | None = None,
    identifier: str | None = None,
    given_name: str = "Antonio",
    family_name: str = "Example",
    birth_date: date | None = None,
) -> int:
    with session_factory() as session:
        politician = Politician(
            canonical_given_name=given_name,
            canonical_family_name=family_name,
            normalized_name=normalize_person_name(given_name, family_name),
            birth_date=birth_date,
        )
        session.add(politician)
        session.flush()
        if source is not None and identifier is not None:
            session.add(
                PoliticianSourceIdentifier(
                    politician_id=politician.id,
                    source_id=source.id,
                    value=identifier,
                )
            )
        session.commit()
        return politician.id


def counts(session_factory) -> tuple[int, int, int]:
    with session_factory() as session:
        return (
            session.scalar(select(func.count()).select_from(IdentityResolutionCase)),
            session.scalar(select(func.count()).select_from(Politician)),
            session.scalar(
                select(func.count()).select_from(PoliticianSourceIdentifier)
            ),
        )


def test_missing_birth_creates_one_idempotent_pending_case(session_factory):
    _, document = setup_governo_source(session_factory)
    incoming = candidate(document)
    coordinator = HumanIdentityResolutionCoordinator(session_factory)

    first = coordinator.process(incoming)
    second = coordinator.process(incoming)

    assert first.match.reason.value == "insufficient_fallback_identity"
    assert first.case is not None and first.case.created is True
    assert second.case is not None and second.case.created is False
    assert second.case.case_id == first.case.case_id
    assert counts(session_factory) == (1, 0, 0)
    with session_factory() as session:
        stored = session.get(IdentityResolutionCase, first.case.case_id)
        assert stored.status is IdentityResolutionStatus.PENDING
        assert stored.candidate_display_name == "Antonio Example"
        assert stored.candidate_snapshot["identity"]["display_name"] == (
            "Antonio Example"
        )


def test_exact_identifier_and_deterministic_fallback_create_no_case(session_factory):
    source, document = setup_governo_source(session_factory)
    exact_candidate = candidate(document)
    exact_id = add_politician(
        session_factory,
        source=source,
        identifier=exact_candidate.identity.source_identifiers[0].value,
    )

    exact = HumanIdentityResolutionCoordinator(session_factory).process(
        exact_candidate
    )

    assert exact.match == MatchedResult(
        politician_id=exact_id,
        method=MatchingMethod.OFFICIAL_SOURCE_IDENTIFIER,
    )
    assert exact.case is None

    fallback_candidate = candidate(
        document,
        identifier="https://www.governo.it/it/node/9002",
        given_name="Maria",
        family_name="Verdi",
        display_name="Maria Verdi",
        birth_date=date(1980, 2, 3),
    )
    fallback_id = add_politician(
        session_factory,
        given_name="Maria",
        family_name="Verdi",
        birth_date=date(1980, 2, 3),
    )

    fallback = HumanIdentityResolutionCoordinator(session_factory).process(
        fallback_candidate
    )

    assert fallback.match == MatchedResult(
        politician_id=fallback_id,
        method=MatchingMethod.NORMALIZED_NAME_BIRTH_DATE,
    )
    assert fallback.case is None
    with session_factory() as session:
        assert session.scalar(
            select(PoliticianSourceIdentifier).where(
                PoliticianSourceIdentifier.politician_id == fallback_id,
                PoliticianSourceIdentifier.value
                == "https://www.governo.it/it/node/9002",
            )
        ) is not None


def test_complete_no_match_stays_in_bootstrap_path_without_case(session_factory):
    _, document = setup_governo_source(session_factory)
    result = HumanIdentityResolutionCoordinator(session_factory).process(
        candidate(document, birth_date=date(1975, 4, 5))
    )

    assert result.match.reason.value == "no_match"
    assert result.case is None
    assert counts(session_factory) == (0, 0, 0)


def test_uncertain_match_creates_case_without_attachment(session_factory):
    _, document = setup_governo_source(session_factory)
    incoming = candidate(document, birth_date=date(1970, 1, 1))
    add_politician(session_factory, birth_date=date(1970, 1, 1))
    add_politician(session_factory, birth_date=date(1970, 1, 1))

    result = HumanIdentityResolutionCoordinator(session_factory).process(incoming)

    assert result.match.status.value == "uncertain"
    assert result.case is not None
    assert counts(session_factory) == (1, 2, 0)


def test_resolve_existing_attaches_identifier_and_future_match_is_exact(
    session_factory,
):
    _, document = setup_governo_source(session_factory)
    incoming = candidate(document)
    politician_id = add_politician(session_factory)
    coordinator = HumanIdentityResolutionCoordinator(session_factory)
    case_id = coordinator.process(incoming).case.case_id

    result = IdentityResolutionService(session_factory).resolve_to_existing(
        case_id,
        politician_id,
        reviewer_identity="human-editor",
        note="Compared the official profiles",
    )
    with session_factory() as session:
        future = MatchingService(session).match(incoming)
        stored = session.get(IdentityResolutionCase, case_id)

    assert result.status is IdentityResolutionStatus.RESOLVED_EXISTING
    assert result.resolved_politician_id == politician_id
    assert result.attachments[0].status == "attached"
    assert future == MatchedResult(
        politician_id=politician_id,
        method=MatchingMethod.OFFICIAL_SOURCE_IDENTIFIER,
    )
    assert stored.reviewer_identity == "human-editor"
    assert stored.resolution_note == "Compared the official profiles"
    assert coordinator.process(incoming).case is None
    assert counts(session_factory) == (1, 1, 1)


def test_resolve_as_new_creates_politician_and_identifier_atomically(session_factory):
    _, document = setup_governo_source(session_factory)
    incoming = candidate(document)
    case_id = HumanIdentityResolutionCoordinator(session_factory).process(
        incoming
    ).case.case_id

    result = IdentityResolutionService(session_factory).resolve_as_new(
        case_id,
        reviewer_identity="human-editor",
    )

    assert result.status is IdentityResolutionStatus.RESOLVED_NEW
    assert result.resolved_politician_id is not None
    assert counts(session_factory) == (1, 1, 1)
    with session_factory() as session:
        politician = session.get(Politician, result.resolved_politician_id)
        assert politician.canonical_given_name == "Antonio"
        assert politician.birth_date is None
        assert MatchingService(session).match(incoming).politician_id == politician.id


def test_ignore_is_terminal_and_creates_no_identity(session_factory):
    _, document = setup_governo_source(session_factory)
    case_id = HumanIdentityResolutionCoordinator(session_factory).process(
        candidate(document)
    ).case.case_id
    service = IdentityResolutionService(session_factory)

    result = service.ignore(
        case_id,
        reviewer_identity="human-editor",
        note="Not enough evidence",
    )

    assert result.status is IdentityResolutionStatus.IGNORED
    assert result.resolved_politician_id is None
    assert result.attachments == ()
    assert counts(session_factory) == (1, 0, 0)
    with pytest.raises(IdentityResolutionStateError):
        service.resolve_as_new(case_id, reviewer_identity="second-editor")
    assert counts(session_factory) == (1, 0, 0)


def test_identifier_conflict_rolls_back_case_and_target_mutation(session_factory):
    source, document = setup_governo_source(session_factory)
    incoming = candidate(document)
    case_id = HumanIdentityResolutionCoordinator(session_factory).process(
        incoming
    ).case.case_id
    target_id = add_politician(
        session_factory,
        given_name="Target",
        family_name="Person",
    )
    owner_id = add_politician(
        session_factory,
        source=source,
        identifier=incoming.identity.source_identifiers[0].value,
        given_name="Current",
        family_name="Owner",
    )

    with pytest.raises(IdentityResolutionConflictError):
        IdentityResolutionService(session_factory).resolve_to_existing(
            case_id,
            target_id,
            reviewer_identity="human-editor",
        )

    with session_factory() as session:
        stored = session.get(IdentityResolutionCase, case_id)
        assert stored.status is IdentityResolutionStatus.PENDING
        assert stored.reviewer_identity is None
        assert session.scalar(
            select(PoliticianSourceIdentifier.politician_id).where(
                PoliticianSourceIdentifier.value
                == incoming.identity.source_identifiers[0].value
            )
        ) == owner_id


def test_resolve_new_identifier_conflict_rolls_back_new_politician(session_factory):
    source, document = setup_governo_source(session_factory)
    incoming = candidate(document)
    case_id = HumanIdentityResolutionCoordinator(session_factory).process(
        incoming
    ).case.case_id
    owner_id = add_politician(
        session_factory,
        source=source,
        identifier=incoming.identity.source_identifiers[0].value,
        given_name="Current",
        family_name="Owner",
    )

    with pytest.raises(IdentityResolutionConflictError):
        IdentityResolutionService(session_factory).resolve_as_new(
            case_id,
            reviewer_identity="human-editor",
        )

    with session_factory() as session:
        stored = session.get(IdentityResolutionCase, case_id)
        assert stored.status is IdentityResolutionStatus.PENDING
        assert session.scalar(select(func.count()).select_from(Politician)) == 1
        assert session.scalar(
            select(PoliticianSourceIdentifier.politician_id).where(
                PoliticianSourceIdentifier.value
                == incoming.identity.source_identifiers[0].value
            )
        ) == owner_id


def test_possible_matches_are_same_name_suggestions_and_never_mutate(
    session_factory,
):
    source, document = setup_governo_source(session_factory)
    incoming = candidate(document)
    suggested_id = add_politician(
        session_factory,
        source=source,
        identifier="https://www.governo.it/it/node/old",
    )
    add_politician(
        session_factory,
        given_name="Different",
        family_name="Person",
    )
    case_id = HumanIdentityResolutionCoordinator(session_factory).process(
        incoming
    ).case.case_id
    before = counts(session_factory)

    suggestions = IdentityResolutionService(session_factory).possible_matches(
        case_id
    )

    assert [item.politician_id for item in suggestions] == [suggested_id]
    assert suggestions[0].signals == ("normalized_full_name",)
    assert suggestions[0].source_identifiers[0].value.endswith("/old")
    assert counts(session_factory) == before


def test_candidate_snapshot_fields_are_immutable(session_factory):
    _, document = setup_governo_source(session_factory)
    case_id = HumanIdentityResolutionCoordinator(session_factory).process(
        candidate(document)
    ).case.case_id

    with session_factory() as session:
        stored = session.get(IdentityResolutionCase, case_id)
        stored.candidate_display_name = "Changed Name"
        with pytest.raises(ImmutableIdentityResolutionSnapshotError):
            session.commit()
        session.rollback()

    with session_factory() as session:
        assert session.get(
            IdentityResolutionCase, case_id
        ).candidate_display_name == "Antonio Example"
