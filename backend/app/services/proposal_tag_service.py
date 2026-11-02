"""Controlled topic and dossier tags on proposals.

A pledge's CAP code already lives on its classification; it is surfaced as a
topic tag too, so filtering by topic finds bills and pledges alike without
storing the same fact twice.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import Select

from backend.app.models import (
    CAP_MAJOR_TOPICS,
    DOSSIERS,
    PledgeClassification,
    Proposal,
    ProposalTag,
    ProposalTagKind,
    tag_label,
)
from backend.app.schemas.proposal import PublicProposalTag


class ProposalTagError(RuntimeError):
    pass


class ProposalTagNotFoundError(ProposalTagError):
    pass


class ProposalTagValidationError(ProposalTagError):
    pass


def tags_for(session: Session, proposal_ids: Iterable[int]) -> dict[int, tuple[PublicProposalTag, ...]]:
    ids = list(proposal_ids)
    if not ids:
        return {}
    found: dict[int, dict[tuple[str, str], PublicProposalTag]] = {item: {} for item in ids}
    for tag in session.scalars(
        select(ProposalTag)
        .where(ProposalTag.proposal_id.in_(ids))
        .order_by(ProposalTag.kind, ProposalTag.value)
    ):
        label = tag_label(tag.kind, tag.value)
        if label is not None:
            found[tag.proposal_id][(tag.kind.value, tag.value)] = PublicProposalTag(
                kind=tag.kind, value=tag.value, label=label
            )
    for proposal_id, code in session.execute(
        select(PledgeClassification.proposal_id, PledgeClassification.cap_topic_code).where(
            PledgeClassification.proposal_id.in_(ids),
            PledgeClassification.cap_topic_code.is_not(None),
        )
    ):
        label = CAP_MAJOR_TOPICS.get(code)
        if label is not None:
            found[proposal_id].setdefault(
                (ProposalTagKind.TOPIC.value, code),
                PublicProposalTag(kind=ProposalTagKind.TOPIC, value=code, label=label),
            )
    return {
        proposal_id: tuple(
            sorted(values.values(), key=lambda tag: (tag.kind.value, int(tag.value) if tag.value.isdigit() else 0, tag.value))
        )
        for proposal_id, values in found.items()
    }


def filter_by_tags(query: Select, *, topic: str | None = None, dossier: str | None = None) -> Select:
    if topic is not None:
        query = query.where(
            or_(
                Proposal.id.in_(
                    select(ProposalTag.proposal_id).where(
                        ProposalTag.kind == ProposalTagKind.TOPIC, ProposalTag.value == topic
                    )
                ),
                Proposal.id.in_(
                    select(PledgeClassification.proposal_id).where(
                        PledgeClassification.cap_topic_code == topic
                    )
                ),
            )
        )
    if dossier is not None:
        query = query.where(
            Proposal.id.in_(
                select(ProposalTag.proposal_id).where(
                    ProposalTag.kind == ProposalTagKind.DOSSIER, ProposalTag.value == dossier
                )
            )
        )
    return query


class ProposalTagService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def replace(
        self,
        proposal_id: int,
        *,
        topics: Iterable[str],
        dossiers: Iterable[str],
        assigned_by: str,
    ) -> tuple[PublicProposalTag, ...]:
        wanted = {(ProposalTagKind.TOPIC, value) for value in topics} | {
            (ProposalTagKind.DOSSIER, value) for value in dossiers
        }
        for kind, value in wanted:
            if tag_label(kind, value) is None:
                registry = CAP_MAJOR_TOPICS if kind is ProposalTagKind.TOPIC else DOSSIERS
                raise ProposalTagValidationError(
                    f"unknown {kind.value} {value!r}; allowed: {', '.join(registry)}"
                )
        with self.session_factory.begin() as session:
            proposal = session.get(Proposal, proposal_id)
            if proposal is None:
                raise ProposalTagNotFoundError("proposal not found")
            existing = {
                (tag.kind, tag.value): tag
                for tag in session.scalars(
                    select(ProposalTag).where(ProposalTag.proposal_id == proposal_id)
                )
            }
            for key, tag in existing.items():
                if key not in wanted:
                    session.delete(tag)
            for kind, value in sorted(wanted - set(existing)):
                session.add(
                    ProposalTag(
                        proposal_id=proposal_id, kind=kind, value=value, assigned_by=assigned_by
                    )
                )
            session.flush()
            return tags_for(session, [proposal_id])[proposal_id]
