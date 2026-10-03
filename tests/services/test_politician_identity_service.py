from datetime import date, datetime, timezone

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError

from backend.app.models import Politician, PoliticianSourceIdentifier, Source
from backend.app.schemas import (
    CandidateIdentity,
    CandidateProfile,
    CandidateProfileData,
    CandidateProvenance,
    MatchedResult,
    MatchingMethod,
    NewResult,
    SourceDocumentProvenance,
    SourceIdentifier,
    UncertainResult,
)
from backend.app.services import (
    CandidateIdentityCoordinator,
    IdentifierAttachmentStatus,
    IdentityConflictError,
    PoliticianIdentityService,
    normalize_person_name,
)


def camera_candidate(
    *values: str,
    given_name: str = "Mario",
    family_name: str = "Rossi",
    birth_date: date | None = date(1970, 1, 1),
) -> CandidateProfile:
    return CandidateProfile(
        identity=CandidateIdentity(
            given_name=given_name,
            family_name=family_name,
            birth_date=birth_date,
            birth_place=None,
            source_identifiers=tuple(
                SourceIdentifier(authority="camera-deputati", value=value)
                for value in (values or ("camera-person-999",))
            ),
        ),
        profile=CandidateProfileData(mandates=()),
        provenance=CandidateProvenance(
            document=SourceDocumentProvenance(
                source_key="camera-deputati",
                raw_document_id=1,
                source_url="https://dati.camera.it/sparql",
                retrieved_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
                raw_sha256="a" * 64,
                normalized_sha256="b" * 64,
                collector_version="camera_collector_v1",
                parser_version="camera_parser_v1",
            ),
            fields=(),
        ),
    )


def add_camera_source(session_factory) -> int:
    with session_factory() as session:
        source = Source(
            key="camera-deputati",
            name="Camera dei Deputati",
            base_url="https://dati.camera.it",
        )
        session.add(source)
        session.commit()
        return source.id


def add_politician(
    session_factory,
    *,
    given_name="Mario",
    family_name="Rossi",
    birth_date=date(1970, 1, 1),
) -> int:
    with session_factory() as session:
        politician = Politician(
            canonical_given_name=given_name,
            canonical_family_name=family_name,
            normalized_name=normalize_person_name(given_name, family_name),
            birth_date=birth_date,
        )
        session.add(politician)
        session.commit()
        return politician.id


def identifier_rows(session_factory):
    with session_factory() as session:
        return list(
            session.execute(
                select(
                    PoliticianSourceIdentifier.politician_id,
                    Source.key,
                    PoliticianSourceIdentifier.value,
                )
                .join(Source)
                .order_by(PoliticianSourceIdentifier.value)
            )
        )


def test_cross_source_fallback_match_attaches_identifier_and_future_match_is_exact(
    session_factory, source
):
    camera_source_id = add_camera_source(session_factory)
    politician_id = add_politician(session_factory)
    with session_factory() as session:
        session.add(
            PoliticianSourceIdentifier(
                politician_id=politician_id,
                source_id=source.id,
                value="senato-person-123",
            )
        )
        session.commit()

    candidate = camera_candidate("camera-person-999")
    first = CandidateIdentityCoordinator(session_factory).match_and_link(candidate)
    second = CandidateIdentityCoordinator(session_factory).match_and_link(candidate)

    assert isinstance(first.match, MatchedResult)
    assert first.match.politician_id == politician_id
    assert first.match.method is MatchingMethod.NORMALIZED_NAME_BIRTH_DATE
    assert first.attachments[0].status is IdentifierAttachmentStatus.ATTACHED
    assert isinstance(second.match, MatchedResult)
    assert second.match.method is MatchingMethod.OFFICIAL_SOURCE_IDENTIFIER
    assert second.attachments[0].status is IdentifierAttachmentStatus.ALREADY_EXISTS
    assert identifier_rows(session_factory) == [
        (politician_id, "camera-deputati", "camera-person-999"),
        (politician_id, "senato-repubblica", "senato-person-123"),
    ]
    assert camera_source_id > 0


