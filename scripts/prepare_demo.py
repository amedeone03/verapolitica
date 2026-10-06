from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
import json
import shutil

from sqlalchemy import func, select

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    AIExtractionCandidate,
    AIExtractionCandidateEvidence,
    AIExtractionCandidateStatus,
    AIExtractionRun,
    AIExtractionRunStatus,
    DocumentChunk,
    Evidence,
    IdentityResolutionCase,
    IdentityResolutionStatus,
    Politician,
    PoliticianVersion,
    PoliticianVersionCitation,
    PoliticalParty,
    ProfileDraft,
    ProfileDraftStatus,
    Proposal,
    ProposalDraft,
    RawDocument,
    RawDocumentStatus,
    Source,
    TerritorialOffice,
)
from backend.app.pipeline.civic import map_referendum_fixture
from backend.app.pipeline.collectors import CollectedDocument
from backend.app.pipeline.ingestion_pipeline import IngestionPipeline
from backend.app.pipeline.mappers import (
    GovernoCandidateProfileMapper,
    SenatoCandidateProfileMapper,
)
from backend.app.pipeline.parsers import GovernoParser, SenatoParser
from backend.app.schemas import (
    DraftCreatedResult,
    GlossaryTermInput,
    MatchedResult,
    MunicipalityObservation,
    ParliamentaryGroupObservation,
    PoliticianVersionProfile,
    ProposalActorObservation,
    ProposalEvidenceObservation,
    ProposalObservation,
    RegionObservation,
    TerritorialMandateObservation,
    VotingGuideInput,
    VotingGuideSection,
)
from backend.app.services import (
    CandidateRebuildResult,
    DraftService,
    HumanIdentityResolutionCoordinator,
    IndexedCandidate,
    MatchingService,
    ParliamentaryGroupService,
    PoliticianBootstrapService,
    PublishService,
    ProposalReviewService,
    ProposalService,
    TerritorialMandateService,
    TerritoryService,
    CivicContentService,
    ReferendumReviewService,
    ReferendumService,
    normalize_person_name,
)
from backend.app.storage import LocalRawStorage


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = REPOSITORY_ROOT / "data" / "fixtures" / "demo" / "senato_demo.json"
DEFAULT_GOVERNO_FIXTURE = (
    REPOSITORY_ROOT
    / "data"
    / "fixtures"
    / "governo"
    / "governo_office_holders.json"
)
SOURCE_KEY = "senato-repubblica"
SOURCE_NAME = "Senato della Repubblica"
SOURCE_BASE_URL = "https://dati.senato.it"
SOURCE_DOCUMENT_URL = "https://dati.senato.it/sparql"
DEMO_ADMIN_KEY = "verapolitica-demo-admin"
DEMO_REVIEWER = "demo-presenter"


class DemoSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class DemoPaths:
    workspace_root: Path
    demo_root: Path
    database: Path
    raw_storage: Path

    @classmethod
    def for_workspace(cls, workspace_root: Path) -> "DemoPaths":
        workspace = workspace_root.expanduser().resolve()
        demo_root = workspace / "data" / "demo"
        return cls(
            workspace_root=workspace,
            demo_root=demo_root,
            database=demo_root / "verapolitica_demo.db",
            raw_storage=demo_root / "raw",
        )


@dataclass(frozen=True)
class DemoSummary:
    database_path: Path
    raw_storage_path: Path
    published_politician_id: int
    published_name: str
    published_version_number: int
    published_citation_count: int
    pending_draft_id: int
    pending_politician_id: int
    pending_name: str
    pending_status: ProfileDraftStatus
    pending_evidence_count: int
    identity_resolution_case_id: int
    identity_resolution_name: str
    identity_resolution_status: IdentityResolutionStatus
    published_proposal_id: int
    pending_proposal_draft_id: int
    published_referendum_id: int
    pending_referendum_draft_id: int


class FixtureCollector:
    def __init__(
        self,
        fixture_path: Path,
        *,
        source_url: str = SOURCE_DOCUMENT_URL,
        content_type: str = "application/sparql-results+json",
        version: str = "senato_demo_fixture_v1",
    ) -> None:
        self.fixture_path = fixture_path
        self.source_url = source_url
        self.content_type = content_type
        self.version = version

    def collect(self) -> CollectedDocument:
        return CollectedDocument(
            content=self.fixture_path.read_bytes(),
            source_url=self.source_url,
            content_type=self.content_type,
            retrieved_at=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
            collector_version=self.version,
        )


