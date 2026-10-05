from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select

from backend.app.models import (
    Evidence,
    Politician,
    PoliticianSourceIdentifier,
    PoliticianVersion,
    ProfileDraft,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.pipeline.mappers import GovernoCandidateProfileMapper
from backend.app.pipeline.parsers import GovernoParser
from backend.app.schemas import MatchedResult, MatchingMethod, SourceDocumentProvenance
from backend.app.services import (
    CandidateIdentityCoordinator,
    DraftService,
    MatchingService,
    candidate_to_version_profile,
    normalize_person_name,
)


def add_governo_candidate(session_factory, *, name="Mario Rossi"):
    content = Path("data/fixtures/governo/governo_office_holders.json").read_bytes()
    record = next(
        record
        for record in GovernoParser().parse(content).structured_records
        if record["display_name"] == name
    )
    with session_factory() as session:
        source = Source(
            key="governo-italiano",
            name="Governo Italiano",
            base_url="https://www.governo.it",
        )
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
            source_url="https://www.governo.it/it/ministri-e-sottosegretari",
            content_type="application/vnd.verapolitica.governo-bundle+json",
            storage_key="governo/fixture.json",
            raw_sha256="e" * 64,
            normalized_sha256="f" * 64,
            structured_records=[record],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="governo_collector_v1",
            parser_version="governo_parser_v1",
        )
        session.add(document)
        session.commit()
        document_id = document.id
    candidate = GovernoCandidateProfileMapper().map_records(
        (record,),
        document=SourceDocumentProvenance(
            source_key="governo-italiano",
            raw_document_id=document_id,
            source_url="https://www.governo.it/it/ministri-e-sottosegretari",
            retrieved_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
            raw_sha256="e" * 64,
            normalized_sha256="f" * 64,
            collector_version="governo_collector_v1",
            parser_version="governo_parser_v1",
        ),
    )[0]
    return candidate, document_id


def add_existing_senato_identity(session_factory, source, *, duplicate=False):
    ids = []
    with session_factory() as session:
        for sequence in range(2 if duplicate else 1):
            politician = Politician(
                canonical_given_name="Mario",
                canonical_family_name="Rossi",
                normalized_name=normalize_person_name("Mario", "Rossi"),
                birth_date=date(1970, 1, 1),
            )
            politician.source_identifiers.append(
                PoliticianSourceIdentifier(
                    source_id=source.id,
                    value=f"senato-person-{sequence + 123}",
                )
            )
            session.add(politician)
            session.flush()
            ids.append(politician.id)
        session.commit()
    return ids


def test_governo_fallback_links_to_senato_identity_then_matches_exactly(
    session_factory, source
):
    candidate, _ = add_governo_candidate(session_factory)
    politician_id = add_existing_senato_identity(session_factory, source)[0]

    first = CandidateIdentityCoordinator(session_factory).match_and_link(candidate)
    with session_factory() as session:
        second = MatchingService(session).match(candidate)

    assert first.match == MatchedResult(
        politician_id=politician_id,
        method=MatchingMethod.NORMALIZED_NAME_BIRTH_DATE,
    )
    assert first.attachments[0].status.value == "attached"
    assert second == MatchedResult(
        politician_id=politician_id,
        method=MatchingMethod.OFFICIAL_SOURCE_IDENTIFIER,
    )


def test_ambiguous_governo_identity_does_not_attach(session_factory, source):
    candidate, _ = add_governo_candidate(session_factory)
    add_existing_senato_identity(session_factory, source, duplicate=True)

    resolution = CandidateIdentityCoordinator(session_factory).match_and_link(candidate)

    assert resolution.match.status.value == "uncertain"
    assert resolution.attachments == ()
    with session_factory() as session:
        governo = session.scalar(select(Source).where(Source.key == "governo-italiano"))
        assert session.scalar(
            select(PoliticianSourceIdentifier).where(
                PoliticianSourceIdentifier.source_id == governo.id
            )
        ) is None


def test_governo_conflict_becomes_reviewable_diff_with_exact_page_evidence(
    session_factory, source
):
    candidate, _ = add_governo_candidate(session_factory)
    politician_id = add_existing_senato_identity(session_factory, source)[0]
    with session_factory() as session:
        politician = session.get(Politician, politician_id)
        baseline = candidate_to_version_profile(candidate).model_dump(mode="json")
        baseline["birth_place"] = {
            "city": "Milano",
            "subdivision": None,
            "country": None,
        }
        version = PoliticianVersion(
            politician_id=politician_id,
            version_number=1,
            profile_schema_version=1,
            profile_data=baseline,
            published_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        )
        session.add(version)
        session.flush()
        politician.current_version_id = version.id
        session.commit()

    resolution = CandidateIdentityCoordinator(session_factory).match_and_link(candidate)
    result = DraftService(session_factory).create(candidate, resolution.match)

    assert [change.field_path for change in result.diff.changes] == [
        "birth_place.city"
    ]
    with session_factory() as session:
        draft = session.get(ProfileDraft, result.draft_id)
        evidence = session.scalars(
            select(Evidence).where(Evidence.draft_id == draft.id)
        ).all()
        assert evidence
        assert {item.source_url for item in evidence} == {
            "https://www.governo.it/it/governo/meloni/presidente-del-consiglio/mario-rossi"
        }
        assert draft.raw_document.source.name == "Governo Italiano"
