from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings
from backend.app.models import Source
from backend.app.pipeline.collectors import (
    CameraCollector,
    DaitMayorCollector,
    GovernoCollector,
    IstatTerritoryCollector,
    SenatoCollector,
    SenatoProposalCollector,
)
from backend.app.pipeline.ingestion_pipeline import IngestionPipeline
from backend.app.pipeline.mappers import (
    CameraCandidateProfileMapper,
    CameraParliamentaryGroupMapper,
    DaitMayorMapper,
    GovernoCandidateProfileMapper,
    IstatTerritoryMapper,
    SenatoCandidateProfileMapper,
    SenatoParliamentaryGroupMapper,
    SenatoProposalMapper,
)
from backend.app.pipeline.parsers import (
    CameraParser,
    DaitMayorParser,
    GovernoParser,
    IstatTerritoryParser,
    SenatoParser,
    SenatoProposalParser,
)
from backend.app.pipeline.proposal_pipeline import ProposalIngestionPipeline
from backend.app.pipeline.territorial_ingestion import TerritorialRawPipeline
from backend.app.schemas.jobs import IngestionJobMetrics
from backend.app.services import (
    HumanIdentityResolutionCoordinator,
    ParliamentaryGroupService,
    ProposalService,
    TerritorialMandateService,
    TerritoryService,
)
from backend.app.storage import LocalRawStorage


@dataclass(frozen=True, slots=True)
class SourceSpec:
    key: str
    name: str
    base_url: str


POLITICIAN_SOURCES = {
    "senato": SourceSpec(
        "senato-repubblica", "Senato della Repubblica", "https://dati.senato.it"
    ),
    "camera": SourceSpec(
        "camera-deputati", "Camera dei Deputati", "https://dati.camera.it"
    ),
    "governo": SourceSpec(
        "governo-italiano", "Governo Italiano", "https://www.governo.it"
    ),
}


class TransientIngestionError(RuntimeError):
    """A retryable transport/source failure."""


def is_transient_error(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            TimeoutError,
            ConnectionError,
            OSError,
            httpx.TimeoutException,
            httpx.TransportError,
        ),
    ):
        return True
    message = str(exc).casefold()
    return any(
        token in message
        for token in ("timeout", "timed out", "503", "502", "connection reset")
    )


def get_or_create_source(session_factory: sessionmaker[Session], spec: SourceSpec) -> Source:
    with session_factory() as session:
        source = session.scalar(select(Source).where(Source.key == spec.key))
        if source is None:
            source = Source(key=spec.key, name=spec.name, base_url=spec.base_url)
            session.add(source)
            session.commit()
            session.refresh(source)
        return source


def _wrap(call: Callable[[], IngestionJobMetrics]) -> IngestionJobMetrics:
    try:
        return call()
    except Exception as exc:
        if is_transient_error(exc):
            raise TransientIngestionError(str(exc)) from exc
        raise


def run_politician_ingestion(
    settings: Settings,
    session_factory: sessionmaker[Session],
    job_name: str,
) -> IngestionJobMetrics:
    spec = POLITICIAN_SOURCES[job_name]
    source = get_or_create_source(session_factory, spec)
    if job_name == "camera":
        collector = CameraCollector(
            endpoint=settings.camera_sparql_endpoint,
            legislature=settings.camera_legislature,
            timeout_seconds=settings.camera_request_timeout_seconds,
        )
        parser = CameraParser()
        mapper = CameraCandidateProfileMapper()
        group_mapper = CameraParliamentaryGroupMapper(settings.camera_legislature)
    elif job_name == "governo":
        collector = GovernoCollector(
            index_url=settings.governo_index_url,
            timeout_seconds=settings.governo_request_timeout_seconds,
        )
        parser = GovernoParser()
        mapper = GovernoCandidateProfileMapper()
        group_mapper = None
    else:
        collector = SenatoCollector(
            endpoint=settings.senato_sparql_endpoint,
            legislature=settings.senato_legislature,
            timeout_seconds=settings.senato_request_timeout_seconds,
        )
        parser = SenatoParser()
        mapper = SenatoCandidateProfileMapper()
        group_mapper = SenatoParliamentaryGroupMapper()

    def run() -> IngestionJobMetrics:
        result = IngestionPipeline(
            session_factory=session_factory,
            storage=LocalRawStorage(settings.raw_storage_path),
            collector=collector,
            parser=parser,
            profile_mapper=mapper,
            parliamentary_group_mapper=group_mapper,
        ).run(source_id=source.id, source_key=source.key)
        identity_results = tuple(
            HumanIdentityResolutionCoordinator(session_factory).process(candidate)
            for candidate in result.candidate_profiles
        )
        group_result = ParliamentaryGroupService(session_factory).sync(
            result.parliamentary_group_observations
        )
        return IngestionJobMetrics(
            records_processed=len(result.candidate_profiles),
            records_created=group_result.memberships_created + group_result.groups_created,
            records_updated=group_result.memberships_updated,
            records_skipped=group_result.unresolved_references
            + group_result.memberships_unchanged,
            metadata={
                "raw_document_id": result.raw_document_id,
                "change_detected": result.change_detected,
                "identity_cases": sum(item.case is not None for item in identity_results),
            },
        )

    return _wrap(run)


