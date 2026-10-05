from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import Municipality, Region, TerritorialOffice
from backend.app.pipeline.mappers.base import CandidateMappingError
from backend.app.pipeline.parsers.territorial import normalize_header
from backend.app.schemas import (
    CandidateIdentity,
    CandidateProfile,
    CandidateProfileData,
    CandidateProvenance,
    FieldProvenance,
    MunicipalityObservation,
    RegionObservation,
    SourceDocumentProvenance,
    SourceIdentifier,
    TerritorialMandateObservation,
)


def normalize_territory_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", plain.casefold())).strip()


def _header_value(
    record: Mapping[str, Any],
    aliases: Sequence[str],
    *,
    required: bool = True,
) -> tuple[str | None, Any]:
    by_normalized = {
        normalize_header(key): (str(key), value) for key, value in record.items()
    }
    for alias in aliases:
        match = by_normalized.get(alias)
        if match is not None and str(match[1]).strip():
            return match
    if required:
        raise CandidateMappingError(
            f"missing required source header ({', '.join(aliases)})"
        )
    return None, None


def _digits(value: Any, width: int) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = re.sub(r"\D", "", str(value))
    if not text:
        raise CandidateMappingError("code contains no digits")
    return text.zfill(width)


class IstatTerritoryMapper:
    """Map source-header-preserving ISTAT rows into domain observations."""

    REGION_CODE = ("codice regione", "cod regione")
    REGION_NAME = ("denominazione regione", "regione")
    MUNICIPALITY_CODE = (
        "codice comune formato alfanumerico",
        "codice comune",
        "cod comune",
        "codice istat del comune",
    )
    MUNICIPALITY_NAME = (
        "denominazione in italiano",
        "denominazione comune",
        "comune",
    )
    PROVINCE_ABBREVIATION = (
        "sigla automobilistica",
        "sigla provincia",
        "provincia sigla",
        "sigla",
    )
    PROVINCE_NAME = (
        "denominazione dell unita territoriale sovracomunale valida a fini statistici",
        "denominazione provincia",
        "provincia",
    )

    def map_records(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        source_key: str,
        raw_document_id: int,
        source_url: str,
    ) -> tuple[tuple[RegionObservation, ...], tuple[MunicipalityObservation, ...]]:
        regions: dict[str, RegionObservation] = {}
        municipalities: list[MunicipalityObservation] = []
        try:
            for record in records:
                _, region_code_value = _header_value(record, self.REGION_CODE)
                _, region_name = _header_value(record, self.REGION_NAME)
                _, municipality_code_value = _header_value(record, self.MUNICIPALITY_CODE)
                _, municipality_name = _header_value(record, self.MUNICIPALITY_NAME)
                _, province_abbreviation = _header_value(
                    record, self.PROVINCE_ABBREVIATION
                )
                _, province_name = _header_value(record, self.PROVINCE_NAME)
                region_code = _digits(region_code_value, 2)
                region = RegionObservation(
                    source_key=source_key,
                    raw_document_id=raw_document_id,
                    istat_code=region_code,
                    canonical_name=str(region_name).strip(),
                    source_url=source_url,
                )
                existing = regions.setdefault(region_code, region)
                if existing.canonical_name != region.canonical_name:
                    raise CandidateMappingError(
                        f"conflicting names for ISTAT region {region_code}"
                    )
                municipalities.append(
                    MunicipalityObservation(
                        source_key=source_key,
                        raw_document_id=raw_document_id,
                        istat_code=_digits(municipality_code_value, 6),
                        region_istat_code=region_code,
                        canonical_name=str(municipality_name).strip(),
                        province_abbreviation=str(province_abbreviation).strip().upper(),
                        province_name=str(province_name).strip(),
                        source_url=source_url,
                    )
                )
        except (ValidationError, ValueError) as exc:
            raise CandidateMappingError(f"Unable to map ISTAT row: {exc}") from exc
        return tuple(regions[key] for key in sorted(regions)), tuple(municipalities)


@dataclass(frozen=True, slots=True)
class UnresolvedDaitRow:
    row_number: int
    reason: str
    record: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class DaitMappingResult:
    candidates: tuple[CandidateProfile, ...]
    mandates: tuple[TerritorialMandateObservation, ...]
    unresolved_rows: tuple[UnresolvedDaitRow, ...]


