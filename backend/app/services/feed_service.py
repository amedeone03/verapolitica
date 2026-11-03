"""Home feed: verified facts already published by VeraPolitica, newest first.

The feed is not a news wire. Every item is a record that went through review
elsewhere in the system:

* a status change of a published proposal (official parliamentary source);
* a published pledge verdict (verbatim official excerpt, human approval);
* a published referendum;
* a newsroom post approved by someone other than its author.

Proposals and pledge verdicts are national. Referendums and newsroom posts carry
their own territory. With a zone (the reader's municipality, province or
region) the "all" filter shows national items plus the items of that zone; it
never shows another region's local items.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    PoliticalParty,
    PoliticalPartyAffiliation,
    ProposalActor,
    ProposalActorRole,
    ProposalActorType,
    EditorialPost,
    EditorialPostStatus,
    FeedScope,
    GeographicScopeType,
    Municipality,
    PledgeAssessment,
    Proposal,
    ProposalStatusEvent,
    Referendum,
    Region,
)
from backend.app.services.redazione import card as card_module
from backend.app.schemas.feed import FeedFilter, FeedItem, FeedItemKind, FeedPage, FeedSource

PROPOSAL_STATUS_IT = {
    "announced": "annunciata",
    "introduced": "presentata",
    "assigned": "assegnata in commissione",
    "under_review": "in esame",
    "approved": "approvata",
    "rejected": "respinta",
    "withdrawn": "ritirata",
    "enacted": "promulgata",
    "completed": "conclusa",
    "superseded": "superata",
    "lapsed": "decaduta",
    "returned": "rinviata",
}
VERDICT_IT = {
    "kept": "mantenuta",
    "partially_kept": "mantenuta parzialmente",
    "in_progress": "in corso",
    "stalled": "con iter bloccato",
    "broken": "non mantenuta",
    "not_yet_rated": "non ancora valutata",
}


TYPE_LABELS = {
    "proposal": "Proposta",
    "legislative_proposal": "Proposta di legge",
    "government_initiative": "Disegno di legge del Governo",
    "explicit_promise": "Promessa",
}
# Four steps of the legislative path, like a progress strip on the card.
STAGE_STEPS = (
    ("presentata", "Presentata"),
    ("esame", "In esame"),
    ("approvata", "Approvata"),
    ("legge", "Legge"),
)
STAGE_OF_STATUS = {
    "announced": 0, "introduced": 0, "assigned": 1, "under_review": 1, "returned": 1,
    "approved": 2, "enacted": 3, "completed": 3,
    "rejected": 1, "withdrawn": 0, "lapsed": 1, "superseded": 1,
}
STOPPED_STATUSES = {"rejected", "withdrawn", "lapsed", "superseded"}


def stage_for(status: str | None) -> dict | None:
    if status is None or status not in STAGE_OF_STATUS:
        return None
    current = STAGE_OF_STATUS[status]
    stopped = status in STOPPED_STATUSES
    steps = []
    for index, (key, label) in enumerate(STAGE_STEPS):
        if index < current or (index == current and status in {"enacted", "completed"}):
            state = "done"
        elif index == current:
            state = "stopped" if stopped else "current"
        else:
            state = "todo"
        steps.append({"key": key, "label": label, "state": state})
    return {"steps": steps, "stopped": stopped}


class FeedValidationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Zone:
    region_id: int | None = None
    province: str | None = None
    municipality_id: int | None = None

    @property
    def empty(self) -> bool:
        return self.region_id is None and self.province is None and self.municipality_id is None


class FeedService:
    def __init__(self, session: Session, *, public_names: frozenset[str] = frozenset()) -> None:
        self.session = session
        self.public_names = public_names
        self._regions: dict[int, str] | None = None

    # ------------------------------------------------------------------ zone
    def resolve_zone(
        self,
        *,
        region_id: int | None = None,
        province: str | None = None,
        municipality_id: int | None = None,
    ) -> Zone:
        if municipality_id is not None:
            municipality = self.session.get(Municipality, municipality_id)
            if municipality is None:
                raise FeedValidationError("municipality not found")
            return Zone(municipality.region_id, municipality.province_abbreviation, municipality.id)
        if province is not None:
            parent = self.session.scalar(
                select(Municipality.region_id)
                .where(Municipality.province_abbreviation == province)
                .limit(1)
            )
            if parent is None:
                raise FeedValidationError("province not found")
            return Zone(parent, province, None)
        if region_id is not None and self.session.get(Region, region_id) is None:
            raise FeedValidationError("region not found")
        return Zone(region_id, None, None)

    @staticmethod
    def _accepts(feed_filter: FeedFilter, zone: Zone, item: FeedItem) -> bool:
        if feed_filter is FeedFilter.NATIONAL:
            return item.scope is FeedScope.NATIONAL
        if feed_filter is not FeedFilter.ALL and item.scope.value != feed_filter.value:
            return False
        if item.scope is FeedScope.NATIONAL or zone.empty:
            return True
        # A local item is shown when it lies inside the most precise level of
        # the reader's zone that is at or above the item's own level.
        if item.scope is FeedScope.REGION:
            return zone.region_id is None or item.region_id == zone.region_id
        if item.scope is FeedScope.PROVINCE:
            if zone.province is not None:
                return item.province_abbreviation == zone.province
            return zone.region_id is None or item.region_id == zone.region_id
        if zone.municipality_id is not None:
            return item.municipality_id == zone.municipality_id
        if zone.province is not None:
            return item.province_abbreviation == zone.province
        return zone.region_id is None or item.region_id == zone.region_id

    # --------------------------------------------------------------- sources
    def _region_name(self, region_id: int | None) -> str | None:
        if region_id is None:
            return None
        if self._regions is None:
            self._regions = {
                row.id: row.canonical_name for row in self.session.scalars(select(Region))
            }
        return self._regions.get(region_id)

    def _proposal_events(self, cap: int) -> list[FeedItem]:
        rows = self.session.execute(
            select(ProposalStatusEvent, Proposal)
            .join(Proposal, Proposal.id == ProposalStatusEvent.proposal_id)
            # Only dated facts: an event without an official date would show the import date.
            .where(Proposal.published_at.is_not(None), ProposalStatusEvent.effective_at.is_not(None))
            .order_by(ProposalStatusEvent.effective_at.desc(), ProposalStatusEvent.id.desc())
            .limit(cap)
        )
        rows = list(rows)
        actors = self._actors([proposal.id for _event, proposal in rows])
        items = []
        for event, proposal in rows:
            status = event.normalized_status.value
            items.append(
                FeedItem(
                    key=f"proposal-status-{event.id}",
                    kind=FeedItemKind.PROPOSAL_STATUS,
                    occurred_on=event.effective_at,
                    title=proposal.canonical_title,
                    detail=f"Proposta {PROPOSAL_STATUS_IT.get(status, status)}: {event.source_status_label}",
                    url=f"./?proposal={proposal.id}",
                    scope=FeedScope.NATIONAL,
                    sources=(FeedSource(title="Fonte ufficiale", url=event.source_url),),
                    label=status,
                    card={
                        "type_label": TYPE_LABELS.get(proposal.proposal_type.value, "Proposta"),
                        "badge": "Nuovo passaggio",
                        "actors": actors.get(proposal.id, {}).get("people", []),
                        "institution": actors.get(proposal.id, {}).get("institution"),
                        "summary": proposal.summary or proposal.exact_statement,
                        "stage": stage_for(status),
                        "stage_label": f"{PROPOSAL_STATUS_IT.get(status, status).capitalize()} · {event.source_status_label}",
                        "since_label": "Presentata il" if proposal.introduced_at else None,
                        "since": proposal.introduced_at.isoformat() if proposal.introduced_at else None,
                    },
                )
            )
        return items

    def _actors(self, proposal_ids: list[int]) -> dict[int, dict]:
        """People (with their current party) and institution behind each proposal."""

        if not proposal_ids:
            return {}
        result: dict[int, dict] = {}
        rows = self.session.scalars(
            select(ProposalActor)
            .where(ProposalActor.proposal_id.in_(proposal_ids))
            .order_by(ProposalActor.proposal_id, ProposalActor.id)
        ).all()
        politician_ids = {row.politician_id for row in rows if row.politician_id}
        parties: dict[int, str] = {}
        if politician_ids:
            for affiliation, party in self.session.execute(
                select(PoliticalPartyAffiliation, PoliticalParty)
                .join(PoliticalParty, PoliticalParty.id == PoliticalPartyAffiliation.political_party_id)
                .where(
                    PoliticalPartyAffiliation.politician_id.in_(politician_ids),
                    PoliticalPartyAffiliation.end_date.is_(None),
                )
            ):
                parties.setdefault(affiliation.politician_id, party.abbreviation or party.canonical_name)
        roles = {
            ProposalActorRole.PROPOSER, ProposalActorRole.SPONSOR, ProposalActorRole.GOVERNMENT,
            ProposalActorRole.COMMITMENT_OWNER, ProposalActorRole.CO_SPONSOR,
        }
        for row in rows:
            entry = result.setdefault(row.proposal_id, {"people": [], "institution": None})
            if row.role not in roles:
                continue
            if row.actor_type is ProposalActorType.INSTITUTION:
                entry["institution"] = entry["institution"] or row.institution_name or row.display_name
            elif row.actor_type is ProposalActorType.POLITICIAN and len(entry["people"]) < 3:
                if any(person["name"] == row.display_name for person in entry["people"]):
                    continue
                entry["people"].append(
                    {
                        "name": row.display_name,
                        "politician_id": row.politician_id,
                        "party": parties.get(row.politician_id) if row.politician_id else None,
                    }
                )
        return result

    def _pledge_verdicts(self, cap: int) -> list[FeedItem]:
        rows = list(self.session.execute(
            select(PledgeAssessment, Proposal)
            .join(Proposal, Proposal.id == PledgeAssessment.proposal_id)
            .where(Proposal.published_at.is_not(None))
            .order_by(PledgeAssessment.created_at.desc(), PledgeAssessment.id.desc())
            .limit(cap)
        ))
        actors = self._actors([proposal.id for _assessment, proposal in rows])
        return [
            FeedItem(
                key=f"pledge-verdict-{assessment.id}",
                kind=FeedItemKind.PLEDGE_VERDICT,
                occurred_on=assessment.created_at.date(),
                title=proposal.canonical_title,
                detail=f"Promessa valutata: {VERDICT_IT.get(assessment.verdict.value, assessment.verdict.value)}",
                url=f"./?proposal={proposal.id}",
                scope=FeedScope.NATIONAL,
                sources=(FeedSource(title="Atto ufficiale citato", url=assessment.source_url),),
                label=assessment.verdict.value,
                card={
                    "type_label": "Promessa",
                    "badge": "Nuova valutazione",
                    "actors": actors.get(proposal.id, {}).get("people", []),
                    "institution": None,
                    "summary": f"«{proposal.exact_statement}»" if proposal.exact_statement else None,
                    "verdict": assessment.verdict.value,
                    "update": assessment.rationale,
                    "stage_label": (
                        f"Aggiornato al {_long_date(assessment.effective_at)}" if assessment.effective_at else None
                    ),
                    "since_label": "Promessa del" if proposal.introduced_at else None,
                    "since": proposal.introduced_at.isoformat() if proposal.introduced_at else None,
                },
            )
            for assessment, proposal in rows
        ]

    def _referendums(self, cap: int) -> list[FeedItem]:
        items = []
        for referendum in self.session.scalars(
            select(Referendum)
            .where(Referendum.published_at.is_not(None))
            .order_by(Referendum.published_at.desc(), Referendum.id.desc())
            .limit(cap)
        ):
            municipality = referendum.municipality
            if referendum.scope_type is GeographicScopeType.MUNICIPALITY and municipality is not None:
                scope = FeedScope.MUNICIPALITY
                region_id = municipality.region_id
                province = municipality.province_abbreviation
            elif referendum.scope_type is GeographicScopeType.REGION:
                scope, region_id, province = FeedScope.REGION, referendum.region_id, None
            else:
                scope, region_id, province = FeedScope.NATIONAL, None, None
            vote = _long_date(referendum.vote_date)
            synthetic = " (record dimostrativo)" if referendum.is_synthetic else ""
            items.append(
                FeedItem(
                    key=f"referendum-{referendum.id}",
                    kind=FeedItemKind.REFERENDUM,
                    occurred_on=referendum.published_at.date(),
                    title=referendum.title,
                    detail=f"Si vota il {vote}{synthetic}",
                    url=f"./?referendum={referendum.id}",
                    scope=scope,
                    region_id=region_id,
                    region_name=self._region_name(region_id),
                    province_abbreviation=province,
                    municipality_id=municipality.id if scope is FeedScope.MUNICIPALITY else None,
                    municipality_name=municipality.canonical_name if scope is FeedScope.MUNICIPALITY else None,
                    sources=(FeedSource(title="Fonte ufficiale", url=referendum.official_source_url),),
                    label=referendum.status.value,
                    card={
                        "type_label": "Referendum",
                        "badge": "Nuova consultazione",
                        "actors": [],
                        "institution": None,
                        "summary": None,
                        "stage_label": f"Si vota il {vote}",
                    },
                )
            )
        return items

    def _posts(self, cap: int) -> list[FeedItem]:
        posts = list(
            self.session.scalars(
                select(EditorialPost)
                .where(EditorialPost.status == EditorialPostStatus.PUBLISHED)
                .order_by(EditorialPost.published_at.desc(), EditorialPost.id.desc())
                .limit(cap)
            )
        )
        return list(self._posts_for(posts))

    # ------------------------------------------------------------------ page
    def page(
        self,
        *,
        feed_filter: FeedFilter = FeedFilter.ALL,
        zone: Zone = Zone(),
        offset: int = 0,
        limit: int = 20,
        redazione_only: bool = False,
        follow_politicians: frozenset[int] = frozenset(),
        follow_parties: frozenset[int] = frozenset(),
    ) -> FeedPage:
        # Every source is newest-first, so its first offset+limit+1 rows can
        # fill this page. Zone filtering drops local rows, so those over-fetch.
        cap = offset + limit + 1
        local_cap = cap * 4
        candidates: list[FeedItem] = []
        if not redazione_only:
            if feed_filter in (FeedFilter.ALL, FeedFilter.NATIONAL):
                candidates += self._proposal_events(cap)
                candidates += self._pledge_verdicts(cap)
            candidates += self._referendums(local_cap)
        candidates += self._posts(local_cap)
        accepted = [item for item in candidates if self._accepts(feed_filter, zone, item)]
        if follow_politicians or follow_parties:
            # "Per te": news about the people and parties the reader follows,
            # plus local news from the reader's own zone.
            accepted = [
                item for item in accepted
                if _involves(item, follow_politicians, follow_parties)
                or (item.scope is not FeedScope.NATIONAL and not zone.empty)
            ]
        accepted.sort(key=lambda item: (item.occurred_on, item.key), reverse=True)
        window = accepted[offset : offset + limit + 1]
        return FeedPage(
            filter=feed_filter,
            region_id=zone.region_id,
            province_abbreviation=zone.province,
            municipality_id=zone.municipality_id,
            items=tuple(window[:limit]),
            offset=offset,
            limit=limit,
            has_more=len(window) > limit,
        )

    def post(self, post_id: int) -> FeedItem | None:
        post = self.session.get(EditorialPost, post_id)
        if post is None or post.status is not EditorialPostStatus.PUBLISHED:
            return None
        return next(item for item in self._posts_for([post]))

    def _post_card(self, post: EditorialPost) -> dict:
        blocks = post.blocks or {}
        composed = card_module.public(blocks.get("card"), self.session)
        base = {
            "type_label": "Notizia",
            "badge": "Correzione" if post.corrects_id else "Dalla redazione",
            "actors": [],
            "institution": None,
            "summary": blocks.get("sommario") or post.body[:280],
        }
        if composed is None:
            return base
        return {**base, **composed, "type_label": composed["category_label"], "composed": True}

    def _posts_for(self, posts: list[EditorialPost]) -> Iterator[FeedItem]:
        for post in posts:
            municipality = (
                self.session.get(Municipality, post.municipality_id) if post.municipality_id else None
            )
            yield FeedItem(
                key=f"editorial-{post.id}",
                kind=FeedItemKind.EDITORIAL,
                occurred_on=post.published_at.date(),
                title=post.title,
                detail=post.body,
                url=f"./?post={post.id}",
                scope=post.scope,
                region_id=post.region_id,
                region_name=self._region_name(post.region_id),
                province_abbreviation=post.province_abbreviation,
                municipality_id=post.municipality_id,
                municipality_name=municipality.canonical_name if municipality else None,
                sources=tuple(FeedSource(**item) for item in post.citations),
                label="correction" if post.corrects_id else None,
                blocks=_public_blocks(post.blocks),
                card=self._post_card(post),
                written_by=post.created_by if post.created_by in self.public_names else None,
                verified_by=post.reviewed_by if post.reviewed_by in self.public_names else None,
            )



def _involves(item: FeedItem, politicians: frozenset[int], parties: frozenset[int]) -> bool:
    card = item.card or {}
    if any(person.get("politician_id") in politicians for person in card.get("people") or []):
        return True
    if any(party.get("id") in parties for party in card.get("parties") or []):
        return True
    return any(person.get("party_id") in parties for person in card.get("people") or [])


_MONTHS = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
           "agosto", "settembre", "ottobre", "novembre", "dicembre")


def _long_date(value) -> str:
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


_PUBLIC_BLOCK_KEYS = (
    "sommario", "perche", "fatto", "perche_deciso", "cosa_cambia", "destra",
    "sinistra", "altri", "numeri", "cosa_succede",
)


def _public_blocks(blocks: dict | None) -> dict | None:
    """The news blocks a citizen reads, plus each source's area and date."""

    if not blocks:
        return None
    public = {key: blocks[key] for key in _PUBLIC_BLOCK_KEYS if blocks.get(key)}
    public["fonti"] = [
        {"name": item.get("name"), "url": item.get("url"), "area": item.get("area"), "date": item.get("date")}
        for item in blocks.get("fonti") or []
    ]
    return public
