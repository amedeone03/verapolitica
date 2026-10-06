from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import (
    Politician,
    PoliticianVersion,
    Proposal,
    ProposalActor,
    ProposalSourceIdentifier,
    ProposalStatus,
    ProposalStatusEvent,
    ProposalType,
    Source,
)
from backend.app.services.official_source_display import (
    citizen_source_label,
    citizen_source_url,
)
from backend.app.schemas import (
    PublicPoliticianProposal,
    PublicProposal,
    PublicProposalActor,
    PublicProposalList,
    PublicProposalSource,
    PublicProposalStatusEvent,
    PublicProposalSummary,
)


class PublicProposalQueryService:
    """Read-only projection of human-approved proposals and status history."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list(
        self,
        *,
        offset: int,
        limit: int,
        proposal_status: ProposalStatus | None = None,
        proposal_type: ProposalType | None = None,
        politician_id: int | None = None,
        source_key: str | None = None,
    ) -> PublicProposalList:
        query = select(Proposal).where(Proposal.published_at.is_not(None))
        count_query = select(func.count(func.distinct(Proposal.id))).where(
            Proposal.published_at.is_not(None)
        )
        if proposal_status is not None:
            query = query.where(Proposal.current_status == proposal_status)
            count_query = count_query.where(Proposal.current_status == proposal_status)
        if proposal_type is not None:
            query = query.where(Proposal.proposal_type == proposal_type)
            count_query = count_query.where(Proposal.proposal_type == proposal_type)
        if politician_id is not None:
            query = query.join(ProposalActor).where(
                ProposalActor.politician_id == politician_id
            )
            count_query = count_query.join(ProposalActor).where(
                ProposalActor.politician_id == politician_id
            )
        if source_key is not None:
            query = query.join(ProposalSourceIdentifier).join(Source).where(
                Source.key == source_key
            )
            count_query = (
                count_query.join(ProposalSourceIdentifier)
                .join(Source)
                .where(Source.key == source_key)
            )
        proposals = list(
            self.session.scalars(
                query.distinct()
                .order_by(
                    Proposal.introduced_at.desc(),
                    Proposal.published_at.desc(),
                    Proposal.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        )
        return PublicProposalList(
            items=tuple(self._summary(proposal) for proposal in proposals),
            total=self.session.scalar(count_query) or 0,
            offset=offset,
            limit=limit,
        )

    def get(self, proposal_id: int) -> PublicProposal | None:
        proposal = self.session.scalar(
            select(Proposal).where(
                Proposal.id == proposal_id,
                Proposal.published_at.is_not(None),
            )
        )
        if proposal is None or proposal.published_at is None:
            return None
        summary = self._summary(proposal)
        history = tuple(
            PublicProposalStatusEvent(
                status=event.normalized_status,
                source_status_label=event.source_status_label,
                effective_at=event.effective_at,
                source=PublicProposalSource(
                    name=citizen_source_label(source.name),
                    url=citizen_source_url(event.source_url),
                ),
            )
            for event, source in self.session.execute(
                select(ProposalStatusEvent, Source)
                .join(Source, Source.id == ProposalStatusEvent.source_id)
                .where(ProposalStatusEvent.proposal_id == proposal.id)
                .order_by(
                    ProposalStatusEvent.effective_at,
                    ProposalStatusEvent.id,
                )
            )
        )
        sources = tuple(
            PublicProposalSource(
                name=citizen_source_label(source.name),
                url=citizen_source_url(
                    identifier.source_url, identifier.official_identifier
                ),
            )
            for identifier, source in self.session.execute(
                select(ProposalSourceIdentifier, Source)
                .join(Source, Source.id == ProposalSourceIdentifier.source_id)
                .where(ProposalSourceIdentifier.proposal_id == proposal.id)
                .order_by(Source.name, ProposalSourceIdentifier.id)
            )
        )
        return PublicProposal(
            **summary.model_dump(),
            summary=proposal.summary,
            exact_statement=proposal.exact_statement,
            status_history=history,
            sources=sources,
            published_at=proposal.published_at,
        )

    def list_for_politician(
        self, politician_id: int
    ) -> tuple[PublicPoliticianProposal, ...]:
        rows = self.session.execute(
            select(Proposal, ProposalActor)
            .join(ProposalActor, ProposalActor.proposal_id == Proposal.id)
            .where(
                Proposal.published_at.is_not(None),
                ProposalActor.politician_id == politician_id,
            )
            .order_by(Proposal.introduced_at.desc(), Proposal.id.desc())
        ).all()
        return tuple(
            PublicPoliticianProposal(
                id=proposal.id,
                title=proposal.canonical_title,
                proposal_type=proposal.proposal_type,
                current_status=proposal.current_status,
                role=actor.role,
                introduced_at=proposal.introduced_at,
            )
            for proposal, actor in rows
            if proposal.current_status is not None
        )

    def _summary(self, proposal: Proposal) -> PublicProposalSummary:
        if proposal.current_status is None:
            raise ValueError("published proposal is missing a current status")
        identifier, source = self.session.execute(
            select(ProposalSourceIdentifier, Source)
            .join(Source, Source.id == ProposalSourceIdentifier.source_id)
            .where(ProposalSourceIdentifier.proposal_id == proposal.id)
            .order_by(ProposalSourceIdentifier.id)
            .limit(1)
        ).one()
        actors = tuple(
            self._public_actor(actor)
            for actor in self.session.scalars(
                select(ProposalActor)
                .where(ProposalActor.proposal_id == proposal.id)
                .order_by(ProposalActor.role, ProposalActor.display_name, ProposalActor.id)
            )
        )
        return PublicProposalSummary(
            id=proposal.id,
            title=proposal.canonical_title,
            proposal_type=proposal.proposal_type,
            introduced_at=proposal.introduced_at,
            current_status=proposal.current_status,
            actors=actors,
            source=PublicProposalSource(
                name=citizen_source_label(source.name),
                url=citizen_source_url(
                    identifier.source_url, identifier.official_identifier
                ),
            ),
        )

    def _public_actor(self, actor: ProposalActor) -> PublicProposalActor:
        politician_id = None
        if actor.politician_id is not None:
            politician_id = self.session.scalar(
                select(Politician.id)
                .join(
                    PoliticianVersion,
                    PoliticianVersion.id == Politician.current_version_id,
                )
                .where(
                    Politician.id == actor.politician_id,
                    PoliticianVersion.published_at.is_not(None),
                )
            )
        return PublicProposalActor(
            actor_type=actor.actor_type,
            role=actor.role,
            display_name=actor.display_name,
            politician_id=politician_id,
        )
