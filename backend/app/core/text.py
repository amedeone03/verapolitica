from __future__ import annotations

import re
import unicodedata


def normalize_search_text(value: str) -> str:
    """Deterministic accent-insensitive search key. Does not stem names."""

    combined = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in combined if not unicodedata.combining(character)
    ).casefold()
    alphanumeric = "".join(
        character if character.isalnum() else " " for character in without_marks
    )
    return re.sub(r"\s+", " ", alphanumeric).strip()


def search_tokens(normalized: str) -> tuple[str, ...]:
    return tuple(token for token in normalized.split() if len(token) >= 3)


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
