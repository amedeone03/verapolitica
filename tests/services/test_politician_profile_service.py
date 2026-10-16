from datetime import date, datetime, timezone

from backend.app.models import Politician, PoliticianVersion
from backend.app.models.politician_profile import (
    PoliticianBiography,
    PoliticianProceeding,
    ProceedingType,
    ProfileContentKind,
    ProfileContentStatus,
    ProfileSourceKind,
)
from backend.app.schemas.politician_profile import (
    BiographyDraftInput,
    PositionDraftInput,
    ProceedingDraftInput,
    ProfileSourceInput,
)
from backend.app.scoring.types import DUAL_APPROVAL_VERDICTS, FulfillmentVerdict
from backend.app.services import (
    PoliticianProfileConflictError,
    PoliticianProfileService,
    PoliticianProfileValidationError,
    normalize_person_name,
)


NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


def _politician(session_factory) -> int:
    with session_factory() as session:
        person = Politician(
            canonical_given_name="Giorgia",
            canonical_family_name="Meloni",
            normalized_name=normalize_person_name("Giorgia", "Meloni"),
            birth_date=date(1977, 1, 15),
        )
        session.add(person)
        session.flush()
        version = PoliticianVersion(
            politician_id=person.id,
            version_number=1,
            profile_schema_version=1,
            profile_data={"given_name": "Giorgia", "family_name": "Meloni", "mandates": []},
            published_at=NOW,
        )
        session.add(version)
        session.flush()
        person.current_version = version
        session.commit()
        return person.id


def test_biography_stays_pending_until_approval(session_factory):
    politician_id = _politician(session_factory)
    service = PoliticianProfileService(session_factory)
    content_id, created = service.upsert_biography(
        politician_id,
        BiographyDraftInput(
            identity_key="primary",
            body="Testo biografico con fonte.",
            sources=(
                ProfileSourceInput(
                    name="Presidenza del Consiglio",
                    kind=ProfileSourceKind.OFFICIAL,
                    url="https://presidenza.governo.it/curriculum.pdf",
                ),
            ),
            created_by="editor",
        ),
    )
    assert created == "created"
    with session_factory() as session:
        assert PoliticianProfileService.published_biography(session, politician_id) is None
        row = session.get(PoliticianBiography, content_id)
        assert row.status is ProfileContentStatus.PENDING
    again, skipped = service.upsert_biography(
        politician_id,
        BiographyDraftInput(
            identity_key="primary",
            body="Altro testo",
            created_by="editor",
        ),
    )
    assert skipped == "skipped" and again == content_id
    detail = service.approve(ProfileContentKind.BIOGRAPHY, content_id, reviewer="desk")
    assert detail.status is ProfileContentStatus.PUBLISHED
    with session_factory() as session:
        published = PoliticianProfileService.published_biography(session, politician_id)
        assert published is not None
        assert published.body.startswith("Testo biografico")
        assert published.sources[0].kind is ProfileSourceKind.OFFICIAL


def test_position_and_proceeding_publication_boundaries(session_factory):
    politician_id = _politician(session_factory)
    service = PoliticianProfileService(session_factory)
    position_id, _ = service.upsert_position(
        politician_id,
        PositionDraftInput(
            identity_key="immigrazione",
            topic="Immigrazione",
            position_statement="Posizione neutrale.",
            verifiable_statement="Dichiarazione verificabile del 16 maggio 2026.",
            statement_date=date(2026, 5, 16),
            sources=(
                ProfileSourceInput(
                    name="Corriere della Sera",
                    kind=ProfileSourceKind.NEWS,
                    url="https://roma.corriere.it/notizie/example",
                ),
            ),
            created_by="editor",
        ),
    )
    proceeding_id, _ = service.upsert_proceeding(
        politician_id,
        ProceedingDraftInput(
            identity_key="caso-almasri-2025",
            title="Caso Almasri (2025)",
            proceeding_types=(ProceedingType.JUDICIAL_PROCEEDING,),
            outcome="archived",
            summary="Iscrizione nel registro degli indagati, poi archiviazione.",
            outcome_summary="Archiviato. Elementi insufficienti per un coinvolgimento penalmente rilevante.",
            sources=(ProfileSourceInput(name="ANSA", kind=ProfileSourceKind.NEWS),),
            created_by="editor",
        ),
    )
    with session_factory() as session:
        assert PoliticianProfileService.published_positions(session, politician_id) == ()
        assert PoliticianProfileService.published_proceedings(session, politician_id) == ()
        row = session.get(PoliticianProceeding, proceeding_id)
        assert row.proceeding_types == ["judicial_proceeding"]
        assert row.outcome.value == "archived"
    service.approve(ProfileContentKind.POSITION, position_id, reviewer="desk")
    service.approve(ProfileContentKind.PROCEEDING, proceeding_id, reviewer="desk")
    with session_factory() as session:
        positions = PoliticianProfileService.published_positions(session, politician_id)
        proceedings = PoliticianProfileService.published_proceedings(session, politician_id)
        assert positions[0].sources[0].kind is ProfileSourceKind.NEWS
        assert proceedings[0].proceeding_types == (ProceedingType.JUDICIAL_PROCEEDING,)
        assert proceedings[0].outcome.value == "archived"
        assert "penalmente rilevante" in proceedings[0].outcome_summary


