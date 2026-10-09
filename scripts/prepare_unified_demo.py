"""Build the unified local demo (Senate civic data + Government + pledges + AI).

Orchestrates existing collectors, identity services, pledge publication and
portrait helpers. It writes only under ``data/unified_demo/``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import AppEnvironment, Settings, configured_environment
from backend.app.db.base import Base
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    IdentityResolutionStatus,
    Politician,
    PoliticianSourceIdentifier,
    PoliticianVersion,
    ProfileDraft,
    ProfileDraftStatus,
    Source,
)
from backend.app.pipeline.collectors import GovernoCollector, IstatTerritoryCollector
from backend.app.pipeline.ingestion_pipeline import IngestionPipeline
from backend.app.pipeline.mappers import GovernoCandidateProfileMapper, IstatTerritoryMapper
from backend.app.pipeline.parsers import GovernoParser, IstatTerritoryParser, SenatoParser
from backend.app.pipeline.mappers import SenatoCandidateProfileMapper
from backend.app.pipeline.territorial_ingestion import TerritorialRawPipeline
from backend.app.schemas import (
    DraftCreatedResult,
    MatchedResult,
    NewMatchReason,
    NewResult,
    UncertainResult,
)
from backend.app.services import (
    CandidateRebuildResult,
    DraftService,
    HumanIdentityResolutionCoordinator,
    IdentityResolutionService,
    IdentityResolutionServiceError,
    IndexedCandidate,
    MatchingService,
    PoliticianBootstrapService,
    PublishService,
    RawDocumentCandidateRebuilder,
    TerritoryService,
)
from backend.app.storage import LocalRawStorage
from scripts.demo_portraits import (
    JsonGetter,
    build_portraits,
    http_get_json,
    load_cache,
    store_portrait_files,
    write_portraits,
)
from scripts.prepare_demo import (
    DEFAULT_FIXTURE,
    DEFAULT_GOVERNO_FIXTURE,
    DemoSafetyError,
    FixtureCollector,
)
from scripts.prepare_real_demo import (
    GOVERNO_SOURCE,
    PROGRAMME_SOURCE,
    PROGRAMME_URL,
    PUBLISHED_OFFICES,
    REVIEWER,
    Fetcher,
    RealDemoReport,
    _ingest_programme,
    _office,
    _prime_minister,
    _publish_commitments,
    http_fetch,
)
from scripts.reset_ceo_ai_demo import reset_ceo_ai_demo
from scripts.unified_demo import (
    UnifiedDemoCounts,
    UnifiedDemoPaths,
    collect_counts,
    ensure_unified_directories,
    integrity_warnings,
    seed_sqlite_from_ceo,
    validate_unified_paths,
    wipe_unified_environment,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OFFLINE_PROGRAMME_HTML = """<html><body><article>