class DaitMayorMapper:
    """Conservatively map DAIT mayors against already-loaded ISTAT territories."""

    MUNICIPALITY = ("denominazione comune", "comune")
    PROVINCE = ("sigla provincia", "provincia", "prov")
    REGION_CODE = ("codice regione", "cod regione", "codice istat regione")
    GIVEN_NAME = ("nome",)
    FAMILY_NAME = ("cognome",)
    BIRTH_DATE = ("data di nascita", "data nascita")
    BIRTH_PLACE = ("luogo di nascita", "luogo nascita")
    SEX = ("sesso",)
    START_DATE = (
        "data entrata in carica",
        "data inizio mandato",
        "data insediamento",
        "data elezione",
    )
    OFFICE = ("descrizione carica", "carica")

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def map_records(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        document: SourceDocumentProvenance,
    ) -> DaitMappingResult:
        with self.session_factory() as session:
            territory_index = self._territory_index(session)
        candidates: list[CandidateProfile] = []
        mandates: list[TerritorialMandateObservation] = []
        unresolved: list[UnresolvedDaitRow] = []
        for index, record in enumerate(records, start=2):
            try:
                _, office = _header_value(record, self.OFFICE, required=False)
                if office and normalize_territory_name(str(office)) not in {
                    "sindaco",
                    "sindaca",
                }:
                    continue
                municipality_header, municipality_name = _header_value(
                    record, self.MUNICIPALITY
                )
                province_header, province = _header_value(record, self.PROVINCE)
                region_header, region_code_value = _header_value(record, self.REGION_CODE)
                key = (
                    normalize_territory_name(str(municipality_name)),
                    str(province).strip().upper(),
                    _digits(region_code_value, 2),
                )
                matches = territory_index.get(key, ())
                if len(matches) != 1:
                    reason = (
                        "territory_not_found" if not matches else "territory_ambiguous"
                    )
                    unresolved.append(UnresolvedDaitRow(index, reason, dict(record)))
                    continue
                given_header, given_name = _header_value(record, self.GIVEN_NAME)
                family_header, family_name = _header_value(record, self.FAMILY_NAME)
                start_header, start_value = _header_value(record, self.START_DATE)
                birth_header, birth_value = _header_value(
                    record, self.BIRTH_DATE, required=False
                )
                start_date = self._date(start_value, required=True)
                birth_date = self._date(birth_value, required=False)
                source_identifier = self._source_identifier(record)
                candidate = self._candidate(
                    document=document,
                    source_identifier=source_identifier,
                    given_name=str(given_name).strip(),
                    family_name=str(family_name).strip(),
                    birth_date=birth_date,
                    source_fields=(
                        (given_header, given_name, "identity.given_name"),
                        (family_header, family_name, "identity.family_name"),
                        (birth_header, birth_value, "identity.birth_date"),
                    ),
                )
                municipality = matches[0]
                mandate = TerritorialMandateObservation(
                    source_key=document.source_key,
                    raw_document_id=document.raw_document_id,
                    office=TerritorialOffice.MAYOR,
                    municipality_istat_code=municipality.istat_code,
                    politician_source_identifier=source_identifier,
                    given_name=candidate.identity.given_name,
                    family_name=candidate.identity.family_name,
                    birth_date=birth_date,
                    source_identifier=source_identifier,
                    start_date=start_date,
                    source_url=document.source_url,
                )
                candidates.append(candidate)
                mandates.append(mandate)
            except (CandidateMappingError, ValidationError, ValueError) as exc:
                unresolved.append(
                    UnresolvedDaitRow(index, f"invalid_row: {exc}", dict(record))
                )
        return DaitMappingResult(tuple(candidates), tuple(mandates), tuple(unresolved))

    @staticmethod
    def _territory_index(
        session: Session,
    ) -> dict[tuple[str, str, str], tuple[Municipality, ...]]:
        index: dict[tuple[str, str, str], list[Municipality]] = {}
        rows = session.execute(
            select(Municipality, Region).join(Region, Municipality.region_id == Region.id)
        )
        for municipality, region in rows:
            key = (
                normalize_territory_name(municipality.canonical_name),
                municipality.province_abbreviation.upper(),
                region.istat_code,
            )
            index.setdefault(key, []).append(municipality)
        return {key: tuple(value) for key, value in index.items()}

    @staticmethod
    def _date(value: Any, *, required: bool) -> date | None:
        if value is None or not str(value).strip():
            if required:
                raise CandidateMappingError("required date is missing")
            return None
        text = str(value).strip()
        for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
            try:
                return datetime.strptime(text, pattern).date()
            except ValueError:
                pass
        raise CandidateMappingError(f"unsupported date {text!r}")

    @classmethod
    def _source_identifier(cls, record: Mapping[str, Any]) -> str:
        def value(aliases: Sequence[str]) -> str:
            _, raw = _header_value(record, aliases, required=False)
            return str(raw).strip() if raw is not None and str(raw).strip() else ""

        canonical = json.dumps(
            [
                value(cls.FAMILY_NAME),
                value(cls.GIVEN_NAME),
                value(cls.BIRTH_DATE),
                value(cls.BIRTH_PLACE),
                value(cls.SEX),
                value(cls.REGION_CODE),
                value(cls.PROVINCE),
                value(cls.MUNICIPALITY),
                value(cls.OFFICE),
                value(cls.START_DATE),
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return "dait:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _candidate(
        *,
        document: SourceDocumentProvenance,
        source_identifier: str,
        given_name: str,
        family_name: str,
        birth_date: date | None,
        source_fields: tuple[tuple[str | None, Any, str], ...],
    ) -> CandidateProfile:
        fields = tuple(
            FieldProvenance(
                target_path=target,
                source_record_id=source_identifier,
                source_field=header,
                source_value=str(value),
                source_url=document.source_url,
            )
            for header, value, target in source_fields
            if header is not None and value is not None and str(value).strip()
        )
        return CandidateProfile(
            identity=CandidateIdentity(
                display_name=f"{given_name} {family_name}",
                given_name=given_name,
                family_name=family_name,
                birth_date=birth_date,
                source_identifiers=(
                    SourceIdentifier(
                        authority=document.source_key, value=source_identifier
                    ),
                ),
            ),
            profile=CandidateProfileData(mandates=()),
            provenance=CandidateProvenance(document=document, fields=fields),
        )
