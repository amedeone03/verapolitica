from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, and_, cast, exists, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from backend.app.core.text import escape_like, normalize_search_text, search_tokens
from backend.app.models import (
    Municipality,
    ParliamentaryGroup,
    PoliticalParty,
    Politician,
    PoliticianVersion,
    PoliticianVersionCitation,
    Proposal,
    ProposalActor,
    Region,
    TerritorialOffice,
    TerritorialOfficeMandate,
)
from backend.app.schemas.search import (
    PublicSearchResult,
    PublicSearchResultList,
    SearchEntityType,
)
from backend.app.services.public_territory_service import PublicTerritoryQueryService


MAX_QUERY_LENGTH = 200
MAX_LIMIT = 50
DEFAULT_LIMIT = 20
PER_TYPE_CAP = 80
SNIPPET_CHARS = 180
ENTITY_ORDER = {
    SearchEntityType.POLITICIAN: 0,
    SearchEntityType.PROPOSAL: 1,
    SearchEntityType.MUNICIPALITY: 2,
    SearchEntityType.REGION: 3,
    SearchEntityType.PARLIAMENTARY_GROUP: 4,
    SearchEntityType.POLITICAL_PARTY: 5,
}
TIER_EXACT = 0
TIER_PREFIX = 1
TIER_TOKEN = 2
TIER_FUZZY = 3
FUZZY_THRESHOLD = 0.42


class SearchValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _Hit:
    tier: int
    title: str
    entity_type: SearchEntityType
    entity_id: int
    result: PublicSearchResult