def test_reject_keeps_record_off_the_public_surface(session_factory):
    politician_id = _politician(session_factory)
    service = PoliticianProfileService(session_factory)
    content_id, _ = service.upsert_biography(
        politician_id,
        BiographyDraftInput(identity_key="primary", body="Bozza rifiutata.", created_by="editor"),
    )
    service.reject(ProfileContentKind.BIOGRAPHY, content_id, reviewer="desk", note="fonte incompleta")
    with session_factory() as session:
        assert PoliticianProfileService.published_biography(session, politician_id) is None
        assert session.get(PoliticianBiography, content_id).status is ProfileContentStatus.REJECTED


def test_published_biography_is_replaced_by_a_new_pending_draft(session_factory):
    politician_id = _politician(session_factory)
    service = PoliticianProfileService(session_factory)
    first_id, _ = service.upsert_biography(
        politician_id,
        BiographyDraftInput(
            identity_key="primary",
            body="guida il governo italiano dal 22 ottobre 2022.",
            sources=(
                ProfileSourceInput(
                    name="Presidenza del Consiglio",
                    kind=ProfileSourceKind.OFFICIAL,
                    url="https://presidenza.governo.it/curriculum.pdf",
                ),
            ),
            created_by="editor",
        ),
    )
    service.approve(ProfileContentKind.BIOGRAPHY, first_id, reviewer="desk")
    second_id, created = service.upsert_biography(
        politician_id,
        BiographyDraftInput(
            identity_key="primary",
            body="guida il governo italiano dall’ottobre 2022.",
            sources=(
                ProfileSourceInput(
                    name="Presidenza del Consiglio",
                    kind=ProfileSourceKind.OFFICIAL,
                    url="https://presidenza.governo.it/curriculum.pdf",
                ),
            ),
            created_by="editor",
        ),
    )
    assert created == "created"
    assert second_id != first_id
    service.approve(ProfileContentKind.BIOGRAPHY, second_id, reviewer="desk")
    with session_factory() as session:
        previous = session.get(PoliticianBiography, first_id)
        current = PoliticianProfileService.published_biography(session, politician_id)
        assert previous.status is ProfileContentStatus.SUPERSEDED
        assert "dall’ottobre 2022" in current.body
        assert "22 ottobre 2022" not in current.body


def test_attach_source_url_validates_and_does_not_publish(session_factory):
    politician_id = _politician(session_factory)
    service = PoliticianProfileService(session_factory)
    proceeding_id, _ = service.upsert_proceeding(
        politician_id,
        ProceedingDraftInput(
            identity_key="caso-almasri-2025",
            title="Caso Almasri (2025)",
            proceeding_types=(ProceedingType.JUDICIAL_PROCEEDING,),
            outcome="archived",
            summary="Iscrizione nel registro degli indagati, poi archiviazione.",
            sources=(ProfileSourceInput(name="ANSA", kind=ProfileSourceKind.NEWS),),
            created_by="editor",
        ),
    )
    detail = service.get_admin(ProfileContentKind.PROCEEDING, proceeding_id)
    source_id = detail.source_ids[0]
    try:
        service.attach_source_url(
            ProfileContentKind.PROCEEDING,
            proceeding_id,
            source_id,
            "not-a-url",
            reviewer="desk",
        )
    except PoliticianProfileValidationError:
        pass
    else:
        raise AssertionError("expected invalid URL to fail")
    updated = service.attach_source_url(
        ProfileContentKind.PROCEEDING,
        proceeding_id,
        source_id,
        "https://www.ansa.it/sito/notizie/example.html",
        reviewer="desk",
    )
    assert updated.status is ProfileContentStatus.PENDING
    assert updated.sources_incomplete is False
    with session_factory() as session:
        assert PoliticianProfileService.published_proceedings(session, politician_id) == ()
    service.approve(ProfileContentKind.PROCEEDING, proceeding_id, reviewer="desk")
    try:
        service.attach_source_url(
            ProfileContentKind.PROCEEDING,
            proceeding_id,
            source_id,
            "https://www.ansa.it/sito/notizie/other.html",
            reviewer="desk",
        )
    except PoliticianProfileConflictError:
        pass
    else:
        raise AssertionError("expected published attach to fail")


def test_cannot_approve_twice(session_factory):
    politician_id = _politician(session_factory)
    service = PoliticianProfileService(session_factory)
    content_id, _ = service.upsert_biography(
        politician_id,
        BiographyDraftInput(identity_key="primary", body="Testo.", created_by="editor"),
    )
    service.approve(ProfileContentKind.BIOGRAPHY, content_id, reviewer="desk")
    try:
        service.approve(ProfileContentKind.BIOGRAPHY, content_id, reviewer="desk-2")
    except PoliticianProfileConflictError:
        pass
    else:
        raise AssertionError("expected conflict")


def test_broken_still_requires_two_reviewers():
    assert FulfillmentVerdict.BROKEN in DUAL_APPROVAL_VERDICTS
    assert len(DUAL_APPROVAL_VERDICTS) == 1
