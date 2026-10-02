from enum import StrEnum
from typing import Any

from backend.app.schemas.candidate_profile import ImmutableSchema
from backend.app.schemas.politician import PoliticianVersionProfile


class DiffStatus(StrEnum):
    INITIAL = "initial"
    UPDATE = "update"


class ChangeType(StrEnum):
    ADDED = "added"
    CHANGED = "changed"
    REMOVED = "removed"


class FieldChange(ImmutableSchema):
    field_path: str
    change_type: ChangeType
    old_value: Any = None
    new_value: Any = None


class ProfileDiff(ImmutableSchema):
    status: DiffStatus
    proposed_profile: PoliticianVersionProfile
    changes: tuple[FieldChange, ...]
