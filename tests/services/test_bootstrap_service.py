from datetime import date, datetime, timezone

import pytest
from sqlalchemy import event, func, select

from backend.app.models import Politician, PoliticianSourceIdentifier
from backend.app.schemas import (
    CandidateIdentity,
    CandidateProfile,
    CandidateProfileData,
    CandidateProvenance,
    MatchingMethod,
    SourceDocumentProvenance,
    SourceIdentifier,
)
from backend.app.services import (
    BootstrapApplyError,
    BootstrapBlockedError,
    BootstrapConflictError,
    CandidateRebuildResult,
    IndexedCandidate,
    PoliticianBootstrapService,
    normalize_person_name,
)


def candidate(
    index: int,
    *,
    identifier: str | None = None,
    authority: str = "senato-repubblica",
    given_name: str = "Maria",
    family_name: str = "Rossi",
    birth_date: date | None = date(1970, 1, 2),
) -> IndexedCandidate:
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
    identifiers = (
        (SourceIdentifier(authority=authority, value=identifier),)
        if identifier is not None
        else ()
    )
    profile = CandidateProfile(
        identity=CandidateIdentity(
            given_name=given_name,
            family_name=family_name,
            birth_date=birth_date,
            birth_place=None,
            source_identifiers=identifiers,
        ),
        profile=CandidateProfileData(mandates=()),
        provenance=CandidateProvenance(document=document, fields=()),
    )
    return IndexedCandidate(index, profile)


def rebuilt(*items: IndexedCandidate) -> CandidateRebuildResult:
    return CandidateRebuildResult(raw_document_id=1, candidates=items, invalid=())


def counts(session_factory) -> tuple[int, int]:
    with session_factory() as session:
        return (
            session.scalar(select(func.count()).select_from(Politician)),
            session.scalar(
                select(func.count()).select_from(PoliticianSourceIdentifier)
            ),
        )


def add_politician(
    session_factory,
    *,
    source=None,
    identifier=None,
    given_name="Maria",
    family_name="Rossi",
    birth_date=date(1970, 1, 2),
) -> int:
    with session_factory() as session:
        politician = Politician(
            canonical_given_name=given_name,
            canonical_family_name=family_name,
            normalized_name=normalize_person_name(given_name, family_name),
            birth_date=birth_date,
        )
        session.add(politician)
        session.flush()
        if identifier is not None:
            session.add(
                PoliticianSourceIdentifier(
                    politician_id=politician.id,
                    source_id=source.id,
                    value=identifier,
                )
            )
        session.commit()
        return politician.id


def test_dry_run_reports_new_details_and_performs_no_writes(session_factory, source):
    service = PoliticianBootstrapService(session_factory)

    plan = service.plan(rebuilt(candidate(0, identifier="senator-100")), dry_run=True)

    assert plan.report.dry_run is True
    assert plan.report.new_count == 1
    assert plan.report.new[0].display_name == "Maria Rossi"
    assert plan.report.new[0].source_identifiers[0].value == "senator-100"
    assert plan.report.politicians_would_create == 1
    assert plan.report.identifiers_would_create == 1
    assert counts(session_factory) == (0, 0)


def test_apply_creates_politicians_and_source_identifiers(session_factory, source):
    service = PoliticianBootstrapService(session_factory)
    plan = service.plan(
        rebuilt(
            candidate(0, identifier="senator-100"),
            candidate(
                1,
                identifier="senator-101",
                given_name="Luca",
                family_name="Bianchi",
            ),
        ),
        dry_run=False,
    )

    report = service.apply(plan)

    assert report.applied is True
    assert report.politicians_created == 2
    assert report.identifiers_created == 2
    assert all(item.created_politician_id for item in report.new)
    assert counts(session_factory) == (2, 2)
    with session_factory() as session:
        stored = list(
            session.scalars(
                select(PoliticianSourceIdentifier).order_by(
                    PoliticianSourceIdentifier.value
                )
            )
        )
        assert [item.value for item in stored] == ["senator-100", "senator-101"]
        assert {item.source_id for item in stored} == {source.id}


