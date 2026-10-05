import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app.models import (
    ParliamentaryGroup,
    ParliamentaryGroupMembership,
    PoliticalParty,
    PoliticalPartyAffiliation,
    PoliticalPartySourceIdentifier,
    Politician,
    PoliticianSourceIdentifier,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.schemas import (
    PartyAffiliationPersistenceStatus,
    PoliticalPartyObservation,
)
from backend.app.services import (
    PoliticalPartyService,
    PoliticalPartyValidationError,
    normalize_person_name,
)


SOURCE_KEY = "governo-italiano"
PERSON_IDENTIFIER = "https://www.governo.it/it/governo/ministro/anna-rossi"


def setup_source_and_person(session_factory):
    with session_factory() as session:
        source = Source(
            key=SOURCE_KEY,
            name="Governo Italiano",
            base_url="https://www.governo.it",
        )
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
            source_url="https://www.governo.it/it/governo",
            content_type="application/json",
            storage_key="governo-italiano/party-fixture.json",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="fixture_collector_v1",
            parser_version="fixture_parser_v1",
        )
        politician = Politician(
            canonical_given_name="Anna",
            canonical_family_name="Rossi",
            normalized_name=normalize_person_name("Anna", "Rossi"),
            birth_date=date(1970, 1, 2),
        )
        session.add_all((document, politician))
        session.flush()
        session.add(
            PoliticianSourceIdentifier(
                politician_id=politician.id,
                source_id=source.id,
                value=PERSON_IDENTIFIER,
            )
        )
        session.commit()
        return source.id, document.id, politician.id


def load_observations(path, document_id):
    records = json.loads(Path(path).read_text())
    return tuple(
        PoliticalPartyObservation(
            source_key=SOURCE_KEY,
            raw_document_id=document_id,
            **record,
        )
        for record in records
    )


def test_normalized_explicit_assertion_fixture_maps_party_and_affiliation_fields(
    session_factory,
):
    _, document_id, _ = setup_source_and_person(session_factory)
    item = load_observations(
        "data/fixtures/parties/explicit_affiliations.json", document_id
    )[0]

    assert item.party_source_identifier == "official-party-register:party-a"
    assert item.party_name == "Partito A"
    assert item.abbreviation == "PA"
    assert item.affiliation_start == date(2022, 10, 1)
    assert item.affiliation_end is None
    assert item.affiliation_type == "member"
    assert item.source_field == "biography.explicit_party_membership"


def observation(document_id, **overrides):
    values = {
        "source_key": SOURCE_KEY,
        "raw_document_id": document_id,
        "politician_source_identifier": PERSON_IDENTIFIER,
        "party_source_identifier": "official-party-register:party-a",
        "party_name": "Partito A",
        "abbreviation": "PA",
        "official_website_url": "https://partito-a.example.org",
        "affiliation_start": date(2022, 10, 1),
        "affiliation_type": "member",
        "source_url": PERSON_IDENTIFIER,
        "source_field": "biography.explicit_party_membership",
    }
    values.update(overrides)
    return PoliticalPartyObservation(**values)


def test_current_affiliation_party_identity_provenance_and_idempotency(
    session_factory,
):
    source_id, document_id, politician_id = setup_source_and_person(session_factory)
    item = observation(document_id)
    service = PoliticalPartyService(session_factory)

    first = service.sync((item,))
    second = service.sync((item,))

    assert first.parties_created == 1
    assert first.affiliations_created == 1
    assert second.affiliations_unchanged == 1
    assert second.details[0].status is PartyAffiliationPersistenceStatus.ALREADY_EXISTS
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PoliticalParty)) == 1
        assert session.scalar(
            select(func.count()).select_from(PoliticalPartySourceIdentifier)
        ) == 1
        affiliation = session.scalar(select(PoliticalPartyAffiliation))
        assert affiliation is not None
        assert affiliation.politician_id == politician_id
        assert affiliation.source_id == source_id
        assert affiliation.raw_document_id == document_id
        assert affiliation.source_url == PERSON_IDENTIFIER
        assert affiliation.source_field == "biography.explicit_party_membership"
        assert affiliation.end_date is None