def reset_demo_environment(paths: DemoPaths) -> None:
    _validate_demo_paths(paths)
    if paths.demo_root.is_symlink():
        raise DemoSafetyError("demo root must not be a symbolic link")
    if paths.database.is_symlink():
        raise DemoSafetyError("demo database must not be a symbolic link")
    if paths.raw_storage.is_symlink():
        raise DemoSafetyError("demo raw storage must not be a symbolic link")

    for database_file in (
        paths.database,
        Path(f"{paths.database}-shm"),
        Path(f"{paths.database}-wal"),
    ):
        if database_file.exists():
            if not database_file.is_file():
                raise DemoSafetyError(f"refusing to remove non-file {database_file}")
            database_file.unlink()

    if paths.raw_storage.exists():
        if not paths.raw_storage.is_dir():
            raise DemoSafetyError("demo raw-storage target is not a directory")
        shutil.rmtree(paths.raw_storage)
    paths.demo_root.mkdir(parents=True, exist_ok=True)


def prepare_demo(
    *,
    workspace_root: Path = REPOSITORY_ROOT,
    fixture_path: Path = DEFAULT_FIXTURE,
    governo_fixture_path: Path = DEFAULT_GOVERNO_FIXTURE,
) -> DemoSummary:
    paths = DemoPaths.for_workspace(workspace_root)
    reset_demo_environment(paths)
    fixture = fixture_path.expanduser().resolve()
    if not fixture.is_file():
        raise FileNotFoundError(f"demo fixture does not exist: {fixture}")
    governo_fixture = governo_fixture_path.expanduser().resolve()
    if not governo_fixture.is_file():
        raise FileNotFoundError(
            f"Governo demo fixture does not exist: {governo_fixture}"
        )

    engine = create_db_engine(f"sqlite:///{paths.database}")
    try:
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            source = Source(
                key=SOURCE_KEY,
                name=SOURCE_NAME,
                base_url=SOURCE_BASE_URL,
            )
            session.add(source)
            session.commit()
            source_id = source.id

        ingestion = IngestionPipeline(
            session_factory=session_factory,
            storage=LocalRawStorage(paths.raw_storage),
            collector=FixtureCollector(fixture),
            parser=SenatoParser(),
            profile_mapper=SenatoCandidateProfileMapper(),
        ).run(source_id=source_id, source_key=SOURCE_KEY)
        if len(ingestion.candidate_profiles) != 2:
            raise RuntimeError("demo fixture must produce exactly two candidates")

        rebuilt = CandidateRebuildResult(
            raw_document_id=ingestion.raw_document_id,
            candidates=tuple(
                IndexedCandidate(candidate_index=index, profile=candidate)
                for index, candidate in enumerate(ingestion.candidate_profiles)
            ),
            invalid=(),
        )
        bootstrap = PoliticianBootstrapService(session_factory)
        bootstrap.apply(bootstrap.plan(rebuilt, dry_run=False))
        group_observations = tuple(
            ParliamentaryGroupObservation(
                source_key=SOURCE_KEY,
                raw_document_id=ingestion.raw_document_id,
                politician_source_identifier=(
                    candidate.identity.source_identifiers[0].value
                ),
                group_source_identifier=(
                    "https://dati.senato.it/gruppo/demo-fdi"
                    if index == 0
                    else "https://dati.senato.it/gruppo/demo-misto"
                ),
                canonical_name=("Fratelli d'Italia" if index == 0 else "Misto"),
                abbreviation=("FdI" if index == 0 else "Misto"),
                institution="Senato della Repubblica",
                legislature="19",
                start_date=datetime(2022, 10, 18).date(),
                source_url=candidate.identity.source_identifiers[0].value,
                role="Membro",
            )
            for index, candidate in enumerate(ingestion.candidate_profiles)
        )
        group_result = ParliamentaryGroupService(session_factory).sync(
            group_observations
        )
        if group_result.memberships_created != 2:
            raise RuntimeError("demo parliamentary-group setup failed")

        drafts: list[DraftCreatedResult] = []
        for candidate in ingestion.candidate_profiles:
            with session_factory() as session:
                match = MatchingService(session).match(candidate)
            if not isinstance(match, MatchedResult):
                raise RuntimeError("demo candidate did not match its bootstrapped identity")
            draft = DraftService(session_factory).create(candidate, match)
            if not isinstance(draft, DraftCreatedResult):
                raise RuntimeError("demo candidate did not create a draft")
            drafts.append(draft)

        publication = PublishService(session_factory).approve(
            drafts[0].draft_id,
            reviewer="demo-setup",
            note="Deterministic demo fixture publication",
        )
        published_proposal_id, pending_proposal_draft_id = _prepare_proposal_example(
            session_factory
        )
        identity_case_id = _prepare_identity_resolution_example(
            session_factory,
            paths,
            governo_fixture,
        )
        _prepare_territorial_example(session_factory)
        published_referendum_id, pending_referendum_draft_id = _prepare_civic_example(
            session_factory
        )
        summary = _load_summary(
            session_factory,
            paths,
            published_politician_id=drafts[0].politician_id,
            published_version_id=publication.created_version_id,
            pending_draft_id=drafts[1].draft_id,
            identity_case_id=identity_case_id,
            published_proposal_id=published_proposal_id,
            pending_proposal_draft_id=pending_proposal_draft_id,
            published_referendum_id=published_referendum_id,
            pending_referendum_draft_id=pending_referendum_draft_id,
        )
        _validate_expected_ids(summary)
        return summary
    finally:
        engine.dispose()


