from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class ImmutableSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"


class BirthPlace(ImmutableSchema):
    city: str | None = None
    subdivision: str | None = None
    country: str | None = None


class SourceIdentifier(ImmutableSchema):
    authority: str
    value: str


class CandidateIdentity(ImmutableSchema):
    given_name: str
    family_name: str
    birth_date: date | None = None
    birth_place: BirthPlace | None = None
    source_identifiers: tuple[SourceIdentifier, ...]


class PoliticalMandate(ImmutableSchema):
    institution: str
    office: str
    legislature: str
    mandate_type: str
    start_date: date
    end_date: date | None = None
    election_area: str | None = None


class CandidateProfileData(ImmutableSchema):
    gender: Gender | None = None
    profession: str | None = None
    image_url: AnyHttpUrl | None = None
    official_homepage_url: AnyHttpUrl | None = None
    mandates: tuple[PoliticalMandate, ...]


class SourceDocumentProvenance(ImmutableSchema):
    source_key: str
    raw_document_id: int = Field(gt=0)
    source_url: AnyHttpUrl
    retrieved_at: datetime
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    collector_version: str
    parser_version: str


class FieldProvenance(ImmutableSchema):
    target_path: str
    source_record_id: str
    source_field: str
    source_value: str
    source_url: AnyHttpUrl | None = None
    method: Literal["deterministic"] = "deterministic"


class CandidateProvenance(ImmutableSchema):
    document: SourceDocumentProvenance
    fields: tuple[FieldProvenance, ...]


class CandidateProfile(ImmutableSchema):
    identity: CandidateIdentity
    profile: CandidateProfileData
    provenance: CandidateProvenance
