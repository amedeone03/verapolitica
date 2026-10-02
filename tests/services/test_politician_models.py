from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from backend.app.models import (
    ImmutablePoliticianVersionError,
    Politician,
    PoliticianSourceIdentifier,
    PoliticianVersion,
)
from backend.app.services import normalize_person_name


def politician() -> Politician:
    return Politician(
        canonical_given_name="Maria",
        canonical_family_name="Rossi",
        normalized_name=normalize_person_name("Maria", "Rossi"),
        birth_date=date(1970, 1, 2),
    )


def version(number: int) -> PoliticianVersion:
    return PoliticianVersion(
        version_number=number,
        profile_schema_version=1,
        profile_data={
            "given_name": "Maria",
            "family_name": "Rossi",
            "birth_date": "1970-01-02",
            "mandates": [],
        },
        published_at=datetime(2026, 10, number, tzinfo=timezone.utc),
    )


def test_source_identifiers_are_generic_and_unique(session_factory, source):
    with session_factory() as session:
        first = politician()
        first.source_identifiers.append(
            PoliticianSourceIdentifier(source_id=source.id, value="senator-100")
        )
        session.add(first)
        session.commit()

        duplicate_owner = Politician(
            canonical_given_name="Another",
            canonical_family_name="Person",
            normalized_name=normalize_person_name("Another", "Person"),
            birth_date=date(1980, 1, 1),
        )
        duplicate_owner.source_identifiers.append(
            PoliticianSourceIdentifier(source_id=source.id, value="senator-100")
        )
        session.add(duplicate_owner)

        with pytest.raises(IntegrityError):
            session.commit()


def test_versions_are_ordered_and_current_version_is_explicit(session_factory):
    with session_factory() as session:
        person = politician()
        session.add(person)
        session.flush()
        second = version(2)
        first = version(1)
        second.politician_id = person.id
        first.politician_id = person.id
        session.add_all([second, first])
        session.flush()
        person.current_version = second
        session.commit()
        person_id = person.id
        second_id = second.id

    with session_factory() as session:
        stored = session.get(Politician, person_id)
        assert stored is not None
        assert [item.version_number for item in stored.versions] == [1, 2]
        assert stored.current_version_id == second_id
        assert stored.current_version is not None
        assert stored.current_version.version_number == 2


def test_politician_version_cannot_be_updated(session_factory):
    with session_factory() as session:
        person = politician()
        stored_version = version(1)
        person.versions.append(stored_version)
        session.add(person)
        session.commit()

        stored_version.profile_data = {"given_name": "Changed"}
        with pytest.raises(ImmutablePoliticianVersionError):
            session.commit()
        session.rollback()


def test_same_normalized_identity_is_allowed_for_uncertainty(session_factory):
    with session_factory() as session:
        session.add_all([politician(), politician()])
        session.commit()
