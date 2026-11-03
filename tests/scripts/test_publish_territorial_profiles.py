from datetime import date, datetime, timezone

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    Municipality,
    Politician,
    PoliticianVersion,
    ProfileDraft,
    ProfileDraftKind,
    ProfileDraftStatus,
    RawDocument,
    RawDocumentStatus,
    Region,
    Source,
    TerritorialOffice,
    TerritorialOfficeMandate,
)
from backend.app.models.territory import TerritoryStatus
from backend.app.services import normalize_person_name
from scripts.publish_territorial_profiles import publish


def test_publish_territorial_profiles_approves_pending_lazio_mayor(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'offices.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with factory() as session:
        source = Source(key="dait-current-mayors", name="DAIT", base_url="https://dait.interno.gov.it")
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=now,
            source_url="https://dait.interno.gov.it/elezioni/anagrafe-amministratori",
            content_type="text/csv",
            storage_key="dait/fixture.bin",
            raw_sha256="a" * 64,
            process_status=RawDocumentStatus.PARSED,
            collector_version="dait_v1",
            parser_version="dait_v1",
        )
        session.add(document)
        session.flush()
        region = Region(
            istat_code="12",
            canonical_name="Lazio",
            status=TerritoryStatus.ACTIVE,
            source_id=source.id,
            raw_document_id=document.id,
            source_url="https://www.istat.it",
        )
        session.add(region)
        session.flush()
        town = Municipality(
            istat_code="058091",
            region_id=region.id,
            canonical_name="Roma",
            province_abbreviation="RM",
            province_name="Roma",
            status=TerritoryStatus.ACTIVE,
            source_id=source.id,
            raw_document_id=document.id,
            source_url="https://www.istat.it",
        )
        politician = Politician(
            canonical_given_name="Roberto",
            canonical_family_name="Gualtieri",
            normalized_name=normalize_person_name("Roberto", "Gualtieri"),
            birth_date=date(1966, 7, 22),
        )
        session.add_all((town, politician))
        session.flush()
        session.add(
            TerritorialOfficeMandate(
                politician_id=politician.id,
                office=TerritorialOffice.MAYOR,
                municipality_id=town.id,
                source_id=source.id,
                raw_document_id=document.id,
                identity_key="b" * 64,
                source_url="https://dait.interno.gov.it/elezioni/anagrafe-amministratori",
                start_date=date(2021, 10, 21),
            )
        )
        session.add(
            ProfileDraft(
                politician_id=politician.id,
                raw_document_id=document.id,
                kind=ProfileDraftKind.INITIAL,
                status=ProfileDraftStatus.PENDING,
                profile_schema_version=1,
                proposed_profile_data={
                    "given_name": "Roberto",
                    "family_name": "Gualtieri",
                    "mandates": [],
                },
                diff_data={"status": "initial", "changes": []},
            )
        )
        session.commit()
        politician_id = politician.id

    dry = publish(factory, region="Lazio", reviewer="Verificatore", dry_run=True)
    assert dry.errors == []
    assert any("Gualtieri" in line for line in dry.published)

    applied = publish(factory, region="Lazio", reviewer="Verificatore", dry_run=False)
    assert applied.errors == []
    assert any("Gualtieri" in line for line in applied.published)
    with factory() as session:
        politician = session.get(Politician, politician_id)
        version = session.get(PoliticianVersion, politician.current_version_id)
        assert version is not None
        assert version.published_at is not None

    again = publish(factory, region="Lazio", reviewer="Verificatore", dry_run=False)
    assert any("già pubblicato" in line for line in again.skipped)
    engine.dispose()


def test_publish_territorial_profiles_reports_missing_region(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    report = publish(factory, region="Lazio", reviewer="Verificatore", dry_run=True)
    assert any("assente" in line for line in report.errors)
    engine.dispose()