def _load_summary(
    session_factory,
    paths: DemoPaths,
    *,
    published_politician_id: int,
    published_version_id: int,
    pending_draft_id: int,
    identity_case_id: int,
    published_proposal_id: int,
    pending_proposal_draft_id: int,
    published_referendum_id: int,
    pending_referendum_draft_id: int,
) -> DemoSummary:
    with session_factory() as session:
        published = session.get(Politician, published_politician_id)
        version = session.get(PoliticianVersion, published_version_id)
        pending = session.get(ProfileDraft, pending_draft_id)
        pending_politician = session.get(Politician, pending.politician_id)
        identity_case = session.get(IdentityResolutionCase, identity_case_id)
        return DemoSummary(
            database_path=paths.database,
            raw_storage_path=paths.raw_storage,
            published_politician_id=published.id,
            published_name=(
                f"{published.canonical_given_name} "
                f"{published.canonical_family_name}"
            ),
            published_version_number=version.version_number,
            published_citation_count=session.scalar(
                select(func.count())
                .select_from(PoliticianVersionCitation)
                .where(
                    PoliticianVersionCitation.politician_version_id == version.id
                )
            ),
            pending_draft_id=pending.id,
            pending_politician_id=pending.politician_id,
            pending_name=(
                f"{pending_politician.canonical_given_name} "
                f"{pending_politician.canonical_family_name}"
            ),
            pending_status=pending.status,
            pending_evidence_count=session.scalar(
                select(func.count())
                .select_from(Evidence)
                .where(Evidence.draft_id == pending.id)
            ),
            identity_resolution_case_id=identity_case.id,
            identity_resolution_name=identity_case.candidate_display_name,
            identity_resolution_status=identity_case.status,
            published_proposal_id=published_proposal_id,
            pending_proposal_draft_id=pending_proposal_draft_id,
            published_referendum_id=published_referendum_id,
            pending_referendum_draft_id=pending_referendum_draft_id,
        )


