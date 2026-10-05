from datetime import date, datetime, timezone

from sqlalchemy import func, select

from backend.app.models import (
    IdentityResolutionCase,
    Politician,
    TerritorialOfficeMandate,
)
from backend.app.pipeline.mappers import DaitMayorMapper, IstatTerritoryMapper
from backend.app.pipeline.parsers import DaitMayorParser, IstatTerritoryParser
from backend.app.schemas import SourceDocumentProvenance
from backend.app.services import (
    HumanIdentityResolutionCoordinator,
    IdentityResolutionService,
    TerritorialMandateService,
    TerritoryService,
)
from tests.pipeline.test_territorial_ingestion import add_document, istat_xlsx_bytes
from tests.scripts.test_run_territorial_ingestion import FIXTURES


def load_dait(session_factory):
    istat_source, istat_document_id = add_document(
        session_factory, "istat-territories", "application/xlsx"
    )
    parsed_istat = IstatTerritoryParser().parse(istat_xlsx_bytes())
    regions, municipalities = IstatTerritoryMapper().map_records(
        parsed_istat.structured_records,
        source_key=istat_source.key,
        raw_document_id=istat_document_id,
        source_url="https://example.test/istat.xlsx",
    )
    TerritoryService(session_factory).sync(regions, municipalities)
    dait_source, dait_document_id = add_document(
        session_factory, "dait-current-mayors", "text/csv"
    )
    parsed = DaitMayorParser().parse((FIXTURES / "dait_mayors.csv").read_bytes())
    provenance = SourceDocumentProvenance(
        source_key=dait_source.key,
        raw_document_id=dait_document_id,
        source_url="https://dait.interno.gov.it/documenti/sindaciincarica.csv",
        retrieved_at=datetime.now(timezone.utc),
        raw_sha256="c" * 64,
        normalized_sha256="d" * 64,
        collector_version="fixture",
        parser_version=parsed.parser_version,
    )
    mapped = DaitMayorMapper(session_factory).map_records(
        parsed.structured_records, document=provenance
    )
    return mapped


def test_incomplete_identity_creates_case_and_never_links_by_name_only(session_factory):
    mapped = load_dait(session_factory)
    incomplete = next(
        candidate for candidate in mapped.candidates if candidate.identity.birth_date is None
    )
    complete = next(
        candidate
        for candidate in mapped.candidates
        if candidate.identity.birth_date == date(1970, 1, 2)
    )
    coordinator = HumanIdentityResolutionCoordinator(session_factory)
    incomplete_result = coordinator.process(incomplete)
    complete_result = coordinator.process(complete)

    assert incomplete_result.case is not None
    assert complete_result.case is None
    sync = TerritorialMandateService(session_factory).sync(mapped.mandates)
    assert sync.unresolved_people == 2
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Politician)) == 0
        assert session.scalar(select(func.count()).select_from(IdentityResolutionCase)) == 1
        assert session.scalar(select(func.count()).select_from(TerritorialOfficeMandate)) == 0


def test_human_resolution_then_replay_creates_mandate_without_name_only_links(
    session_factory,
):
    mapped = load_dait(session_factory)
    incomplete = next(
        candidate for candidate in mapped.candidates if candidate.identity.birth_date is None
    )
    coordinator = HumanIdentityResolutionCoordinator(session_factory)
    case = coordinator.process(incomplete).case
    assert case is not None
    IdentityResolutionService(session_factory).resolve_as_new(
        case.case_id,
        reviewer_identity="editor",
        note="explicit demo identity decision",
    )
    HumanIdentityResolutionCoordinator(session_factory).process(incomplete)
    sync = TerritorialMandateService(session_factory).sync(mapped.mandates)
    assert sync.mandates_created == 1
    assert sync.unresolved_people == 1
    with session_factory() as session:
        politician = session.scalar(select(Politician))
        mandate = session.scalar(select(TerritorialOfficeMandate))
        assert politician is not None and mandate is not None
        assert politician.canonical_family_name == "Verdi"
        assert mandate.politician_id == politician.id
        assert mandate.municipality.istat_code == "058091"
