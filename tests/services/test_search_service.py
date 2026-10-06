from datetime import date, datetime, timezone

import pytest

from backend.app.models import (
    IdentityResolutionCase,
    IdentityResolutionStatus,
    Municipality,
    ParliamentaryGroup,
    PoliticalParty,
    Politician,
    PoliticianVersion,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalActorType,
    ProposalDraft,
    ProposalDraftKind,
    ProposalDraftStatus,
    ProposalType,
    RawDocument,
    RawDocumentStatus,
    Region,
    Source,
    TerritoryStatus,
)
from backend.app.schemas import PoliticalMandate, PoliticianVersionProfile
from backend.app.schemas.search import SearchEntityType
from backend.app.services import SearchService, SearchValidationError, normalize_person_name


def _source(session) -> Source:
    source = Source(key="search-source", name="Search Source", base_url="https://example.test")
    session.add(source)
    session.flush()
    return source


def _document(session, source: Source) -> RawDocument:
    document = RawDocument(
        source_id=source.id,
        retrieved_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
        source_url="https://example.test/search",
        content_type="application/json",
        storage_key="search.json",
        raw_sha256="c" * 64,
        normalized_sha256="d" * 64,
        structured_records=[],
        process_status=RawDocumentStatus.PARSED,
        change_detected=True,
        collector_version="search_v1",
        parser_version="search_v1",
    )
    session.add(document)
    session.flush()
    return document


def _publish(session, given: str, family: str, *, office="senator", institution="Senato della Repubblica"):
    politician = Politician(
        canonical_given_name=given,
        canonical_family_name=family,
        normalized_name=normalize_person_name(given, family),
        birth_date=date(1970, 1, 2),
    )
    session.add(politician)
    session.flush()
    version = PoliticianVersion(
        politician_id=politician.id,
        version_number=1,
        profile_schema_version=1,
        profile_data=PoliticianVersionProfile(
            given_name=given,
            family_name=family,
            birth_date=date(1970, 1, 2),
            mandates=(
                PoliticalMandate(
                    institution=institution,
                    office=office,
                    legislature="19",
                    mandate_type="elettivo",
                    start_date=date(2022, 10, 13),
                    election_area="Lazio",
                ),
            ),
        ).model_dump(mode="json"),
        published_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
    )
    session.add(version)
    session.flush()
    politician.current_version_id = version.id
    return politician


def _territories(session, source, document):
    region = Region(
        istat_code="03",
        canonical_name="Lombardia",
        status=TerritoryStatus.ACTIVE,
        source_id=source.id,
        raw_document_id=document.id,
        source_url="https://example.test/istat",
    )
    session.add(region)
    session.flush()
    milano = Municipality(
        istat_code="015146",
        region_id=region.id,
        canonical_name="Milano",
        province_abbreviation="MI",
        province_name="Milano",
        status=TerritoryStatus.ACTIVE,
        source_id=source.id,
        raw_document_id=document.id,
        source_url="https://example.test/istat",
    )
    forli = Municipality(
        istat_code="040012",
        region_id=region.id,
        canonical_name="Forlì",
        province_abbreviation="FC",
        province_name="Forlì-Cesena",
        status=TerritoryStatus.ACTIVE,
        source_id=source.id,
        raw_document_id=document.id,
        source_url="https://example.test/istat",
    )
    session.add_all((milano, forli))
    session.flush()
    return region, milano, forli


def test_politician_exact_and_surname_and_case_search(session_factory):
    with session_factory() as session:
        _publish(session, "Giorgia", "Meloni")
        _publish(session, "Anna", "Rossi")
        session.commit()
    with session_factory() as session:
        service = SearchService(session)
        exact = service.search("Giorgia Meloni")
        surname = service.search("meloni")
        given = service.search("GIORGIA")
        assert exact.total == 1
        assert exact.items[0].title == "Giorgia Meloni"
        assert exact.items[0].entity_type is SearchEntityType.POLITICIAN
        assert surname.total == 1
        assert given.total == 1
        assert given.normalized_query == "giorgia"


