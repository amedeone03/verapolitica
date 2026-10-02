from typing import Any

from pydantic import ValidationError

from backend.app.models import PoliticianVersion
from backend.app.schemas import (
    CandidateProfile,
    ChangeType,
    DiffStatus,
    FieldChange,
    PoliticalMandate,
    PoliticianVersionProfile,
    ProfileDiff,
)


class DiffServiceError(ValueError):
    """The candidate or stored baseline cannot be compared safely."""


def _mandate_sort_key(mandate: PoliticalMandate) -> tuple[str, ...]:
    return (
        mandate.institution,
        mandate.office,
        mandate.legislature,
        mandate.mandate_type,
        mandate.start_date.isoformat(),
        mandate.end_date.isoformat() if mandate.end_date else "",
        mandate.election_area or "",
    )


def _ordered_profile(profile: PoliticianVersionProfile) -> PoliticianVersionProfile:
    return profile.model_copy(
        update={"mandates": tuple(sorted(profile.mandates, key=_mandate_sort_key))}
    )


def candidate_to_version_profile(
    candidate: CandidateProfile,
) -> PoliticianVersionProfile:
    """Convert a transient candidate into the public version schema."""

    identity = candidate.identity
    profile = candidate.profile
    return _ordered_profile(
        PoliticianVersionProfile(
            given_name=identity.given_name,
            family_name=identity.family_name,
            birth_date=identity.birth_date,
            birth_place=identity.birth_place,
            gender=profile.gender,
            profession=profile.profession,
            image_url=profile.image_url,
            official_homepage_url=profile.official_homepage_url,
            mandates=profile.mandates,
        )
    )


class DiffService:
    """Pure deterministic comparison against an immutable current version."""

    scalar_paths = (
        "given_name",
        "family_name",
        "birth_date",
        "birth_place.city",
        "birth_place.subdivision",
        "birth_place.country",
        "gender",
        "profession",
        "image_url",
        "official_homepage_url",
    )

    def compare(
        self,
        candidate: CandidateProfile,
        baseline: PoliticianVersion | None,
    ) -> ProfileDiff:
        proposed = candidate_to_version_profile(candidate)
        proposed_data = proposed.model_dump(mode="json")

        if baseline is None:
            changes = self._initial_changes(proposed_data)
            return ProfileDiff(
                status=DiffStatus.INITIAL,
                proposed_profile=proposed,
                changes=tuple(changes),
            )

        try:
            baseline_profile = _ordered_profile(
                PoliticianVersionProfile.model_validate(baseline.profile_data)
            )
        except ValidationError as exc:
            raise DiffServiceError(
                f"PoliticianVersion {baseline.id} has invalid profile data: {exc}"
            ) from exc

        baseline_data = baseline_profile.model_dump(mode="json")
        changes = self._update_changes(baseline_data, proposed_data)
        return ProfileDiff(
            status=DiffStatus.UPDATE,
            proposed_profile=proposed,
            changes=tuple(changes),
        )

    def _initial_changes(self, proposed: dict[str, Any]) -> list[FieldChange]:
        changes = []
        for path in self.scalar_paths:
            value = self._value_at(proposed, path)
            if value is not None:
                changes.append(
                    FieldChange(
                        field_path=path,
                        change_type=ChangeType.ADDED,
                        old_value=None,
                        new_value=value,
                    )
                )
        mandates = proposed["mandates"]
        if mandates:
            changes.append(
                FieldChange(
                    field_path="mandates",
                    change_type=ChangeType.ADDED,
                    old_value=None,
                    new_value=mandates,
                )
            )
        return changes

    def _update_changes(
        self,
        baseline: dict[str, Any],
        proposed: dict[str, Any],
    ) -> list[FieldChange]:
        changes = []
        for path in self.scalar_paths:
            old_value = self._value_at(baseline, path)
            new_value = self._value_at(proposed, path)
            if old_value != new_value:
                changes.append(
                    FieldChange(
                        field_path=path,
                        change_type=self._change_type(old_value, new_value),
                        old_value=old_value,
                        new_value=new_value,
                    )
                )

        old_mandates = baseline["mandates"]
        new_mandates = proposed["mandates"]
        if old_mandates != new_mandates:
            changes.append(
                FieldChange(
                    field_path="mandates",
                    change_type=self._change_type(old_mandates, new_mandates),
                    old_value=old_mandates,
                    new_value=new_mandates,
                )
            )
        return changes

    @staticmethod
    def _value_at(data: dict[str, Any], path: str) -> Any:
        value: Any = data
        for part in path.split("."):
            if value is None:
                return None
            value = value[part]
        return value

    @staticmethod
    def _change_type(old_value: Any, new_value: Any) -> ChangeType:
        if old_value is None or old_value == []:
            return ChangeType.ADDED
        if new_value is None or new_value == []:
            return ChangeType.REMOVED
        return ChangeType.CHANGED
