"""Historical archive: legislatures, parliamentary rosters and territory history."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.services import symbols
from backend.app.models import (
    ERA_LABELS,
    Chamber,
    HistoricalEra,
    HistoricalParliamentMandate,
    Legislature,
    Municipality,
    PoliticianSourceIdentifier,
    Proposal,
    ProposalStatus,
    Referendum,
    Region,
    TerritorialOffice,
    TerritorialOfficeMandate,
    era_for,
)
from backend.app.schemas.archive import (
    PublicArchiveReferendum,
    PublicEra,
    PublicEraList,
    PublicHistoricalMandate,
    PublicHistoricalMandateList,
    PublicLegislature,
    PublicLegislatureDetail,
    PublicLegislatureLaw,
    PublicOfficeHolder,
    PublicProvince,
    PublicProvinceList,
    PublicTerritoryHistory,
)
from backend.app.services.party_scorecard_service import published_names

LEGISLATURE_FIXTURE = Path(__file__).resolve().parents[3] / "data/fixtures/archive/legislatures.json"
ERA_NOTES = {
    HistoricalEra.COSTITUENTE: "1946–1948. Eletta con il referendum istituzionale, scrisse la Costituzione.",
    HistoricalEra.PRIMA_REPUBBLICA: (
        "Legislature I–XI (1948–1994). \"Prima Repubblica\" è una convenzione giornalistica, "
        "non una categoria istituzionale: la Costituzione è la stessa."
    ),
    HistoricalEra.SECONDA_REPUBBLICA: (
        "Dalla XII legislatura (1994). Anche \"Seconda Repubblica\" è una convenzione: "
        "segna il passaggio al sistema elettorale maggioritario e il nuovo sistema dei partiti."
    ),
}
TERRITORY_COVERAGE = (
    "Contiene solo i record pubblicati da VeraPolitica con fonte ufficiale. Le serie storiche "
    "regionali e provinciali sono frammentate: un elenco breve indica una copertura ancora "
    "parziale, non l'assenza di storia. Dal 2014 (legge 56/2014) i presidenti e i consigli "
    "provinciali non sono più eletti direttamente dai cittadini."
)
_ROMAN = ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
_PERSON = re.compile(r"/persona\.rdf/p(\d+)$")
_DEPUTY = re.compile(r"/deputato\.rdf/d(\d+)_\d+$")


def roman(number: int) -> str:
    out = ""
    for value, symbol in _ROMAN:
        while number >= value:
            out += symbol
            number -= value
    return out


def legislature_label(number: int) -> str:
    return "Assemblea Costituente" if number == 0 else f"{roman(number)} legislatura"


class ArchiveNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ArchiveSync:
    legislatures_upserted: int
    mandates_created: int
    mandates_updated: int
    mandates_unchanged: int
    mandates_linked: int


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class ArchiveService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    # ----------------------------------------------------------------- writes
    @staticmethod
    def _upsert_legislatures(session: Session, records: Iterable[dict[str, Any]]) -> int:
        count = 0
        for record in records:
            row = session.get(Legislature, record["number"])
            values = {
                "start_date": _parse_date(record["start_date"]),
                "end_date": _parse_date(record.get("end_date")),
                "source_url": record["source_url"],
            }
            if row is None:
                session.add(Legislature(number=record["number"], **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            count += 1
        return count

    def load_legislature_fixture(self, path: Path = LEGISLATURE_FIXTURE) -> int:
        records = json.loads(path.read_text(encoding="utf-8"))["records"]
        with self.session_factory.begin() as session:
            existing = {number for (number,) in session.execute(select(Legislature.number))}
            # The fixture only bootstraps; it never overwrites collected rows.
            return self._upsert_legislatures(
                session, [item for item in records if item["number"] not in existing]
            )

    def sync_camera_history(
        self,
        records: list[dict[str, Any]],
        *,
        source_id: int,
        profile_source_id: int,
        raw_document_id: int,
        source_url: str,
    ) -> ArchiveSync:
        """Upsert legislatures and mandates; link mandates to reviewed Camera profiles."""

        legislatures = [item for item in records if item["kind"] == "legislature"]
        mandates = [item for item in records if item["kind"] == "mandate"]
        created = updated = unchanged = linked = 0
        with self.session_factory.begin() as session:
            upserted = self._upsert_legislatures(session, legislatures)
            session.flush()
            known = {number for (number,) in session.execute(select(Legislature.number))}
            missing = {item["legislature"] for item in mandates} - known
            if missing:
                raise ValueError(f"mandates reference unknown legislatures: {sorted(missing)}")

            # Reviewed Camera profiles carry deputy URIs (d<person>_<legislature>);
            # the same person number links every historical mandate.
            people: dict[str, int] = {}
            for identifier in session.scalars(
                select(PoliticianSourceIdentifier).where(
                    PoliticianSourceIdentifier.source_id == profile_source_id
                )
            ):
                match = _DEPUTY.search(identifier.value)
                if match:
                    people[match.group(1)] = identifier.politician_id

            existing = {
                row.official_identifier: row
                for row in session.scalars(
                    select(HistoricalParliamentMandate).where(
                        HistoricalParliamentMandate.source_id == source_id
                    )
                )
            }
            for item in mandates:
                person = _PERSON.search(item["person_identifier"])
                politician_id = people.get(person.group(1)) if person else None
                values = {
                    "chamber": Chamber(item["chamber"]),
                    "legislature": item["legislature"],
                    "person_identifier": item["person_identifier"],
                    "given_name": item["given_name"],
                    "family_name": item["family_name"],
                    "gender": item.get("gender"),
                    "start_date": _parse_date(item.get("start_date")),
                    "end_date": _parse_date(item.get("end_date")),
                    "election_area": item.get("election_area"),
                    "group_name": item.get("group_name"),
                    "source_url": item.get("deputy_identifier") or source_url,
                    "politician_id": politician_id,
                }
                linked += politician_id is not None
                row = existing.get(item["official_identifier"])
                if row is None:
                    session.add(
                        HistoricalParliamentMandate(
                            source_id=source_id,
                            raw_document_id=raw_document_id,
                            official_identifier=item["official_identifier"],
                            **values,
                        )
                    )
                    created += 1
                elif any(getattr(row, key) != value for key, value in values.items()):
                    for key, value in values.items():
                        setattr(row, key, value)
                    row.raw_document_id = raw_document_id
                    updated += 1
                else:
                    unchanged += 1
        return ArchiveSync(upserted, created, updated, unchanged, linked)

    def sync_senato_history(
        self,
        records: list[dict[str, Any]],
        *,
        source_id: int,
        profile_source_id: int,
        raw_document_id: int,
        source_url: str,
    ) -> ArchiveSync:
        """Upsert Senate mandates; link to reviewed Senato profiles by senator URI.

        Does not write TerritorialOfficeMandate rows or invent legislature dates.
        """

        mandates = [item for item in records if item["kind"] == "mandate"]
        created = updated = unchanged = linked = 0
        with self.session_factory.begin() as session:
            known = {number for (number,) in session.execute(select(Legislature.number))}
            missing = {item["legislature"] for item in mandates} - known
            if missing:
                raise ValueError(f"mandates reference unknown legislatures: {sorted(missing)}")

            people = {
                identifier.value: identifier.politician_id
                for identifier in session.scalars(
                    select(PoliticianSourceIdentifier).where(
                        PoliticianSourceIdentifier.source_id == profile_source_id
                    )
                )
            }
            existing = {
                row.official_identifier: row
                for row in session.scalars(
                    select(HistoricalParliamentMandate).where(
                        HistoricalParliamentMandate.source_id == source_id
                    )
                )
            }
            for item in mandates:
                politician_id = people.get(item["person_identifier"])
                values = {
                    "chamber": Chamber(item["chamber"]),
                    "legislature": item["legislature"],
                    "person_identifier": item["person_identifier"],
                    "given_name": item["given_name"],
                    "family_name": item["family_name"],
                    "gender": item.get("gender"),
                    "start_date": _parse_date(item.get("start_date")),
                    "end_date": _parse_date(item.get("end_date")),
                    "election_area": item.get("election_area"),
                    "group_name": item.get("group_name"),
                    "source_url": item["person_identifier"] or source_url,
                    "politician_id": politician_id,
                }
                linked += politician_id is not None
                row = existing.get(item["official_identifier"])
                if row is None:
                    session.add(
                        HistoricalParliamentMandate(
                            source_id=source_id,
                            raw_document_id=raw_document_id,
                            official_identifier=item["official_identifier"],
                            **values,
                        )
                    )
                    created += 1
                elif any(getattr(row, key) != value for key, value in values.items()):
                    for key, value in values.items():
                        setattr(row, key, value)
                    row.raw_document_id = raw_document_id
                    updated += 1
                else:
                    unchanged += 1
        return ArchiveSync(0, created, updated, unchanged, linked)

    # ------------------------------------------------------------------ reads
    @staticmethod
    def _counts(session: Session) -> dict[tuple[int, Chamber], int]:
        return {
            (number, chamber): count
            for number, chamber, count in session.execute(
                select(
                    HistoricalParliamentMandate.legislature,
                    HistoricalParliamentMandate.chamber,
                    func.count(HistoricalParliamentMandate.id),
                ).group_by(HistoricalParliamentMandate.legislature, HistoricalParliamentMandate.chamber)
            )
        }

    @staticmethod
    def _public(row: Legislature, counts: dict[tuple[int, Chamber], int]) -> PublicLegislature:
        era = era_for(row.number)
        return PublicLegislature(
            number=row.number,
            label=legislature_label(row.number),
            roman=roman(row.number) if row.number else "AC",
            era=era,
            era_label=ERA_LABELS[era],
            start_date=row.start_date,
            end_date=row.end_date,
            source_url=row.source_url,
            camera_mandates=counts.get((row.number, Chamber.CAMERA), 0),
            senato_mandates=counts.get((row.number, Chamber.SENATO), 0),
        )

    def eras(self) -> PublicEraList:
        with self.session_factory() as session:
            counts = self._counts(session)
            rows = list(session.scalars(select(Legislature).order_by(Legislature.number)))
        grouped: dict[HistoricalEra, list[PublicLegislature]] = {era: [] for era in HistoricalEra}
        for row in rows:
            item = self._public(row, counts)
            grouped[item.era].append(item)
        return PublicEraList(
            eras=tuple(
                PublicEra(era=era, label=ERA_LABELS[era], note=ERA_NOTES[era], legislatures=tuple(items))
                for era, items in grouped.items()
                if items
            )
        )

    @staticmethod
    def _referendums(session: Session, *filters) -> tuple[PublicArchiveReferendum, ...]:
        return tuple(
            PublicArchiveReferendum(
                id=row.id, title=row.title, vote_date=row.vote_date, scope_type=row.scope_type.value
            )
            for row in session.scalars(
                select(Referendum)
                .where(Referendum.published_at.is_not(None), *filters)
                .order_by(Referendum.vote_date, Referendum.id)
            )
        )

    def legislature(self, number: int) -> PublicLegislatureDetail:
        with self.session_factory() as session:
            row = session.get(Legislature, number)
            if row is None:
                raise ArchiveNotFoundError("legislature not found")
            counts = self._counts(session)
            numbers = [n for (n,) in session.execute(select(Legislature.number).order_by(Legislature.number))]
            position = numbers.index(number)
            end = row.end_date or date.max
            in_term = (
                Proposal.published_at.is_not(None),
                Proposal.introduced_at >= row.start_date,
                Proposal.introduced_at <= end,
            )
            proposals = session.scalar(select(func.count(Proposal.id)).where(*in_term)) or 0
            enacted = tuple(
                PublicLegislatureLaw(
                    id=item.id,
                    title=item.title,
                    status=item.current_status.value if item.current_status else "enacted",
                    introduced_at=item.introduced_at,
                )
                for item in session.scalars(
                    select(Proposal)
                    .where(*in_term, Proposal.current_status == ProposalStatus.ENACTED)
                    .order_by(Proposal.introduced_at, Proposal.id)
                    .limit(12)
                )
            )
            return PublicLegislatureDetail(
                legislature=self._public(row, counts),
                previous=numbers[position - 1] if position > 0 else None,
                next=numbers[position + 1] if position + 1 < len(numbers) else None,
                referendums=self._referendums(
                    session, Referendum.vote_date >= row.start_date, Referendum.vote_date <= end
                ),
                published_proposals=proposals,
                enacted_laws=enacted,
            )

    def mandates(
        self,
        *,
        legislature: int | None = None,
        chamber: Chamber | None = None,
        query: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> PublicHistoricalMandateList:
        filters = []
        if legislature is not None:
            filters.append(HistoricalParliamentMandate.legislature == legislature)
        if chamber is not None:
            filters.append(HistoricalParliamentMandate.chamber == chamber)
        if query:
            for token in query.casefold().split()[:5]:
                like = f"%{token}%"
                filters.append(
                    or_(
                        func.lower(HistoricalParliamentMandate.family_name).like(like),
                        func.lower(HistoricalParliamentMandate.given_name).like(like),
                    )
                )
        with self.session_factory() as session:
            total = session.scalar(
                select(func.count(HistoricalParliamentMandate.id)).where(*filters)
            ) or 0
            rows = list(
                session.scalars(
                    select(HistoricalParliamentMandate)
                    .where(*filters)
                    .order_by(
                        HistoricalParliamentMandate.family_name,
                        HistoricalParliamentMandate.given_name,
                        HistoricalParliamentMandate.legislature,
                        HistoricalParliamentMandate.id,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            # Link only to profiles that are published.
            visible = published_names(
                session, {row.politician_id for row in rows if row.politician_id}
            )
        return PublicHistoricalMandateList(
            items=tuple(
                PublicHistoricalMandate(
                    id=row.id,
                    chamber=row.chamber,
                    legislature=row.legislature,
                    given_name=row.given_name,
                    family_name=row.family_name,
                    start_date=row.start_date,
                    end_date=row.end_date,
                    election_area=row.election_area,
                    group_name=row.group_name,
                    source_url=row.source_url,
                    politician_id=row.politician_id if row.politician_id in visible else None,
                )
                for row in rows
            ),
            total=total,
            offset=offset,
            limit=limit,
        )

    def provinces(self, *, region_id: int | None = None) -> PublicProvinceList:
        with self.session_factory() as session:
            query = (
                select(
                    Municipality.province_abbreviation,
                    func.min(Municipality.province_name),
                    Municipality.region_id,
                    func.count(Municipality.id),
                )
                .group_by(Municipality.province_abbreviation, Municipality.region_id)
                .order_by(func.min(Municipality.province_name))
            )
            if region_id is not None:
                query = query.where(Municipality.region_id == region_id)
            regions = {row.id: row.canonical_name for row in session.scalars(select(Region))}
            logos = symbols.logo_urls(session, "province")
            items = tuple(
                PublicProvince(
                    abbreviation=abbreviation,
                    name=name,
                    region_id=parent,
                    region_name=regions.get(parent, ""),
                    municipalities=count,
                    logo_url=logos.get(abbreviation),
                )
                for abbreviation, name, parent, count in session.execute(query)
            )
        return PublicProvinceList(items=items, total=len(items))

    @staticmethod
    def _holders(session: Session, rows: list[TerritorialOfficeMandate]) -> tuple[PublicOfficeHolder, ...]:
        names = published_names(session, {row.politician_id for row in rows})
        holders = []
        for row in rows:
            if row.politician_id not in names:
                continue
            territory = row.region if row.office is TerritorialOffice.REGIONAL_PRESIDENT else row.municipality
            holders.append(
                PublicOfficeHolder(
                    politician_id=row.politician_id,
                    name=names[row.politician_id],
                    office=row.office.value,
                    territory_id=territory.id,
                    territory_name=territory.canonical_name,
                    start_date=row.start_date,
                    end_date=row.end_date,
                    source_url=row.source_url,
                )
            )
        holders.sort(key=lambda item: (item.start_date or date.min, item.territory_name))
        return tuple(holders)

    def region_history(self, region_id: int) -> PublicTerritoryHistory:
        with self.session_factory() as session:
            region = session.get(Region, region_id)
            if region is None:
                raise ArchiveNotFoundError("region not found")
            rows = list(
                session.scalars(
                    select(TerritorialOfficeMandate).where(
                        TerritorialOfficeMandate.region_id == region_id,
                        TerritorialOfficeMandate.office == TerritorialOffice.REGIONAL_PRESIDENT,
                    )
                )
            )
            municipalities = select(Municipality.id).where(Municipality.region_id == region_id)
            return PublicTerritoryHistory(
                kind="region",
                name=region.canonical_name,
                region_id=region.id,
                office_holders=self._holders(session, rows),
                referendums=self._referendums(
                    session,
                    or_(
                        Referendum.region_id == region_id,
                        Referendum.municipality_id.in_(municipalities),
                    ),
                ),
                coverage_note=TERRITORY_COVERAGE,
            )

    def province_history(self, abbreviation: str) -> PublicTerritoryHistory:
        with self.session_factory() as session:
            first = session.scalar(
                select(Municipality).where(Municipality.province_abbreviation == abbreviation).limit(1)
            )
            if first is None:
                raise ArchiveNotFoundError("province not found")
            municipalities = select(Municipality.id).where(
                Municipality.province_abbreviation == abbreviation
            )
            rows = list(
                session.scalars(
                    select(TerritorialOfficeMandate).where(
                        TerritorialOfficeMandate.municipality_id.in_(municipalities),
                        TerritorialOfficeMandate.office == TerritorialOffice.MAYOR,
                    )
                )
            )
            return PublicTerritoryHistory(
                kind="province",
                name=first.province_name,
                region_id=first.region_id,
                province_abbreviation=abbreviation,
                office_holders=self._holders(session, rows),
                referendums=self._referendums(session, Referendum.municipality_id.in_(municipalities)),
                coverage_note=TERRITORY_COVERAGE,
            )
