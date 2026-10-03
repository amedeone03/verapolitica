import json
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select

from backend.app.models import (
    Evidence,
    Politician,
    PoliticianSourceIdentifier,
    PoliticianVersion,
    ProfileDraft,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.pipeline.mappers import CameraCandidateProfileMapper
from backend.app.pipeline.parsers import CameraParser
from backend.app.schemas import (
    MatchedResult,
    MatchingMethod,
    SourceDocumentProvenance,
    UncertainResult,
)
from backend.app.services import (
    CandidateIdentityCoordinator,
    DraftService,
    MatchingService,
    candidate_to_version_profile,
    normalize_person_name,
)


def add_camera_candidate(session_factory):
    content = Path("data/fixtures/camera/camera_deputies.json").read_bytes()
    record = CameraParser().parse(content).structured_records[0]
    with session_factory() as session:
        source = Source(
            key="camera-deputati",
            name="Camera dei Deputati",
            base_url="https://dati.camera.it",
        )
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
            source_url="https://dati.camera.it/sparql",
            content_type="application/sparql-results+json",
            storage_key="camera/fixture.json",
            raw_sha256="c" * 64,
            normalized_sha256="d" * 64,
            structured_records=[record],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="camera_collector_v1",
            parser_version="camera_parser_v1",
        )
        session.add(document)
        session.commit()
        source_id = source.id
        document_id = document.id
    provenance = SourceDocumentProvenance(
        source_key="camera-deputati",
        raw_document_id=document_id,
        source_url="https://dati.camera.it/sparql",
        retrieved_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
        raw_sha256="c" * 64,
        normalized_sha256="d" * 64,
        collector_version="camera_collector_v1",
        parser_version="camera_parser_v1",
    )
    candidate = CameraCandidateProfileMapper().map_records(
        (record,), document=provenance
    )[0]
    return candidate, source_id, document_id


def add_named_politician(session, *, with_senato_identifier=False):
    politician = Politician(
        canonical_given_name="Maria",
        canonical_family_name="Rossi",
        normalized_name=normalize_person_name("Maria", "Rossi"),
        birth_date=date(1970, 1, 2),
    )
    session.add(politician)
    session.flush()
    if with_senato_identifier:
        senato = Source(
            key="senato-repubblica",
            name="Senato della Repubblica",
            base_url="https://dati.senato.it",
        )
        session.add(senato)
        session.flush()
        session.add(
            PoliticianSourceIdentifier(
                politician_id=politician.id,
                source_id=senato.id,
                value="https://dati.senato.it/senatore/100",
            )
        )
    session.flush()
    return politician


def test_cross_source_name_and_birth_date_matches_then_identifier_can_be_attached(
    session_factory,
):
    candidate, _, _ = add_camera_candidate(session_factory)
    with session_factory() as session:
        politician = add_named_politician(session, with_senato_identifier=True)
        session.commit()
        politician_id = politician.id

    resolution = CandidateIdentityCoordinator(session_factory).match_and_link(candidate)
    assert resolution.match == MatchedResult(
        politician_id=politician_id,
        method=MatchingMethod.NORMALIZED_NAME_BIRTH_DATE,
    )
    assert resolution.attachments[0].status.value == "attached"

    with session_factory() as session:
        exact = MatchingService(session).match(candidate)
        assert exact == MatchedResult(
            politician_id=politician_id,
            method=MatchingMethod.OFFICIAL_SOURCE_IDENTIFIER,
        )


def test_ambiguous_cross_source_identity_remains_uncertain(session_factory):
    candidate, _, _ = add_camera_candidate(session_factory)
    with session_factory() as session:
        first = add_named_politician(session)
        second = add_named_politician(session)
        session.commit()
        expected = tuple(sorted((first.id, second.id)))

    with session_factory() as session:
        result = MatchingService(session).match(candidate)

    assert isinstance(result, UncertainResult)
    assert result.candidate_politician_ids == expected
    assert result.method is MatchingMethod.NORMALIZED_NAME_BIRTH_DATE


def test_camera_conflict_creates_reviewable_draft_with_camera_evidence(
    session_factory,
):
    candidate, _, _ = add_camera_candidate(session_factory)
    with session_factory() as session:
        politician = add_named_politician(session, with_senato_identifier=True)
        session.flush()
        baseline_data = candidate_to_version_profile(candidate).model_dump(mode="json")
        baseline_data["profession"] = "Docente"
        version = PoliticianVersion(
            politician_id=politician.id,
            version_number=1,
            profile_schema_version=1,
            profile_data=baseline_data,
            published_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        )
        session.add(version)
        session.flush()
        politician.current_version_id = version.id
        session.commit()
        politician_id = politician.id

    result = DraftService(session_factory).create(
        candidate,
        MatchedResult(
            politician_id=politician_id,
            method=MatchingMethod.NORMALIZED_NAME_BIRTH_DATE,
        ),
    )

    assert [change.field_path for change in result.diff.changes] == ["profession"]
    with session_factory() as session:
        draft = session.get(ProfileDraft, result.draft_id)
        evidence = session.scalars(
            select(Evidence).where(Evidence.draft_id == draft.id)
        ).all()
        assert len(evidence) == 1
        assert evidence[0].source_url == "https://dati.camera.it/sparql"
        assert evidence[0].source_field_name == "profession"
        assert evidence[0].source_value == "Avvocata"
        assert draft.raw_document.source.name == "Camera dei Deputati"
