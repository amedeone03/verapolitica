from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil

from sqlalchemy import func, select

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    Evidence,
    IdentityResolutionCase,
    IdentityResolutionStatus,
    Politician,
    PoliticianVersion,
    PoliticianVersionCitation,
    ProfileDraft,
    ProfileDraftStatus,
    Source,
)
from backend.app.pipeline.collectors import CollectedDocument
from backend.app.pipeline.ingestion_pipeline import IngestionPipeline
from backend.app.pipeline.mappers import (
    GovernoCandidateProfileMapper,
    SenatoCandidateProfileMapper,
)
from backend.app.pipeline.parsers import GovernoParser, SenatoParser
from backend.app.schemas import DraftCreatedResult, MatchedResult
from backend.app.services import (
    CandidateRebuildResult,
    DraftService,
    HumanIdentityResolutionCoordinator,
    IndexedCandidate,
    MatchingService,
    PoliticianBootstrapService,
    PublishService,
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
        identity_case_id = _prepare_identity_resolution_example(
            session_factory,
            paths,
            governo_fixture,
        )
        summary = _load_summary(
            session_factory,
            paths,
            published_politician_id=drafts[0].politician_id,
            published_version_id=publication.created_version_id,
            pending_draft_id=drafts[1].draft_id,
            identity_case_id=identity_case_id,
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
        )


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
    print(f"  GET /politicians/{summary.pending_politician_id}")
    print()
    print("Reset after rehearsal:")
    print("  python -m scripts.prepare_demo")


def main() -> int:
    summary = prepare_demo()
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