<h1>Le dichiarazioni programmatiche (fixture)</h1>
<p>Signor Presidente, onorevoli colleghi, è un onore essere qui oggi davanti a voi.</p>
<p>Intendiamo ridurre il cuneo fiscale di cinque punti a favore dei lavoratori nel corso della legislatura. Vogliamo una Nazione orgogliosa del proprio futuro e del proprio destino.</p>
<p>Ci impegneremo a introdurre una riforma della giustizia civile che dimezzi i tempi dei processi.</p>
<p>Porteremo la banda ultralarga in tutti i comuni con un piano di investimenti da 3 miliardi di euro.</p>
<p>Introdurremo un assegno unico rafforzato per le famiglie con figli e una legge sulla natalità.</p>
<p>Siete d'accordo con noi su questo percorso?</p>
</article></body></html>"""


def _offline_governo_collector():
    from backend.app.pipeline.collectors import GovernoCollector

    return FixtureCollector(
        DEFAULT_GOVERNO_FIXTURE,
        source_url="https://www.governo.it/it/ministri-e-sottosegretari",
        content_type=GovernoCollector.response_media_type,
        version="governo_demo_fixture_v1",
    )


def _offline_fetch(url: str) -> tuple[bytes, str]:
    if url != PROGRAMME_URL:
        raise ValueError(f"offline unified demo does not fetch {url}")
    return OFFLINE_PROGRAMME_HTML.encode("utf-8"), "text/html"


@dataclass
class UnifiedDemoReport:
    database_path: str
    seeded_from_ceo: bool = False
    senate_profiles_published: list[str] = field(default_factory=list)
    identities_linked: list[str] = field(default_factory=list)
    identities_created: list[str] = field(default_factory=list)
    identities_left_unresolved: list[str] = field(default_factory=list)
    government: RealDemoReport | None = None
    counts: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _get_or_create_source(session_factory, key: str, name: str, base_url: str) -> int:
    with session_factory() as session:
        source = session.scalar(select(Source).where(Source.key == key))
        if source is None:
            source = Source(key=key, name=name, base_url=base_url)
            session.add(source)
            session.commit()
            session.refresh(source)
        return source.id


def _settings_for(paths: UnifiedDemoPaths, settings: Settings | None) -> Settings:
    base = settings or Settings()
    return base.model_copy(update=paths.settings_kwargs())


def _ingest_senate_fixture(session_factory, storage, fixture: Path, report: UnifiedDemoReport) -> None:
    source_id = _get_or_create_source(
        session_factory,
        "senato-repubblica",
        "Senato della Repubblica",
        "https://dati.senato.it",
    )
    ingestion = IngestionPipeline(
        session_factory=session_factory,
        storage=storage,
        collector=FixtureCollector(fixture),
        parser=SenatoParser(),
        profile_mapper=SenatoCandidateProfileMapper(),
    ).run(source_id=source_id, source_key="senato-repubblica")
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
    drafts = DraftService(session_factory)
    publish = PublishService(session_factory)
    for candidate in ingestion.candidate_profiles:
        with session_factory() as session:
            match = MatchingService(session).match(candidate)
        if not isinstance(match, MatchedResult):
            report.warnings.append(
                f"senate fixture candidate not matched: {candidate.identity.display_name}"
            )
            continue
        draft = drafts.create(candidate, match)
        if isinstance(draft, DraftCreatedResult):
            publish.approve(
                draft.draft_id,
                reviewer=REVIEWER,
                note="Unified demo: official Senato fixture profile",
            )
            report.senate_profiles_published.append(candidate.identity.display_name)


def _ingest_territories_fixture(session_factory, storage, fixture: Path) -> None:
    source_id = _get_or_create_source(
        session_factory,
        "istat-territories",
        "ISTAT territorial classifications",
        "https://www.istat.it",
    )
    collector = IstatTerritoryCollector(
        "https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.xlsx",
        fixture_path=fixture,
    )
    raw = TerritorialRawPipeline(
        session_factory, storage, collector, IstatTerritoryParser()
    ).run(source_id=source_id, source_key="istat-territories")
    regions, municipalities = IstatTerritoryMapper().map_records(
        raw.parsed.structured_records,
        source_key="istat-territories",
        raw_document_id=raw.raw_document_id,
        source_url="https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.xlsx",
    )
    TerritoryService(session_factory).sync(regions, municipalities)


def _possible_name_collision(resolutions: IdentityResolutionService, case_id: int) -> bool:
    matches = resolutions.possible_matches(case_id)
    return any("normalized_full_name" in item.signals for item in matches)


def _safe_existing_match(resolutions: IdentityResolutionService, case_id: int):
    matches = [
        item
        for item in resolutions.possible_matches(case_id)
        if "normalized_full_name" in item.signals and "exact_birth_date" in item.signals
    ]
    return matches[0] if len(matches) == 1 else None


def _count_published_government(session_factory) -> int:
    with session_factory() as session:
        rows = session.execute(
            select(PoliticianVersion.profile_data)
            .join(Politician, Politician.current_version_id == PoliticianVersion.id)
            .where(PoliticianVersion.published_at.is_not(None))
        ).all()
    count = 0
    for (profile,) in rows:
        mandates = (profile or {}).get("mandates") or []
        office = mandates[0].get("office") if mandates else None
        if office in PUBLISHED_OFFICES:
            count += 1
    return count


def _overlay_government(
    session_factory,
    storage,
    collector,
    report: UnifiedDemoReport,
) -> RealDemoReport:
    gov = RealDemoReport(database_path=report.database_path)
    source_id = _get_or_create_source(session_factory, *GOVERNO_SOURCE)
    ingestion = IngestionPipeline(
        session_factory=session_factory,
        storage=storage,
        collector=collector,
        parser=GovernoParser(),
        profile_mapper=GovernoCandidateProfileMapper(),
    ).run(source_id=source_id, source_key=GOVERNO_SOURCE[0])
    candidates = ingestion.candidate_profiles
    if not candidates:
        rebuilt = RawDocumentCandidateRebuilder(session_factory).rebuild(
            raw_document_id=ingestion.raw_document_id,
            source_key=GOVERNO_SOURCE[0],
        )
        candidates = tuple(item.profile for item in rebuilt.candidates)
    gov.politicians_collected = len(candidates)
    if not candidates:
        if _count_published_government(session_factory):
            gov.warnings.append("governo document unchanged; existing profiles kept")
            return gov
        raise RuntimeError("governo.it returned no office holders")

    coordinator = HumanIdentityResolutionCoordinator(session_factory)
    resolutions = IdentityResolutionService(session_factory)
    bootstrap = PoliticianBootstrapService(session_factory)

    new_with_birth = []
    for index, candidate in enumerate(candidates):
        with session_factory() as session:
            match = MatchingService(session).match(candidate)
        if isinstance(match, NewResult) and match.reason is NewMatchReason.NO_MATCH:
            new_with_birth.append(IndexedCandidate(candidate_index=index, profile=candidate))
    if new_with_birth:
        rebuilt = CandidateRebuildResult(
            raw_document_id=ingestion.raw_document_id,
            candidates=tuple(new_with_birth),
            invalid=(),
        )
        plan = bootstrap.plan(rebuilt, dry_run=False)
        if plan.report.safe_to_apply:
            bootstrap.apply(plan)
            for item in new_with_birth:
                gov.identities_confirmed_by_editor.append(item.profile.identity.display_name)
                report.identities_created.append(item.profile.identity.display_name)

    for candidate in candidates:
        processed = coordinator.process(candidate)
        name = candidate.identity.display_name
        if isinstance(processed.match, MatchedResult):
            report.identities_linked.append(name)
            continue
        if processed.case is None:
            continue
        if processed.case.status is not IdentityResolutionStatus.PENDING:
            continue
        safe = _safe_existing_match(resolutions, processed.case.case_id)
        if safe is not None:
            resolutions.resolve_to_existing(
                processed.case.case_id,
                safe.politician_id,
                reviewer_identity=REVIEWER,
                note=(
                    "Unified demo: official governo.it holder matches an existing "
                    "politician by normalized name and exact birth date"
                ),
            )
            report.identities_linked.append(name)
            continue
        if _possible_name_collision(resolutions, processed.case.case_id):
            report.identities_left_unresolved.append(name)
            gov.warnings.append(
                f"identity left for review (name collision, no safe birth date): {name}"
            )
            continue
        if isinstance(processed.match, UncertainResult):
            report.identities_left_unresolved.append(name)
            continue
        try:
            resolutions.resolve_as_new(
                processed.case.case_id,
                reviewer_identity=REVIEWER,
                note=(
                    "Unified demo: distinct governo.it office holder with no "
                    "existing canonical person of that name"
                ),
            )
            report.identities_created.append(name)
            gov.identities_confirmed_by_editor.append(name)
        except IdentityResolutionServiceError as exc:
            report.identities_left_unresolved.append(name)
            gov.warnings.append(f"identity left for review: {name} ({exc})")

    drafts = DraftService(session_factory)
    publish = PublishService(session_factory)
    for candidate in candidates:
        with session_factory() as session:
            match = MatchingService(session).match(candidate)
        if not isinstance(match, MatchedResult):
            continue
        if _already_published_with_identifier(session_factory, match.politician_id, candidate):
            office = candidate.profile.mandates[0].office if candidate.profile.mandates else None
            if office in PUBLISHED_OFFICES:
                gov.profiles_published.append(f"{candidate.identity.display_name} — {office}")
            else:
                gov.profiles_pending_review += 1
            continue
        draft = drafts.create(candidate, match)
        if not isinstance(draft, DraftCreatedResult):
            office = candidate.profile.mandates[0].office if candidate.profile.mandates else None
            if office in PUBLISHED_OFFICES:
                gov.profiles_published.append(f"{candidate.identity.display_name} — {office}")
            continue
        office = candidate.profile.mandates[0].office if candidate.profile.mandates else None
        if office in PUBLISHED_OFFICES:
            publish.approve(
                draft.draft_id,
                reviewer=REVIEWER,
                note="Unified demo: official governo.it profile",
            )
            gov.profiles_published.append(f"{candidate.identity.display_name} — {office}")
        else:
            gov.profiles_pending_review += 1
    return gov


def _already_published_with_identifier(session_factory, politician_id: int, candidate) -> bool:
    values = {
        item.value
        for item in candidate.identity.source_identifiers
        if item.authority == GOVERNO_SOURCE[0]
    }
    with session_factory() as session:
        politician = session.get(Politician, politician_id)
        if politician is None or politician.current_version is None:
            return False
        if politician.current_version.published_at is None:
            return False
        attached = session.scalars(
            select(PoliticianSourceIdentifier.value)
            .join(Source, Source.id == PoliticianSourceIdentifier.source_id)
            .where(
                PoliticianSourceIdentifier.politician_id == politician_id,
                Source.key == GOVERNO_SOURCE[0],
            )
        )
        return bool(values.intersection(attached))


def _published_people(session_factory) -> list[dict]:
    with session_factory() as session:
        rows = session.execute(
            select(Politician, PoliticianVersion)
            .join(PoliticianVersion, PoliticianVersion.id == Politician.current_version_id)
            .where(PoliticianVersion.published_at.is_not(None))
            .order_by(Politician.id)
        ).all()
        people = []
        for politician, version in rows:
            source_name = (
                session.scalar(
                    select(Source.name)
                    .join(
                        PoliticianSourceIdentifier,
                        PoliticianSourceIdentifier.source_id == Source.id,
                    )
                    .where(PoliticianSourceIdentifier.politician_id == politician.id)
                    .order_by(PoliticianSourceIdentifier.id)
                )
                or "Official source"
            )
            people.append(
                {
                    "id": politician.id,
                    "name": f"{politician.canonical_given_name} {politician.canonical_family_name}",
                    "given_name": politician.canonical_given_name,
                    "family_name": politician.canonical_family_name,
                    "image_url": version.profile_data.get("image_url"),
                    "source_name": source_name,
                    "source_url": version.profile_data.get("official_homepage_url")
                    or version.profile_data.get("image_url"),
                }
            )
        return people


def _prepare_portraits(
    session_factory,
    paths: UnifiedDemoPaths,
    report: UnifiedDemoReport,
    *,
    portrait_lookup: JsonGetter | None,
    portrait_download,
) -> int:
    if portrait_lookup is None:
        write_portraits(paths.portraits_json, {})
        return 0
    cache = load_cache(paths.portrait_cache)
    portraits = build_portraits(
        _published_people(session_factory),
        get_json=portrait_lookup,
        warnings=report.warnings,
        cache=cache,
    )
    store_portrait_files(
        portraits,
        paths.portraits_dir,
        fetch_bytes=portrait_download,
        warnings=report.warnings,
    )
    write_portraits(paths.portraits_json, portraits)
    write_portraits(paths.portrait_cache, cache)
    return len(portraits)


def prepare_unified_demo(
    *,
    workspace_root: Path,
    rebuild: bool = False,
    seed_from_ceo: bool | None = None,
    offline: bool = False,
    senato_fixture: Path | None = None,
    istat_fixture: Path | None = None,
    governo_collector=None,
    fetch: Fetcher = http_fetch,
    portrait_lookup: JsonGetter | None = http_get_json,
    portrait_download=None,
    settings: Settings | None = None,
) -> UnifiedDemoReport:
    if configured_environment() is AppEnvironment.PRODUCTION:
        raise DemoSafetyError("prepare_unified_demo refuses VERAPOLITICA_ENV=production")
    paths = UnifiedDemoPaths.for_workspace(workspace_root)
    validate_unified_paths(paths)
    if rebuild or not paths.database.is_file():
        wipe_unified_environment(paths)
    else:
        ensure_unified_directories(paths)

    report = UnifiedDemoReport(database_path=str(paths.database))
    seeded = False
    should_seed = (
        (rebuild or not _has_politicians(paths))
        and (seed_from_ceo is True or (seed_from_ceo is None and not offline))
    )
    if should_seed:
        seeded = seed_sqlite_from_ceo(paths)
        report.seeded_from_ceo = seeded
        if not seeded and not offline:
            raise DemoSafetyError(
                "CEO snapshot not found; pass --offline to build from fixtures, "
                "or create data/ceo_demo first"
            )

    runtime = _settings_for(paths, settings)
    engine = create_db_engine(runtime.database_url)
    try:
        prepare_runtime_schema(engine, runtime)
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)
        storage = LocalRawStorage(paths.raw_storage)

        if seeded:
            reset_ceo_ai_demo(
                settings=runtime,
                dry_run=False,
                demo_upload_path=paths.uploads,
                protected_source_keys=(PROGRAMME_SOURCE[0],),
                protected_source_urls=(PROGRAMME_URL,),
            )

        civic_from_fixtures = not _has_politicians(paths)
        if civic_from_fixtures:
            _ingest_senate_fixture(
                session_factory,
                storage,
                senato_fixture or DEFAULT_FIXTURE,
                report,
            )
            if istat_fixture is not None:
                _ingest_territories_fixture(session_factory, storage, istat_fixture)

        collector = governo_collector
        if collector is None:
            collector = (
                _offline_governo_collector()
                if offline
                else GovernoCollector(runtime.governo_index_url)
            )
        programme_fetch = fetch
        if offline and fetch is http_fetch:
            programme_fetch = _offline_fetch
        gov = _overlay_government(session_factory, storage, collector, report)
        owner = _prime_minister(session_factory)
        if owner is None:
            report.warnings.append("Prime Minister profile not found; no commitments published")
        else:
            try:
                url, raw_document_id = _ingest_programme(
                    session_factory, storage, programme_fetch, runtime, gov
                )
                _publish_commitments(session_factory, url, raw_document_id, owner, gov)
            except Exception as exc:
                report.warnings.append(f"programme not loaded: {exc}")
        report.government = gov
        report.warnings.extend(gov.warnings)

        if portrait_download is None:
            from scripts.demo_portraits import http_get_bytes as portrait_download
        portraits = _prepare_portraits(
            session_factory,
            paths,
            report,
            portrait_lookup=portrait_lookup,
            portrait_download=portrait_download,
        )
        if report.government is not None:
            report.government.portraits_found = portraits

        counts = collect_counts(session_factory, paths)
        counts.warnings.extend(integrity_warnings(session_factory, counts))
        report.counts = counts.as_dict()
        report.warnings.extend(counts.warnings)
    finally:
        engine.dispose()

    paths.report_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2, default=str), "utf-8")
    return report


def _has_politicians(paths: UnifiedDemoPaths) -> bool:
    if not paths.database.is_file():
        return False
    import sqlite3

    try:
        with sqlite3.connect(paths.database) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='politicians'"
            ).fetchone()
            if not row or row[0] == 0:
                return False
            return connection.execute("SELECT COUNT(*) FROM politicians").fetchone()[0] > 0
    except sqlite3.Error:
        return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare the unified local VeraPolitica demo")
    parser.add_argument("--rebuild", action="store_true", help="wipe only data/unified_demo and rebuild")
    parser.add_argument(
        "--seed-from-ceo",
        action="store_true",
        help="copy the existing CEO SPARQL snapshot (read-only) as the civic baseline",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="use repository fixtures instead of live official endpoints",
    )
    parser.add_argument("--senato-fixture", type=Path)
    parser.add_argument("--istat-fixture", type=Path)
    parser.add_argument("--no-portraits", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = prepare_unified_demo(
            workspace_root=REPOSITORY_ROOT,
            rebuild=args.rebuild,
            seed_from_ceo=True if args.seed_from_ceo else None,
            offline=args.offline,
            senato_fixture=args.senato_fixture,
            istat_fixture=args.istat_fixture,
            portrait_lookup=None if args.no_portraits or args.offline else http_get_json,
            fetch=_offline_fetch if args.offline else http_fetch,
            governo_collector=_offline_governo_collector() if args.offline else None,
        )
    except Exception as exc:
        print(f"Unified demo failed: {exc}", file=sys.stderr)
        return 1
    print("VeraPolitica unified demo ready")
    print(f"  Database: {report.database_path}")
    print(f"  Seeded from CEO snapshot: {report.seeded_from_ceo}")
    print(f"  Senate profiles published this run: {len(report.senate_profiles_published)}")
    print(f"  Identities linked: {len(report.identities_linked)}")
    print(f"  Identities created: {len(report.identities_created)}")
    print(f"  Identity cases left open: {len(report.identities_left_unresolved)}")
    if report.government:
        print(f"  Government profiles published: {len(report.government.profiles_published)}")
        print(f"  Commitments: {len(report.government.commitments_published)}")
        print(f"  Portraits: {report.government.portraits_found}")
    print(f"  Counts: {json.dumps(report.counts, ensure_ascii=False)}")
    for warning in report.warnings:
        print(f"  warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
