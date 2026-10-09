"""Shared paths and safety for the unified local demo.

The unified environment lives only at ``<workspace>/data/unified_demo/``.
It must never read for write, delete, or reset ``data/ceo_demo/`` or
``data/demo/``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    IdentityResolutionCase,
    IdentityResolutionStatus,
    Municipality,
    PledgeAssessment,
    PledgeClassification,
    Politician,
    PoliticianVersion,
    ProfileDraft,
    ProfileDraftStatus,
    Proposal,
    Region,
    Source,
)
from scripts.prepare_demo import DemoSafetyError

UNIFIED_ROOT_NAME = "unified_demo"
UNIFIED_DATABASE_NAME = "verapolitica.db"
CEO_RELATIVE_DB = Path("data") / "ceo_demo" / "verapolitica.db"
CEO_RELATIVE_RAW = Path("data") / "ceo_demo" / "raw"
FORBIDDEN_ROOT_NAMES = frozenset({"ceo_demo", "demo"})


@dataclass(frozen=True)
class UnifiedDemoPaths:
    workspace_root: Path
    demo_root: Path
    database: Path
    raw_storage: Path
    portraits_json: Path
    portraits_dir: Path
    portrait_cache: Path
    uploads: Path
    report_path: Path

    @classmethod
    def for_workspace(cls, workspace_root: Path) -> UnifiedDemoPaths:
        workspace = workspace_root.expanduser().resolve()
        demo_root = workspace / "data" / UNIFIED_ROOT_NAME
        return cls(
            workspace_root=workspace,
            demo_root=demo_root,
            database=demo_root / UNIFIED_DATABASE_NAME,
            raw_storage=demo_root / "raw",
            portraits_json=demo_root / "portraits.json",
            portraits_dir=demo_root / "portraits",
            portrait_cache=demo_root / "portrait_cache.json",
            uploads=demo_root / "uploads",
            report_path=demo_root / "unified_demo_report.json",
        )

    def settings_kwargs(self) -> dict:
        return {
            "database_url": f"sqlite:///{self.database}",
            "raw_storage_path": self.raw_storage,
            "demo_upload_path": self.uploads,
            "portraits_path": self.portraits_json,
        }


def validate_unified_paths(paths: UnifiedDemoPaths) -> None:
    expected = (paths.workspace_root / "data" / UNIFIED_ROOT_NAME).resolve()
    if paths.demo_root.resolve() != expected:
        raise DemoSafetyError("unified demo root must be exactly <workspace>/data/unified_demo")
    if paths.demo_root.name != UNIFIED_ROOT_NAME:
        raise DemoSafetyError(f"unsafe unified demo root: {paths.demo_root}")
    if paths.database.parent.resolve() != expected or paths.database.name != UNIFIED_DATABASE_NAME:
        raise DemoSafetyError("unified database must be data/unified_demo/verapolitica.db")
    if paths.raw_storage.parent.resolve() != expected or paths.raw_storage.name != "raw":
        raise DemoSafetyError("unified raw storage must be data/unified_demo/raw")
    _refuse_foreign_tree(paths.demo_root)
    _refuse_foreign_tree(paths.database)
    _refuse_foreign_tree(paths.raw_storage)


def _refuse_foreign_tree(path: Path) -> None:
    parts = set(path.expanduser().resolve().parts)
    if FORBIDDEN_ROOT_NAMES & parts:
        raise DemoSafetyError(f"refusing to touch protected demo path: {path}")


def assert_settings_are_unified(database_url: str, raw_storage_path: Path, workspace_root: Path) -> None:
    paths = UnifiedDemoPaths.for_workspace(workspace_root)
    validate_unified_paths(paths)
    if "ceo_demo" in database_url or "/data/demo/" in database_url:
        raise DemoSafetyError("unified demo refuses to use the CEO or synthetic demo database")
    resolved_raw = Path(raw_storage_path).expanduser().resolve()
    if resolved_raw != paths.raw_storage.resolve():
        raise DemoSafetyError("unified demo refuses a raw-storage path outside data/unified_demo/raw")
    if not database_url.endswith(str(paths.database)) and Path(
        database_url.replace("sqlite:///", "")
    ).resolve() != paths.database.resolve():
        raise DemoSafetyError("unified demo refuses a database path outside data/unified_demo")


def wipe_unified_environment(paths: UnifiedDemoPaths) -> None:
    """Delete only the unified demo tree. Never touches ceo_demo or data/demo."""

    import shutil

    validate_unified_paths(paths)
    if paths.demo_root.is_symlink() or paths.database.is_symlink() or paths.raw_storage.is_symlink():
        raise DemoSafetyError("unified demo paths must not be symbolic links")
    if paths.demo_root.exists():
        shutil.rmtree(paths.demo_root)
    paths.demo_root.mkdir(parents=True, exist_ok=True)
    paths.raw_storage.mkdir(parents=True, exist_ok=True)
    paths.portraits_dir.mkdir(parents=True, exist_ok=True)
    paths.uploads.mkdir(parents=True, exist_ok=True)


def ensure_unified_directories(paths: UnifiedDemoPaths) -> None:
    validate_unified_paths(paths)
    paths.demo_root.mkdir(parents=True, exist_ok=True)
    paths.raw_storage.mkdir(parents=True, exist_ok=True)
    paths.portraits_dir.mkdir(parents=True, exist_ok=True)
    paths.uploads.mkdir(parents=True, exist_ok=True)


def ceo_seed_paths(workspace_root: Path) -> tuple[Path, Path]:
    root = workspace_root.expanduser().resolve()
    return root / CEO_RELATIVE_DB, root / CEO_RELATIVE_RAW


def seed_sqlite_from_ceo(paths: UnifiedDemoPaths) -> bool:
    """Copy the CEO SQLite snapshot into the unified DB. Read-only on CEO files."""

    source_db, source_raw = ceo_seed_paths(paths.workspace_root)
    if not source_db.is_file():
        return False
    validate_unified_paths(paths)
    ensure_unified_directories(paths)
    if paths.database.exists():
        paths.database.unlink()
    source = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    try:
        dest = sqlite3.connect(paths.database)
        try:
            source.backup(dest)
            dest.commit()
        finally:
            dest.close()
    finally:
        source.close()
    if source_raw.is_dir():
        import shutil

        shutil.copytree(source_raw, paths.raw_storage, dirs_exist_ok=True)
    return True


@dataclass
class UnifiedDemoCounts:
    politicians: int = 0
    published_politician_versions: int = 0
    government_holders: int = 0
    regions: int = 0
    municipalities: int = 0
    proposals: int = 0
    published_proposals: int = 0
    pledge_classifications: int = 0
    pledge_assessments: int = 0
    portraits: int = 0
    unresolved_identity_cases: int = 0
    pending_profile_drafts: int = 0
    sources: int = 0
    duplicate_canonical_people: int = 0
    missing_portrait_files: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def collect_counts(session_factory: sessionmaker[Session], paths: UnifiedDemoPaths) -> UnifiedDemoCounts:
    import json

    counts = UnifiedDemoCounts()
    with session_factory() as session:
        counts.politicians = session.scalar(select(func.count()).select_from(Politician)) or 0
        counts.published_politician_versions = session.scalar(
            select(func.count()).select_from(PoliticianVersion).where(
                PoliticianVersion.published_at.is_not(None)
            )
        ) or 0
        counts.government_holders = _count_government_holders(session)
        counts.regions = session.scalar(select(func.count()).select_from(Region)) or 0
        counts.municipalities = session.scalar(select(func.count()).select_from(Municipality)) or 0
        counts.proposals = session.scalar(select(func.count()).select_from(Proposal)) or 0
        counts.published_proposals = session.scalar(
            select(func.count()).select_from(Proposal).where(Proposal.published_at.is_not(None))
        ) or 0
        counts.pledge_classifications = session.scalar(
            select(func.count()).select_from(PledgeClassification)
        ) or 0
        counts.pledge_assessments = session.scalar(
            select(func.count()).select_from(PledgeAssessment)
        ) or 0
        counts.unresolved_identity_cases = session.scalar(
            select(func.count()).select_from(IdentityResolutionCase).where(
                IdentityResolutionCase.status == IdentityResolutionStatus.PENDING
            )
        ) or 0
        counts.pending_profile_drafts = session.scalar(
            select(func.count()).select_from(ProfileDraft).where(
                ProfileDraft.status == ProfileDraftStatus.PENDING
            )
        ) or 0
        counts.sources = session.scalar(select(func.count()).select_from(Source)) or 0
        counts.duplicate_canonical_people = _duplicate_people(session)
    if paths.portraits_json.is_file():
        try:
            raw = json.loads(paths.portraits_json.read_text("utf-8"))
        except ValueError:
            raw = {}
        if isinstance(raw, dict):
            counts.portraits = len(raw)
            for entry in raw.values():
                name = entry.get("file") if isinstance(entry, dict) else None
                if name and not (paths.portraits_dir / name).is_file():
                    counts.missing_portrait_files += 1
    return counts


def _count_government_holders(session: Session) -> int:
    rows = session.execute(
        select(PoliticianVersion.profile_data)
        .join(Politician, Politician.current_version_id == PoliticianVersion.id)
        .where(PoliticianVersion.published_at.is_not(None))
    ).all()
    count = 0
    for (profile,) in rows:
        mandates = (profile or {}).get("mandates") or []
        office = mandates[0].get("office") if mandates else None
        institution = (mandates[0].get("institution") if mandates else "") or ""
        if office in {
            "Presidente del Consiglio",
            "Vice Presidente del Consiglio",
            "Ministro",
            "Ministro senza portafoglio",
        } or "Governo" in institution:
            count += 1
    return count


def _duplicate_people(session: Session) -> int:
    rows = session.execute(
        text(
            "SELECT normalized_name, birth_date, COUNT(*) AS n "
            "FROM politicians WHERE birth_date IS NOT NULL "
            "GROUP BY normalized_name, birth_date HAVING n > 1"
        )
    ).all()
    return sum(int(row.n) - 1 for row in rows)


def integrity_warnings(session_factory: sessionmaker[Session], counts: UnifiedDemoCounts) -> list[str]:
    warnings: list[str] = []
    if counts.duplicate_canonical_people:
        warnings.append(
            f"{counts.duplicate_canonical_people} duplicate canonical politician(s) "
            "(same normalized name + birth date)"
        )
    if counts.missing_portrait_files:
        warnings.append(f"{counts.missing_portrait_files} portrait manifest entries lack a local file")
    with session_factory() as session:
        orphans = session.execute(
            text(
                "SELECT COUNT(*) FROM politicians p "
                "WHERE p.current_version_id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM politician_versions v WHERE v.id = p.current_version_id)"
            )
        ).scalar_one()
        if orphans:
            warnings.append(f"{orphans} politician(s) point at a missing current version")
    return warnings
