import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select

from backend.app.ai import FakeExtractionProvider, OpenAIExtractionProvider
from backend.app.core.config import Settings, get_settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import Source
from backend.app.pipeline.official_document_pipeline import (
    OfficialDocumentPipeline,
    OfficialDocumentPipelineError,
)
from backend.app.schemas import StructuredExtractionResult
from backend.app.services import ProposalExtractionError, ProposalExtractionService
from backend.app.storage import LocalRawStorage, StorageError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Internal editorial extraction from an operator-approved official HTML/PDF. "
            "Creates ProposalDraft rows only; never publishes."
        )
    )
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--source-key")
    parser.add_argument("--source-name", default="Operator-approved official document")
    parser.add_argument(
        "--fake-response",
        type=Path,
        help="Deterministic structured provider response for local testing; no API call.",
    )
    return parser


def _source_details(source_url: str, source_key: str | None) -> tuple[str, str]:
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("--source-url must be an absolute HTTPS official URL")
    base_url = f"https://{parsed.hostname}"
    if source_key is None:
        host_key = re.sub(r"[^a-z0-9]+", "-", parsed.hostname.lower()).strip("-")
        source_key = f"official-{host_key}"[:100]
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", source_key):
        raise ValueError("--source-key must use lowercase letters, digits, '_' or '-'")
    return source_key, base_url


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix == ".pdf":
        return "application/pdf"
    raise ValueError("only .html, .htm, and text-based .pdf files are supported")


def _provider(settings: Settings, fake_response: Path | None):
    if fake_response is not None:
        payload = json.loads(fake_response.read_text(encoding="utf-8"))
        if "output" not in payload:
            payload = {"output": payload, "usage": {"request_count": 1}}
        return FakeExtractionProvider(StructuredExtractionResult.model_validate(payload))
    if settings.llm_provider != "openai":
        raise ValueError(
            "live extraction is disabled: configure VERAPOLITICA_LLM_PROVIDER=openai "
            "or pass --fake-response"
        )
    if settings.llm_model is None or settings.llm_api_key is None:
        raise ValueError(
            "OpenAI extraction requires VERAPOLITICA_LLM_MODEL and "
            "VERAPOLITICA_LLM_API_KEY"
        )
    return OpenAIExtractionProvider(
        api_key=settings.llm_api_key.get_secret_value(),
        model_name=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def run(args: argparse.Namespace, *, settings: Settings | None = None) -> dict:
    runtime = settings or get_settings()
    file_path = args.file.expanduser().resolve()
    if not file_path.is_file():
        raise ValueError(f"document does not exist: {file_path}")
    source_key, base_url = _source_details(args.source_url, args.source_key)
    content_type = _content_type(file_path)
    provider = _provider(runtime, args.fake_response)

    engine = create_db_engine(runtime.database_url)
    try:
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            source = session.scalar(select(Source).where(Source.key == source_key))
            if source is None:
                source = Source(
                    key=source_key,
                    name=args.source_name,
                    base_url=base_url,
                )
                session.add(source)
                session.commit()
                session.refresh(source)
            elif source.base_url != base_url:
                raise ValueError(
                    f"source key {source_key!r} already belongs to {source.base_url}"
                )
            source_id = source.id
        ingestion = OfficialDocumentPipeline(
            session_factory,
            LocalRawStorage(runtime.raw_storage_path),
            max_document_bytes=runtime.ai_max_document_bytes,
            max_chunk_chars=runtime.ai_max_chunk_chars,
            max_chunks=runtime.ai_max_document_chunks,
        ).ingest(
            source_id=source_id,
            source_key=source_key,
            source_url=args.source_url,
            content_type=content_type,
            content=file_path.read_bytes(),
        )
        extraction = ProposalExtractionService(
            session_factory,
            provider,
            max_chunks_per_run=runtime.ai_max_chunks_per_run,
            max_evidence_excerpt_chars=runtime.ai_max_evidence_excerpt_chars,
        ).extract(ingestion.raw_document_id)
        return {
            "raw_document_id": ingestion.raw_document_id,
            "raw_sha256": ingestion.raw_sha256,
            "chunk_count": ingestion.chunk_count,
            "warnings": list(ingestion.warnings),
            "extraction_run_id": extraction.run_id,
            "reused_completed_run": extraction.reused_completed_run,
            "candidate_count": extraction.candidate_count,
            "accepted_count": extraction.accepted_count,
            "rejected_count": extraction.rejected_count,
            "abstained_count": extraction.abstained_count,
            "duplicate_count": extraction.duplicate_count,
            "proposal_draft_ids": list(extraction.draft_ids),
            "publication": "none — human review and approval are still required",
        }
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = run(args)
    except (
        json.JSONDecodeError,
        ValueError,
        OSError,
        OfficialDocumentPipelineError,
        ProposalExtractionError,
        StorageError,
    ) as exc:
        print(f"AI extraction failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
