from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from backend.app.schemas import ExtractedPoliticalClaim, PoliticalClaimExtraction


ITALIAN_MONTHS = (
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
)
ENGLISH_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
WINDOW_CHARS = 160
PROCEDURAL_TARGET_PATTERNS = (
    r"scadenza",
    r"decreto-legge",
    r"decreto legge",
    r"\bd\.?l\.?\b",
    r"\bconversione\b",
    r"seduta n",
    r"assegnaz",
    r"trasmesso",
    r"relazione tecnica",
    r"\bg\.?u\.?\b",
    r"gazzetta",
    r"non ancora pubblicato",
    r"\biter\b",
    r"presentazione",
    r"annunciato nella seduta",
    r"approvato definitivamente",
)
TARGET_COMMITMENT_PATTERNS = (
    r"\bentro\b",
    r"\bby\b",
    r"deadline",
    r"target",
    r"da raggiung",
    r"si impegna",
    r"\bcommit",
    r"\bpledge",
    r"no later than",
    r"per l['’]anno",
    r"entro il",
)
ANNOUNCEMENT_PATTERNS = (
    r"annunciato",
    r"announced",
    r"presentato",
    r"presentata",
    r"presentazione",
    r"presented",
    r"introdot",
    r"introduced",
    r"seduta",
)


@dataclass(frozen=True, slots=True)
class SemanticIssue:
    field: str
    reason: str
    value: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {"field": self.field, "reason": self.reason, "value": self.value}

    def compact_line(self) -> str:
        return f"field: {self.field}\nreason: {self.reason}\nvalue: {self.value}"


class SemanticValidationError(ValueError):
    def __init__(self, issues: tuple[SemanticIssue, ...]) -> None:
        self.issues = issues
        super().__init__("; ".join(issue.compact_line() for issue in issues))

    def compact_messages(self) -> tuple[str, ...]:
        return tuple(issue.compact_line() for issue in self.issues)

    def field_names(self) -> tuple[str, ...]:
        return tuple(issue.field for issue in self.issues)

    def repair_prompt(self) -> str:
        lines = [
            "Correct only unsupported fields. If an optional field has no explicit "
            "support, set it to null. Preserve valid evidence and other fields.",
        ]
        for issue in self.issues:
            lines.append(issue.compact_line())
            if issue.reason == "procedural_deadline_not_proposal_target":
                lines.append(
                    f"target_date={issue.value} is supported only by a procedural "
                    'decreto-legge "scadenza", not by a proposal deadline. '
                    "Return target_date=null unless another cited passage explicitly "
                    "establishes a true proposal target date."
                )
            elif issue.field == "target_date":
                lines.append(
                    "Return target_date=null unless cited evidence explicitly states "
                    "a future deadline for the proposed action itself."
                )
            elif issue.field == "announced_at":
                lines.append(
                    "Return announced_at=null unless cited evidence explicitly states "
                    "an announcement, presentation, or introduction date."
                )
        return "\n".join(lines)


def cited_support_parts(claim: ExtractedPoliticalClaim) -> tuple[str, ...]:
    parts = [claim.exact_statement or ""]
    parts.extend(item.supporting_text for item in claim.evidence)
    return tuple(part for part in parts if part)


def cited_support_text(claim: ExtractedPoliticalClaim) -> str:
    return " ".join(cited_support_parts(claim))


def validate_temporal_semantics(
    payload: PoliticalClaimExtraction | ExtractedPoliticalClaim,
) -> None:
    claims = (
        (payload,)
        if isinstance(payload, ExtractedPoliticalClaim)
        else payload.candidates
    )
    issues: list[SemanticIssue] = []
    for claim in claims:
        if claim.abstention_reason is not None:
            continue
        issues.extend(validate_claim_temporal(claim))
    if issues:
        raise SemanticValidationError(tuple(issues))


def validate_claim_temporal(claim: ExtractedPoliticalClaim) -> tuple[SemanticIssue, ...]:
    parts = cited_support_parts(claim)
    issues: list[SemanticIssue] = []
    if claim.announced_at is not None:
        issue = _validate_announced_at(claim.announced_at, parts)
        if issue is not None:
            issues.append(issue)
    if claim.target_date is not None:
        issue = _validate_target_date(claim.target_date, parts)
        if issue is not None:
            issues.append(issue)
    return tuple(issues)


def _validate_announced_at(
    value: date, parts: tuple[str, ...]
) -> SemanticIssue | None:
    windows = _all_mention_windows(parts, value, allow_year_only=False)
    if not windows:
        return SemanticIssue(
            field="announced_at",
            reason="unsupported_announced_at",
            value=value.isoformat(),
        )
    if any(_matches_any(window, ANNOUNCEMENT_PATTERNS) for window in windows):
        return None
    return SemanticIssue(
        field="announced_at",
        reason="unsupported_announced_at",
        value=value.isoformat(),
    )


def _validate_target_date(
    value: date, parts: tuple[str, ...]
) -> SemanticIssue | None:
    windows = _all_mention_windows(parts, value, allow_year_only=True)
    if not windows:
        return SemanticIssue(
            field="target_date",
            reason="unsupported_target_date",
            value=value.isoformat(),
        )
    genuine = False
    procedural = False
    for window in windows:
        if _matches_any(window, PROCEDURAL_TARGET_PATTERNS):
            procedural = True
            continue
        if _matches_any(window, TARGET_COMMITMENT_PATTERNS):
            genuine = True
    if genuine:
        return None
    if procedural:
        return SemanticIssue(
            field="target_date",
            reason="procedural_deadline_not_proposal_target",
            value=value.isoformat(),
        )
    return SemanticIssue(
        field="target_date",
        reason="unsupported_target_date",
        value=value.isoformat(),
    )


def _all_mention_windows(
    parts: tuple[str, ...], value: date, *, allow_year_only: bool
) -> tuple[str, ...]:
    windows: list[str] = []
    for part in parts:
        windows.extend(_mention_windows(part, value, allow_year_only=allow_year_only))
    return tuple(windows)


def _mention_windows(
    text: str, value: date, *, allow_year_only: bool
) -> tuple[str, ...]:
    haystack = text.casefold()
    spans: list[tuple[int, int]] = []
    for pattern in _date_patterns(value, allow_year_only=allow_year_only):
        for match in re.finditer(re.escape(pattern), haystack):
            spans.append((match.start(), match.end()))
    windows: list[str] = []
    for start, end in spans:
        left = max(0, start - WINDOW_CHARS)
        right = min(len(haystack), end + WINDOW_CHARS)
        windows.append(haystack[left:right])
    return tuple(windows)


def _date_patterns(value: date, *, allow_year_only: bool) -> tuple[str, ...]:
    italian = ITALIAN_MONTHS[value.month - 1]
    english = ENGLISH_MONTHS[value.month - 1]
    patterns = [
        value.isoformat(),
        f"{value.day} {italian} {value.year}",
        f"{value.day:02d} {italian} {value.year}",
        f"{value.day} {english} {value.year}",
        f"{value.day:02d}/{value.month:02d}/{value.year}",
        f"{value.day}/{value.month}/{value.year}",
        f"{value.month:02d}/{value.day:02d}/{value.year}",
    ]
    if allow_year_only:
        patterns.extend(
            (
                f"by {value.year}",
                f"entro il {value.year}",
                f"entro {value.year}",
                f"anno {value.year}",
            )
        )
    return tuple(item.casefold() for item in patterns)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)
