"""Read-only catalog over the unified-demo published corpus.

Never writes. Never falls back to the synthetic Ask fixture.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.text import normalize_search_text
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.evaluation.ask_dataset import default_real_ask_gold_root
from backend.app.evaluation.ask_fixture import AskEvalCatalog
from backend.app.evaluation.dataset import EvaluationDatasetError
from backend.app.models import (
    PledgeAssessment,
    PledgeClassification,
    Politician,
    PoliticianVersion,
    Proposal,
    ProposalType,
)
from backend.app.scoring.types import FulfillmentVerdict
from backend.app.services.pledge_service import PledgeService
from scripts.prepare_demo import DemoSafetyError
from scripts.unified_demo import UnifiedDemoPaths, validate_unified_paths


@dataclass(frozen=True, slots=True)
class RealAskCorpusSpec:
    corpus_name: str
    corpus_date: str
    database_relpath: str
    published_fingerprint: str
    politicians: dict[str, dict[str, str]]
    pledges: dict[str, dict[str, str]]
    notes: str = ""
    counts: dict[str, int] | None = None


def load_real_corpus_spec(root: Path | None = None) -> RealAskCorpusSpec:
    path = (root or default_real_ask_gold_root()) / "corpus.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationDatasetError(f"invalid real-corpus spec: {exc}") from exc
    try:
        return RealAskCorpusSpec(
            corpus_name=str(payload["corpus_name"]),
            corpus_date=str(payload["corpus_date"]),
            database_relpath=str(payload["database_relpath"]),
            published_fingerprint=str(payload["published_fingerprint"]),
            politicians=dict(payload["politicians"]),
            pledges=dict(payload["pledges"]),
            notes=str(payload.get("notes") or ""),
            counts=dict(payload["counts"]) if payload.get("counts") else None,
        )
    except KeyError as exc:
        raise EvaluationDatasetError(f"real-corpus spec missing {exc}") from exc


def unified_demo_database(workspace_root: Path | None = None) -> Path:
    workspace = (workspace_root or Path(__file__).resolve().parents[3]).expanduser().resolve()
    paths = UnifiedDemoPaths.for_workspace(workspace)
    try:
        validate_unified_paths(paths)
    except DemoSafetyError as exc:
        raise EvaluationDatasetError(f"real-corpus path is not the unified demo: {exc}") from exc
    if not paths.database.is_file():
        raise EvaluationDatasetError(
            "real-corpus unified demo database is unavailable at "
            f"{paths.database}. Run `python -m scripts.prepare_unified_demo` "
            "locally; the evaluator will not fall back to the synthetic fixture."
        )
    return paths.database


def create_readonly_sqlite_engine(database: Path) -> Engine:
    if not database.is_file():
        raise EvaluationDatasetError(f"real-corpus database missing: {database}")
    engine = create_db_engine(f"sqlite:///{database}")

    @event.listens_for(engine, "connect")
    def _query_only(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA query_only=ON")
        cursor.close()

    return engine


def published_ask_records(session: Session) -> tuple[dict[str, object], ...]:
    pledges = list(
        session.scalars(
            select(Proposal)
            .where(
                Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
                Proposal.published_at.is_not(None),
            )
            .order_by(Proposal.id)
        )
    )
    ids = [row.id for row in pledges]
    classifications = {
        row.proposal_id: row
        for row in session.scalars(
            select(PledgeClassification).where(PledgeClassification.proposal_id.in_(ids))
        )
    } if ids else {}
    latest = PledgeService._latest_assessments(session, ids)
    records: list[dict[str, object]] = []
    for pledge in pledges:
        classification = classifications.get(pledge.id)
        if classification is None:
            continue
        assessment = latest.get(pledge.id)
        records.append(
            {
                "title": pledge.canonical_title,
                "statement": pledge.exact_statement or "",
                "topic": classification.cap_topic_code or "",
                "verdict": (
                    assessment.verdict.value
                    if assessment is not None
                    else FulfillmentVerdict.NOT_YET_RATED.value
                ),
                "source_url": (assessment.source_url if assessment is not None else "") or "",
            }
        )
    return tuple(records)


def fingerprint_published_records(records: tuple[dict[str, object], ...]) -> str:
    blob = json.dumps(list(records), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _published_politicians(session: Session) -> list[Politician]:
    return list(
        session.scalars(
            select(Politician)
            .join(
                PoliticianVersion,
                (PoliticianVersion.id == Politician.current_version_id)
                & (PoliticianVersion.politician_id == Politician.id),
            )
            .where(
                Politician.current_version_id.is_not(None),
                PoliticianVersion.published_at.is_not(None),
            )
            .order_by(Politician.id)
        )
    )


def build_real_ask_catalog(session: Session, spec: RealAskCorpusSpec) -> AskEvalCatalog:
    records = published_ask_records(session)
    found = fingerprint_published_records(records)
    if found != spec.published_fingerprint:
        raise EvaluationDatasetError(
            "real-corpus fingerprint mismatch: the unified demo published world "
            f"is {found}, gold freeze is {spec.published_fingerprint}. "
            "Regenerate evaluation/ask_verapolitica/real_v1 or restore that corpus."
        )
    classified = list(
        session.scalars(
            select(Proposal)
            .join(PledgeClassification, PledgeClassification.proposal_id == Proposal.id)
            .where(
                Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
                Proposal.published_at.is_not(None),
            )
            .order_by(Proposal.id)
        )
    )
    latest = PledgeService._latest_assessments(session, [row.id for row in classified])
    politicians = _published_politicians(session)
    politician_ids: dict[str, int] = {}
    politician_names: dict[str, str] = {}
    for key, item in spec.politicians.items():
        given = normalize_search_text(item["given_name"])
        family = normalize_search_text(item["family_name"])
        matches = [
            row
            for row in politicians
            if normalize_search_text(row.canonical_given_name) == given
            and normalize_search_text(row.canonical_family_name) == family
        ]
        if len(matches) != 1:
            raise EvaluationDatasetError(
                f"cannot resolve published politician {key!r} ({given} {family})"
            )
        politician_ids[key] = matches[0].id
        politician_names[key] = (
            f"{matches[0].canonical_given_name} {matches[0].canonical_family_name}"
        )

    pledge_ids: dict[str, int] = {}
    pledge_titles: dict[str, str] = {}
    source_urls: dict[str, str] = {}
    for key, item in spec.pledges.items():
        prefix = normalize_search_text(item["title_prefix"])
        matches = [
            row
            for row in classified
            if prefix and prefix in normalize_search_text(row.canonical_title)
        ]
        if len(matches) != 1:
            raise EvaluationDatasetError(
                f"cannot resolve published pledge {key!r} from title_prefix {item['title_prefix']!r}"
            )
        pledge_ids[key] = matches[0].id
        pledge_titles[key] = matches[0].canonical_title
        assessment = latest.get(matches[0].id)
        if assessment is not None and assessment.source_url:
            source_urls[key] = assessment.source_url

    published_urls = tuple(
        sorted(
            {
                (assessment.source_url or "").strip()
                for assessment in session.scalars(select(PledgeAssessment))
                if (assessment.source_url or "").strip()
            }
        )
    )
    return AskEvalCatalog(
        politician_ids=politician_ids,
        politician_names=politician_names,
        pledge_ids=pledge_ids,
        pledge_titles=pledge_titles,
        source_urls=source_urls,
        published_source_urls=published_urls,
        unpublished_titles=(),
        clarification_names=(),
    )


def open_real_ask_session_factory(
    *,
    workspace_root: Path | None = None,
) -> tuple[Engine, sessionmaker[Session], Path]:
    database = unified_demo_database(workspace_root)
    engine = create_readonly_sqlite_engine(database)
    return engine, create_session_factory(engine), database
