from datetime import date, datetime, time
from typing import Any

from backend.app.models.civic import (
    GeographicScopeType,
    ReferendumStatus,
    ReferendumType,
)
from backend.app.schemas.civic import (
    ReferendumEvidenceObservation,
    ReferendumObservation,
)


class CivicFixtureMapperError(ValueError):
    pass


def map_referendum_fixture(
    record: dict[str, Any],
    *,
    source_key: str,
    raw_document_id: int,
    observed_at: datetime,
) -> ReferendumObservation:
    """Map a curated official-like JSON record to a ReferendumObservation.

    This is the editorial/manual ingestion contract. There is no live Eligendo
    HTML scraper: Ministry pages are HTML/PDF-first and eleapi.interno.gov.it
    is an undocumented browser API.
    """
    try:
        evidence_rows = record["evidence"]
        evidence = tuple(
            ReferendumEvidenceObservation(
                field_path=item["field_path"],
                source_url=item["source_url"],
                source_field=item["source_field"],
                source_value=item["source_value"],
            )
            for item in evidence_rows
        )
        return ReferendumObservation(
            source_key=source_key,
            raw_document_id=raw_document_id,
            official_identifier=record["official_identifier"],
            title=record["title"],
            official_question=record["official_question"],
            referendum_type=ReferendumType(record["referendum_type"]),
            status=ReferendumStatus(record["status"]),
            vote_date=date.fromisoformat(record["vote_date"]),
            vote_end_date=(
                date.fromisoformat(record["vote_end_date"])
                if record.get("vote_end_date")
                else None
            ),
            start_time=_parse_time(record.get("start_time")),
            end_time=_parse_time(record.get("end_time")),
            voting_hours_description=record.get("voting_hours_description"),
            scope_type=GeographicScopeType(record["scope_type"]),
            region_istat_code=record.get("region_istat_code"),
            municipality_istat_code=record.get("municipality_istat_code"),
            quorum_required=record.get("quorum_required"),
            quorum_description=record.get("quorum_description"),
            official_source_url=record["official_source_url"],
            is_synthetic=bool(record.get("is_synthetic", False)),
            observed_at=observed_at,
            evidence=evidence,
            metadata=dict(record.get("metadata") or {}),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CivicFixtureMapperError(f"invalid referendum fixture: {exc}") from exc


def _parse_time(value: str | None) -> time | None:
    if not value:
        return None
    hour, minute, *rest = value.split(":")
    second = int(rest[0]) if rest else 0
    return time(int(hour), int(minute), second)
