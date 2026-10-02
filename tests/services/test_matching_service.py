from datetime import date, datetime, timezone

from sqlalchemy import func, select

from backend.app.models import Politician, PoliticianSourceIdentifier
from backend.app.schemas import (
    CandidateIdentity,
    CandidateProfile,
    CandidateProfileData,
    CandidateProvenance,
    MatchedResult,
    MatchingMethod,
    NewMatchReason,
    NewResult,
    SourceDocumentProvenance,
    SourceIdentifier,
    UncertainResult,
)
from backend.app.services import MatchingService, normalize_person_name


def candidate_profile(
    *,
    given_name: str = "Maria",
    family_name: str = "Rossi",
    birth_date: date | None = date(1970, 1, 2),
    identifiers: tuple[tuple[str, str], ...] = (
        ("senato-repubblica", "http://dati.senato.it/senatore/100"),
    ),
) -> CandidateProfile:
    document = SourceDocumentProvenance(
        source_key="senato-repubblica",
        raw_document_id=1,
        source_url="https://dati.senato.it/sparql",
        retrieved_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        raw_sha256="a" * 64,
        normalized_sha256="b" * 64,
        collector_version="senato_collector_v1",
        parser_version="senato_parser_v1",
    )
    return CandidateProfile(
        identity=CandidateIdentity(
            given_name=given_name,
            family_name=family_name,
            birth_date=birth_date,
            birth_place=None,
            source_identifiers=tuple(
                SourceIdentifier(authority=authority, value=value)
                for authority, value in identifiers
            ),
        ),
        profile=CandidateProfileData(mandates=()),
        provenance=CandidateProvenance(document=document, fields=()),
    )


def add_politician(
    session,
    *,
    given_name: str,
    family_name: str,
    birth_date: date | None,
    source=None,
    source_identifier: str | None = None,
) -> Politician:
    politician = Politician(
        canonical_given_name=given_name,
        canonical_family_name=family_name,
        normalized_name=normalize_person_name(given_name, family_name),
        birth_date=birth_date,
    )
    session.add(politician)
    session.flush()
    if source is not None and source_identifier is not None:
        session.add(
            PoliticianSourceIdentifier(
                politician_id=politician.id,
                source_id=source.id,
                value=source_identifier,
            )
        )
    session.commit()
    return politician


def test_exact_official_identifier_match_has_priority(session_factory, source):
    with session_factory() as session:
        politician = add_politician(
            session,
            given_name="Different",
            family_name="Name",
            birth_date=date(1950, 1, 1),
            source=source,
            source_identifier="http://dati.senato.it/senatore/100",
        )

        result = MatchingService(session).match(candidate_profile())

        assert isinstance(result, MatchedResult)
        assert result.politician_id == politician.id
        assert result.method is MatchingMethod.OFFICIAL_SOURCE_IDENTIFIER


def test_fallback_matches_normalized_name_and_birth_date(session_factory, source):
    with session_factory() as session:
        politician = add_politician(
            session,
            given_name="José",
            family_name="D'Angelo",
            birth_date=date(1970, 1, 2),
        )
        candidate = candidate_profile(
            given_name="JOSE",
            family_name="D ANGELO",
            identifiers=(("senato-repubblica", "unknown"),),
        )

        result = MatchingService(session).match(candidate)

        assert isinstance(result, MatchedResult)
        assert result.politician_id == politician.id
        assert result.method is MatchingMethod.NORMALIZED_NAME_BIRTH_DATE


def test_no_match_returns_new(session_factory, source):
    with session_factory() as session:
        result = MatchingService(session).match(candidate_profile())

        assert isinstance(result, NewResult)
        assert result.reason is NewMatchReason.NO_MATCH


def test_missing_birth_date_does_not_use_name_only_fallback(session_factory, source):
    with session_factory() as session:
        add_politician(
            session,
            given_name="Maria",
            family_name="Rossi",
            birth_date=None,
        )

        result = MatchingService(session).match(
            candidate_profile(birth_date=None, identifiers=())
        )

        assert isinstance(result, NewResult)
        assert result.reason is NewMatchReason.INSUFFICIENT_FALLBACK_IDENTITY


def test_ambiguous_fallback_returns_uncertain(session_factory, source):
    with session_factory() as session:
        first = add_politician(
            session,
            given_name="Maria",
            family_name="Rossi",
            birth_date=date(1970, 1, 2),
        )
        second = add_politician(
            session,
            given_name="Maria",
            family_name="Rossi",
            birth_date=date(1970, 1, 2),
        )

        result = MatchingService(session).match(
            candidate_profile(identifiers=(("senato-repubblica", "unknown"),))
        )

        assert isinstance(result, UncertainResult)
        assert result.candidate_politician_ids == tuple(sorted((first.id, second.id)))
        assert result.method is MatchingMethod.NORMALIZED_NAME_BIRTH_DATE


def test_conflicting_exact_identifiers_return_uncertain(session_factory, source):
    with session_factory() as session:
        first = add_politician(
            session,
            given_name="Maria",
            family_name="Rossi",
            birth_date=date(1970, 1, 2),
            source=source,
            source_identifier="identifier-1",
        )
        second = add_politician(
            session,
            given_name="Maria",
            family_name="Rossi",
            birth_date=date(1970, 1, 2),
            source=source,
            source_identifier="identifier-2",
        )
        candidate = candidate_profile(
            identifiers=(
                ("senato-repubblica", "identifier-1"),
                ("senato-repubblica", "identifier-2"),
            )
        )

        result = MatchingService(session).match(candidate)

        assert isinstance(result, UncertainResult)
        assert result.candidate_politician_ids == tuple(sorted((first.id, second.id)))
        assert result.method is MatchingMethod.OFFICIAL_SOURCE_IDENTIFIER


def test_matching_does_not_mutate_database(session_factory, source):
    with session_factory() as session:
        add_politician(
            session,
            given_name="Maria",
            family_name="Rossi",
            birth_date=date(1970, 1, 2),
            source=source,
            source_identifier="http://dati.senato.it/senatore/100",
        )
        counts_before = (
            session.scalar(select(func.count()).select_from(Politician)),
            session.scalar(
                select(func.count()).select_from(PoliticianSourceIdentifier)
            ),
        )

        MatchingService(session).match(candidate_profile())

        counts_after = (
            session.scalar(select(func.count()).select_from(Politician)),
            session.scalar(
                select(func.count()).select_from(PoliticianSourceIdentifier)
            ),
        )
        assert counts_after == counts_before
        assert not session.new
        assert not session.dirty
        assert not session.deleted
