from datetime import date, datetime, timezone

from sqlalchemy import func, select

from backend.app.models import Politician, PoliticianVersion
from backend.app.schemas import (
    BirthPlace,
    CandidateIdentity,
    CandidateProfile,
    CandidateProfileData,
    CandidateProvenance,
    ChangeType,
    DiffStatus,
    Gender,
    PoliticalMandate,
    SourceDocumentProvenance,
    SourceIdentifier,
)
from backend.app.services import (
    DiffService,
    candidate_to_version_profile,
    normalize_person_name,
)


def mandate(*, legislature: str = "19", area: str = "Lazio") -> PoliticalMandate:
    return PoliticalMandate(
        institution="Senato della Repubblica",
        office="senator",
        legislature=legislature,
        mandate_type="elettivo",
        start_date=date(2022, 10, 13),
        election_area=area,
    )


def candidate(
    *,
    profession: str | None = "Avvocata",
    homepage: str | None = "https://example.test/profile",
    mandates: tuple[PoliticalMandate, ...] | None = None,
) -> CandidateProfile:
    document = SourceDocumentProvenance(
        source_key="senato-repubblica",
        raw_document_id=1,
        source_url="https://dati.senato.it/sparql",
        retrieved_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        raw_sha256="a" * 64,
        normalized_sha256="b" * 64,
        collector_version="senato_collector_v1",
        parser_version="senato_parser_v1",
    )
    return CandidateProfile(
        identity=CandidateIdentity(
            given_name="Maria",
            family_name="Rossi",
            birth_date=date(1970, 1, 2),
            birth_place=BirthPlace(city="Roma", subdivision="RM", country="Italia"),
            source_identifiers=(
                SourceIdentifier(
                    authority="senato-repubblica",
                    value="senator-100",
                ),
            ),
        ),
        profile=CandidateProfileData(
            gender=Gender.FEMALE,
            profession=profession,
            image_url=None,
            official_homepage_url=homepage,
            mandates=mandates if mandates is not None else (mandate(),),
        ),
        provenance=CandidateProvenance(document=document, fields=()),
    )


def version_for(candidate_profile: CandidateProfile) -> PoliticianVersion:
    return PoliticianVersion(
        politician_id=1,
        version_number=1,
        profile_schema_version=1,
        profile_data=candidate_to_version_profile(candidate_profile).model_dump(
            mode="json"
        ),
    )


def changes_by_path(diff):
    return {change.field_path: change for change in diff.changes}


def test_initial_profile_diff_when_no_current_version_exists():
    diff = DiffService().compare(candidate(), None)

    changes = changes_by_path(diff)
    assert diff.status is DiffStatus.INITIAL
    assert changes["given_name"].old_value is None
    assert changes["given_name"].new_value == "Maria"
    assert changes["profession"].change_type is ChangeType.ADDED
    assert changes["mandates"].old_value is None
    assert changes["mandates"].new_value[0]["legislature"] == "19"


def test_equal_candidate_and_current_version_have_no_changes():
    profile = candidate()

    diff = DiffService().compare(profile, version_for(profile))

    assert diff.status is DiffStatus.UPDATE
    assert diff.changes == ()


def test_changed_scalar_field_is_reported():
    baseline = version_for(candidate(profession="Avvocata"))

    diff = DiffService().compare(candidate(profession="Magistrata"), baseline)

    change = changes_by_path(diff)["profession"]
    assert change.change_type is ChangeType.CHANGED
    assert change.old_value == "Avvocata"
    assert change.new_value == "Magistrata"


def test_added_and_removed_optional_fields_are_typed():
    added = DiffService().compare(
        candidate(profession="Avvocata"),
        version_for(candidate(profession=None)),
    )
    removed = DiffService().compare(
        candidate(homepage=None),
        version_for(candidate(homepage="https://example.test/profile")),
    )

    assert changes_by_path(added)["profession"].change_type is ChangeType.ADDED
    homepage = changes_by_path(removed)["official_homepage_url"]
    assert homepage.change_type is ChangeType.REMOVED
    assert homepage.new_value is None


def test_mandate_change_is_reported_as_one_explicit_collection_change():
    baseline = version_for(candidate(mandates=(mandate(area="Lazio"),)))

    diff = DiffService().compare(
        candidate(mandates=(mandate(area="Sicilia"),)), baseline
    )

    mandate_change = changes_by_path(diff)["mandates"]
    assert mandate_change.change_type is ChangeType.CHANGED
    assert mandate_change.old_value[0]["election_area"] == "Lazio"
    assert mandate_change.new_value[0]["election_area"] == "Sicilia"


def test_mandate_order_is_not_a_meaningful_change():
    first = mandate(legislature="18")
    second = mandate(legislature="19")
    baseline = version_for(candidate(mandates=(first, second)))

    diff = DiffService().compare(candidate(mandates=(second, first)), baseline)

    assert diff.changes == ()


def test_diff_service_does_not_mutate_database(session_factory):
    profile = candidate(profession="Magistrata")
    with session_factory() as session:
        politician = Politician(
            canonical_given_name="Maria",
            canonical_family_name="Rossi",
            normalized_name=normalize_person_name("Maria", "Rossi"),
            birth_date=date(1970, 1, 2),
        )
        session.add(politician)
        session.flush()
        baseline = version_for(candidate(profession="Avvocata"))
        baseline.politician_id = politician.id
        session.add(baseline)
        session.commit()
        profile_data_before = dict(baseline.profile_data)
        counts_before = session.scalar(
            select(func.count()).select_from(PoliticianVersion)
        )

        DiffService().compare(profile, baseline)

        assert not session.dirty
        assert baseline.profile_data == profile_data_before
        assert (
            session.scalar(select(func.count()).select_from(PoliticianVersion))
            == counts_before
        )
