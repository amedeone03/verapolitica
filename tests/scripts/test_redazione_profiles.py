"""The redazione's Conte and Schlein sheets load as drafts, audit honestly and
publish only what has real citations."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.app.models import (
    Politician,
    PoliticianSourceIdentifier,
    PoliticianVersion,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalDraft,
    ProposalType,
    Source,
)
from backend.app.models.politician_profile import (
    PoliticianBiography,
    PoliticianCareerEntry,
    PoliticianPosition,
    PoliticianProceeding,
    ProfileContentStatus,
)
from backend.app.services import normalize_person_name
from backend.app.services.reference_profile_audit import (
    audit_from_factory,
    fixture_for_slug,
    is_complete_source_url,
)
from scripts.approve_reference_profile import approve_reference_profile
from scripts.prepare_reference_profile import prepare_reference_profile

NOW = datetime(2026, 10, 31, 9, tzinfo=timezone.utc)
FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "reference_profiles"


def _seed(session_factory, given, family, birth, identifier):
    with session_factory() as session:
        source = session.scalar(select(Source).where(Source.key == "camera-deputati"))
        if source is None:
            source = Source(key="camera-deputati", name="Camera dei Deputati", base_url="https://dati.camera.it")
            session.add(source)
            session.flush()
        politician = Politician(
            canonical_given_name=given,
            canonical_family_name=family,
            normalized_name=normalize_person_name(given, family),
            birth_date=birth,
        )
        session.add(politician)
        session.flush()
        version = PoliticianVersion(
            politician_id=politician.id,
            version_number=1,
            profile_schema_version=1,
            profile_data={"given_name": given, "family_name": family, "mandates": []},
            published_at=NOW,
        )
        session.add(version)
        session.flush()
        politician.current_version = version
        session.add(PoliticianSourceIdentifier(politician_id=politician.id, source_id=source.id, value=identifier))
        session.commit()
        return politician.id


@pytest.fixture
def seeded(session_factory):
    conte = _seed(session_factory, "Giuseppe", "Conte", date(1964, 8, 8), "http://dati.camera.it/ocd/deputato.rdf/d306970_19")
    # The Camera registers Schlein as "Elly"; the sheet says "Elena Ethel".
    schlein = _seed(session_factory, "Elly", "Schlein", date(1985, 5, 4), "http://dati.camera.it/ocd/deputato.rdf/d308805_19")
    return {"conte": conte, "schlein": schlein}


def test_fixtures_are_clean_and_marked_for_review():
    for name in ("giuseppe_conte_v1.json", "elly_schlein_v1.json"):
        text = (FIXTURES / name).read_text(encoding="utf-8")
        data = json.loads(text)
        assert "requires editorial verification" in data["disclaimer"]
        assert "utm_" not in text and "chatgpt" not in text
        assert data["editorial_issues"]
    conte = json.loads((FIXTURES / "giuseppe_conte_v1.json").read_text(encoding="utf-8"))
    assert len(conte["pledges"]) == 27 and len(conte["proposals"]) == 24
    verdicts = {item["number"]: item["suggested_verdict"] for item in conte["pledges"]}
    assert verdicts[1] == "kept" and verdicts[4] == "partially_kept" and verdicts[8] == "broken"
    assert verdicts[16] is None and verdicts[23] is None  # not a methodology state
    schlein = json.loads((FIXTURES / "elly_schlein_v1.json").read_text(encoding="utf-8"))
    assert [item["status"] for item in schlein["proposals"]].count("rejected") == 3
    assert fixture_for_slug("elly-schlein").name == "elly_schlein_v1.json"
    assert fixture_for_slug("giorgia-meloni").name == "giorgia_meloni_v1.json"


def test_index_pages_are_not_citations():
    assert not is_complete_source_url("https://www.partitodemocratico.it/")
    assert not is_complete_source_url("https://www.ansa.it/sito/notizie/politica/politica.shtml")
    assert not is_complete_source_url("https://www.europarl.europa.eu/meps/it/home")
    assert is_complete_source_url("https://www.camera.it/leg19/126?idDocumento=1741&leg=19")
    assert is_complete_source_url("https://tg24.sky.it/cronaca/2023/03/08/inchiesta-covid-tribunale-ministri-archiviazione-conte-speranza")


def test_conte_loads_as_drafts_and_publishes_only_cited_content(session_factory, seeded):
    report = prepare_reference_profile(
        fixture_path=FIXTURES / "giuseppe_conte_v1.json", session_factory=session_factory, dry_run=False
    )
    assert report["politician_id"] == seeded["conte"]
    assert report["blocked"] == []
    again = prepare_reference_profile(
        fixture_path=FIXTURES / "giuseppe_conte_v1.json", session_factory=session_factory, dry_run=False
    )
    assert not [row for row in again["created"] if row["kind"] in {"pledge", "proposal"}]

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Proposal).where(Proposal.published_at.is_not(None))) == 0
        drafts = session.scalar(select(func.count()).select_from(ProposalDraft))
        assert drafts == 27 + 24
        roles = {
            (proposal.proposal_type, actor.role)
            for proposal, actor in session.execute(
                select(Proposal, ProposalActor).join(ProposalActor, ProposalActor.proposal_id == Proposal.id)
            )
        }
        assert roles <= {
            (ProposalType.EXPLICIT_PROMISE, ProposalActorRole.COMMITMENT_OWNER),
            (ProposalType.PROPOSAL, ProposalActorRole.PROPOSER),
        }

    audit = audit_from_factory(session_factory, "giuseppe-conte")
    by_key = {item.identity_key: item for item in audit.profile_items}
    assert by_key["primary"].source_completeness == "READY_FOR_EDITORIAL_REVIEW"
    assert by_key["pdc-conte-ii"].source_completeness == "READY_FOR_EDITORIAL_REVIEW"
    assert by_key["cpga-2013"].source_completeness == "MISSING_SOURCE_METADATA"

    approved = approve_reference_profile(
        "giuseppe-conte", session_factory=session_factory, dry_run=False, allow_non_unified=True
    )
    approved_keys = {row["identity_key"] for row in approved["approved"]}
    assert {"primary", "pdc-conte-i", "giustizia"} <= approved_keys
    assert "cpga-2013" not in approved_keys
    with session_factory() as session:
        published = session.scalar(
            select(func.count()).select_from(PoliticianPosition).where(
                PoliticianPosition.politician_id == seeded["conte"],
                PoliticianPosition.status == ProfileContentStatus.PUBLISHED,
            )
        )
        assert published == 5
        assert session.scalar(
            select(func.count()).select_from(PoliticianProceeding).where(
                PoliticianProceeding.status == ProfileContentStatus.PUBLISHED
            )
        ) == 0


def test_schlein_matches_alias_and_index_page_sources_stay_blocked(session_factory, seeded):
    report = prepare_reference_profile(
        fixture_path=FIXTURES / "elly_schlein_v1.json", session_factory=session_factory, dry_run=False
    )
    assert report["politician_id"] == seeded["schlein"]
    assert len(report["blocked"]) == 10  # positions without a dated, verifiable statement
    proposals = [row for row in report["created"] if row["kind"] == "proposal"]
    assert len(proposals) == 21

    approved = approve_reference_profile(
        "elly-schlein", session_factory=session_factory, dry_run=False, allow_non_unified=True
    )
    assert approved["approved"] == []  # every source in the sheet is a home or section page
    with session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(PoliticianBiography).where(
                PoliticianBiography.status == ProfileContentStatus.PUBLISHED
            )
        ) == 0
        assert session.scalar(select(func.count()).select_from(PoliticianCareerEntry)) == 4
        statuses = {
            draft.proposed_data.get("normalized_status")
            for draft in session.scalars(select(ProposalDraft))
        }
        assert {"rejected", "enacted", "superseded", "assigned"} <= statuses
