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


class CameraCandidateProfileMapper:
    """Map normalized Camera records to source-independent candidate profiles."""

    institution = "Camera dei Deputati"
    office = "deputy"
    source_fields = {
        "deputy_uri": "deputyUri",
        "first_name": "firstName",
        "last_name": "lastName",
        "gender": "gender",
        "birth_date": "birthDate",
        "birth_city": "birthCity",
        "birth_province": "birthProvince",
        "profession": "profession",
        "photo_url": "photoUrl",
        "homepage": "homepage",
        "mandate_uri": "mandateUri",
        "mandate_type": "mandateType",
        "mandate_start": "mandateStart",
        "legislature": "legislature",
        "election_area": "electionArea",
    }

    def map_records(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        document: SourceDocumentProvenance,
    ) -> tuple[CandidateProfile, ...]:
        return tuple(
            self._map_record(record, index, document)
            for index, record in enumerate(records)
        )

    def _map_record(
        self,
        record: Mapping[str, Any],
        index: int,
        document: SourceDocumentProvenance,
    ) -> CandidateProfile:
        label = self._record_label(record, index)
        try:
            deputy_uri = self._required(record, "deputy_uri")
            person_uri = self._required(record, "person_uri")
            mandate_uri = self._required(record, "mandate_uri")
            given_name = self._required(record, "first_name")
            family_name = self._required(record, "last_name")
            mandate_type = self._required(record, "mandate_type")
            mandate_start = self._required(record, "mandate_start")
            legislature = self._required(record, "legislature")
            birth_city = self._optional(record, "birth_city")
            birth_province = self._optional(record, "birth_province")
            birth_place = None
            if birth_city or birth_province:
                birth_place = BirthPlace(
                    city=birth_city, subdivision=birth_province, country=None
                )
            return CandidateProfile(
                identity=CandidateIdentity(
                    display_name=f"{given_name} {family_name}".strip(),
                    given_name=given_name,
                    family_name=family_name,
                    birth_date=self._optional(record, "birth_date"),
                    birth_place=birth_place,
                    source_identifiers=(
                        SourceIdentifier(authority=document.source_key, value=deputy_uri),
                    ),
                ),
                profile=CandidateProfileData(
                    gender=self._map_gender(self._optional(record, "gender")),
                    profession=self._optional(record, "profession"),
                    image_url=self._optional(record, "photo_url"),
                    official_homepage_url=self._optional(record, "homepage"),
                    mandates=(
                        PoliticalMandate(
                            institution=self.institution,
                            office=self.office,
                            legislature=legislature,
                            mandate_type=mandate_type,
                            start_date=mandate_start,
                            end_date=None,
                            election_area=self._optional(record, "election_area"),
                        ),
                    ),
                ),
                provenance=self._build_provenance(
                    record, deputy_uri, person_uri, mandate_uri, document
                ),
            )
        except (CandidateMappingError, ValidationError, ValueError) as exc:
            raise CandidateMappingError(
                f"Unable to map Camera record {label}: {exc}"
            ) from exc

    def _build_provenance(
        self,
        record: Mapping[str, Any],
        deputy_uri: str,
        person_uri: str,
        mandate_uri: str,
        document: SourceDocumentProvenance,
    ) -> CandidateProvenance:
        specs = (
            ("identity.source_identifiers[0].value", "deputy_uri", deputy_uri),
            ("identity.given_name", "first_name", deputy_uri),
            ("identity.family_name", "last_name", deputy_uri),
            ("identity.birth_date", "birth_date", person_uri),
            ("identity.birth_place.city", "birth_city", person_uri),
            ("identity.birth_place.subdivision", "birth_province", person_uri),
            ("profile.gender", "gender", deputy_uri),
            ("profile.profession", "profession", deputy_uri),
            ("profile.image_url", "photo_url", deputy_uri),
            ("profile.official_homepage_url", "homepage", deputy_uri),
            ("profile.mandates[0].legislature", "legislature", mandate_uri),
            ("profile.mandates[0].mandate_type", "mandate_type", mandate_uri),
            ("profile.mandates[0].start_date", "mandate_start", mandate_uri),
            ("profile.mandates[0].election_area", "election_area", mandate_uri),
        )
        fields = tuple(
            FieldProvenance(
                target_path=target,
                source_record_id=source_record_id,
                source_field=self.source_fields[field],
                source_value=value,
            )
            for target, field, source_record_id in specs
            if isinstance((value := record.get(field)), str) and value
        )
        return CandidateProvenance(document=document, fields=fields)

    @staticmethod
    def _required(record: Mapping[str, Any], field: str) -> str:
        value = record.get(field)
        if not isinstance(value, str) or not value:
            raise CandidateMappingError(f"required field {field!r} is missing or invalid")
        return value

    @staticmethod
    def _optional(record: Mapping[str, Any], field: str) -> str | None:
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
        identifier = record.get("deputy_uri")
        return (
            f"at index {index} ({identifier})"
            if isinstance(identifier, str) and identifier
            else f"at index {index}"
        )
