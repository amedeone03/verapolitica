from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app.models import (
    ParliamentaryGroup,
    ParliamentaryGroupMembership,
    ParliamentaryGroupSourceIdentifier,
    Politician,
    PoliticianSourceIdentifier,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.pipeline.collectors.base import encode_sparql_bundle
from backend.app.pipeline.mappers import (
    CameraParliamentaryGroupMapper,
    SenatoParliamentaryGroupMapper,
)
from backend.app.pipeline.parsers import CameraParser, SenatoParser
from backend.app.schemas import (
    MembershipPersistenceStatus,
    ParliamentaryGroupObservation,
)
from backend.app.services import (
    ParliamentaryGroupService,
    ParliamentaryGroupValidationError,
    normalize_person_name,
)


def setup_identity(session_factory, *, source_key="camera-deputati"):
    with session_factory() as session:
        source = Source(
            key=source_key,
            name="Camera dei Deputati" if source_key == "camera-deputati" else "Senato della Repubblica",
            base_url="https://dati.camera.it" if source_key == "camera-deputati" else "https://dati.senato.it",
        )
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
            source_url=f"{source.base_url}/sparql",
            content_type="application/json",
            storage_key=f"{source_key}/fixture.json",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="fixture_collector_v1",
            parser_version="fixture_parser_v1",
        )
        politician = Politician(
            canonical_given_name="Maria",
            canonical_family_name="Rossi",
            normalized_name=normalize_person_name("Maria", "Rossi"),
            birth_date=date(1970, 1, 2),
        )
        session.add_all((document, politician))
        session.flush()
        person_identifier = (
            "http://dati.camera.it/ocd/deputato.rdf/d100_19"
            if source_key == "camera-deputati"
            else "https://dati.senato.it/senatore/100"
        )
        session.add(
            PoliticianSourceIdentifier(
                politician_id=politician.id,
                source_id=source.id,
                value=person_identifier,
            )
        )
        session.commit()
        return source.id, document.id, politician.id, person_identifier


def observation(
    document_id,
    person_identifier,
    *,
    group="x",
    start=date(2022, 10, 18),
    end=None,
    source_key="camera-deputati",
    role=None,
):
    camera = source_key == "camera-deputati"
    return ParliamentaryGroupObservation(
        source_key=source_key,
        raw_document_id=document_id,
        politician_source_identifier=person_identifier,
        group_source_identifier=(
            f"http://dati.camera.it/ocd/gruppoParlamentare.rdf/gr-{group}"
            if camera
            else f"https://dati.senato.it/gruppo/{group}"
        ),
        canonical_name=f"Gruppo {group.upper()}",
        abbreviation=f"G{group.upper()}",
        institution="Camera dei Deputati" if camera else "Senato della Repubblica",
        legislature="19",
        start_date=start,
        end_date=end,
        role=role,
        source_url=person_identifier,
    )


def add_raw_document(session_factory, source_id, source_key, marker):
    with session_factory() as session:
        document = RawDocument(
            source_id=source_id,
            retrieved_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
            source_url=(
                "https://dati.camera.it/sparql"
                if source_key == "camera-deputati"
                else "https://dati.senato.it/sparql"
            ),
            content_type="application/json",
            storage_key=f"{source_key}/{marker}.json",
            raw_sha256=marker * 64,
            normalized_sha256=marker * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="fixture_collector_v2",
            parser_version="fixture_parser_v2",
        )
        session.add(document)
        session.commit()
        return document.id


def test_current_membership_group_identity_and_idempotency(session_factory):
    _, document_id, politician_id, person_identifier = setup_identity(session_factory)
    item = observation(document_id, person_identifier)
    service = ParliamentaryGroupService(session_factory)

    first = service.sync((item,))
    second = service.sync((item,))

    assert first.groups_created == 1
    assert first.memberships_created == 1
    assert second.memberships_unchanged == 1
    assert second.details[0].status is MembershipPersistenceStatus.ALREADY_EXISTS
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ParliamentaryGroup)) == 1
        assert session.scalar(select(func.count()).select_from(ParliamentaryGroupSourceIdentifier)) == 1
        membership = session.scalar(select(ParliamentaryGroupMembership))
        assert membership is not None
        assert membership.politician_id == politician_id
        assert membership.end_date is None
        assert membership.source_url == person_identifier


def test_group_change_updates_end_date_and_preserves_history(session_factory):
    _, document_id, politician_id, person_identifier = setup_identity(session_factory)
    service = ParliamentaryGroupService(session_factory)
    service.sync((observation(document_id, person_identifier),))

    result = service.sync(
        (
            observation(document_id, person_identifier, end=date(2024, 1, 31)),
            observation(
                document_id,
                person_identifier,
                group="y",
                start=date(2024, 2, 1),
            ),
        )
    )

    assert result.memberships_updated == 1
    assert result.memberships_created == 1
    with session_factory() as session:
        rows = list(
            session.scalars(
                select(ParliamentaryGroupMembership)
                .where(ParliamentaryGroupMembership.politician_id == politician_id)
                .order_by(ParliamentaryGroupMembership.start_date)
            )
        )
        assert len(rows) == 2
        assert rows[0].end_date == date(2024, 1, 31)
        assert rows[1].end_date is None
        assert rows[0].parliamentary_group.canonical_name == "Gruppo X"
        assert rows[1].parliamentary_group.canonical_name == "Gruppo Y"