def _prepare_proposal_example(session_factory) -> tuple[int, int]:
    observed_at = datetime(2026, 1, 11, 12, tzinfo=timezone.utc)
    proposal_url = "https://dati.senato.it/ddl/synthetic-demo-100"
    with session_factory() as session:
        source = Source(
            key="senato-ddl",
            name="Senato della Repubblica — Disegni di legge",
            base_url="https://dati.senato.it",
        )
        session.add(source)
        session.flush()
        initial_document = RawDocument(
            source_id=source.id,
            retrieved_at=observed_at,
            source_url="https://dati.senato.it/sparql",
            content_type="application/json",
            storage_key="senato-ddl/synthetic-demo-initial.json",
            raw_sha256="3" * 64,
            normalized_sha256="4" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="synthetic_demo_v1",
            parser_version="synthetic_demo_v1",
        )
        update_document = RawDocument(
            source_id=source.id,
            retrieved_at=observed_at,
            source_url="https://dati.senato.it/sparql",
            content_type="application/json",
            storage_key="senato-ddl/synthetic-demo-update.json",
            raw_sha256="5" * 64,
            normalized_sha256="6" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="synthetic_demo_v1",
            parser_version="synthetic_demo_v1",
        )
        session.add_all((initial_document, update_document))
        session.commit()
        initial_document_id = initial_document.id
        update_document_id = update_document.id

    def make_observation(document_id: int, status: str, label: str, day: int):
        return ProposalObservation(
            source_key="senato-ddl",
            raw_document_id=document_id,
            proposal_identifier=proposal_url,
            title="Synthetic housing transparency proposal",
            proposal_type="legislative_proposal",
            introduced_at=datetime(2026, 1, 10).date(),
            source_status_label=label,
            normalized_status=status,
            status_effective_at=datetime(2026, 1, day).date(),
            status_source_identifier=f"{proposal_url}#{status}",
            official_url=proposal_url,
            source_field="osr:statoDdl",
            observed_at=observed_at,
            actors=(
                ProposalActorObservation(
                    actor_type="politician",
                    role="proposer",
                    display_name="Sen. Anna Rossi",
                    authority_key=SOURCE_KEY,
                    source_identifier="https://dati.senato.it/senatore/demo-001",
                    source_field="osr:senatore",
                ),
            ),
            evidence=tuple(
                ProposalEvidenceObservation(
                    field_path=path,
                    source_url=proposal_url,
                    source_field=field,
                    source_value=value,
                )
                for path, field, value in (
                    ("title", "osr:titolo", "Synthetic housing transparency proposal"),
                    ("proposal_type", "rdf:type", "osr:Ddl"),
                    ("introduced_at", "osr:dataPresentazione", "2026-01-10"),
                    ("current_status", "osr:statoDdl", label),
                    (
                        "actors[0]",
                        "osr:senatore",
                        "https://dati.senato.it/senatore/demo-001",
                    ),
                )
            ),
            metadata={"fixture": "synthetic_demo_only"},
        )

    initial = ProposalService(session_factory).sync(
        (make_observation(initial_document_id, "introduced", "da assegn. a commis.", 10),)
    )
    ProposalReviewService(session_factory).approve(
        initial.details[0].draft_id,
        reviewer="demo-setup",
        note="Synthetic proposal fixture publication",
    )
    update = ProposalService(session_factory).sync(
        (make_observation(update_document_id, "under_review", "esame in comm.", 20),)
    )
    update_draft_id = update.details[0].draft_id
    evidence_text = "La proposta sarà sottoposta all'esame della commissione."
    with session_factory() as session:
        chunk = DocumentChunk(
            raw_document_id=update_document_id,
            chunk_index=0,
            text=evidence_text,
            page_start=1,
            page_end=1,
            char_start=0,
            char_end=len(evidence_text),
            chunk_hash="7" * 64,
        )
        session.add(chunk)
        session.flush()
        run = AIExtractionRun(
            raw_document_id=update_document_id,
            provider="fake",
            model="fake-extraction-v1",
            prompt_version="proposal_extraction_v1",
            schema_version="proposal_claim_schema_v1",
            status=AIExtractionRunStatus.COMPLETED,
            idempotency_key="8" * 64,
            completed_idempotency_key="8" * 64,
            input_chunk_count=1,
            output_candidate_count=1,
            completed_at=observed_at,
        )
        session.add(run)
        session.flush()
        candidate = AIExtractionCandidate(
            run_id=run.id,
            candidate_index=0,
            status=AIExtractionCandidateStatus.ACCEPTED,
            deduplication_key="9" * 64,
            model_output={
                "claim_type": "proposal",
                "exact_statement": evidence_text,
                "normalized_title": "Synthetic housing transparency proposal",
                "summary": None,
                "topic": "housing",
                "actor_mentions": [],
                "announced_at": "2026-01-20",
                "target_date": None,
                "evidence": [
                    {
                        "chunk_index": 0,
                        "page": 1,
                        "supporting_text": evidence_text,
                    }
                ],
                "confidence": "high",
                "abstention_reason": None,
            },
            proposal_draft_id=update_draft_id,
        )
        session.add(candidate)
        session.flush()
        session.add(
            AIExtractionCandidateEvidence(
                candidate_id=candidate.id,
                document_chunk_id=chunk.id,
                page=1,
                supporting_text=evidence_text,
                source_url=proposal_url,
            )
        )
        session.commit()
    return initial.details[0].proposal_id, update_draft_id


def _prepare_identity_resolution_example(
    session_factory,
    paths: DemoPaths,
    fixture_path: Path,
) -> int:
    with session_factory() as session:
        source = Source(
            key="governo-italiano",
            name="Governo Italiano",
            base_url="https://www.governo.it",
        )
        session.add(source)
        session.commit()
        source_id = source.id
    ingestion = IngestionPipeline(
        session_factory=session_factory,
        storage=LocalRawStorage(paths.raw_storage),
        collector=FixtureCollector(
            fixture_path,
            source_url="https://www.governo.it/it/ministri-e-sottosegretari",
            content_type="application/vnd.verapolitica.governo-bundle+json",
            version="governo_demo_fixture_v1",
        ),
        parser=GovernoParser(),
        profile_mapper=GovernoCandidateProfileMapper(),
    ).run(source_id=source_id, source_key="governo-italiano")
    candidate = next(
        item
        for item in ingestion.candidate_profiles
        if item.identity.display_name == "Carlo Verdi"
    )
    result = HumanIdentityResolutionCoordinator(session_factory).process(candidate)
    if result.case is None:
        raise RuntimeError("demo Governo candidate did not create a resolution case")
    return result.case.case_id