def run_proposal_ingestion(
    settings: Settings, session_factory: sessionmaker[Session]
) -> IngestionJobMetrics:
    spec = SourceSpec(
        "senato-ddl",
        "Senato della Repubblica — Disegni di legge",
        "https://dati.senato.it",
    )
    source = get_or_create_source(session_factory, spec)

    def run() -> IngestionJobMetrics:
        ingestion = ProposalIngestionPipeline(
            session_factory=session_factory,
            storage=LocalRawStorage(settings.raw_storage_path),
            collector=SenatoProposalCollector(
                endpoint=settings.senato_sparql_endpoint,
                legislature=settings.senato_legislature,
                record_limit=settings.senato_proposal_record_limit,
                timeout_seconds=settings.senato_request_timeout_seconds,
            ),
            parser=SenatoProposalParser(),
            mapper=SenatoProposalMapper(),
        ).run(source_id=source.id, source_key=source.key)
        sync = ProposalService(session_factory).sync(ingestion.observations)
        return IngestionJobMetrics(
            records_processed=len(ingestion.observations),
            records_created=sync.proposals_created + sync.drafts_created,
            records_updated=0,
            records_skipped=sync.unchanged,
            metadata={
                "raw_document_id": ingestion.raw_document_id,
                "change_detected": ingestion.change_detected,
                "sync": sync.model_dump(mode="json"),
            },
        )

    return _wrap(run)


def run_territory_ingestion(
    settings: Settings, session_factory: sessionmaker[Session]
) -> IngestionJobMetrics:
    spec = SourceSpec(
        "istat-territories",
        "ISTAT territorial classifications",
        "https://www.istat.it",
    )
    source = get_or_create_source(session_factory, spec)

    def run() -> IngestionJobMetrics:
        raw = TerritorialRawPipeline(
            session_factory,
            LocalRawStorage(settings.raw_storage_path),
            IstatTerritoryCollector(
                settings.istat_municipalities_xlsx_url,
                timeout_seconds=settings.territorial_request_timeout_seconds,
            ),
            IstatTerritoryParser(),
        ).run(source_id=source.id, source_key=source.key)
        regions, municipalities = IstatTerritoryMapper().map_records(
            raw.parsed.structured_records,
            source_key=source.key,
            raw_document_id=raw.raw_document_id,
            source_url=settings.istat_municipalities_xlsx_url,
        )
        sync = TerritoryService(session_factory).sync(regions, municipalities)
        return IngestionJobMetrics(
            records_processed=len(regions) + len(municipalities),
            records_created=sync.regions_created + sync.municipalities_created,
            records_updated=sync.regions_updated + sync.municipalities_updated,
            records_skipped=sync.regions_unchanged + sync.municipalities_unchanged,
            metadata={"raw_document_id": raw.raw_document_id},
        )

    return _wrap(run)


def run_territorial_office_ingestion(
    settings: Settings, session_factory: sessionmaker[Session]
) -> IngestionJobMetrics:
    spec = SourceSpec(
        "dait-current-mayors",
        "DAIT current mayors",
        "https://dait.interno.gov.it",
    )
    source = get_or_create_source(session_factory, spec)

    def run() -> IngestionJobMetrics:
        raw = TerritorialRawPipeline(
            session_factory,
            LocalRawStorage(settings.raw_storage_path),
            DaitMayorCollector(
                settings.dait_current_mayors_csv_url,
                timeout_seconds=settings.territorial_request_timeout_seconds,
            ),
            DaitMayorParser(),
        ).run(source_id=source.id, source_key=source.key)
        mapped = DaitMayorMapper(session_factory).map_records(
            raw.parsed.structured_records, document=raw.provenance
        )
        identity_results = tuple(
            HumanIdentityResolutionCoordinator(session_factory).process(candidate)
            for candidate in mapped.candidates
        )
        sync = TerritorialMandateService(session_factory).sync(mapped.mandates)
        return IngestionJobMetrics(
            records_processed=len(mapped.mandates),
            records_created=sync.mandates_created,
            records_updated=sync.mandates_updated,
            records_skipped=sync.mandates_unchanged
            + sync.unresolved_people
            + sync.unresolved_territories,
            metadata={
                "raw_document_id": raw.raw_document_id,
                "identity_cases": sum(item.case is not None for item in identity_results),
                "unresolved_rows": len(mapped.unresolved_rows),
            },
        )

    return _wrap(run)


def run_civic_reminders(
    settings: Settings, session_factory: sessionmaker[Session]
) -> IngestionJobMetrics:
    del settings

    def run() -> IngestionJobMetrics:
        from backend.app.services.notification_service import NotificationService

        result = NotificationService(session_factory).generate_reminder_candidates()
        return IngestionJobMetrics(
            records_processed=len(result.referendum_ids),
            records_created=result.created,
            records_updated=0,
            records_skipped=result.already_present,
            metadata={"referendum_ids": list(result.referendum_ids)},
        )

    return _wrap(run)


def run_pledge_evidence_matching(
    settings: Settings, session_factory: sessionmaker[Session]
) -> IngestionJobMetrics:
    """Propose fulfilment drafts for open pledges. Never publishes anything.

    The default judge abstains, so the job only exercises retrieval until a
    validated judge is configured (see docs/scoring-methodology.md).
    """

    del settings

    def run() -> IngestionJobMetrics:
        from backend.app.services.pledge_evidence_service import PledgeEvidenceService

        service = PledgeEvidenceService(session_factory)
        report = service.run()
        return IngestionJobMetrics(
            records_processed=report.pledges_considered,
            records_created=report.drafts_created,
            records_updated=0,
            records_skipped=report.drafts_replayed + report.skipped_outcome_pledges,
            metadata={
                "judge": f"{service.judge.name}/{service.judge.version}",
                "passages_judged": report.passages_judged,
                "skipped_outcome_pledges": report.skipped_outcome_pledges,
                "rejections": report.rejections,
            },
        )

    return _wrap(run)