def test_unresolved_politician_is_reported_without_group_or_membership(session_factory):
    _, document_id, _, _ = setup_identity(session_factory)
    missing = "http://dati.camera.it/ocd/deputato.rdf/missing_19"

    result = ParliamentaryGroupService(session_factory).sync(
        (observation(document_id, missing),)
    )

    assert result.unresolved_references == 1
    assert result.details[0].status is MembershipPersistenceStatus.UNRESOLVED_POLITICIAN
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ParliamentaryGroup)) == 0
        assert session.scalar(select(func.count()).select_from(ParliamentaryGroupMembership)) == 0


def test_invalid_chronology_is_rejected_and_rolls_back(session_factory):
    _, document_id, _, person_identifier = setup_identity(session_factory)
    with pytest.raises(ValidationError, match="end_date cannot be before start_date"):
        observation(
            document_id,
            person_identifier,
            start=date(2024, 2, 1),
            end=date(2024, 1, 31),
        )

    invalid = ParliamentaryGroupObservation.model_construct(
        **(
            observation(document_id, person_identifier).model_dump()
            | {
                "start_date": date(2024, 2, 1),
                "end_date": date(2024, 1, 31),
            }
        )
    )
    with pytest.raises(ParliamentaryGroupValidationError):
        ParliamentaryGroupService(session_factory).sync((invalid,))
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ParliamentaryGroupMembership)) == 0


def test_senato_role_intervals_use_same_generic_model_and_flag_overlap(session_factory):
    _, document_id, politician_id, person_identifier = setup_identity(
        session_factory, source_key="senato-repubblica"
    )
    result = ParliamentaryGroupService(session_factory).sync(
        (
            observation(
                document_id,
                person_identifier,
                source_key="senato-repubblica",
                role="Vicepresidente",
            ),
            observation(
                document_id,
                person_identifier,
                source_key="senato-repubblica",
                start=date(2025, 2, 25),
                role="Tesoriere",
            ),
        )
    )

    assert result.memberships_created == 2
    assert result.overlap_warnings
    assert result.overlap_warnings[0].politician_id == politician_id


def test_existing_multisource_politician_receives_camera_membership(session_factory):
    camera_id, document_id, politician_id, person_identifier = setup_identity(session_factory)
    with session_factory() as session:
        senato = Source(
            key="senato-repubblica",
            name="Senato della Repubblica",
            base_url="https://dati.senato.it",
        )
        session.add(senato)
        session.flush()
        session.add(
            PoliticianSourceIdentifier(
                politician_id=politician_id,
                source_id=senato.id,
                value="https://dati.senato.it/senatore/100",
            )
        )
        session.commit()

    ParliamentaryGroupService(session_factory).sync(
        (observation(document_id, person_identifier),)
    )

    with session_factory() as session:
        membership = session.scalar(select(ParliamentaryGroupMembership))
        assert membership is not None
        assert membership.politician_id == politician_id
        assert membership.source_id == camera_id


@pytest.mark.parametrize(
    (
        "source_key",
        "people_fixture",
        "initial_groups_fixture",
        "updated_groups_fixture",
        "parser",
        "mapper",
    ),
    (
        (
            "camera-deputati",
            "data/fixtures/camera/camera_deputies.json",
            "data/fixtures/camera/camera_groups.json",
            "data/fixtures/camera/camera_groups_updated.json",
            CameraParser(),
            CameraParliamentaryGroupMapper(19),
        ),
        (
            "senato-repubblica",
            "data/fixtures/demo/senato_demo.json",
            "data/fixtures/senato/senato_groups.json",
            "data/fixtures/senato/senato_groups_updated.json",
            SenatoParser(),
            SenatoParliamentaryGroupMapper(),
        ),
    ),
)
def test_official_fixture_group_change_closes_old_interval_and_appends_new_one(
    session_factory,
    source_key,
    people_fixture,
    initial_groups_fixture,
    updated_groups_fixture,
    parser,
    mapper,
):
    source_id, first_document_id, politician_id, _ = setup_identity(
        session_factory, source_key=source_key
    )
    second_document_id = add_raw_document(
        session_factory, source_id, source_key, "c"
    )

    def mapped(groups_fixture, document_id):
        parsed = parser.parse(
            encode_sparql_bundle(
                schema=(
                    "verapolitica_camera_bundle_v1"
                    if source_key == "camera-deputati"
                    else "verapolitica_senato_bundle_v1"
                ),
                people_response=Path(people_fixture).read_bytes(),
                parliamentary_groups_response=Path(groups_fixture).read_bytes(),
            )
        )
        return mapper.map_records(
            parsed.parliamentary_group_records,
            source_key=source_key,
            raw_document_id=document_id,
        )

    service = ParliamentaryGroupService(session_factory)
    initial = service.sync(mapped(initial_groups_fixture, first_document_id))
    changed = service.sync(mapped(updated_groups_fixture, second_document_id))

    assert initial.memberships_created == 1
    assert changed.memberships_updated == 1
    assert changed.memberships_created == 1
    with session_factory() as session:
        rows = list(
            session.scalars(
                select(ParliamentaryGroupMembership)
                .where(ParliamentaryGroupMembership.politician_id == politician_id)
                .order_by(ParliamentaryGroupMembership.start_date)
            )
        )
        assert len(rows) == 2
        assert rows[0].end_date == date(2024, 1, 31)
        assert rows[1].start_date == date(2024, 2, 1)
        assert rows[1].end_date is None