def _prepare_territorial_example(session_factory) -> None:
    observed_at = datetime(2026, 2, 21, 12, tzinfo=timezone.utc)
    with session_factory() as session:
        istat = Source(
            key="istat-territories",
            name="ISTAT territorial classifications",
            base_url="https://www.istat.it",
        )
        demo_source = Source(
            key="demo-territorial-offices",
            name="Synthetic demo territorial fixture",
            base_url="https://example.test",
        )
        session.add_all((istat, demo_source))
        session.flush()
        istat_document = RawDocument(
            source_id=istat.id,
            retrieved_at=observed_at,
            source_url="https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            storage_key="istat-territories/demo.xlsx",
            raw_sha256="7" * 64,
            normalized_sha256="8" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="demo_territory_v1",
            parser_version="demo_territory_v1",
        )
        office_document = RawDocument(
            source_id=demo_source.id,
            retrieved_at=observed_at,
            source_url="https://example.test/demo/synthetic-milano-mayor",
            content_type="text/csv",
            storage_key="demo-territorial-offices/synthetic-mayor.csv",
            raw_sha256="9" * 64,
            normalized_sha256="a" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="demo_territory_v1",
            parser_version="demo_territory_v1",
        )
        session.add_all((istat_document, office_document))
        session.commit()
        istat_document_id = istat_document.id
        office_document_id = office_document.id

    TerritoryService(session_factory).sync(
        (
            RegionObservation(
                source_key="istat-territories",
                raw_document_id=istat_document_id,
                istat_code="03",
                canonical_name="Lombardia",
                source_url="https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.xlsx",
            ),
        ),
        (
            MunicipalityObservation(
                source_key="istat-territories",
                raw_document_id=istat_document_id,
                istat_code="015146",
                region_istat_code="03",
                canonical_name="Milano",
                province_abbreviation="MI",
                province_name="Milano",
                source_url="https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.xlsx",
            ),
        ),
    )
    with session_factory() as session:
        giulia = Politician(
            canonical_given_name="Giulia",
            canonical_family_name="Neri",
            normalized_name=normalize_person_name("Giulia", "Neri"),
            birth_date=date(1985, 4, 9),
        )
        session.add(giulia)
        session.flush()
        version = PoliticianVersion(
            politician_id=giulia.id,
            version_number=1,
            profile_schema_version=1,
            profile_data=PoliticianVersionProfile(
                given_name="Giulia",
                family_name="Neri",
                birth_date=date(1985, 4, 9),
                profession="Synthetic demo mayor — not a real office holder",
                mandates=(),
            ).model_dump(mode="json"),
            published_at=observed_at,
        )
        session.add(version)
        session.flush()
        giulia.current_version_id = version.id
        session.add(
            PoliticianVersionCitation(
                politician_version_id=version.id,
                field_path="profession",
                source_name="Synthetic demo territorial fixture",
                source_url="https://example.test/demo/synthetic-milano-mayor",
                source_field="profession",
            )
        )
        session.commit()

    result = TerritorialMandateService(session_factory).sync(
        (
            TerritorialMandateObservation(
                source_key="demo-territorial-offices",
                raw_document_id=office_document_id,
                office=TerritorialOffice.MAYOR,
                municipality_istat_code="015146",
                given_name="Giulia",
                family_name="Neri",
                birth_date=date(1985, 4, 9),
                source_identifier="demo-mayor-milano-2024",
                start_date=date(2024, 6, 10),
                source_url="https://example.test/demo/synthetic-milano-mayor",
            ),
        )
    )
    if result.mandates_created != 1:
        raise RuntimeError("demo territorial mayor mandate was not created")
    with session_factory() as session:
        session.add(
            PoliticalParty(
                canonical_name="Demo Civic Alliance",
                abbreviation="DCA-SYN",
                official_website_url=None,
                country="Italy",
            )
        )
        session.commit()


