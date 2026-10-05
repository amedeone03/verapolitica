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
    PoliticalMandate,
    SourceDocumentProvenance,
    SourceIdentifier,
)


class GovernoCandidateProfileMapper:
    """Map normalized Governo holder records into generic CandidateProfiles."""

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
        try:
            given_name = self._required(record, "given_name")
            family_name = self._required(record, "family_name")
            identifiers = self._string_list(record, "source_identifiers")
            profile_urls = self._string_list(record, "profile_urls")
            mandates_data = record.get("mandates")
            if not isinstance(mandates_data, list) or not mandates_data:
                raise CandidateMappingError("required field 'mandates' is missing or invalid")

            mandates = []
            for mandate_index, item in enumerate(mandates_data):
                if not isinstance(item, Mapping):
                    raise CandidateMappingError(
                        f"mandate {mandate_index} is not an object"
                    )
                mandates.append(
                    PoliticalMandate(
                        institution=self._required(item, "institution"),
                        office=self._required(item, "office"),
                        legislature=self._required(item, "government"),
                        mandate_type=self._required(item, "role_title"),
                        start_date=self._required(item, "mandate_start"),
                        end_date=None,
                        election_area=None,
                    )
                )
            birth_date = self._optional(record, "birth_date")
            birth_city = self._optional(record, "birth_city")
            return CandidateProfile(
                identity=CandidateIdentity(
                    display_name=self._required(record, "display_name"),
                    given_name=given_name,
                    family_name=family_name,
                    birth_date=birth_date,
                    birth_place=(BirthPlace(city=birth_city) if birth_city else None),
                    source_identifiers=tuple(
                        SourceIdentifier(authority=document.source_key, value=value)
                        for value in identifiers
                    ),
                ),
                profile=CandidateProfileData(
                    gender=None,
                    profession=None,
                    image_url=self._optional(record, "photo_url"),
                    official_homepage_url=profile_urls[0],
                    mandates=tuple(mandates),
                ),
                provenance=self._provenance(record, document),
            )
        except (CandidateMappingError, ValidationError, ValueError) as exc:
            label = record.get("display_name", f"index {index}")
            raise CandidateMappingError(
                f"Unable to map Governo record {index} ({label}): {exc}"
            ) from exc

    def _provenance(
        self, record: Mapping[str, Any], document: SourceDocumentProvenance
    ) -> CandidateProvenance:
        profile_urls = self._string_list(record, "profile_urls")
        identifiers = self._string_list(record, "source_identifiers")
        identifier_pages = record.get("source_identifier_pages")
        if not isinstance(identifier_pages, list):
            raise CandidateMappingError(
                "required field 'source_identifier_pages' is missing or invalid"
            )
        primary_url = profile_urls[0]
        fields: list[FieldProvenance] = []

        def add(path: str, source_field: str, value: Any, url: str = primary_url) -> None:
            if isinstance(value, str) and value:
                fields.append(
                    FieldProvenance(
                        target_path=path,
                        source_record_id=url,
                        source_field=source_field,
                        source_value=value,
                        source_url=url,
                    )
                )

        page_by_identifier: dict[str, str] = {}
        for item in identifier_pages:
            if not isinstance(item, Mapping):
                raise CandidateMappingError(
                    "source_identifier_pages contains a non-object value"
                )
            identifier = self._required(item, "value")
            source_url = self._required(item, "profile_url")
            page_by_identifier.setdefault(identifier, source_url)
        for identifier_index, identifier in enumerate(identifiers):
            source_url = page_by_identifier.get(identifier)
            if source_url is None:
                raise CandidateMappingError(
                    f"source identifier {identifier!r} has no profile URL"
                )
            add(
                f"identity.source_identifiers[{identifier_index}].value",
                "link[rel=shortlink]",
                identifier,
                source_url,
            )
        add("identity.given_name", "h1.title_small", record.get("given_name"))
        add("identity.family_name", "h1.title_small", record.get("family_name"))
        add("identity.birth_date", "biography.birth_date", record.get("birth_date"))
        add("identity.birth_place.city", "biography.birth_city", record.get("birth_city"))
        add("profile.image_url", "div.thumb_container img[src]", record.get("photo_url"))
        add(
            "profile.official_homepage_url",
            "link[rel=canonical]",
            profile_urls[0],
        )
        mandates = record.get("mandates")
        assert isinstance(mandates, list)
        for mandate_index, mandate in enumerate(mandates):
            assert isinstance(mandate, Mapping)
            url = self._required(mandate, "profile_url")
            add(
                f"profile.mandates[{mandate_index}].institution",
                "role.institution",
                mandate.get("institution"),
                url,
            )
            add(
                f"profile.mandates[{mandate_index}].office",
                "blockquote.role",
                mandate.get("office"),
                url,
            )
            add(
                f"profile.mandates[{mandate_index}].legislature",
                "government",
                mandate.get("government"),
                url,
            )
            add(
                f"profile.mandates[{mandate_index}].mandate_type",
                "blockquote.role",
                mandate.get("role_title"),
                url,
            )
            add(
                f"profile.mandates[{mandate_index}].start_date",
                "appointment.date",
                mandate.get("mandate_start"),
                mandate.get("appointment_url") or url,
            )
        return CandidateProvenance(document=document, fields=tuple(fields))

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
    def _string_list(record: Mapping[str, Any], field: str) -> list[str]:
        value = record.get(field)
        if not isinstance(value, list) or not value or not all(
            isinstance(item, str) and item for item in value
        ):
            raise CandidateMappingError(f"required field {field!r} is missing or invalid")
        return value
