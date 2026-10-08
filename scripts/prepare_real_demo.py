"""Rebuild the local demo from real, official data (no synthetic politicians).

1. Collect the current Government from governo.it with the production
   collector, parser and mapper.
2. Bootstrap identities and publish the profiles of the Prime Minister,
   Deputy Prime Ministers and Ministers (the demo-setup reviewer stands in
   for the editorial approval). Other office holders stay as pending drafts
   for the editorial demo.
3. Ingest the official programme statement (dichiarazioni programmatiche)
   as an operator-approved document, select explicit-commitment sentences
   deterministically, publish them as explicit promises owned by the Prime
   Minister, quoted verbatim, and classify them.
4. No fulfilment verdict is created: every commitment stays "not yet rated"
   until an editor approves an evidence-backed assessment.

Demo only. It never runs against VERAPOLITICA_ENV=production and never
touches the normal development database.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import select

from backend.app.core.config import AppEnvironment, Settings, configured_environment
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    DocumentChunk,
    Politician,
    PoliticianSourceIdentifier,
    PoliticianVersion,
    RawDocument,
    Source,
)
from backend.app.pipeline.collectors import GovernoCollector
from backend.app.pipeline.collectors.base import CollectedDocument
from backend.app.pipeline.ingestion_pipeline import IngestionPipeline
from backend.app.pipeline.mappers import GovernoCandidateProfileMapper
from backend.app.pipeline.official_document_pipeline import OfficialDocumentPipeline
from backend.app.pipeline.parsers import GovernoParser
from backend.app.pipeline.pledge_candidates import EXTRACTOR_VERSION, select_pledge_candidates
from backend.app.schemas import (
    DraftCreatedResult,
    MatchedResult,
    ProposalActorObservation,
    ProposalEvidenceObservation,
    ProposalObservation,
)
from backend.app.schemas.pledge import PledgeClassificationRequest
from backend.app.scoring import CommitmentType, HolderRole
from backend.app.services import (
    CandidateRebuildResult,
    DraftService,
    HumanIdentityResolutionCoordinator,
    IdentityResolutionService,
    IdentityResolutionServiceError,
    IndexedCandidate,
    MatchingService,
    PoliticianBootstrapService,
    ProposalReviewService,
    ProposalService,
    PublishService,
)
from backend.app.services.pledge_service import PledgeService
from backend.app.storage import LocalRawStorage
from scripts.demo_portraits import JsonGetter, build_portraits, http_get_json, write_portraits
from scripts.prepare_demo import DemoPaths, DemoSafetyError, reset_demo_environment

GOVERNO_SOURCE = ("governo-italiano", "Governo Italiano", "https://www.governo.it")
PROGRAMME_SOURCE = (
    "governo-dichiarazioni-programmatiche",
    "Governo Italiano — Dichiarazioni programmatiche",
    "https://www.governo.it",
)
PROGRAMME_URL = (
    "https://www.governo.it/it/articolo/"
    "le-dichiarazioni-programmatiche-del-governo-meloni/20770"
)
PROGRAMME_DATE = date(2022, 10, 25)
# Mandate window used for "mandate elapsed": government sworn in on 22 Oct 2022;
# the XIX legislature reaches its natural end five years after its first sitting.
MANDATE_START = date(2022, 10, 22)
MANDATE_END = date(2027, 10, 12)
PUBLISHED_OFFICES = (
    "Presidente del Consiglio",
    "Vice Presidente del Consiglio",
    "Ministro",
    "Ministro senza portafoglio",
)
REVIEWER = "demo-setup"
USER_AGENT = "VeraPolitica/0.1 (+official-data-ingestion; local demo)"
MIN_CANDIDATES_BEFORE_PDF = 6


@dataclass
class RealDemoReport:
    database_path: str
    politicians_collected: int = 0
    profiles_published: list[str] = field(default_factory=list)
    profiles_pending_review: int = 0
    identities_confirmed_by_editor: list[str] = field(default_factory=list)
    programme_url: str | None = None
    programme_chunks: int = 0
    commitment_owner: str | None = None
    commitments_published: list[str] = field(default_factory=list)
    portraits_found: int = 0
    warnings: list[str] = field(default_factory=list)
    extractor_version: str = EXTRACTOR_VERSION


Fetcher = Callable[[str], tuple[bytes, str]]


def http_fetch(url: str) -> tuple[bytes, str]:
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        content_type = response.headers.get("content-type", "text/html").split(";")[0].strip()
        return response.content, content_type


def _source(session_factory, key: str, name: str, base_url: str) -> int:
    with session_factory() as session:
        source = Source(key=key, name=name, base_url=base_url)
        session.add(source)
        session.commit()
        return source.id


def _office(profile_data: dict) -> str | None:
    mandates = profile_data.get("mandates") or []
    return mandates[0].get("office") if mandates else None


def _publish_government(session_factory, storage, collector, report: RealDemoReport) -> None:
    source_id = _source(session_factory, *GOVERNO_SOURCE)
    ingestion = IngestionPipeline(
        session_factory=session_factory,
        storage=storage,
        collector=collector,
        parser=GovernoParser(),
        profile_mapper=GovernoCandidateProfileMapper(),
    ).run(source_id=source_id, source_key=GOVERNO_SOURCE[0])
    candidates = ingestion.candidate_profiles
    report.politicians_collected = len(candidates)
    if not candidates:
        raise RuntimeError("governo.it returned no office holders")
    rebuilt = CandidateRebuildResult(
        raw_document_id=ingestion.raw_document_id,
        candidates=tuple(
            IndexedCandidate(candidate_index=index, profile=candidate)
            for index, candidate in enumerate(candidates)
        ),
        invalid=(),
    )
    bootstrap = PoliticianBootstrapService(session_factory)
    plan = bootstrap.plan(rebuilt, dry_run=False)
    blocked: set[int] = set()
    if not plan.report.safe_to_apply:
        # Identity safety rules (e.g. no birth date on the official page) block
        # automatic creation. Those candidates go through the editorial path
        # instead: an identity-resolution case that the demo editor resolves.
        blocked = {item.candidate_index for item in plan.report.invalid} | {
            item.candidate_index for item in plan.report.uncertain
        }
        rebuilt = CandidateRebuildResult(
            raw_document_id=ingestion.raw_document_id,
            candidates=tuple(c for c in rebuilt.candidates if c.candidate_index not in blocked),
            invalid=(),
        )
        plan = bootstrap.plan(rebuilt, dry_run=False)
    bootstrap.apply(plan)

    coordinator = HumanIdentityResolutionCoordinator(session_factory)
    resolutions = IdentityResolutionService(session_factory)
    for index in sorted(blocked):
        candidate = candidates[index]
        processed = coordinator.process(candidate)
        if processed.case is None:
            continue
        try:
            resolutions.resolve_as_new(
                processed.case.case_id,
                reviewer_identity=REVIEWER,
                note=(
                    "Local real-data demo: distinct office holder listed on the "
                    "official governo.it Government page (no birth date published)"
                ),
            )
            report.identities_confirmed_by_editor.append(candidate.identity.display_name)
        except IdentityResolutionServiceError as exc:
            report.warnings.append(
                f"identity left for review: {candidate.identity.display_name} ({exc})"
            )

    for candidate in candidates:
        with session_factory() as session:
            match = MatchingService(session).match(candidate)
        if not isinstance(match, MatchedResult):
            continue
        draft = DraftService(session_factory).create(candidate, match)
        if not isinstance(draft, DraftCreatedResult):
            continue
        office = candidate.profile.mandates[0].office if candidate.profile.mandates else None
        if office in PUBLISHED_OFFICES:
            PublishService(session_factory).approve(
                draft.draft_id,
                reviewer=REVIEWER,
                note="Local real-data demo: official governo.it profile",
            )
            report.profiles_published.append(f"{candidate.identity.display_name} — {office}")
        else:
            report.profiles_pending_review += 1


def _prime_minister(session_factory) -> tuple[int, str, str] | None:
    """(politician_id, display name, governo source identifier) of the PM."""

    with session_factory() as session:
        rows = session.execute(
            select(Politician, PoliticianVersion)
            .join(PoliticianVersion, PoliticianVersion.id == Politician.current_version_id)
            .where(PoliticianVersion.published_at.is_not(None))
        ).all()
        for politician, version in rows:
            if _office(version.profile_data) == "Presidente del Consiglio":
                identifier = session.scalar(
                    select(PoliticianSourceIdentifier.value)
                    .join(Source, Source.id == PoliticianSourceIdentifier.source_id)
                    .where(
                        PoliticianSourceIdentifier.politician_id == politician.id,
                        Source.key == GOVERNO_SOURCE[0],
                    )
                    .order_by(PoliticianSourceIdentifier.id)
                )
                if identifier:
                    name = f"{politician.canonical_given_name} {politician.canonical_family_name}"
                    return politician.id, name, identifier
    return None


def _pdf_link(html_bytes: bytes, base_url: str) -> str | None:
    text = html_bytes.decode("utf-8", errors="ignore")
    for href in re.findall(r'href=["\']([^"\']+\.pdf)["\']', text, re.IGNORECASE):
        absolute = urljoin(base_url, href)
        if urlparse(absolute).hostname in {"www.governo.it", "governo.it"}:
            return absolute
    return None


def _ingest_programme(session_factory, storage, fetch: Fetcher, settings: Settings, report):
    source_id = _source(session_factory, *PROGRAMME_SOURCE)
    pipeline = OfficialDocumentPipeline(
        session_factory,
        storage,
        max_document_bytes=settings.ai_max_document_bytes,
        max_chunk_chars=settings.ai_max_chunk_chars,
        max_chunks=settings.ai_max_document_chunks,
    )
    content, content_type = fetch(PROGRAMME_URL)
    result = pipeline.ingest(
        source_id=source_id,
        source_key=PROGRAMME_SOURCE[0],
        source_url=PROGRAMME_URL,
        content_type=content_type,
        content=content,
    )
    url, raw_document_id, chunks = PROGRAMME_URL, result.raw_document_id, result.chunk_count
    with session_factory() as session:
        text = session.get(RawDocument, raw_document_id).normalized_text or ""
    if len(select_pledge_candidates(text)) < MIN_CANDIDATES_BEFORE_PDF:
        pdf_url = _pdf_link(content, PROGRAMME_URL)
        if pdf_url:
            pdf_content, _ = fetch(pdf_url)
            pdf = pipeline.ingest(
                source_id=source_id,
                source_key=PROGRAMME_SOURCE[0],
                source_url=pdf_url,
                content_type="application/pdf",
                content=pdf_content,
            )
            url, raw_document_id, chunks = pdf_url, pdf.raw_document_id, pdf.chunk_count
    report.programme_url = url
    report.programme_chunks = chunks
    return url, raw_document_id


def _publish_commitments(session_factory, url: str, raw_document_id: int, owner, report) -> None:
    politician_id, owner_name, owner_identifier = owner
    report.commitment_owner = owner_name
    with session_factory() as session:
        document = session.get(RawDocument, raw_document_id)
        text = document.normalized_text or ""
        chunk_texts = list(
            session.scalars(
                select(DocumentChunk.text)
                .where(DocumentChunk.raw_document_id == raw_document_id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
    # Select within chunks so every quote is fully inside one stored chunk.
    candidates = []
    for chunk in chunk_texts:
        candidates.extend(select_pledge_candidates(chunk, limit=40, per_topic=40))
    candidates.sort(key=lambda item: (-item.score, item.position))
    chosen, per_topic = [], {}
    for candidate in candidates:
        if per_topic.get(candidate.topic_code, 0) >= 2:
            continue
        chosen.append(candidate)
        per_topic[candidate.topic_code] = per_topic.get(candidate.topic_code, 0) + 1
        if len(chosen) >= 12:
            break

    proposals = ProposalService(session_factory)
    reviews = ProposalReviewService(session_factory)
    pledges = PledgeService(session_factory)
    for index, candidate in enumerate(chosen, start=1):
        if candidate.sentence not in text:
            report.warnings.append(f"skipped non-verbatim candidate: {candidate.title}")
            continue
        identifier = f"{url}#impegno-{index}"
        observation = ProposalObservation(
            source_key=PROGRAMME_SOURCE[0],
            raw_document_id=raw_document_id,
            proposal_identifier=identifier,
            title=candidate.title,
            exact_statement=candidate.sentence,
            proposal_type="explicit_promise",
            introduced_at=PROGRAMME_DATE,
            source_status_label="impegno dichiarato",
            normalized_status="announced",
            status_effective_at=PROGRAMME_DATE,
            official_url=url,
            source_field="dichiarazioni programmatiche",
            observed_at=datetime.now(timezone.utc),
            actors=(
                ProposalActorObservation(
                    actor_type="politician",
                    role="commitment_owner",
                    display_name=owner_name,
                    authority_key=GOVERNO_SOURCE[0],
                    source_identifier=owner_identifier,
                    source_field="Presidente del Consiglio",
                ),
            ),
            evidence=tuple(
                ProposalEvidenceObservation(
                    field_path=path, source_url=url, source_field=field_name, source_value=value
                )
                for path, field_name, value in (
                    ("title", "testo", candidate.sentence),
                    ("proposal_type", "tipo", "impegno esplicito"),
                    ("current_status", "stato", "impegno dichiarato"),
                    ("introduced_at", "data", PROGRAMME_DATE.isoformat()),
                    ("exact_statement", "testo", candidate.sentence),
                )
            ),
            metadata={"extractor": EXTRACTOR_VERSION, "demo": "real_data"},
        )
        detail = proposals.sync((observation,)).details[0]
        if not detail.draft_id:
            continue
        reviews.approve(
            detail.draft_id,
            reviewer=REVIEWER,
            note="Local real-data demo: verbatim sentence from the official programme",
        )
        pledges.classify(
            detail.proposal_id,
            PledgeClassificationRequest(
                specificity=candidate.specificity,
                commitment_type=CommitmentType.ACTION,
                holder_role=HolderRole.GOVERNMENT_COALITION,
                cap_topic_code=candidate.topic_code,
                mandate_start=MANDATE_START,
                mandate_end=MANDATE_END,
                note="Automatic demo classification; editorial review pending",
            ),
            classified_by=REVIEWER,
        )
        report.commitments_published.append(candidate.title)


def _published_people(session_factory) -> list[dict]:
    with session_factory() as session:
        rows = session.execute(
            select(Politician, PoliticianVersion)
            .join(PoliticianVersion, PoliticianVersion.id == Politician.current_version_id)
            .where(PoliticianVersion.published_at.is_not(None))
            .order_by(Politician.id)
        ).all()
    return [
        {
            "id": politician.id,
            "name": f"{politician.canonical_given_name} {politician.canonical_family_name}",
            "given_name": politician.canonical_given_name,
            "family_name": politician.canonical_family_name,
            "image_url": version.profile_data.get("image_url"),
            "source_name": GOVERNO_SOURCE[1],
            "source_url": version.profile_data.get("official_homepage_url"),
        }
        for politician, version in rows
    ]


def prepare_real_demo(
    *,
    workspace_root: Path,
    collector=None,
    fetch: Fetcher = http_fetch,
    portrait_lookup: JsonGetter | None = http_get_json,
    settings: Settings | None = None,
) -> RealDemoReport:
    if configured_environment() is AppEnvironment.PRODUCTION:
        raise DemoSafetyError("prepare_real_demo refuses VERAPOLITICA_ENV=production")
    settings = settings or Settings()
    paths = DemoPaths.for_workspace(workspace_root)
    reset_demo_environment(paths)
    report = RealDemoReport(database_path=str(paths.database))
    engine = create_db_engine(f"sqlite:///{paths.database}")
    try:
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)
        storage = LocalRawStorage(paths.raw_storage)
        _publish_government(
            session_factory,
            storage,
            collector or GovernoCollector(settings.governo_index_url),
            report,
        )
        owner = _prime_minister(session_factory)
        if owner is None:
            report.warnings.append("Prime Minister profile not found; no commitments published")
        else:
            try:
                url, raw_document_id = _ingest_programme(
                    session_factory, storage, fetch, settings, report
                )
                _publish_commitments(session_factory, url, raw_document_id, owner, report)
            except Exception as exc:  # the profiles are still useful on their own
                report.warnings.append(f"programme not loaded: {exc}")
        portraits = (
            build_portraits(
                _published_people(session_factory),
                get_json=portrait_lookup,
                warnings=report.warnings,
            )
            if portrait_lookup is not None
            else {}
        )
        write_portraits(paths.demo_root / "portraits.json", portraits)
        report.portraits_found = len(portraits)
    finally:
        engine.dispose()
    report_path = paths.demo_root / "real_demo_report.json"
    report_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), "utf-8")
    return report


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        report = prepare_real_demo(workspace_root=root)
    except Exception as exc:
        print(f"Real-data demo failed: {exc}", file=sys.stderr)
        print("Check the internet connection, or run the synthetic demo: scripts\\run_demo.cmd synthetic")
        return 1
    print("VeraPolitica real-data demo ready")
    print(f"  Profiles collected from governo.it: {report.politicians_collected}")
    print(f"  Published profiles: {len(report.profiles_published)}")
    print(f"  Pending profile drafts for editors: {report.profiles_pending_review}")
    print(f"  Commitments from {report.programme_url}: {len(report.commitments_published)}")
    print(f"  Portraits (official or Wikimedia Commons, credited): {report.portraits_found}")
    for warning in report.warnings:
        print(f"  warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