def test_matched_candidates_are_reported_and_skipped(session_factory, source):
    politician_id = add_politician(
        session_factory, source=source, identifier="senator-100"
    )
    service = PoliticianBootstrapService(session_factory)

    plan = service.plan(rebuilt(candidate(0, identifier="senator-100")), dry_run=False)
    report = service.apply(plan)

    assert report.matched_count == 1
    assert report.matched[0].politician_id == politician_id
    assert report.matched[0].method is MatchingMethod.OFFICIAL_SOURCE_IDENTIFIER
    assert report.politicians_created == 0
    assert counts(session_factory) == (1, 1)


def test_uncertain_candidate_prevents_all_mutation(session_factory, source):
    first = add_politician(session_factory)
    second = add_politician(session_factory)
    service = PoliticianBootstrapService(session_factory)
    plan = service.plan(
        rebuilt(
            candidate(0, identifier="unknown"),
            candidate(
                1,
                identifier="new",
                given_name="Luca",
                family_name="Bianchi",
            ),
        ),
        dry_run=False,
    )

    assert plan.report.uncertain[0].candidate_politician_ids == (first, second)
    with pytest.raises(BootstrapBlockedError):
        service.apply(plan)
    assert counts(session_factory) == (2, 0)


def test_invalid_candidate_is_reported_and_blocks_apply(session_factory, source):
    service = PoliticianBootstrapService(session_factory)
    plan = service.plan(rebuilt(candidate(0, identifier=None)), dry_run=False)

    assert plan.report.invalid_count == 1
    assert "source identifier" in plan.report.invalid[0].error
    with pytest.raises(BootstrapBlockedError):
        service.apply(plan)
    assert counts(session_factory) == (0, 0)


def test_duplicate_batch_identifiers_mark_every_occurrence_invalid(
    session_factory, source
):
    service = PoliticianBootstrapService(session_factory)
    plan = service.plan(
        rebuilt(
            candidate(0, identifier="duplicate"),
            candidate(
                1,
                identifier="duplicate",
                given_name="Luca",
                family_name="Bianchi",
            ),
        ),
        dry_run=True,
    )

    assert plan.report.invalid_count == 2
    assert plan.report.new_count == 0
    assert {item.candidate_index for item in plan.report.invalid} == {0, 1}
    assert counts(session_factory) == (0, 0)


def test_rerunning_after_apply_is_idempotent(session_factory, source):
    service = PoliticianBootstrapService(session_factory)
    data = rebuilt(candidate(0, identifier="senator-100"))
    service.apply(service.plan(data, dry_run=False))

    second_plan = service.plan(data, dry_run=True)

    assert second_plan.report.new_count == 0
    assert second_plan.report.matched_count == 1
    assert second_plan.report.politicians_would_create == 0
    assert counts(session_factory) == (1, 1)


def test_stale_plan_identifier_conflict_rolls_back(session_factory, source):
    service = PoliticianBootstrapService(session_factory)
    plan = service.plan(
        rebuilt(candidate(0, identifier="senator-100")), dry_run=False
    )
    add_politician(
        session_factory,
        source=source,
        identifier="senator-100",
        given_name="Already",
        family_name="Created",
    )

    with pytest.raises(BootstrapConflictError, match="senator-100"):
        service.apply(plan)

    assert counts(session_factory) == (1, 1)


def test_creation_failure_rolls_back_entire_batch(session_factory, source):
    service = PoliticianBootstrapService(session_factory)
    plan = service.plan(
        rebuilt(
            candidate(0, identifier="senator-100"),
            candidate(
                1,
                identifier="explode",
                given_name="Luca",
                family_name="Bianchi",
            ),
        ),
        dry_run=False,
    )

    def fail_on_second_identifier(mapper, connection, target):
        if target.value == "explode":
            raise RuntimeError("injected failure")

    event.listen(PoliticianSourceIdentifier, "before_insert", fail_on_second_identifier)
    try:
        with pytest.raises(BootstrapApplyError, match="rolled back"):
            service.apply(plan)
    finally:
        event.remove(
            PoliticianSourceIdentifier, "before_insert", fail_on_second_identifier
        )

    assert counts(session_factory) == (0, 0)