def _prepare_civic_example(session_factory) -> tuple[int, int]:
    observed_at = datetime(2026, 10, 6, 8, tzinfo=timezone.utc)
    fixture_path = (
        REPOSITORY_ROOT / "tests" / "fixtures" / "civic" / "synthetic_referendum.json"
    )
    record = json.loads(fixture_path.read_text(encoding="utf-8"))
    with session_factory() as session:
        source = Source(
            key="ministero-interno-elezioni",
            name="Ministero dell'Interno — Servizi elettorali",
            base_url="https://dait.interno.gov.it",
        )
        demo_source = Source(
            key="demo-civic",
            name="Synthetic civic demo fixture",
            base_url="https://example.test",
        )
        session.add_all((source, demo_source))
        session.flush()
        document = RawDocument(
            source_id=demo_source.id,
            retrieved_at=observed_at,
            source_url="https://example.test/demo/synthetic-civic-referendum",
            content_type="application/json",
            storage_key="demo-civic/synthetic-referendum.json",
            raw_sha256="b" * 64,
            normalized_sha256="c" * 64,
            structured_records=[record],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="synthetic_civic_v1",
            parser_version="synthetic_civic_v1",
        )
        pending_document = RawDocument(
            source_id=demo_source.id,
            retrieved_at=observed_at,
            source_url="https://example.test/demo/synthetic-civic-referendum-pending",
            content_type="application/json",
            storage_key="demo-civic/synthetic-referendum-pending.json",
            raw_sha256="d" * 64,
            normalized_sha256="e" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="synthetic_civic_v1",
            parser_version="synthetic_civic_v1",
        )
        session.add_all((document, pending_document))
        session.commit()
        document_id = document.id
        pending_document_id = pending_document.id

    CivicContentService(session_factory).upsert_voting_guide(
        VotingGuideInput(
            title="How to vote in a national referendum",
            scope="national",
            source_key="ministero-interno-elezioni",
            source_url="https://dait.interno.gov.it/elezioni/faq/faq-referendum-2026",
            publish=True,
            sections=(
                VotingGuideSection(
                    key="eligibility",
                    title="Who can vote",
                    body="The Constitution states that all citizens entitled to elect the Chamber of Deputies may take part in a national referendum.",
                    source_url="https://www.senato.it/istituzione/la-costituzione/parte-ii/titolo-i/sezione-ii/articolo-75",
                ),
                VotingGuideSection(
                    key="required_documents",
                    title="What you need",
                    body="Bring a valid identity document with photograph issued by a public administration and your electoral card (tessera elettorale). A CIE request receipt with photograph is also accepted as identification.",
                    source_url="https://dait.interno.gov.it/elezioni/faq/faq-referendum-2026",
                ),
                VotingGuideSection(
                    key="date_and_hours",
                    title="When to vote",
                    body="Polling hours are those published by the Ministry of the Interior for each consultation. For the March 2026 constitutional referendum they were Sunday 07:00–23:00 and Monday 07:00–15:00.",
                    source_url="https://www.interno.gov.it/it/notizie/referendum-urne-aperte-domenica-22-marzo-dalle-7-23-e-lunedi-23-marzo-dalle-7-15",
                ),
                VotingGuideSection(
                    key="ballot_instructions",
                    title="How the ballot works",
                    body="Mark the chosen answer on the ballot, inside the rectangle that contains it. Phones must be handed to polling-station staff before entering the cabin. If a voter realises a marking error, the station president may issue a replacement ballot.",
                    source_url="https://dait.interno.gov.it/elezioni/faq/faq-referendum-2026",
                ),
                VotingGuideSection(
                    key="quorum",
                    title="Quorum",
                    body="An abrogative referendum is approved if a majority of those entitled to vote take part and a majority of valid votes are in favour (Constitution Art. 75). A confirmatory constitutional referendum has no participation quorum: it is approved if yes votes exceed no votes among valid ballots.",
                    source_url="https://www.senato.it/istituzione/la-costituzione/parte-ii/titolo-i/sezione-ii/articolo-75",
                ),
                VotingGuideSection(
                    key="accessibility",
                    title="Accessibility",
                    body="Assisted voting in the cabin is available only where a disability prevents autonomous expression of the vote, as documented by the Ministry of the Interior FAQ (for example visual impairment or severe motor impairment of the upper limbs). One accompanying voter may assist only one person.",
                    source_url="https://dait.interno.gov.it/elezioni/faq/faq-referendum-2026",
                ),
                VotingGuideSection(
                    key="official_links",
                    title="Official sources",
                    body="Ministry of the Interior electoral pages, DAIT referendum FAQ and dossiers, Eligendo for turnout and results when published, and the Constitution on the Senate website.",
                    source_url="https://dait.interno.gov.it/elezioni",
                ),
            ),
        )
    )
    glossary = CivicContentService(session_factory)
    for payload in _glossary_terms():
        glossary.upsert_glossary_term(payload)

    published = ReferendumService(session_factory).sync(
        (
            map_referendum_fixture(
                record,
                source_key="demo-civic",
                raw_document_id=document_id,
                observed_at=observed_at,
            ),
        )
    )
    ReferendumReviewService(session_factory).approve(
        published.details[0].draft_id,
        reviewer="demo-setup",
        note="Synthetic civic demo publication — not a real vote",
    )
    pending_record = dict(record)
    pending_record["official_identifier"] = "synthetic-demo-civic-referendum-pending"
    pending_record["title"] = "Unpublished synthetic civic referendum (demo fixture)"
    pending_record["official_question"] = (
        "This unpublished synthetic question must remain hidden until editorial approval."
    )
    pending = ReferendumService(session_factory).sync(
        (
            map_referendum_fixture(
                pending_record,
                source_key="demo-civic",
                raw_document_id=pending_document_id,
                observed_at=observed_at,
            ),
        )
    )
    with session_factory() as session:
        from backend.app.models.civic import Referendum, VotingGuide

        guide = session.scalar(select(VotingGuide).order_by(VotingGuide.id.asc()))
        referendum = session.get(Referendum, published.details[0].referendum_id)
        if guide is not None and referendum is not None:
            referendum.voting_guide_id = guide.id
            session.commit()
    return published.details[0].referendum_id, pending.details[0].draft_id