def test_fixture_party_switch_updates_end_date_and_preserves_history(session_factory):
    _, document_id, politician_id = setup_source_and_person(session_factory)
    service = PoliticalPartyService(session_factory)
    initial = load_observations(
        "data/fixtures/parties/explicit_affiliations.json", document_id
    )[0]
    updated = load_observations(
        "data/fixtures/parties/explicit_affiliations_updated.json", document_id
    )

    service.sync((initial,))
    result = service.sync(updated)

    assert result.affiliations_updated == 1
    assert result.affiliations_created == 1
    with session_factory() as session:
        affiliations = list(
            session.scalars(
                select(PoliticalPartyAffiliation)
                .where(PoliticalPartyAffiliation.politician_id == politician_id)
                .order_by(PoliticalPartyAffiliation.start_date)
            )
        )
        assert len(affiliations) == 2
        assert affiliations[0].end_date == date(2024, 5, 15)
        assert affiliations[0].political_party.canonical_name == "Partito A"
        assert affiliations[1].start_date == date(2024, 5, 16)
        assert affiliations[1].end_date is None
        assert affiliations[1].political_party.canonical_name == "Partito B"


def test_missing_dates_are_preserved_as_null(session_factory):
    _, document_id, _ = setup_source_and_person(session_factory)
    item = observation(
        document_id,
        party_source_identifier="official-party-register:no-dates",
        party_name="Partito senza date",
        affiliation_start=None,
        affiliation_end=None,
        affiliation_type=None,
    )

    PoliticalPartyService(session_factory).sync((item,))

    with session_factory() as session:
        affiliation = session.scalar(select(PoliticalPartyAffiliation))
        assert affiliation is not None
        assert affiliation.start_date is None
        assert affiliation.end_date is None


def test_unresolved_politician_creates_no_party_or_affiliation(session_factory):
    _, document_id, _ = setup_source_and_person(session_factory)
    item = observation(
        document_id,
        politician_source_identifier="https://www.governo.it/missing",
    )

    result = PoliticalPartyService(session_factory).sync((item,))

    assert result.unresolved_references == 1
    assert (
        result.details[0].status
        is PartyAffiliationPersistenceStatus.UNRESOLVED_POLITICIAN
    )
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PoliticalParty)) == 0
        assert session.scalar(
            select(func.count()).select_from(PoliticalPartyAffiliation)
        ) == 0


def test_invalid_chronology_rolls_back_whole_sync(session_factory):
    _, document_id, _ = setup_source_and_person(session_factory)
    with pytest.raises(ValidationError, match="affiliation_end"):
        observation(
            document_id,
            affiliation_start=date(2024, 5, 16),
            affiliation_end=date(2024, 5, 15),
        )
    invalid = PoliticalPartyObservation.model_construct(
        **(
            observation(document_id).model_dump()
            | {
                "affiliation_start": date(2024, 5, 16),
                "affiliation_end": date(2024, 5, 15),
            }
        )
    )

    with pytest.raises(PoliticalPartyValidationError):
        PoliticalPartyService(session_factory).sync(
            (
                observation(
                    document_id,
                    party_source_identifier="official-party-register:valid-first",
                ),
                invalid,
            )
        )

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PoliticalParty)) == 0
        assert session.scalar(
            select(func.count()).select_from(PoliticalPartyAffiliation)
        ) == 0


def test_explicit_overlapping_affiliations_are_preserved_and_flagged(session_factory):
    _, document_id, politician_id = setup_source_and_person(session_factory)
    result = PoliticalPartyService(session_factory).sync(
        (
            observation(document_id),
            observation(
                document_id,
                party_source_identifier="official-party-register:party-b",
                party_name="Partito B",
                abbreviation="PB",
                affiliation_start=date(2023, 1, 1),
            ),
        )
    )

    assert result.affiliations_created == 2
    assert result.overlap_warnings
    assert result.overlap_warnings[0].politician_id == politician_id


def test_parliamentary_group_does_not_create_party_affiliation(session_factory):
    source_id, document_id, politician_id = setup_source_and_person(session_factory)
    with session_factory() as session:
        group = ParliamentaryGroup(
            canonical_name="Partito A",
            abbreviation="PA",
            institution="Camera dei Deputati",
            legislature="19",
        )
        session.add(group)
        session.flush()
        session.add(
            ParliamentaryGroupMembership(
                politician_id=politician_id,
                parliamentary_group_id=group.id,
                source_id=source_id,
                raw_document_id=document_id,
                identity_key="c" * 64,
                source_url=PERSON_IDENTIFIER,
                start_date=date(2022, 10, 1),
            )
        )
        session.commit()

    result = PoliticalPartyService(session_factory).sync(())

    assert result.total_observations == 0
    with session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(ParliamentaryGroupMembership)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(PoliticalPartyAffiliation)
        ) == 0
