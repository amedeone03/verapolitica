from datetime import date, datetime, timezone

import pytest

from backend.app.pipeline.mappers import (
    CandidateMappingError,
    SenatoCandidateProfileMapper,
)
from backend.app.schemas import Gender, SourceDocumentProvenance


def document_provenance() -> SourceDocumentProvenance:
    return SourceDocumentProvenance(
        source_key="senato-repubblica",
        raw_document_id=42,
        source_url="https://dati.senato.it/sparql",
        retrieved_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        raw_sha256="a" * 64,
        normalized_sha256="b" * 64,
        collector_version="senato_collector_v1",
        parser_version="senato_parser_v1",
    )


def parsed_record(identifier: str = "1103") -> dict[str, str | None]:
    return {
        "senator_uri": f"http://dati.senato.it/senatore/{identifier}",
        "first_name": "Maria",
        "last_name": "Rossi",
        "gender": "F",
        "birth_date": "1970-01-02",
        "birth_city": "Roma",
        "birth_province": "Roma",
        "birth_country": "Italia",
        "profession": "Avvocata",
        "photo_url": f"http://www.senato.it/photo/{identifier}.jpg",
        "homepage": f"https://example.test/{identifier}",
        "mandate_uri": f"http://dati.senato.it/mandato/S_19_{identifier}_1",
        "mandate_type": "elettivo",
        "mandate_start": "2022-10-13",
        "legislature": "19",
        "election_region": "Lazio",
    }


def test_maps_complete_record_to_source_independent_profile():
    mapper = SenatoCandidateProfileMapper()

    candidate = mapper.map_records(
        [parsed_record()], document=document_provenance()
    )[0]

    assert candidate.identity.given_name == "Maria"
    assert candidate.identity.family_name == "Rossi"
    assert candidate.identity.birth_date == date(1970, 1, 2)
    assert candidate.identity.birth_place is not None
    assert candidate.identity.birth_place.subdivision == "Roma"
    assert candidate.identity.source_identifiers[0].authority == "senato-repubblica"
    assert candidate.identity.source_identifiers[0].value.endswith("/1103")
    assert candidate.profile.gender is Gender.FEMALE
    assert candidate.profile.profession == "Avvocata"
    assert str(candidate.profile.image_url).startswith("http://www.senato.it/")
    mandate = candidate.profile.mandates[0]
    assert mandate.institution == "Senato della Repubblica"
    assert mandate.office == "senator"
    assert mandate.start_date == date(2022, 10, 13)
    assert mandate.election_area == "Lazio"


def test_preserves_document_and_field_level_provenance():
    candidate = SenatoCandidateProfileMapper().map_records(
        [parsed_record()], document=document_provenance()
    )[0]

    assert candidate.provenance.document.raw_document_id == 42
    given_name_evidence = next(
        field
        for field in candidate.provenance.fields
        if field.target_path == "identity.given_name"
    )
    assert given_name_evidence.source_field == "firstName"
    assert given_name_evidence.source_value == "Maria"
    assert given_name_evidence.source_record_id.endswith("/1103")
    mandate_evidence = next(
        field
        for field in candidate.provenance.fields
        if field.target_path == "profile.mandates[0].start_date"
    )
    assert "/mandato/" in mandate_evidence.source_record_id
    assert mandate_evidence.method == "deterministic"


def test_maps_missing_optional_values_without_inventing_data():
    record = parsed_record()
    for field in (
        "gender",
        "birth_date",
        "birth_city",
        "birth_province",
        "birth_country",
        "profession",
        "photo_url",
        "homepage",
        "election_region",
    ):
        record[field] = None

    candidate = SenatoCandidateProfileMapper().map_records(
        [record], document=document_provenance()
    )[0]

    assert candidate.identity.birth_date is None
    assert candidate.identity.birth_place is None
    assert candidate.profile.gender is None
    assert candidate.profile.profession is None
    assert candidate.profile.image_url is None
    assert candidate.profile.official_homepage_url is None
    assert candidate.profile.mandates[0].election_area is None
    assert all(
        field.source_value is not None for field in candidate.provenance.fields
    )


@pytest.mark.parametrize(
    ("source_value", "expected"),
    [("M", Gender.MALE), ("male", Gender.MALE), ("F", Gender.FEMALE), ("female", Gender.FEMALE)],
)
def test_normalizes_supported_gender_values(source_value, expected):
    record = parsed_record()
    record["gender"] = source_value

    candidate = SenatoCandidateProfileMapper().map_records(
        [record], document=document_provenance()
    )[0]

    assert candidate.profile.gender is expected


def test_one_malformed_record_fails_the_complete_mapping_with_record_context():
    malformed = parsed_record("9999")
    malformed["mandate_start"] = "not-a-date"

    with pytest.raises(CandidateMappingError) as error:
        SenatoCandidateProfileMapper().map_records(
            [parsed_record(), malformed],
            document=document_provenance(),
        )

    assert "index 1" in str(error.value)
    assert "/9999" in str(error.value)
    assert "start_date" in str(error.value)
