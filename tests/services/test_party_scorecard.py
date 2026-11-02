from datetime import date

import pytest

from backend.app.models import (
    PoliticalPartyAffiliation,
    Politician,
    PoliticianVersion,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalActorType,
    ProposalType,
)
from backend.app.schemas.pledge import PledgeAttribution, ScorecardWindow
from backend.app.scoring import EvidenceLabel, FulfillmentVerdict, HolderRole
from backend.app.services.party_scorecard_service import (
    ComparisonValidationError,
    PartyNotFoundError,
    PartyScorecardService,
)
from backend.app.services.pledge_service import PledgeService
from tests.services.pledge_seed import NOW, add_extra_pledges, seed
from tests.services.test_pledge_service import classification, editor_draft


def _kept(service, data, proposal_id):
    draft, _ = editor_draft(service, data, proposal_id, FulfillmentVerdict.KEPT, EvidenceLabel.SUPPORTS)
    service.approve(draft.id, reviewer="caporedattore")


def _member(session_factory, data, *, start, end=None, name=("Lucia", "Bianchi")):
    """A second published politician affiliated with the seed party."""

    with session_factory() as session:
        politician = Politician(
            canonical_given_name=name[0],
            canonical_family_name=name[1],
            normalized_name=" ".join(name).lower(),
        )
        session.add(politician)
        session.flush()
        version = PoliticianVersion(
            politician_id=politician.id,
            version_number=1,
            profile_schema_version=1,
            profile_data={"given_name": name[0], "family_name": name[1], "mandates": []},
            published_at=NOW,
        )
        session.add(version)
        session.flush()
        politician.current_version = version
        session.add(
            PoliticalPartyAffiliation(
                politician_id=politician.id,
                political_party_id=data.party_id,
                source_id=data.source_id,
                raw_document_id=data.raw_document_id,
                identity_key=f"aff-{politician.id}",
                source_url="https://www.senato.it/aff",
                source_field="party",
                start_date=start,
                end_date=end,
            )
        )
        session.commit()
        return politician.id


def _member_pledge(session_factory, politician_id, *, introduced):
    with session_factory() as session:
        proposal = Proposal(
            canonical_title="Impegno personale",
            exact_statement="Approverò la riforma.",
            proposal_type=ProposalType.EXPLICIT_PROMISE,
            published_at=NOW,
            introduced_at=introduced,
        )
        session.add(proposal)
        session.flush()
        session.add(
            ProposalActor(
                proposal_id=proposal.id,
                actor_type=ProposalActorType.POLITICIAN,
                role=ProposalActorRole.COMMITMENT_OWNER,
                politician_id=politician_id,
                display_name="Membro",
                identity_key=f"m-{proposal.id}",
            )
        )
        session.commit()
        return proposal.id


@pytest.fixture
def data(session_factory):
    return seed(session_factory)


def test_party_score_pools_counts_and_attributes_members_by_date(session_factory, data):
    pledges = PledgeService(session_factory)
    extra = add_extra_pledges(session_factory, data, 8)
    member = _member(session_factory, data, start=date(2020, 1, 1))
    in_party = _member_pledge(session_factory, member, introduced=date(2023, 5, 1))
    before = _member_pledge(session_factory, member, introduced=date(2019, 5, 1))
    for proposal_id in (data.pledge_id, *extra, in_party, before):
        pledges.classify(proposal_id, classification(), classified_by="editor-a")
    for proposal_id in (data.pledge_id, *extra, in_party):
        _kept(pledges, data, proposal_id)

    card = PartyScorecardService(session_factory).scorecard_for_party(
        data.party_id, as_of=date(2026, 10, 7)
    )
    attribution = {item.proposal_id: item.attribution for item in card.pledges}
    assert attribution[data.pledge_id] is PledgeAttribution.PARTY
    assert attribution[in_party] is PledgeAttribution.MEMBER
    assert before not in attribution  # pledged before joining the party
    assert [(c.politician_id, c.pledges) for c in card.contributors] == [(member, 1)]

    (stratum,) = card.strata
    # 1 + 8 party pledges + 1 member pledge, all kept: pooled counts, not an average.
    assert stratum.closed_pledges == 10
    assert stratum.rate == 1.0
    assert card.aggregation.startswith("pooled counts")


