from datetime import date
from enum import StrEnum

from pydantic import AnyHttpUrl, Field, model_validator

from backend.app.schemas.candidate_profile import ImmutableSchema


class ParliamentaryGroupObservation(ImmutableSchema):
    """Source-independent, transient observation produced by a chamber mapper."""

    source_key: str
    raw_document_id: int = Field(gt=0)
    politician_source_identifier: str
    group_source_identifier: str
    membership_source_identifier: str | None = None
    canonical_name: str
    abbreviation: str | None = None
    institution: str
    legislature: str
    start_date: date | None = None
    end_date: date | None = None
    role: str | None = None
    source_url: AnyHttpUrl

    @model_validator(mode="after")
    def validate_interval(self) -> "ParliamentaryGroupObservation":
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date cannot be before start_date")
        return self


class MembershipPersistenceStatus(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    ALREADY_EXISTS = "already_exists"
    UNRESOLVED_POLITICIAN = "unresolved_politician"


class MembershipPersistenceDetail(ImmutableSchema):
    status: MembershipPersistenceStatus
    politician_id: int | None = None
    politician_source_identifier: str
    group_name: str
    group_source_identifier: str
    start_date: date | None = None
    end_date: date | None = None
    role: str | None = None


class MembershipOverlapWarning(ImmutableSchema):
    politician_id: int
    institution: str
    legislature: str
    membership_ids: tuple[int, int]


class ParliamentaryGroupSyncResult(ImmutableSchema):
    total_observations: int = Field(ge=0)
    groups_created: int = Field(ge=0)
    memberships_created: int = Field(ge=0)
    memberships_updated: int = Field(ge=0)
    memberships_unchanged: int = Field(ge=0)
    unresolved_references: int = Field(ge=0)
    details: tuple[MembershipPersistenceDetail, ...]
    overlap_warnings: tuple[MembershipOverlapWarning, ...] = ()
