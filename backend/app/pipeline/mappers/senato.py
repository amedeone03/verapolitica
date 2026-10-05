from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from backend.app.pipeline.mappers.base import CandidateMappingError
from backend.app.schemas import (
    BirthPlace,
    CandidateIdentity,
    CandidateProfile,
    CandidateProfileData,
    CandidateProvenance,
    FieldProvenance,
    Gender,
    PoliticalMandate,
    SourceDocumentProvenance,
    SourceIdentifier,
)


class SenatoCandidateProfileMapper:
    """Map normalized Senato records to source-independent candidate profiles."""

    institution = "Senato della Repubblica"
    office = "senator"

    source_fields = {
        "senator_uri": "senatorUri",
        "first_name": "firstName",
        "last_name": "lastName",
        "gender": "gender",
        "birth_date": "birthDate",
        "birth_city": "birthCity",
        "birth_province": "birthProvince",
        "birth_country": "birthCountry",
        "profession": "profession",
        "photo_url": "photoUrl",
        "homepage": "homepage",
        "mandate_uri": "mandateUri",
        "mandate_type": "mandateType",
        "mandate_start": "mandateStart",
        "legislature": "legislature",
        "election_region": "electionRegion",
    }

    def map_records(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        document: SourceDocumentProvenance,
    ) -> tuple[CandidateProfile, ...]:
        candidates: list[CandidateProfile] = []
        for index, record in enumerate(records):
            candidates.append(self._map_record(record, index, document))
        return tuple(candidates)

    def _map_record(
        self,
        record: Mapping[str, Any],
        index: int,
        document: SourceDocumentProvenance,
    ) -> CandidateProfile:
        record_label = self._record_label(record, index)
        try:
            senator_uri = self._required_string(record, "senator_uri")
            mandate_uri = self._required_string(record, "mandate_uri")
            given_name = self._required_string(record, "first_name")
            family_name = self._required_string(record, "last_name")
            mandate_type = self._required_string(record, "mandate_type")
            mandate_start = self._required_string(record, "mandate_start")
            legislature = self._required_string(record, "legislature")

            gender_value = self._optional_string(record, "gender")
            birth_date = self._optional_string(record, "birth_date")
            birth_city = self._optional_string(record, "birth_city")
            birth_province = self._optional_string(record, "birth_province")
            birth_country = self._optional_string(record, "birth_country")
            profession = self._optional_string(record, "profession")
            photo_url = self._optional_string(record, "photo_url")
            homepage = self._optional_string(record, "homepage")
            election_region = self._optional_string(record, "election_region")

            birth_place = None
            if any((birth_city, birth_province, birth_country)):
                birth_place = BirthPlace(
                    city=birth_city,
                    subdivision=birth_province,
                    country=birth_country,
                )

            provenance = self._build_provenance(
                record=record,
                senator_uri=senator_uri,
                mandate_uri=mandate_uri,
                document=document,
            )
            return CandidateProfile(
                identity=CandidateIdentity(
                    display_name=f"{given_name} {family_name}".strip(),
                    given_name=given_name,
                    family_name=family_name,
                    birth_date=birth_date,
                    birth_place=birth_place,
                    source_identifiers=(
                        SourceIdentifier(
                            authority=document.source_key,
                            value=senator_uri,
                        ),
                    ),
                ),
                profile=CandidateProfileData(
                    gender=self._map_gender(gender_value),
                    profession=profession,
                    image_url=photo_url,
                    official_homepage_url=homepage,
                    mandates=(
                        PoliticalMandate(
                            institution=self.institution,
                            office=self.office,
                            legislature=legislature,
                            mandate_type=mandate_type,
                            start_date=mandate_start,
                            end_date=None,
                            election_area=election_region,
                        ),
                    ),
                ),
                provenance=provenance,
            )
        except (CandidateMappingError, ValidationError, ValueError) as exc:
            if isinstance(exc, CandidateMappingError) and str(exc).startswith(
                "Unable to map Senato record"
            ):
                raise
            raise CandidateMappingError(
                f"Unable to map Senato record {record_label}: {exc}"
            ) from exc

    def _build_provenance(
        self,
        *,
        record: Mapping[str, Any],
        senator_uri: str,
        mandate_uri: str,
        document: SourceDocumentProvenance,
    ) -> CandidateProvenance:
        field_specs = (
            ("identity.source_identifiers[0].value", "senator_uri", senator_uri),
            ("identity.given_name", "first_name", senator_uri),
            ("identity.family_name", "last_name", senator_uri),
            ("identity.birth_date", "birth_date", senator_uri),
            ("identity.birth_place.city", "birth_city", senator_uri),
            ("identity.birth_place.subdivision", "birth_province", senator_uri),
            ("identity.birth_place.country", "birth_country", senator_uri),
            ("profile.gender", "gender", senator_uri),
            ("profile.profession", "profession", senator_uri),
            ("profile.image_url", "photo_url", senator_uri),
            ("profile.official_homepage_url", "homepage", senator_uri),
            ("profile.mandates[0].legislature", "legislature", mandate_uri),
            ("profile.mandates[0].mandate_type", "mandate_type", mandate_uri),
            ("profile.mandates[0].start_date", "mandate_start", mandate_uri),
            ("profile.mandates[0].election_area", "election_region", mandate_uri),
        )
        fields = []
        for target_path, record_field, source_record_id in field_specs:
            value = record.get(record_field)
            if isinstance(value, str) and value:
                fields.append(
                    FieldProvenance(
                        target_path=target_path,
                        source_record_id=source_record_id,
                        source_field=self.source_fields[record_field],
                        source_value=value,
                    )
                )
        return CandidateProvenance(document=document, fields=tuple(fields))

    @staticmethod
    def _required_string(record: Mapping[str, Any], field: str) -> str:
        value = record.get(field)
        if not isinstance(value, str) or not value:
            raise CandidateMappingError(f"required field {field!r} is missing or invalid")
        return value

    @staticmethod
    def _optional_string(record: Mapping[str, Any], field: str) -> str | None:
        value = record.get(field)
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise CandidateMappingError(f"optional field {field!r} is invalid")
        return value

    @staticmethod
    def _map_gender(value: str | None) -> Gender | None:
        if value is None:
            return None
        normalized = value.casefold()
        if normalized in {"m", "male", "maschio"}:
            return Gender.MALE
        if normalized in {"f", "female", "femmina"}:
            return Gender.FEMALE
        raise CandidateMappingError(f"unsupported gender value {value!r}")

    @staticmethod
    def _record_label(record: Mapping[str, Any], index: int) -> str:
        identifier = record.get("senator_uri")
        if isinstance(identifier, str) and identifier:
            return f"at index {index} ({identifier})"
        return f"at index {index}"
