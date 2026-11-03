from datetime import date

from sqlalchemy import func, select

from backend.app.models import (
    IdentityResolutionCase,
    IdentityResolutionStatus,
    Politician,
    PoliticianSourceIdentifier,
)
from backend.app.services import HumanIdentityResolutionCoordinator, normalize_person_name
from scripts.attach_governo_identities import (
    Action,
    apply_attachments,
    plan_attachments,
)
from tests.services.test_identity_resolution_service import (
    add_politician,
    candidate,
    setup_governo_source,
)


def open_case(session_factory, document, **kwargs) -> int:
    incoming = candidate(document, **kwargs)
    result = HumanIdentityResolutionCoordinator(session_factory).process(incoming)
    assert result.case is not None
    return result.case.case_id


def politician_count(session_factory) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(Politician)) or 0


def identifier_values(session_factory, politician_id: int) -> set[str]:
    with session_factory() as session:
        return set(
            session.scalars(
                select(PoliticianSourceIdentifier.value).where(
                    PoliticianSourceIdentifier.politician_id == politician_id
                )
            )
        )


def test_unique_existing_name_is_linked(session_factory):
    _source, document = setup_governo_source(session_factory)
    politician_id = add_politician(
        session_factory,
        given_name="Matteo",
        family_name="Salvini",
        birth_date=date(1973, 3, 9),
    )
    case_id = open_case(
        session_factory,
        document,
        identifier="https://www.governo.it/it/node/20692",
        given_name="Matteo",
        family_name="Salvini",
        display_name="Matteo Salvini",
    )

    plans = plan_attachments(session_factory)
    assert len(plans) == 1
    assert plans[0].action is Action.LINK_EXISTING
    assert plans[0].politician_id == politician_id
    assert plans[0].case_id == case_id

    report = apply_attachments(
        session_factory,
        plans,
        reviewer="operatore-test",
        create_new=False,
        dry_run=False,
    )
    assert [row["display_name"] for row in report.linked] == ["Matteo Salvini"]
    assert report.created == []
    assert report.left_pending == []
    assert "https://www.governo.it/it/node/20692" in identifier_values(
        session_factory, politician_id
    )
    with session_factory() as session:
        stored = session.get(IdentityResolutionCase, case_id)
        assert stored is not None
        assert stored.status is IdentityResolutionStatus.RESOLVED_EXISTING
        assert stored.resolved_politician_id == politician_id


def test_unique_new_name_stays_pending_unless_explicitly_created(session_factory):
    _, document = setup_governo_source(session_factory)
    case_id = open_case(
        session_factory,
        document,
        identifier="https://www.governo.it/it/node/20843",
        given_name="Luigi",
        family_name="D'Eramo",
        display_name="Luigi D’Eramo",
    )

    plans = plan_attachments(session_factory)
    assert plans[0].action is Action.CREATE_NEW
    assert plans[0].case_id == case_id

    skipped = apply_attachments(
        session_factory,
        plans,
        reviewer="operatore-test",
        create_new=False,
        dry_run=False,
    )
    assert skipped.created == []
    assert skipped.left_pending[0]["case_id"] == case_id
    assert politician_count(session_factory) == 0

    created = apply_attachments(
        session_factory,
        plans,
        reviewer="operatore-test",
        create_new=True,
        dry_run=False,
    )
    assert len(created.created) == 1
    assert created.created[0]["politician_id"] is not None
    assert politician_count(session_factory) == 1
    with session_factory() as session:
        politician = session.get(Politician, created.created[0]["politician_id"])
        assert politician is not None
        assert politician.normalized_name == normalize_person_name("Luigi", "D'Eramo")
        stored = session.get(IdentityResolutionCase, case_id)
        assert stored is not None
        assert stored.status is IdentityResolutionStatus.RESOLVED_NEW


def test_name_collision_among_archived_people_stays_pending(session_factory):
    _, document = setup_governo_source(session_factory)
    add_politician(
        session_factory,
        given_name="Mario",
        family_name="Rossi",
        birth_date=date(1950, 1, 1),
    )
    add_politician(
        session_factory,
        given_name="Mario",
        family_name="Rossi",
        birth_date=date(1980, 5, 5),
    )
    open_case(
        session_factory,
        document,
        identifier="https://www.governo.it/it/node/1",
        given_name="Mario",
        family_name="Rossi",
        display_name="Mario Rossi",
    )

    plans = plan_attachments(session_factory)
    assert plans[0].action is Action.LEAVE_PENDING
    assert "more than one archived politician" in plans[0].reason
    report = apply_attachments(
        session_factory,
        plans,
        reviewer="operatore-test",
        create_new=True,
        dry_run=False,
    )
    assert report.linked == []
    assert report.created == []
    assert len(report.left_pending) == 1
    assert politician_count(session_factory) == 2


def test_two_governo_pages_with_the_same_name_stay_pending(session_factory):
    _, document = setup_governo_source(session_factory)
    open_case(
        session_factory,
        document,
        identifier="https://www.governo.it/it/node/10",
        given_name="Paolo",
        family_name="Bianchi",
        display_name="Paolo Bianchi",
    )
    open_case(
        session_factory,
        document,
        identifier="https://www.governo.it/it/node/11",
        given_name="Paolo",
        family_name="Bianchi",
        display_name="Paolo Bianchi",
    )

    plans = plan_attachments(session_factory)
    assert {item.action for item in plans} == {Action.LEAVE_PENDING}
    assert all("two Governo pages" in item.reason for item in plans)


def test_camera_uppercase_name_matches_governo_title_case(session_factory):
    _, document = setup_governo_source(session_factory)
    politician_id = add_politician(
        session_factory,
        given_name="GIORGIA",
        family_name="MELONI",
        birth_date=date(1977, 1, 15),
    )
    open_case(
        session_factory,
        document,
        identifier="https://www.governo.it/it/node/20681",
        given_name="Giorgia",
        family_name="Meloni",
        display_name="Giorgia Meloni",
    )

    plans = plan_attachments(session_factory)
    assert plans[0].action is Action.LINK_EXISTING
    assert plans[0].politician_id == politician_id


def test_dry_run_does_not_write(session_factory):
    _, document = setup_governo_source(session_factory)
    politician_id = add_politician(
        session_factory,
        given_name="Antonio",
        family_name="Tajani",
        birth_date=date(1953, 8, 8),
    )
    case_id = open_case(
        session_factory,
        document,
        identifier="https://www.governo.it/it/node/20682",
        given_name="Antonio",
        family_name="Tajani",
        display_name="Antonio Tajani",
    )

    plans = plan_attachments(session_factory)
    report = apply_attachments(
        session_factory,
        plans,
        reviewer="operatore-test",
        create_new=False,
        dry_run=True,
    )
    assert report.dry_run is True
    assert report.linked[0]["politician_id"] == politician_id
    with session_factory() as session:
        stored = session.get(IdentityResolutionCase, case_id)
        assert stored is not None
        assert stored.status is IdentityResolutionStatus.PENDING
    assert identifier_values(session_factory, politician_id) == set()
