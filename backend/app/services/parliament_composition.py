"""Seats in the Camera and the Senato by parliamentary group, from the official data.

Counts the people with an open membership in a group of the current legislature,
as published by camera.it and senato.it (ingested as parliamentary group
memberships). Names are not returned here: only the groups and their seats.
"""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.models import ParliamentaryGroup
from backend.app.models.parliamentary_group_membership import ParliamentaryGroupMembership

CHAMBERS = {
    "camera": {"institution": "Camera dei Deputati", "label": "Camera dei deputati", "seats_by_law": 400},
    "senato": {"institution": "Senato della Repubblica", "label": "Senato della Repubblica", "seats_by_law": 200},
}
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def legislature_number(value: str | None) -> int:
    text = str(value or "").strip().upper()
    digits = re.search(r"\d+", text)
    if digits:
        return int(digits.group())
    total, previous = 0, 0
    for char in reversed(re.sub(r"[^IVXLC]", "", text)):
        current = ROMAN[char]
        total = total - current if current < previous else total + current
        previous = max(previous, current)
    return total


def composition(session: Session, chamber: str, *, today: date | None = None) -> dict:
    spec = CHAMBERS[chamber]
    today = today or date.today()
    groups = list(session.scalars(select(ParliamentaryGroup).where(ParliamentaryGroup.institution == spec["institution"])))
    current = max((legislature_number(group.legislature) for group in groups), default=0)
    groups = [group for group in groups if legislature_number(group.legislature) == current]
    seats = dict(
        tuple(row)
        for row in session.execute(
            select(ParliamentaryGroupMembership.parliamentary_group_id, func.count(func.distinct(ParliamentaryGroupMembership.politician_id)))
            .where(
                ParliamentaryGroupMembership.parliamentary_group_id.in_([group.id for group in groups] or [0]),
                or_(ParliamentaryGroupMembership.end_date.is_(None), ParliamentaryGroupMembership.end_date >= today),
                or_(ParliamentaryGroupMembership.start_date.is_(None), ParliamentaryGroupMembership.start_date <= today),
            )
            .group_by(ParliamentaryGroupMembership.parliamentary_group_id)
        )
    )
    items = [
        {"id": group.id, "name": group.canonical_name, "abbreviation": group.abbreviation, "seats": int(seats.get(group.id, 0))}
        for group in groups
        if seats.get(group.id)
    ]
    items.sort(key=lambda item: (-item["seats"], item["name"]))
    total = sum(item["seats"] for item in items)
    return {
        "chamber": chamber,
        "label": spec["label"],
        "legislature": current or None,
        "seats_by_law": spec["seats_by_law"],
        "counted": total,
        "majority": total // 2 + 1 if total else None,
        "groups": items,
        "as_of": today.isoformat(),
    }