def test_accent_and_de_corato_normalization(session_factory):
    with session_factory() as session:
        source = _source(session)
        document = _document(session, source)
        _territories(session, source, document)
        _publish(session, "Andrea", "De Corato")
        session.commit()
    with session_factory() as session:
        service = SearchService(session)
        assert service.search("forli").items[0].title == "Forlì"
        assert service.search("DE CORATO").items[0].title == "Andrea De Corato"
        assert service.search("de corato").items[0].title == "Andrea De Corato"


def test_municipality_and_region_search(session_factory):
    with session_factory() as session:
        source = _source(session)
        document = _document(session, source)
        _territories(session, source, document)
        session.commit()
    with session_factory() as session:
        service = SearchService(session)
        city = service.search("Milano", entity_type=SearchEntityType.MUNICIPALITY)
        comune = service.search("Comune di Milano", entity_type=SearchEntityType.MUNICIPALITY)
        region = service.search("lombardia", entity_type=SearchEntityType.REGION)
        assert city.items[0].title == "Milano"
        assert city.items[0].metadata["region"] == "Lombardia"
        assert comune.items[0].title == "Milano"
        assert region.items[0].title == "Lombardia"


def test_proposal_title_and_unpublished_exclusion(session_factory):
    with session_factory() as session:
        published = Proposal(
            canonical_title="Synthetic housing transparency proposal",
            summary="A published housing reform summary.",
            proposal_type=ProposalType.LEGISLATIVE_PROPOSAL,
            published_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        )
        hidden = Proposal(
            canonical_title="Hidden housing draft title",
            proposal_type=ProposalType.LEGISLATIVE_PROPOSAL,
        )
        session.add_all((published, hidden))
        session.flush()
        session.add(
            ProposalActor(
                proposal_id=published.id,
                actor_type=ProposalActorType.POLITICIAN,
                role=ProposalActorRole.PROPOSER,
                display_name="Sen. Anna Rossi",
                identity_key="a" * 64,
            )
        )
        session.commit()
    with session_factory() as session:
        service = SearchService(session)
        results = service.search("housing", entity_type=SearchEntityType.PROPOSAL)
        titles = [item.title for item in results.items]
        assert "Synthetic housing transparency proposal" in titles
        assert "Hidden housing draft title" not in titles
        actor = service.search("Anna Rossi", entity_type=SearchEntityType.PROPOSAL)
        assert actor.total == 1


def test_party_group_distinction_and_type_filter(session_factory):
    with session_factory() as session:
        session.add(
            ParliamentaryGroup(
                canonical_name="Fratelli d'Italia",
                abbreviation="FdI",
                institution="Senato della Repubblica",
                legislature="19",
            )
        )
        session.add(
            PoliticalParty(
                canonical_name="Demo Civic Alliance",
                abbreviation="DCA-SYN",
            )
        )
        session.commit()
    with session_factory() as session:
        service = SearchService(session)
        mixed = service.search("italia")
        group = service.search("Fratelli", entity_type=SearchEntityType.PARLIAMENTARY_GROUP)
        party = service.search("Demo Civic Alliance", entity_type=SearchEntityType.POLITICAL_PARTY)
        assert group.items[0].subtitle.startswith("Parliamentary group")
        assert party.items[0].subtitle.startswith("Political party")
        types = {item.entity_type for item in mixed.items}
        assert SearchEntityType.PARLIAMENTARY_GROUP in types
        assert all(item.entity_type is SearchEntityType.POLITICAL_PARTY for item in party.items)


def test_deterministic_ranking_exact_before_prefix(session_factory):
    with session_factory() as session:
        _publish(session, "Andrea", "De Corato")
        _publish(session, "Andrea", "De Coratozzi")
        session.commit()
    with session_factory() as session:
        items = SearchService(session).search("de corato").items
        titles = [item.title for item in items]
        assert titles[0] == "Andrea De Corato"
        assert "Andrea De Coratozzi" in titles


