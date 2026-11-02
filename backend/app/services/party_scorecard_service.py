"""Party scorecard and same-stratum comparison (methodology ``pledge-score/v1``).

A party score is **not** an average of its members' rates. Averaging rates
computed on a handful of pledges each gives a two-pledge member the same weight
as a forty-pledge member and hides how little evidence sits behind the number.
Instead, the party's pledges are pooled and the ordinary scorer runs on the
pooled counts, so every role stratum keeps its own composition, interval and
minimum-size rule. Pooling is the "weighted mean" of member rates with weights
equal to each member's closed pledges.

A pledge belongs to a party when either

* the party itself is a ``commitment_owner`` of the pledge, or
* a published politician is the ``commitment_owner`` and was affiliated with
  the party on the pledge date (``introduced_at``, else the classification's
  ``mandate_start``). Member pledges with no usable date are not attributed and
  are counted in ``unattributed_member_pledges``.

Each pledge is counted once even when both rules match.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    PledgeClassification,
    PoliticalParty,
    PoliticalPartyAffiliation,
    Politician,
    PoliticianVersion,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalActorType,
    ProposalType,
)
from backend.app.schemas.pledge import (
    ComparisonEntry,
    PartyContributor,
    PartyScorecardPledge,
    PledgeAttribution,
    PublicComparison,
    PublicPartyScorecard,
    ScorecardWindow,
)
from backend.app.scoring import DEFAULT_METHODOLOGY, HolderRole, ScoringMethodology, compute_scorecard
from backend.app.services.pledge_service import METHODOLOGY_URL, PledgeService

AGGREGATION = "pooled counts per role stratum; pledges attributed to the party or to members affiliated on the pledge date"
MAX_COMPARED = 6


class PartyScorecardError(RuntimeError):
    pass


class PartyNotFoundError(PartyScorecardError):
    pass


class ComparisonValidationError(PartyScorecardError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _covers(affiliation: PoliticalPartyAffiliation, when: date) -> bool:
    if affiliation.start_date is not None and when < affiliation.start_date:
        return False
    if affiliation.end_date is not None and when > affiliation.end_date:
        return False
    return True


def in_window(
    classification: PledgeClassification | None, window: ScorecardWindow, as_of: date
) -> bool:
    if window is ScorecardWindow.ALL:
        return True
    if classification is None or classification.mandate_start is None:
        return False
    if classification.mandate_start > as_of:
        return False
    return classification.mandate_end is None or as_of <= classification.mandate_end


def published_names(session: Session, politician_ids: set[int]) -> dict[int, str]:
    if not politician_ids:
        return {}
    names: dict[int, str] = {}
    rows = session.execute(
        select(Politician, PoliticianVersion)
        .join(
            PoliticianVersion,
            (PoliticianVersion.id == Politician.current_version_id)
            & (PoliticianVersion.politician_id == Politician.id),
        )
        .where(
            Politician.id.in_(politician_ids),
            PoliticianVersion.published_at.is_not(None),
        )
    )
    for politician, version in rows:
        data = version.profile_data or {}
        given = data.get("given_name") or politician.canonical_given_name
        family = data.get("family_name") or politician.canonical_family_name
        names[politician.id] = f"{given} {family}".strip()
    return names


class PartyScorecardService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        methodology: ScoringMethodology = DEFAULT_METHODOLOGY,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.session_factory = session_factory
        self.methodology = methodology
        self.clock = clock
        self.pledges = PledgeService(session_factory, methodology=methodology, clock=clock)

    @staticmethod
    def _owners(session: Session) -> dict[int, tuple[Proposal, list[ProposalActor]]]:
        rows = session.execute(
            select(Proposal, ProposalActor)
            .join(ProposalActor, ProposalActor.proposal_id == Proposal.id)
            .where(
                ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
                Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
                Proposal.published_at.is_not(None),
            )
            .order_by(Proposal.id, ProposalActor.id)
        )
        owners: dict[int, tuple[Proposal, list[ProposalActor]]] = {}
        for proposal, actor in rows:
            owners.setdefault(proposal.id, (proposal, []))[1].append(actor)
        return owners

    def scorecard_for_party(
        self,
        party_id: int,
        *,
        window: ScorecardWindow = ScorecardWindow.ALL,
        as_of: date | None = None,
    ) -> PublicPartyScorecard:
        as_of = as_of or self.clock().date()
        with self.session_factory() as session:
            party = session.get(PoliticalParty, party_id)
            if party is None:
                raise PartyNotFoundError("political party not found")
            affiliations: dict[int, list[PoliticalPartyAffiliation]] = {}
            for row in session.scalars(
                select(PoliticalPartyAffiliation).where(
                    PoliticalPartyAffiliation.political_party_id == party_id
                )
            ):
                affiliations.setdefault(row.politician_id, []).append(row)
            names = published_names(session, set(affiliations))

            owners = self._owners(session)
            classifications = {
                row.proposal_id: row
                for row in session.scalars(
                    select(PledgeClassification).where(
                        PledgeClassification.proposal_id.in_(list(owners))
                    )
                )
            } if owners else {}

            attributed: dict[int, tuple[PledgeAttribution, int | None]] = {}
            unattributed = 0
            for proposal_id, (proposal, actors) in owners.items():
                classification = classifications.get(proposal_id)
                if not in_window(classification, window, as_of):
                    continue
                if any(
                    actor.actor_type is ProposalActorType.POLITICAL_PARTY
                    and actor.political_party_id == party_id
                    for actor in actors
                ):
                    attributed[proposal_id] = (PledgeAttribution.PARTY, None)
                    continue
                when = proposal.introduced_at or (
                    classification.mandate_start if classification else None
                )
                for actor in actors:
                    if actor.politician_id not in names:
                        continue
                    if when is None:
                        unattributed += 1
                        break
                    if any(_covers(item, when) for item in affiliations[actor.politician_id]):
                        attributed[proposal_id] = (PledgeAttribution.MEMBER, actor.politician_id)
                        break

            pledges = [owners[proposal_id][0] for proposal_id in sorted(attributed)]
            outcomes, items, _classifications, _progress = self.pledges._scored_items(
                session, pledges, as_of
            )

        scorecard = compute_scorecard(outcomes, methodology=self.methodology)
        contributions = Counter(
            member for kind, member in attributed.values() if kind is PledgeAttribution.MEMBER
        )
        rows = tuple(
            PartyScorecardPledge(
                **item.model_dump(),
                attribution=attributed[item.proposal_id][0],
                member_politician_id=attributed[item.proposal_id][1],
            )
            for item in items
        )
        return PublicPartyScorecard(
            political_party_id=party.id,
            name=party.canonical_name,
            window=window,
            methodology_version=scorecard.methodology_version,
            methodology_url=METHODOLOGY_URL,
            aggregation=AGGREGATION,
            as_of=as_of,
            pledges=rows,
            contributors=tuple(
                PartyContributor(politician_id=member, name=names[member], pledges=count)
                for member, count in sorted(
                    contributions.items(), key=lambda pair: (-pair[1], names[pair[0]])
                )
            ),
            unattributed_member_pledges=unattributed,
            tracked_pledges=scorecard.tracked_pledges,
            unclassified_pledges=len(pledges) - len(items),
            excluded_vague_pledges=scorecard.excluded_vague_pledges,
            credible_level=scorecard.credible_level,
            min_closed_for_rate=scorecard.min_closed_for_rate,
            strata=self.pledges.stratum_responses(scorecard),
        )

    def compare_politicians(
        self,
        politician_ids: list[int],
        *,
        role: HolderRole,
        as_of: date | None = None,
    ) -> PublicComparison:
        unique = list(dict.fromkeys(politician_ids))
        if not 2 <= len(unique) <= MAX_COMPARED:
            raise ComparisonValidationError(
                f"compare between 2 and {MAX_COMPARED} distinct politicians"
            )
        as_of = as_of or self.clock().date()
        with self.session_factory() as session:
            names = published_names(session, set(unique))
        missing = [item for item in unique if item not in names]
        if missing:
            raise PartyNotFoundError(f"published politician not found: {missing[0]}")
        entries = []
        for politician_id in unique:
            card = self.pledges.scorecard_for_politician(politician_id, as_of=as_of)
            stratum = next((item for item in card.strata if item.role is role), None)
            entries.append(
                ComparisonEntry(
                    politician_id=politician_id, name=names[politician_id], stratum=stratum
                )
            )
        intervals = [
            entry.stratum.credible_interval
            for entry in entries
            if entry.stratum is not None and entry.stratum.credible_interval is not None
        ]
        overlapping = len(intervals) >= 2 and max(low for low, _ in intervals) <= min(
            high for _, high in intervals
        )
        return PublicComparison(
            role=role,
            methodology_version=self.methodology.version,
            methodology_url=METHODOLOGY_URL,
            as_of=as_of,
            credible_level=self.methodology.credible_level,
            min_closed_for_rate=self.methodology.min_closed_for_rate,
            entries=tuple(entries),
            overlapping_intervals=overlapping,
        )
