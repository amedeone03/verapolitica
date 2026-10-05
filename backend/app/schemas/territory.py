from datetime import date
from enum import StrEnum

from pydantic import AnyHttpUrl, Field, model_validator

from backend.app.models.territorial_office_mandate import TerritorialOffice
from backend.app.models.territory import TerritoryStatus
from backend.app.schemas.candidate_profile import ImmutableSchema


class RegionObservation(ImmutableSchema):
    source_key: str = Field(min_length=1)
    raw_document_id: int = Field(gt=0)
    istat_code: str = Field(pattern=r"^\d{2}$")
    canonical_name: str = Field(min_length=1)
    status: TerritoryStatus = TerritoryStatus.ACTIVE
    active_from: date | None = None
    active_until: date | None = None
    source_url: AnyHttpUrl

    @model_validator(mode="after")
    def validate_dates(self) -> "RegionObservation":
        if (
            self.active_from is not None
            and self.active_until is not None
            and self.active_until < self.active_from
        ):
            raise ValueError("active_until cannot be before active_from")
        if self.status is TerritoryStatus.INACTIVE and self.active_until is None:
            raise ValueError("inactive territory requires active_until")
        return self


class MunicipalityObservation(ImmutableSchema):
    source_key: str = Field(min_length=1)
    raw_document_id: int = Field(gt=0)
    istat_code: str = Field(pattern=r"^\d{6}$")
    region_istat_code: str = Field(pattern=r"^\d{2}$")
    canonical_name: str = Field(min_length=1)
    province_abbreviation: str = Field(pattern=r"^[A-Za-z]{2}$")
    province_name: str = Field(min_length=1)
    status: TerritoryStatus = TerritoryStatus.ACTIVE
    active_from: date | None = None
    active_until: date | None = None
    source_url: AnyHttpUrl

    @model_validator(mode="after")
    def validate_dates(self) -> "MunicipalityObservation":
        if (
            self.active_from is not None
            and self.active_until is not None
            and self.active_until < self.active_from
        ):
            raise ValueError("active_until cannot be before active_from")
        if self.status is TerritoryStatus.INACTIVE and self.active_until is None:
            raise ValueError("inactive territory requires active_until")
        return self


class TerritorySyncResult(ImmutableSchema):
    regions_created: int = Field(ge=0)
    regions_updated: int = Field(ge=0)
    regions_unchanged: int = Field(ge=0)
    municipalities_created: int = Field(ge=0)
    municipalities_updated: int = Field(ge=0)
    municipalities_unchanged: int = Field(ge=0)


class TerritorialMandateObservation(ImmutableSchema):
    source_key: str = Field(min_length=1)
    raw_document_id: int = Field(gt=0)
    office: TerritorialOffice
    region_istat_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    municipality_istat_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    politician_source_identifier: str | None = Field(default=None, min_length=1)
    given_name: str = Field(min_length=1)
    family_name: str = Field(min_length=1)
    birth_date: date | None = None
    source_identifier: str | None = Field(default=None, min_length=1)
    start_date: date
    end_date: date | None = None
    source_url: AnyHttpUrl

    @model_validator(mode="after")
    def validate_target_and_dates(self) -> "TerritorialMandateObservation":
        if self.office is TerritorialOffice.MAYOR:
            if self.municipality_istat_code is None or self.region_istat_code is not None:
                raise ValueError("mayor requires only municipality_istat_code")
        elif self.region_istat_code is None or self.municipality_istat_code is not None:
            raise ValueError("regional_president requires only region_istat_code")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        return self


class TerritorialMandatePersistenceStatus(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    ALREADY_EXISTS = "already_exists"
    UNRESOLVED_POLITICIAN = "unresolved_politician"
    UNRESOLVED_TERRITORY = "unresolved_territory"


class TerritorialMandatePersistenceDetail(ImmutableSchema):
    status: TerritorialMandatePersistenceStatus
    politician_id: int | None = None
    office: TerritorialOffice
    territory_istat_code: str
    start_date: date
    end_date: date | None = None


class TerritorialMandateSyncResult(ImmutableSchema):
    total_observations: int = Field(ge=0)
    mandates_created: int = Field(ge=0)
    mandates_updated: int = Field(ge=0)
    mandates_unchanged: int = Field(ge=0)
    unresolved_people: int = Field(ge=0)
    unresolved_territories: int = Field(ge=0)
    details: tuple[TerritorialMandatePersistenceDetail, ...]


# Full domain-name alias kept for callers that mirror the ORM model name.
TerritorialOfficeMandateObservation = TerritorialMandateObservation
