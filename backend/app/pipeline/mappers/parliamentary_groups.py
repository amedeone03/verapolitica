import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from pydantic import ValidationError

from backend.app.pipeline.mappers.base import CandidateMappingError
from backend.app.schemas import ParliamentaryGroupObservation


class ParliamentaryGroupMapper(Protocol):
    def map_records(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        source_key: str,
        raw_document_id: int,
    ) -> tuple[ParliamentaryGroupObservation, ...]: ...


class _BaseParliamentaryGroupMapper:
    institution: str
    person_field: str

    def map_records(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        source_key: str,
        raw_document_id: int,
    ) -> tuple[ParliamentaryGroupObservation, ...]:
        observations: list[ParliamentaryGroupObservation] = []
        for index, record in enumerate(records):
            try:
                person_identifier = self._required(record, self.person_field)
                observations.append(
                    ParliamentaryGroupObservation(
                        source_key=source_key,
                        raw_document_id=raw_document_id,
                        politician_source_identifier=person_identifier,
                        group_source_identifier=self._required(record, "group_uri"),
                        canonical_name=self._group_name(record),
                        abbreviation=self._optional(record, "group_abbreviation"),
                        institution=self.institution,
                        legislature=self._legislature(record),
                        start_date=self._optional(record, "membership_start"),
                        end_date=self._optional(record, "membership_end"),
                        role=self._optional(record, "membership_role"),
                        source_url=person_identifier,
                    )
                )
            except (CandidateMappingError, ValidationError, ValueError) as exc:
                raise CandidateMappingError(
                    f"Unable to map {self.institution} group record at index "
                    f"{index}: {exc}"
                ) from exc
        return tuple(observations)

    def _group_name(self, record: Mapping[str, Any]) -> str:
        return self._required(record, "group_name")

    def _legislature(self, record: Mapping[str, Any]) -> str:
        return self._required(record, "legislature")

    @staticmethod
    def _required(record: Mapping[str, Any], field: str) -> str:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CandidateMappingError(f"required field {field!r} is missing or invalid")
        return value.strip()

    @staticmethod
    def _optional(record: Mapping[str, Any], field: str) -> str | None:
        value = record.get(field)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise CandidateMappingError(f"optional field {field!r} is invalid")
        return value.strip()


class SenatoParliamentaryGroupMapper(_BaseParliamentaryGroupMapper):
    institution = "Senato della Repubblica"
    person_field = "senator_uri"


class CameraParliamentaryGroupMapper(_BaseParliamentaryGroupMapper):
    institution = "Camera dei Deputati"
    person_field = "deputy_uri"
    legislature = "19"
    _date_suffix = re.compile(
        r"\s+\(\d{2}\.\d{2}\.\d{4}"
        r"(?:-\d{2}\.\d{2}\.\d{4})?\)?\s*$"
    )

    def __init__(self, legislature: int | str) -> None:
        self.legislature = str(legislature)

    def _group_name(self, record: Mapping[str, Any]) -> str:
        raw_name = self._required(record, "group_name")
        cleaned = self._date_suffix.sub("", raw_name).strip()
        abbreviation = self._optional(record, "group_abbreviation")
        if abbreviation and cleaned.endswith(f" ({abbreviation})"):
            cleaned = cleaned[: -len(abbreviation) - 3].rstrip()
        if not cleaned:
            raise CandidateMappingError("group_name is empty after date normalization")
        return cleaned

    def _legislature(self, record: Mapping[str, Any]) -> str:
        return self.legislature
