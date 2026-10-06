from __future__ import annotations

from sqlalchemy import event

from backend.app.core.text import normalize_search_text
from backend.app.models.parliamentary_group import ParliamentaryGroup
from backend.app.models.political_party import PoliticalParty
from backend.app.models.proposal import Proposal, ProposalActor
from backend.app.models.territory import Municipality, Region
from backend.app.models.civic import GlossaryTerm, Referendum


def _set_search_fields(target, primary: str, *document_parts: str | None) -> None:
    target.search_primary = normalize_search_text(primary)
    target.search_document = normalize_search_text(
        " ".join(part for part in document_parts if part)
    )


@event.listens_for(Region, "before_insert")
@event.listens_for(Region, "before_update")
def _region_search(mapper, connection, target: Region) -> None:
    del mapper, connection
    _set_search_fields(target, target.canonical_name, target.canonical_name)


@event.listens_for(Municipality, "before_insert")
@event.listens_for(Municipality, "before_update")
def _municipality_search(mapper, connection, target: Municipality) -> None:
    del mapper, connection
    _set_search_fields(
        target,
        target.canonical_name,
        "comune",
        target.canonical_name,
        target.province_abbreviation,
    )


@event.listens_for(ParliamentaryGroup, "before_insert")
@event.listens_for(ParliamentaryGroup, "before_update")
def _group_search(mapper, connection, target: ParliamentaryGroup) -> None:
    del mapper, connection
    _set_search_fields(
        target,
        target.canonical_name,
        target.canonical_name,
        target.abbreviation,
        target.institution,
        target.legislature,
    )


@event.listens_for(PoliticalParty, "before_insert")
@event.listens_for(PoliticalParty, "before_update")
def _party_search(mapper, connection, target: PoliticalParty) -> None:
    del mapper, connection
    _set_search_fields(
        target,
        target.canonical_name,
        target.canonical_name,
        target.abbreviation,
    )


@event.listens_for(Proposal, "before_insert")
@event.listens_for(Proposal, "before_update")
def _proposal_search(mapper, connection, target: Proposal) -> None:
    del mapper, connection
    proposal_type = (
        target.proposal_type.value
        if hasattr(target.proposal_type, "value")
        else str(target.proposal_type or "")
    )
    _set_search_fields(
        target,
        target.canonical_title,
        target.canonical_title,
        target.summary,
        target.exact_statement,
        proposal_type,
    )


@event.listens_for(ProposalActor, "before_insert")
@event.listens_for(ProposalActor, "before_update")
def _actor_search(mapper, connection, target: ProposalActor) -> None:
    del mapper, connection
    target.search_primary = normalize_search_text(target.display_name)


@event.listens_for(Referendum, "before_insert")
@event.listens_for(Referendum, "before_update")
def _referendum_search(mapper, connection, target: Referendum) -> None:
    del mapper, connection
    kind = (
        target.referendum_type.value
        if hasattr(target.referendum_type, "value")
        else str(target.referendum_type or "")
    )
    _set_search_fields(
        target,
        target.title,
        target.title,
        target.official_question,
        kind,
    )


@event.listens_for(GlossaryTerm, "before_insert")
@event.listens_for(GlossaryTerm, "before_update")
def _glossary_search(mapper, connection, target: GlossaryTerm) -> None:
    del mapper, connection
    _set_search_fields(
        target,
        target.term,
        target.term,
        target.slug,
        target.short_definition,
    )