def _glossary_terms():
    constitution = "https://www.senato.it/istituzione/la-costituzione"
    return (
        GlossaryTermInput(
            slug="quorum",
            term="Quorum",
            short_definition="For an abrogative referendum, the proposal is approved only if a majority of those entitled to vote take part, and a majority of valid votes are in favour.",
            extended_definition="Constitution Article 75. A confirmatory constitutional referendum has no participation quorum.",
            source_url=f"{constitution}/parte-ii/titolo-i/sezione-ii/articolo-75",
            source_key="ministero-interno-elezioni",
            publish=True,
        ),
        GlossaryTermInput(
            slug="referendum-abrogativo",
            term="Referendum abrogativo",
            short_definition="A popular vote to repeal all or part of a law or an act with the force of law, when requested by 500,000 electors or five Regional Councils.",
            extended_definition="Tax, budget, amnesty, pardon, and treaty-authorisation laws cannot be the object of an abrogative referendum (Constitution Article 75).",
            source_url=f"{constitution}/parte-ii/titolo-i/sezione-ii/articolo-75",
            source_key="ministero-interno-elezioni",
            publish=True,
        ),
        GlossaryTermInput(
            slug="legge",
            term="Legge",
            short_definition="The legislative function is exercised collectively by the two Houses of Parliament.",
            source_url=f"{constitution}/parte-ii/titolo-i/sezione-ii/articolo-70",
            source_key="ministero-interno-elezioni",
            publish=True,
        ),
        GlossaryTermInput(
            slug="decreto-legge",
            term="Decreto-legge",
            short_definition="In extraordinary cases of necessity and urgency the Government may adopt provisional measures with the force of law, which must be presented to Parliament on the same day.",
            extended_definition="If not converted into law within sixty days of publication they lose effect from the beginning (Constitution Article 77).",
            source_url=f"{constitution}/parte-ii/titolo-i/sezione-ii/articolo-77",
            source_key="ministero-interno-elezioni",
            publish=True,
        ),
        GlossaryTermInput(
            slug="disegno-di-legge",
            term="Disegno di legge",
            short_definition="The initiative for legislation belongs to the Government, to each member of the Houses, and to the bodies and persons granted that power by constitutional law.",
            source_url=f"{constitution}/parte-ii/titolo-i/sezione-ii/articolo-71",
            source_key="ministero-interno-elezioni",
            publish=True,
        ),
        GlossaryTermInput(
            slug="maggioranza",
            term="Maggioranza",
            short_definition="Each House adopts its decisions by an absolute majority of those present, unless the Constitution prescribes a special majority.",
            source_url=f"{constitution}/parte-ii/titolo-i/sezione-i/articolo-64",
            source_key="ministero-interno-elezioni",
            publish=True,
        ),
        GlossaryTermInput(
            slug="legislatura",
            term="Legislatura",
            short_definition="The Chamber of Deputies and the Senate of the Republic are elected for five years.",
            source_url=f"{constitution}/parte-ii/titolo-i/sezione-i/articolo-60",
            source_key="ministero-interno-elezioni",
            publish=True,
        ),
        GlossaryTermInput(
            slug="gruppo-parlamentare",
            term="Gruppo parlamentare",
            short_definition="A parliamentary group is the organisational unit of members inside a House of Parliament. It is not the same as a political party.",
            source_url="https://www.senato.it/istituzione/il-senato",
            source_key="ministero-interno-elezioni",
            publish=True,
        ),
        GlossaryTermInput(
            slug="partito-politico",
            term="Partito politico",
            short_definition="All citizens have the right to freely associate in parties in order to contribute to determining national policy through democratic methods.",
            source_url=f"{constitution}/parte-i/titolo-iv/articolo-49",
            source_key="ministero-interno-elezioni",
            publish=True,
        ),
    )


