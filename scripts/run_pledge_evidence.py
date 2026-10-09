"""Run official pledge-evidence matching. Never publishes assessments.

Examples:

    python -m scripts.run_pledge_evidence --proposal-id 106 --dry-run
    python -m scripts.run_pledge_evidence --all-unrated --conservative-judge
    python -m scripts.run_pledge_evidence --ingest-url https://www.gazzettaufficiale.it/...
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import httpx

from backend.app.core.config import Settings, get_settings
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import RawDocument
from backend.app.scoring.official_sources import classify_source_url
from backend.app.services.official_extraction_runner import (
    content_type_for_path,
    ingest_official_document,
)
from backend.app.services.pledge_evidence_service import (
    PledgeEvidenceService,
    judge_from_name,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Retrieve official evidence for classified pledges and propose "
            "pending assessment drafts. Never approves or publishes."
        )
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--proposal-id", type=int)
    target.add_argument("--all-unrated", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--conservative-judge", action="store_true")
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--ingest-url")
    parser.add_argument("--ingest-file", type=Path)
    parser.add_argument("--source-name", default="Official public document")
    parser.add_argument("--source-key")
    parser.add_argument("--published-at", help="ISO date of the official act, if known")
    return parser.parse_args(argv)


def _judge(args: argparse.Namespace, settings: Settings):
    if args.use_llm:
        model = (settings.llm_model or "").strip() or "qwen3:8b"
        return judge_from_name(
            "ollama", model_name=model, base_url=settings.ollama_base_url
        )
    if args.conservative_judge:
        return judge_from_name("conservative")
    return judge_from_name("abstaining")


def _fetch_official(url: str) -> tuple[bytes, str]:
    decision = classify_source_url(url)
    if not decision.official:
        raise ValueError(f"refusing non-official source ({decision.reason}): {url}")
    response = httpx.get(
        url,
        follow_redirects=True,
        timeout=60.0,
        headers={"User-Agent": "VeraPolitica-official-evidence/1.0"},
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "text/html").split(";")[0]
    return response.content, content_type


def _stamp_published_at(session_factory, raw_document_id: int, published: date) -> None:
    with session_factory() as session:
        document = session.get(RawDocument, raw_document_id)
        if document is None:
            return
        records = list(document.structured_records or [])
        records.append({"official_published_at": published.isoformat()})
        document.structured_records = records
        session.commit()


def ingest(
    args: argparse.Namespace, settings: Settings, session_factory
) -> dict:
    if args.ingest_file is not None:
        if not args.ingest_url:
            raise ValueError("--ingest-file requires --ingest-url of the official page")
        decision = classify_source_url(args.ingest_url)
        if not decision.official:
            raise ValueError(f"refusing non-official source ({decision.reason})")
        path = args.ingest_file.expanduser().resolve()
        content = path.read_bytes()
        content_type = content_type_for_path(path)
        source_url = args.ingest_url
    elif args.ingest_url:
        content, content_type = _fetch_official(args.ingest_url)
        source_url = args.ingest_url
    else:
        raise ValueError("ingest requires --ingest-url or --ingest-file")
    result = ingest_official_document(
        settings=settings,
        content=content,
        source_url=source_url,
        source_name=args.source_name,
        content_type=content_type,
        source_key=args.source_key,
    )
    if args.published_at:
        _stamp_published_at(
            session_factory, result["raw_document_id"], date.fromisoformat(args.published_at)
        )
    return result


def run(args: argparse.Namespace, *, settings: Settings | None = None) -> dict:
    runtime = settings or get_settings()
    engine = create_db_engine(runtime.database_url)
    try:
        prepare_runtime_schema(engine, runtime)
        session_factory = create_session_factory(engine)
        ingested = None
        if args.ingest_url or args.ingest_file:
            ingested = ingest(args, runtime, session_factory)
        if args.proposal_id is None and not args.all_unrated and ingested is not None:
            return {"ingested": ingested, "published": False}
        if args.proposal_id is None and not args.all_unrated:
            raise ValueError("pass --proposal-id, --all-unrated, or an ingest option")
        service = PledgeEvidenceService(session_factory, judge=_judge(args, runtime))
        report = service.run(
            proposal_ids=[args.proposal_id] if args.proposal_id else None,
            dry_run=args.dry_run,
        )
        return {
            "ingested": ingested,
            "pledges_considered": report.pledges_considered,
            "skipped_outcome_pledges": report.skipped_outcome_pledges,
            "passages_judged": report.passages_judged,
            "drafts_created": report.drafts_created,
            "drafts_replayed": report.drafts_replayed,
            "candidates_stored": report.candidates_stored,
            "no_candidate_abstentions": report.no_candidate_abstentions,
            "rejections": report.rejections,
            "judge": f"{service.judge.name}/{service.judge.version}",
            "dry_run": report.dry_run,
            "published": False,
        }
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run(args)
    except (ValueError, OSError, httpx.HTTPError) as exc:
        print(f"pledge evidence failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
