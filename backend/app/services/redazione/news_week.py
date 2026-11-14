"""Editorial news week in trial: Tuesday → Monday.

Proposals are collected at the Friday meeting; the full assignment list
lands on Monday. The rest of the week is for writing and publishing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")

# Monday=0 … Sunday=6. Week starts Tuesday (1), ends Monday (0).
_WEEKDAY_TUESDAY = 1
_WEEKDAY_FRIDAY = 4
_WEEKDAY_MONDAY = 0


@dataclass(frozen=True, slots=True)
class NewsWeek:
    """Current publication week and the next process milestones."""

    week_start: str  # ISO date, Tuesday
    week_end: str  # ISO date, Monday
    today: str
    phase: str  # proposte | assegnazioni | scrittura
    phase_label: str
    proposals_on: str  # Friday of this week (or next if past)
    assignments_on: str  # Monday closing this week (or next)
    summary: str

    def as_dict(self) -> dict:
        return asdict(self)


def _rome_today(now: datetime | None = None) -> date:
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(ROME).date()


def week_bounds(day: date) -> tuple[date, date]:
    """Return (Tuesday, Monday) covering ``day``."""

    # Days since Tuesday: Tue=0 … Mon=6
    since_tuesday = (day.weekday() - _WEEKDAY_TUESDAY) % 7
    start = day - timedelta(days=since_tuesday)
    end = start + timedelta(days=6)
    return start, end


def news_week(*, now: datetime | None = None) -> NewsWeek:
    today = _rome_today(now)
    start, end = week_bounds(today)
    friday = start + timedelta(days=(_WEEKDAY_FRIDAY - _WEEKDAY_TUESDAY) % 7)
    monday = end  # week ends on Monday

    if today.weekday() == _WEEKDAY_FRIDAY:
        phase, phase_label = "proposte", "Oggi: riunione proposte"
    elif today.weekday() == _WEEKDAY_MONDAY:
        phase, phase_label = "assegnazioni", "Oggi: lista completa e assegnazioni"
    else:
        phase, phase_label = "scrittura", "Settimana di scrittura e pubblicazione"

    summary = (
        f"Settimana {start.day}/{start.month}–{end.day}/{end.month}: "
        f"proposte venerdì {friday.day}/{friday.month}, "
        f"assegnazioni lunedì {monday.day}/{monday.month}."
    )
    return NewsWeek(
        week_start=start.isoformat(),
        week_end=end.isoformat(),
        today=today.isoformat(),
        phase=phase,
        phase_label=phase_label,
        proposals_on=friday.isoformat(),
        assignments_on=monday.isoformat(),
        summary=summary,
    )