def _validate_demo_paths(paths: DemoPaths) -> None:
    expected_root = (paths.workspace_root / "data" / "demo").resolve()
    forbidden = {
        Path("/").resolve(),
        paths.workspace_root.resolve(),
        (paths.workspace_root / "data").resolve(),
    }
    if paths.demo_root.resolve() != expected_root:
        raise DemoSafetyError("demo root must be exactly <workspace>/data/demo")
    if paths.demo_root.resolve() in forbidden or paths.demo_root.name != "demo":
        raise DemoSafetyError(f"unsafe demo root: {paths.demo_root}")
    if paths.database.parent.resolve() != expected_root:
        raise DemoSafetyError("demo database must be directly under the demo root")
    if paths.database.name != "verapolitica_demo.db":
        raise DemoSafetyError("unexpected demo database filename")
    if paths.raw_storage.parent.resolve() != expected_root:
        raise DemoSafetyError("demo raw storage must be directly under the demo root")
    if paths.raw_storage.name != "raw":
        raise DemoSafetyError("unexpected demo raw-storage directory")


def _validate_expected_ids(summary: DemoSummary) -> None:
    expected = (1, 1, 2, 2, 1)
    actual = (
        summary.published_politician_id,
        summary.published_version_number,
        summary.pending_draft_id,
        summary.pending_politician_id,
        summary.identity_resolution_case_id,
    )
    if actual != expected:
        raise RuntimeError(f"demo IDs are not deterministic: expected {expected}, got {actual}")


def _print_summary(summary: DemoSummary) -> None:
    print("VeraPolitica demo ready")
    print()
    print(f"Demo database: {summary.database_path}")
    print(f"Demo raw storage: {summary.raw_storage_path}")
    print()
    print("Published politician:")
    print(f"  ID: {summary.published_politician_id}")
    print(f"  Name: {summary.published_name}")
    print(f"  Version: {summary.published_version_number}")
    print(f"  Citations: {summary.published_citation_count}")
    print()
    print("Pending review:")
    print(f"  Draft ID: {summary.pending_draft_id}")
    print(f"  Politician ID: {summary.pending_politician_id}")
    print(f"  Name: {summary.pending_name}")
    print(f"  Status: {summary.pending_status.value}")
    print(f"  Evidence: {summary.pending_evidence_count}")
    print()
    print("Pending identity resolution:")
    print(f"  Case ID: {summary.identity_resolution_case_id}")
    print(f"  Name: {summary.identity_resolution_name}")
    print(f"  Status: {summary.identity_resolution_status.value}")
    print()
    print("Proposal tracker (synthetic demo data):")
    print(f"  Published proposal ID: {summary.published_proposal_id}")
    print(f"  Pending status-update draft ID: {summary.pending_proposal_draft_id}")
    print()
    print("Territorial archive (synthetic demo mayor):")
    print("  Region: Lombardia")
    print("  Municipality: Milano")
    print("  Synthetic mayor: Giulia Neri")
    print("  Synthetic political party: Demo Civic Alliance (DCA-SYN)")
    print()
    print("Civic features (synthetic referendum is demo-only):")
    print(f"  Published synthetic referendum ID: {summary.published_referendum_id}")
    print(f"  Pending referendum draft ID: {summary.pending_referendum_draft_id}")
    print("  Voting guide: How to vote in a national referendum")
    print("  Glossary: quorum, referendum abrogativo, legge, and related terms")
    print()
    print("Start API with:")
    print('  export VERAPOLITICA_DATABASE_URL="sqlite:///./data/demo/verapolitica_demo.db"')
    print('  export VERAPOLITICA_RAW_STORAGE_PATH="./data/demo/raw"')
    print(f'  export VERAPOLITICA_ADMIN_API_KEY="{DEMO_ADMIN_KEY}"')
    print(f'  export VERAPOLITICA_ADMIN_REVIEWER_IDENTITY="{DEMO_REVIEWER}"')
    print("  uvicorn backend.app.main:app --reload")
    print()
    print("Public demo:")
    print(f"  GET /politicians/{summary.published_politician_id}")
    print("Admin demo:")
    print(f"  GET /admin/drafts/{summary.pending_draft_id}")
    print(f"  POST /admin/drafts/{summary.pending_draft_id}/start-review")
    print(f"  POST /admin/drafts/{summary.pending_draft_id}/approve")
    print(f"  GET /admin/identity-resolution/{summary.identity_resolution_case_id}")
    print(f"  GET /admin/referendums/drafts/{summary.pending_referendum_draft_id}")
    print(f"  GET /politicians/{summary.pending_politician_id}")
    print(f"  GET /referendums/{summary.published_referendum_id}")
    print()
    print("Reset after rehearsal:")
    print("  python -m scripts.prepare_demo")


def main() -> int:
    summary = prepare_demo()
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