def test_repeated_attachment_is_idempotent(session_factory):
    add_camera_source(session_factory)
    politician_id = add_politician(session_factory)
    candidate = camera_candidate()
    match = MatchedResult(
        politician_id=politician_id,
        method=MatchingMethod.NORMALIZED_NAME_BIRTH_DATE,
    )
    service = PoliticianIdentityService(session_factory)

    first = service.attach_candidate_identifiers(candidate, match)
    second = service.attach_candidate_identifiers(candidate, match)

    assert first[0].status is IdentifierAttachmentStatus.ATTACHED
    assert second[0].status is IdentifierAttachmentStatus.ALREADY_EXISTS
    assert len(identifier_rows(session_factory)) == 1


def test_identifier_owned_by_different_politician_is_a_conflict(session_factory):
    camera_source_id = add_camera_source(session_factory)
    target_id = add_politician(session_factory)
    owner_id = add_politician(
        session_factory, given_name="Other", family_name="Person"
    )
    with session_factory() as session:
        session.add(
            PoliticianSourceIdentifier(
                politician_id=owner_id,
                source_id=camera_source_id,
                value="camera-person-999",
            )
        )
        session.commit()

    with pytest.raises(IdentityConflictError, match=f"Politician {owner_id}"):
        PoliticianIdentityService(session_factory).attach_candidate_identifiers(
            camera_candidate(),
            MatchedResult(
                politician_id=target_id,
                method=MatchingMethod.NORMALIZED_NAME_BIRTH_DATE,
            ),
        )

    assert identifier_rows(session_factory) == [
        (owner_id, "camera-deputati", "camera-person-999")
    ]


def test_uncertain_match_does_not_attach_identifier(session_factory):
    add_camera_source(session_factory)
    first = add_politician(session_factory)
    second = add_politician(session_factory)

    result = CandidateIdentityCoordinator(session_factory).match_and_link(
        camera_candidate()
    )

    assert isinstance(result.match, UncertainResult)
    assert result.match.candidate_politician_ids == tuple(sorted((first, second)))
    assert result.attachments == ()
    assert identifier_rows(session_factory) == []


def test_no_match_does_not_attach_to_existing_politician(session_factory):
    add_camera_source(session_factory)
    add_politician(
        session_factory, given_name="Different", family_name="Person"
    )

    result = CandidateIdentityCoordinator(session_factory).match_and_link(
        camera_candidate()
    )

    assert isinstance(result.match, NewResult)
    assert result.attachments == ()
    assert identifier_rows(session_factory) == []


def test_multiple_identifiers_for_same_source_are_preserved(session_factory):
    add_camera_source(session_factory)
    politician_id = add_politician(session_factory)
    candidate = camera_candidate("camera-old-id", "camera-current-id")

    result = CandidateIdentityCoordinator(session_factory).match_and_link(candidate)

    assert isinstance(result.match, MatchedResult)
    assert {item.status for item in result.attachments} == {
        IdentifierAttachmentStatus.ATTACHED
    }
    assert identifier_rows(session_factory) == [
        (politician_id, "camera-deputati", "camera-current-id"),
        (politician_id, "camera-deputati", "camera-old-id"),
    ]


def test_integrity_conflict_rolls_back_every_identifier(session_factory):
    add_camera_source(session_factory)
    politician_id = add_politician(session_factory)
    candidate = camera_candidate("camera-first", "camera-conflict")

    def fail_as_concurrent_conflict(mapper, connection, target):
        del mapper, connection
        if target.value == "camera-conflict":
            raise IntegrityError("insert", {}, RuntimeError("simulated conflict"))

    event.listen(
        PoliticianSourceIdentifier, "before_insert", fail_as_concurrent_conflict
    )
    try:
        with pytest.raises(IdentityConflictError, match="rolled back"):
            CandidateIdentityCoordinator(session_factory).match_and_link(candidate)
    finally:
        event.remove(
            PoliticianSourceIdentifier,
            "before_insert",
            fail_as_concurrent_conflict,
        )

    assert identifier_rows(session_factory) == []
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Politician)) == 1
        assert session.get(Politician, politician_id) is not None