def test_pagination_and_query_validation(session_factory):
    with session_factory() as session:
        source = _source(session)
        document = _document(session, source)
        region = Region(
            istat_code="12",
            canonical_name="Lazio",
            status=TerritoryStatus.ACTIVE,
            source_id=source.id,
            raw_document_id=document.id,
            source_url="https://example.test/istat",
        )
        session.add(region)
        session.flush()
        for index in range(3):
            session.add(
                Municipality(
                    istat_code=f"05800{index}",
                    region_id=region.id,
                    canonical_name=f"Roma {index}",
                    province_abbreviation="RM",
                    province_name="Roma",
                    status=TerritoryStatus.ACTIVE,
                    source_id=source.id,
                    raw_document_id=document.id,
                    source_url="https://example.test/istat",
                )
            )
        session.commit()
    with session_factory() as session:
        service = SearchService(session)
        page = service.search("roma", entity_type=SearchEntityType.MUNICIPALITY, offset=1, limit=1)
        assert page.total == 3
        assert page.offset == 1
        assert len(page.items) == 1
        with pytest.raises(SearchValidationError):
            service.search("   ")
        with pytest.raises(SearchValidationError):
            service.search("x" * 201)
        with pytest.raises(SearchValidationError):
            service.search("roma", limit=99)


def test_internal_entities_are_not_searchable(session_factory):
    with session_factory() as session:
        source = _source(session)
        document = _document(session, source)
        session.add(
            IdentityResolutionCase(
                raw_document_id=document.id,
                source_id=source.id,
                source_identifier="hidden-person",
                candidate_display_name="Carlo Verdi",
                candidate_snapshot={"name": "Carlo Verdi"},
                matching_result_data={"status": "uncertain"},
                status=IdentityResolutionStatus.PENDING,
            )
        )
        unpublished = Proposal(
            canonical_title="Not a public draft title unique xyz",
            proposal_type=ProposalType.LEGISLATIVE_PROPOSAL,
        )
        session.add(unpublished)
        session.flush()
        session.add(
            ProposalDraft(
                proposal_id=unpublished.id,
                raw_document_id=document.id,
                kind=ProposalDraftKind.INITIAL,
                status=ProposalDraftStatus.PENDING,
                observation_hash="e" * 64,
                proposed_data={"title": "Not a public draft title unique xyz"},
            )
        )
        session.commit()
    with session_factory() as session:
        service = SearchService(session)
        assert service.search("Carlo Verdi").total == 0
        assert service.search("unique xyz").total == 0


def test_municipality_scale_stays_paginated(session_factory):
    with session_factory() as session:
        source = _source(session)
        document = _document(session, source)
        region = Region(
            istat_code="03",
            canonical_name="Lombardia",
            status=TerritoryStatus.ACTIVE,
            source_id=source.id,
            raw_document_id=document.id,
            source_url="https://example.test/istat",
        )
        session.add(region)
        session.flush()
        session.add(
            Municipality(
                istat_code="015146",
                region_id=region.id,
                canonical_name="Milano",
                province_abbreviation="MI",
                province_name="Milano",
                status=TerritoryStatus.ACTIVE,
                source_id=source.id,
                raw_document_id=document.id,
                source_url="https://example.test/istat",
            )
        )
        session.add_all(
            [
                Municipality(
                    istat_code=f"{100000 + index:06d}",
                    region_id=region.id,
                    canonical_name=f"Comune{index:04d}",
                    province_abbreviation="MI",
                    province_name="Milano",
                    status=TerritoryStatus.ACTIVE,
                    source_id=source.id,
                    raw_document_id=document.id,
                    source_url="https://example.test/istat",
                )
                for index in range(1, 7894)
            ]
        )
        session.commit()
    with session_factory() as session:
        import time

        started = time.monotonic()
        result = SearchService(session).search(
            "Milano", entity_type=SearchEntityType.MUNICIPALITY, limit=20
        )
        elapsed = time.monotonic() - started
        assert result.total >= 1
        assert result.items[0].title == "Milano"
        assert len(result.items) <= 20
        assert elapsed < 5