def test_current_window_and_undated_member_pledges(session_factory, data):
    pledges = PledgeService(session_factory)
    member = _member(session_factory, data, start=date(2020, 1, 1))
    undated = _member_pledge(session_factory, member, introduced=None)
    pledges.classify(data.pledge_id, classification(), classified_by="editor-a")
    pledges.classify(
        undated,
        classification(mandate_start=None, mandate_end=None),
        classified_by="editor-a",
    )
    service = PartyScorecardService(session_factory)

    everything = service.scorecard_for_party(data.party_id, as_of=date(2026, 10, 7))
    assert everything.unattributed_member_pledges == 1

    past = service.scorecard_for_party(
        data.party_id, window=ScorecardWindow.CURRENT, as_of=date(2030, 1, 1)
    )
    assert past.pledges == ()  # the 2022-2027 mandate no longer contains as_of
    current = service.scorecard_for_party(
        data.party_id, window=ScorecardWindow.CURRENT, as_of=date(2026, 10, 7)
    )
    assert [item.proposal_id for item in current.pledges] == [data.pledge_id]

    with pytest.raises(PartyNotFoundError):
        service.scorecard_for_party(999)


def test_comparison_stays_inside_one_stratum(session_factory, data):
    pledges = PledgeService(session_factory)
    pledges.classify(data.pledge_id, classification(), classified_by="editor-a")
    _kept(pledges, data, data.pledge_id)
    other = _member(session_factory, data, start=date(2020, 1, 1))
    service = PartyScorecardService(session_factory)

    comparison = service.compare_politicians(
        [data.politician_id, other], role=HolderRole.GOVERNMENT_COALITION, as_of=date(2026, 10, 7)
    )
    by_id = {entry.politician_id: entry for entry in comparison.entries}
    assert by_id[data.politician_id].stratum.closed_pledges == 1
    assert by_id[data.politician_id].stratum.rate is None  # below the minimum
    assert by_id[other].stratum is None
    opposition = service.compare_politicians(
        [data.politician_id, other], role=HolderRole.OPPOSITION
    )
    assert all(entry.stratum is None for entry in opposition.entries)

    with pytest.raises(ComparisonValidationError):
        service.compare_politicians([data.politician_id], role=HolderRole.OPPOSITION)
    with pytest.raises(PartyNotFoundError):
        service.compare_politicians([data.politician_id, 999], role=HolderRole.OPPOSITION)


def test_party_api_lists_members_and_scorecard(tmp_path):
    from fastapi.testclient import TestClient

    from backend.app.core.config import Settings
    from backend.app.db.base import Base
    from backend.app.db.session import create_db_engine, create_session_factory
    from backend.app.main import create_app

    url = f"sqlite:///{tmp_path / 'party.db'}"
    engine = create_db_engine(url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    data = seed(factory)
    member = _member(factory, data, start=date(2020, 1, 1))
    _member(factory, data, start=date(2010, 1, 1), end=date(2015, 1, 1), name=("Ex", "Membro"))
    engine.dispose()
    with TestClient(create_app(Settings(database_url=url, raw_storage_path=tmp_path / "raw"))) as client:
        _check_party_api(client, data, member)


def _check_party_api(client, data, member):

    parties = client.get("/political-parties").json()
    assert parties["items"][0]["current_member_count"] == 1
    detail = client.get(f"/political-parties/{data.party_id}").json()
    assert [m["politician_id"] for m in detail["current_members"]] == [member]
    assert [m["name"] for m in detail["former_members"]] == ["Ex Membro"]

    card = client.get(f"/political-parties/{data.party_id}/scorecard?window=current")
    assert card.status_code == 200, card.text
    assert card.json()["window"] == "current"
    assert client.get("/political-parties/999/scorecard").status_code == 404

    compare = client.get(
        f"/compare/politicians?ids={data.politician_id},{member}&role=opposition"
    )
    assert compare.status_code == 200, compare.text
    assert client.get(f"/compare/politicians?ids={data.politician_id}&role=opposition").status_code == 422
    assert client.get(f"/compare/politicians?ids={data.politician_id},{member}").status_code == 422
    assert "party_aggregation" in client.get("/methodology/scoring").json()


