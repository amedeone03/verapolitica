from datetime import date
from enum import StrEnum

from pydantic import AnyHttpUrl, Field, model_validator

from backend.app.schemas.candidate_profile import ImmutableSchema


class PoliticalPartyObservation(ImmutableSchema):
    """Transient representation of an explicit official affiliation assertion."""

    source_key: str = Field(min_length=1)
    raw_document_id: int = Field(gt=0)
    politician_source_identifier: str = Field(min_length=1)
    party_source_identifier: str = Field(min_length=1)
    affiliation_source_identifier: str | None = Field(default=None, min_length=1)
    party_name: str = Field(min_length=1)
    abbreviation: str | None = None
    official_website_url: AnyHttpUrl | None = None
    country: str = Field(default="Italy", min_length=1)
    party_active_from: date | None = None
    party_active_until: date | None = None
    affiliation_start: date | None = None
    affiliation_end: date | None = None
    affiliation_type: str | None = None
    source_url: AnyHttpUrl
    source_field: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dates(self) -> "PoliticalPartyObservation":
        if (
            self.affiliation_start is not None
            and self.affiliation_end is not None
            and self.affiliation_end < self.affiliation_start
        ):
            raise ValueError("affiliation_end cannot be before affiliation_start")
        if (
            self.party_active_from is not None
            and self.party_active_until is not None
            and self.party_active_until < self.party_active_from
        ):
            raise ValueError("party_active_until cannot be before party_active_from")
        return self


class PartyAffiliationPersistenceStatus(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    ALREADY_EXISTS = "already_exists"
    UNRESOLVED_POLITICIAN = "unresolved_politician"


class PartyAffiliationPersistenceDetail(ImmutableSchema):
    status: PartyAffiliationPersistenceStatus
    politician_id: int | None = None
    politician_source_identifier: str
    party_name: str
    party_source_identifier: str
    start_date: date | None = None
    end_date: date | None = None
    affiliation_type: str | None = None


class PartyAffiliationOverlapWarning(ImmutableSchema):
    politician_id: int
    affiliation_ids: tuple[int, int]


class PoliticalPartySyncResult(ImmutableSchema):
    total_observations: int = Field(ge=0)
    parties_created: int = Field(ge=0)
    affiliations_created: int = Field(ge=0)
    affiliations_updated: int = Field(ge=0)
    affiliations_unchanged: int = Field(ge=0)
    unresolved_references: int = Field(ge=0)
    details: tuple[PartyAffiliationPersistenceDetail, ...]
    overlap_warnings: tuple[PartyAffiliationOverlapWarning, ...] = ()