class SearchService:
    """Public, read-only, dialect-aware citizen search."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.dialect = session.get_bind().dialect.name

    def search(
        self,
        query: str,
        *,
        entity_type: SearchEntityType | None = None,
        offset: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> PublicSearchResultList:
        raw = query.strip()
        if not raw:
            raise SearchValidationError("query is required")
        if len(query) > MAX_QUERY_LENGTH:
            raise SearchValidationError(
                f"query must be at most {MAX_QUERY_LENGTH} characters"
            )
        if offset < 0:
            raise SearchValidationError("offset must be zero or greater")
        if limit < 1 or limit > MAX_LIMIT:
            raise SearchValidationError(f"limit must be between 1 and {MAX_LIMIT}")
        normalized = normalize_search_text(raw)
        if not normalized:
            raise SearchValidationError("query is required")
        types = (entity_type,) if entity_type is not None else tuple(SearchEntityType)
        hits: list[_Hit] = []
        for item_type in types:
            hits.extend(self._search_type(item_type, normalized, limited=entity_type is not None))
        hits.sort(
            key=lambda item: (
                item.tier,
                item.title.casefold(),
                ENTITY_ORDER[item.entity_type],
                item.entity_id,
            )
        )
        total = len(hits)
        page = hits[offset : offset + limit]
        return PublicSearchResultList(
            query=raw,
            normalized_query=normalized,
            entity_type=entity_type,
            items=tuple(item.result for item in page),
            total=total,
            offset=offset,
            limit=limit,
        )

    def _search_type(
        self, entity_type: SearchEntityType, normalized: str, *, limited: bool
    ) -> list[_Hit]:
        searchers = {
            SearchEntityType.POLITICIAN: self._politicians,
            SearchEntityType.PROPOSAL: self._proposals,
            SearchEntityType.MUNICIPALITY: self._municipalities,
            SearchEntityType.REGION: self._regions,
            SearchEntityType.PARLIAMENTARY_GROUP: self._groups,
            SearchEntityType.POLITICAL_PARTY: self._parties,
        }
        return searchers[entity_type](normalized, limited=limited)

    def _politicians(self, normalized: str, *, limited: bool) -> list[_Hit]:
        visible = (
            select(Politician, PoliticianVersion)
            .join(
                PoliticianVersion,
                (PoliticianVersion.id == Politician.current_version_id)
                & (PoliticianVersion.politician_id == Politician.id),
            )
            .where(
                Politician.current_version_id.is_not(None),
                PoliticianVersion.published_at.is_not(None),
                self._politician_match(normalized),
            )
            .limit(self._cap(limited))
        )
        rows = list(self.session.execute(visible))
        if not rows:
            return []
        version_ids = [version.id for _politician, version in rows]
        citation_counts = dict(
            self.session.execute(
                select(
                    PoliticianVersionCitation.politician_version_id,
                    func.count(PoliticianVersionCitation.id),
                )
                .where(PoliticianVersionCitation.politician_version_id.in_(version_ids))
                .group_by(PoliticianVersionCitation.politician_version_id)
            ).all()
        )
        hits: list[_Hit] = []
        for politician, version in rows:
            title = f"{politician.canonical_given_name} {politician.canonical_family_name}".strip()
            profile = version.profile_data if isinstance(version.profile_data, dict) else {}
            mandates = profile.get("mandates") or []
            mandate = mandates[0] if mandates else {}
            office = str(mandate.get("office") or "").replace("_", " ")
            institution = str(mandate.get("institution") or "")
            area = str(mandate.get("election_area") or "")
            subtitle = " · ".join(part for part in (office.title() if office else "", institution, area) if part) or "Published representative"
            family = normalize_search_text(politician.canonical_family_name)
            given = normalize_search_text(politician.canonical_given_name)
            primary = politician.normalized_name
            document = normalize_search_text(
                " ".join(
                    (
                        primary,
                        family,
                        given,
                        office,
                        institution,
                        area,
                        str(profile.get("profession") or ""),
                    )
                )
            )
            tier = self._tier(normalized, primary, document, extra_exact=(family, given))
            hits.append(
                _Hit(
                    tier,
                    title,
                    SearchEntityType.POLITICIAN,
                    politician.id,
                    PublicSearchResult(
                        entity_type=SearchEntityType.POLITICIAN,
                        title=title,
                        subtitle=subtitle,
                        url=f"/app/?politician={politician.id}",
                        metadata={
                            "id": politician.id,
                            "office": office or None,
                            "institution": institution or None,
                            "citation_count": citation_counts.get(version.id, 0),
                        },
                    ),
                )
            )
        return hits

    def _politician_match(self, normalized: str) -> ColumnElement[bool]:
        tokens = search_tokens(normalized) or (normalized,)
        profile_text = cast(PoliticianVersion.profile_data, String)
        territorial = exists(
            select(TerritorialOfficeMandate.id)
            .outerjoin(Municipality, Municipality.id == TerritorialOfficeMandate.municipality_id)
            .outerjoin(Region, Region.id == TerritorialOfficeMandate.region_id)
            .where(
                TerritorialOfficeMandate.politician_id == Politician.id,
                or_(
                    self._document_contains(Municipality.search_document, tokens),
                    self._document_contains(Region.search_document, tokens),
                    self._document_contains(Municipality.search_primary, tokens),
                    self._document_contains(Region.search_primary, tokens),
                ),
            )
        )
        return or_(
            self._text_match(Politician.normalized_name, Politician.normalized_name, normalized),
            self._document_contains(profile_text, tokens),
            territorial,
        )

    def _proposals(self, normalized: str, *, limited: bool) -> list[_Hit]:
        tokens = search_tokens(normalized) or (normalized,)
        actor_match = exists(
            select(ProposalActor.id).where(
                ProposalActor.proposal_id == Proposal.id,
                self._text_match(
                    ProposalActor.search_primary,
                    ProposalActor.search_primary,
                    normalized,
                ),
            )
        )
        query = (
            select(Proposal)
            .where(
                Proposal.published_at.is_not(None),
                or_(
                    self._text_match(
                        Proposal.search_primary, Proposal.search_document, normalized
                    ),
                    actor_match,
                    self._document_contains(Proposal.search_document, tokens),
                ),
            )
            .limit(self._cap(limited))
        )
        proposals = list(self.session.scalars(query))
        if not proposals:
            return []
        actors_by_proposal: dict[int, list[str]] = {}
        for actor in self.session.scalars(
            select(ProposalActor).where(
                ProposalActor.proposal_id.in_([item.id for item in proposals])
            )
        ):
            actors_by_proposal.setdefault(actor.proposal_id, []).append(actor.display_name)
        hits: list[_Hit] = []
        for proposal in proposals:
            actors = actors_by_proposal.get(proposal.id, [])
            document = normalize_search_text(
                " ".join(
                    (
                        proposal.search_document,
                        *actors,
                    )
                )
            )
            snippet = self._snippet(proposal.summary or proposal.exact_statement)
            hits.append(
                _Hit(
                    self._tier(normalized, proposal.search_primary, document),
                    proposal.canonical_title,
                    SearchEntityType.PROPOSAL,
                    proposal.id,
                    PublicSearchResult(
                        entity_type=SearchEntityType.PROPOSAL,
                        title=proposal.canonical_title,
                        subtitle=self._proposal_subtitle(proposal, actors),
                        url=f"/app/?proposal={proposal.id}",
                        snippet=snippet,
                        metadata={
                            "id": proposal.id,
                            "status": proposal.current_status.value
                            if proposal.current_status
                            else None,
                            "proposal_type": proposal.proposal_type.value,
                            "actors": actors[:4],
                        },
                    ),
                )
            )
        return hits

    def _municipalities(self, normalized: str, *, limited: bool) -> list[_Hit]:
        query = (
            select(Municipality, Region)
            .join(Region, Region.id == Municipality.region_id)
            .where(
                self._text_match(
                    Municipality.search_primary,
                    Municipality.search_document,
                    normalized,
                )
            )
            .order_by(Municipality.search_primary, Municipality.id)
            .limit(self._cap(limited))
        )
        rows = list(self.session.execute(query))
        mayors = PublicTerritoryQueryService(self.session)._current_holders(
            TerritorialOffice.MAYOR,
            municipality_ids=tuple(municipality.id for municipality, _region in rows),
        )
        hits: list[_Hit] = []
        for municipality, region in rows:
            mayor = mayors.get(municipality.id)
            mayor_name = (
                f"{mayor.given_name} {mayor.family_name}".strip() if mayor else None
            )
            subtitle = f"{region.canonical_name} · {municipality.province_abbreviation}"
            if mayor_name:
                subtitle = f"{subtitle} · Mayor {mayor_name}"
            hits.append(
                _Hit(
                    self._tier(
                        normalized,
                        municipality.search_primary,
                        municipality.search_document,
                    ),
                    municipality.canonical_name,
                    SearchEntityType.MUNICIPALITY,
                    municipality.id,
                    PublicSearchResult(
                        entity_type=SearchEntityType.MUNICIPALITY,
                        title=municipality.canonical_name,
                        subtitle=subtitle,
                        url=f"/app/?municipality={municipality.id}",
                        metadata={
                            "id": municipality.id,
                            "region": region.canonical_name,
                            "province": municipality.province_abbreviation,
                            "mayor": mayor_name,
                        },
                    ),
                )
            )
        return hits

    def _regions(self, normalized: str, *, limited: bool) -> list[_Hit]:
        regions = list(
            self.session.scalars(
                select(Region)
                .where(
                    self._text_match(
                        Region.search_primary, Region.search_document, normalized
                    )
                )
                .order_by(Region.search_primary, Region.id)
                .limit(self._cap(limited))
            )
        )
        presidents = PublicTerritoryQueryService(self.session)._current_holders(
            TerritorialOffice.REGIONAL_PRESIDENT,
            region_ids=tuple(region.id for region in regions),
        )
        hits: list[_Hit] = []
        for region in regions:
            president = presidents.get(region.id)
            president_name = (
                f"{president.given_name} {president.family_name}".strip()
                if president
                else None
            )
            subtitle = "Italian region"
            if president_name:
                subtitle = f"Italian region · President {president_name}"
            hits.append(
                _Hit(
                    self._tier(normalized, region.search_primary, region.search_document),
                    region.canonical_name,
                    SearchEntityType.REGION,
                    region.id,
                    PublicSearchResult(
                        entity_type=SearchEntityType.REGION,
                        title=region.canonical_name,
                        subtitle=subtitle,
                        url=f"/app/?region={region.id}",
                        metadata={
                            "id": region.id,
                            "president": president_name,
                        },
                    ),
                )
            )
        return hits

    def _groups(self, normalized: str, *, limited: bool) -> list[_Hit]:
        groups = list(
            self.session.scalars(
                select(ParliamentaryGroup)
                .where(
                    self._text_match(
                        ParliamentaryGroup.search_primary,
                        ParliamentaryGroup.search_document,
                        normalized,
                    )
                )
                .limit(self._cap(limited))
            )
        )
        return [
            _Hit(
                self._tier(normalized, group.search_primary, group.search_document),
                group.canonical_name,
                SearchEntityType.PARLIAMENTARY_GROUP,
                group.id,
                PublicSearchResult(
                    entity_type=SearchEntityType.PARLIAMENTARY_GROUP,
                    title=group.canonical_name,
                    subtitle=(
                        f"Parliamentary group · {group.institution} · "
                        f"{group.legislature} legislature"
                    ),
                    url=f"/app/?parliamentary_group={group.id}",
                    metadata={
                        "id": group.id,
                        "abbreviation": group.abbreviation,
                        "institution": group.institution,
                        "legislature": group.legislature,
                    },
                ),
            )
            for group in groups
        ]

    def _parties(self, normalized: str, *, limited: bool) -> list[_Hit]:
        parties = list(
            self.session.scalars(
                select(PoliticalParty)
                .where(
                    self._text_match(
                        PoliticalParty.search_primary,
                        PoliticalParty.search_document,
                        normalized,
                    )
                )
                .limit(self._cap(limited))
            )
        )
        return [
            _Hit(
                self._tier(normalized, party.search_primary, party.search_document),
                party.canonical_name,
                SearchEntityType.POLITICAL_PARTY,
                party.id,
                PublicSearchResult(
                    entity_type=SearchEntityType.POLITICAL_PARTY,
                    title=party.canonical_name,
                    subtitle="Political party"
                    + (f" · {party.abbreviation}" if party.abbreviation else ""),
                    url=f"/app/?political_party={party.id}",
                    metadata={
                        "id": party.id,
                        "abbreviation": party.abbreviation,
                    },
                ),
            )
            for party in parties
        ]

    def _text_match(
        self, primary: Any, document: Any, normalized: str
    ) -> ColumnElement[bool]:
        tokens = search_tokens(normalized)
        clauses = [
            primary == normalized,
            self._like(primary, f"{escape_like(normalized)}%"),
            self._document_contains(document, tokens or (normalized,)),
        ]
        if self.dialect == "postgresql" and len(normalized) >= 4:
            clauses.append(func.similarity(primary, normalized) >= FUZZY_THRESHOLD)
        return or_(*clauses)

    def _document_contains(self, column: Any, tokens: tuple[str, ...]) -> ColumnElement[bool]:
        return and_(
            *(self._like(column, f"%{escape_like(token)}%") for token in tokens)
        )

    def _like(self, column: Any, pattern: str) -> ColumnElement[bool]:
        if self.dialect == "postgresql":
            return column.ilike(pattern, escape="\\")
        return column.like(pattern, escape="\\")

    def _tier(
        self,
        normalized: str,
        primary: str,
        document: str,
        extra_exact: tuple[str, ...] = (),
    ) -> int:
        if primary == normalized or normalized in extra_exact:
            return TIER_EXACT
        if primary.startswith(normalized) or any(
            value.startswith(normalized) for value in extra_exact if value
        ):
            return TIER_PREFIX
        tokens = search_tokens(normalized) or (normalized,)
        if all(token in document.split() or token in document for token in tokens):
            if all(token in document.split() for token in tokens) or all(
                token in document for token in tokens
            ):
                return TIER_TOKEN
        if self.dialect == "postgresql" and len(normalized) >= 4:
            return TIER_FUZZY
        return TIER_TOKEN

    def _cap(self, limited: bool) -> int:
        return 250 if limited else PER_TYPE_CAP

    @staticmethod
    def _snippet(value: str | None) -> str | None:
        if not value:
            return None
        compact = " ".join(value.split())
        if len(compact) <= SNIPPET_CHARS:
            return compact
        return compact[: SNIPPET_CHARS - 1].rsplit(" ", 1)[0] + "…"

    @staticmethod
    def _proposal_subtitle(proposal: Proposal, actors: list[str]) -> str:
        kind = proposal.proposal_type.value.replace("_", " ")
        status = (
            proposal.current_status.value.replace("_", " ")
            if proposal.current_status
            else "published"
        )
        actor_summary = ", ".join(actors[:3]) if actors else "No public actors"
        return f"{kind} · {status} · {actor_summary}"
