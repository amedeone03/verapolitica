from datetime import date, datetime, timezone

from sqlalchemy import func, select

from backend.app.models import (
    Municipality,
    Politician,
    PoliticianSourceIdentifier,
    RawDocument,
    RawDocumentStatus,
    Region,
    Source,
    TerritorialOffice,
    TerritorialOfficeMandate,
    TerritoryStatus,
)
from backend.app.schemas import (
    MunicipalityObservation,
    RegionObservation,
    TerritorialMandateObservation,
    TerritorialMandatePersistenceStatus,
)
from backend.app.services import (
    TerritorialMandateService,
    TerritoryService,
    normalize_person_name,
)


def setup_source(session_factory):
    with session_factory() as session:
        source = Source(
            key="istat-territories",
            name="ISTAT / DAIT fixture",
            base_url="https://example.test",
        )
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
            source_url="https://example.test/source",
            content_type="application/octet-stream",
            storage_key="territories/fixture",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="fixture",
            parser_version="fixture",
        )
        session.add(document)
        session.commit()
        return document.id


def region(document_id, *, name="Lombardia", status=TerritoryStatus.ACTIVE, until=None):
    return RegionObservation(
        source_key="istat-territories",
        raw_document_id=document_id,
        istat_code="03",
        canonical_name=name,
        status=status,
        active_until=until,
        source_url="https://example.test/istat",
    )


def municipality(document_id, *, name="Milano"):
    return MunicipalityObservation(
        source_key="istat-territories",
        raw_document_id=document_id,
        istat_code="015146",
        region_istat_code="03",
        canonical_name=name,
        province_abbreviation="mi",
        province_name="Milano",
        source_url="https://example.test/istat",
    )


def test_code_identity_hierarchy_replay_rename_and_inactive_retention(session_factory):
    document_id = setup_source(session_factory)
    service = TerritoryService(session_factory)

    first = service.sync((region(document_id),), (municipality(document_id),))
    replay = service.sync((region(document_id),), (municipality(document_id),))
    renamed = service.sync(
        (
            region(
                document_id,
                name="Lombardia storica",
                status=TerritoryStatus.INACTIVE,
                until=date(2026, 1, 1),
            ),
        ),
        (municipality(document_id, name="Milano Città"),),
    )

    assert first.regions_created == first.municipalities_created == 1
    assert replay.regions_unchanged == replay.municipalities_unchanged == 1
    assert renamed.regions_updated == renamed.municipalities_updated == 1
    with session_factory() as session:
        stored_region = session.scalar(select(Region))
        stored_municipality = session.scalar(select(Municipality))
        assert stored_region is not None and stored_municipality is not None
        assert stored_region.istat_code == "03"
        assert stored_region.status is TerritoryStatus.INACTIVE
        assert stored_municipality.region_id == stored_region.id
        assert stored_municipality.province_abbreviation == "MI"
        assert stored_municipality.canonical_name == "Milano Città"


def add_people(session_factory):
    with session_factory() as session:
        source = session.scalar(select(Source))
        assert source is not None
        maria = Politician(
            canonical_given_name="Maria",
            canonical_family_name="Rossi",
            normalized_name=normalize_person_name("Maria", "Rossi"),
            birth_date=date(1970, 1, 2),
        )
        luca = Politician(
            canonical_given_name="Luca",
            canonical_family_name="Bianchi",
            normalized_name=normalize_person_name("Luca", "Bianchi"),
            birth_date=date(1980, 3, 4),
        )
        session.add_all((maria, luca))
        session.flush()
        session.add(
            PoliticianSourceIdentifier(
                politician_id=maria.id,
                source_id=source.id,
                value="dait:maria-rossi",
            )
        )
        session.commit()
        return maria.id, luca.id


def mandate(
    document_id,
    *,
    given="Maria",
    family="Rossi",
    birth=date(1970, 1, 2),
    person_identifier="dait:maria-rossi",
    source_identifier="record-1",
    start=date(2024, 1, 1),
    end=None,
):
    return TerritorialMandateObservation(
        source_key="istat-territories",
        raw_document_id=document_id,
        office=TerritorialOffice.MAYOR,
        municipality_istat_code="015146",
        politician_source_identifier=person_identifier,
        given_name=given,
        family_name=family,
        birth_date=birth,
        source_identifier=source_identifier,
        start_date=start,
        end_date=end,
        source_url="https://example.test/dait",
    )


def test_mandate_create_replay_end_date_transition_and_exact_matching(session_factory):
    document_id = setup_source(session_factory)
    TerritoryService(session_factory).sync(
        (region(document_id),), (municipality(document_id),)
    )
    maria_id, luca_id = add_people(session_factory)
    service = TerritorialMandateService(session_factory)

    created = service.sync((mandate(document_id),))
    replay = service.sync((mandate(document_id),))
    ended = service.sync((mandate(document_id, end=date(2025, 5, 31)),))
    transitioned = service.sync(
        (
            mandate(
                document_id,
                given="Luca",
                family="Bianchi",
                birth=date(1980, 3, 4),
                person_identifier=None,
                source_identifier="record-2",
                start=date(2025, 6, 1),
            ),
        )
    )

    assert created.mandates_created == 1
    assert replay.mandates_unchanged == 1
    assert ended.mandates_updated == 1
    assert transitioned.mandates_created == 1
    with session_factory() as session:
        rows = list(
            session.scalars(
                select(TerritorialOfficeMandate).order_by(
                    TerritorialOfficeMandate.start_date
                )
            )
        )
        assert [row.politician_id for row in rows] == [maria_id, luca_id]
        assert rows[0].end_date == date(2025, 5, 31)

    unresolved = service.sync(
        (
            mandate(
                document_id,
                given="Unknown",
                family="Person",
                birth=None,
                person_identifier=None,
                source_identifier="record-3",
            ),
        )
    )
    assert unresolved.unresolved_people == 1
    assert (
        unresolved.details[0].status
        is TerritorialMandatePersistenceStatus.UNRESOLVED_POLITICIAN
    )
    with session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(TerritorialOfficeMandate))
            == 2
        )
