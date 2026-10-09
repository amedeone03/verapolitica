import argparse
import json
from pathlib import Path

from sqlalchemy import select

from backend.app.core.config import Settings, get_settings
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    AIExtractionCandidate,
    AIExtractionCandidateEvidence,
    AIExtractionRun,
    DocumentChunk,
    Proposal,
    ProposalActor,
    ProposalDraft,
    ProposalEvidence,
    ProposalReview,
    ProposalSourceIdentifier,
    ProposalStatusEvent,
    RawDocument,
)
from backend.app.pipeline.official_document_pipeline import OfficialDocumentPipeline


CEO_AI_SOURCE_URL = "https://dati.senato.it/ddl/60476.html"
PROTECTED_IDENTIFIER_PREFIXES = (
    "http://dati.senato.it/ddl/",
    "https://dati.senato.it/ddl/",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Remove AI-demo operator-document artifacts (uploads, extraction runs, "
            "unpublished or approved AI drafts). Leaves Senato SPARQL / Camera / "
            "Governo collectors, published SPARQL proposals, politicians, and "
            "territorial data intact."
        )
    )
    parser.add_argument(
        "--source-url",
        default=None,
        help=(
            "Optional official HTML URL filter. Default: all operator official-document "
            "pipeline rows (never SPARQL Senato DDL records)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print matching rows without deleting them",
    )
    return parser


def _is_protected_identifier(value: str) -> bool:
    if value.startswith("urn:verapolitica:official-claim:"):
        return False
    return value.startswith(PROTECTED_IDENTIFIER_PREFIXES) or not value.startswith(
        "urn:verapolitica:"
    )


def _empty_counts() -> dict:
    return {
        "raw_documents": 0,
        "document_chunks": 0,
        "ai_extraction_runs": 0,
        "proposal_drafts": 0,
        "proposals": 0,
        "storage_files": 0,
        "upload_files": 0,
        "skipped_protected_proposals": 0,
    }


def reset_ceo_ai_demo(
    *,
    settings: Settings | None = None,
    source_url: str | None = None,
    dry_run: bool = False,
    demo_upload_path: Path | None = None,
    protected_source_keys: tuple[str, ...] = (),
    protected_source_urls: tuple[str, ...] = (),
) -> dict:
    runtime = settings or get_settings()
    upload_root = Path(demo_upload_path or runtime.demo_upload_path)
    engine = create_db_engine(runtime.database_url)
    deleted = _empty_counts()
    try:
        prepare_runtime_schema(engine, runtime)
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            documents = list(
                session.scalars(
                    select(RawDocument).where(
                        RawDocument.collector_version
                        == OfficialDocumentPipeline.collector_version,
                    )
                )
            )
            if source_url:
                documents = [
                    document
                    for document in documents
                    if document.source_url == source_url
                ]
            if protected_source_keys or protected_source_urls:
                documents = [
                    document
                    for document in documents
                    if (document.source.key if document.source is not None else "")
                    not in protected_source_keys
                    and document.source_url not in protected_source_urls
                ]
            proposal_ids: set[int] = set()
            draft_ids: set[int] = set()
            skipped_ids: list[int] = []
            for document in documents:
                drafts = list(
                    session.scalars(
                        select(ProposalDraft).where(
                            ProposalDraft.raw_document_id == document.id
                        )
                    )
                )
                for draft in drafts:
                    identifiers = list(
                        session.scalars(
                            select(ProposalSourceIdentifier).where(
                                ProposalSourceIdentifier.proposal_id == draft.proposal_id
                            )
                        )
                    )
                    if any(
                        _is_protected_identifier(item.official_identifier)
                        for item in identifiers
                    ):
                        deleted["skipped_protected_proposals"] += 1
                        skipped_ids.append(draft.proposal_id)
                        continue
                    draft_ids.add(draft.id)
                    proposal_ids.add(draft.proposal_id)
            document_ids = [document.id for document in documents]
            run_rows = list(
                session.scalars(
                    select(AIExtractionRun).where(
                        AIExtractionRun.raw_document_id.in_(document_ids or [0])
                    )
                )
            )
            chunk_count = len(
                list(
                    session.scalars(
                        select(DocumentChunk.id).where(
                            DocumentChunk.raw_document_id.in_(document_ids or [0])
                        )
                    )
                )
            )
            storage_keys = sorted({document.storage_key for document in documents})
            upload_names = (
                sorted(item.name for item in upload_root.iterdir() if item.is_file())
                if upload_root.is_dir()
                else []
            )
            inventory = {
                "raw_document_ids": document_ids,
                "ai_extraction_run_ids": [item.id for item in run_rows],
                "proposal_draft_ids": sorted(draft_ids),
                "proposal_ids": sorted(proposal_ids),
                "skipped_protected_proposal_ids": skipped_ids,
                "storage_keys": storage_keys,
                "upload_files_listed": upload_names,
                "preserved": (
                    "Senato/Camera/Governo/ISTAT/DAIT collectors, SPARQL proposal "
                    "drafts, published SPARQL proposals, politician profiles, "
                    "and territories. Failed operator-document extraction history "
                    "is removed with those documents, not preserved."
                ),
            }
            if dry_run:
                deleted["raw_documents"] = len(documents)
                deleted["document_chunks"] = chunk_count
                deleted["ai_extraction_runs"] = len(run_rows)
                deleted["proposal_drafts"] = len(draft_ids)
                deleted["proposals"] = len(proposal_ids)
                deleted["storage_files"] = len(storage_keys)
                deleted["upload_files"] = len(upload_names)
                return {
                    "dry_run": True,
                    "source_url": source_url,
                    **deleted,
                    **inventory,
                }

            candidates = list(
                session.scalars(
                    select(AIExtractionCandidate).where(
                        AIExtractionCandidate.proposal_draft_id.in_(draft_ids or [0])
                    )
                )
            )
            run_ids = {
                item.id
                for item in session.scalars(
                    select(AIExtractionRun).where(
                        AIExtractionRun.raw_document_id.in_(
                            [document.id for document in documents] or [0]
                        )
                    )
                )
            }
            run_ids.update(candidate.run_id for candidate in candidates)
            all_candidates = list(
                session.scalars(
                    select(AIExtractionCandidate).where(
                        AIExtractionCandidate.run_id.in_(run_ids or [0])
                    )
                )
            )
            candidate_ids = [item.id for item in all_candidates]
            session.query(AIExtractionCandidateEvidence).filter(
                AIExtractionCandidateEvidence.candidate_id.in_(candidate_ids or [0])
            ).delete(synchronize_session=False)
            for candidate in all_candidates:
                candidate.proposal_draft_id = None
            session.flush()
            session.query(AIExtractionCandidate).filter(
                AIExtractionCandidate.id.in_(candidate_ids or [0])
            ).delete(synchronize_session=False)
            deleted["ai_extraction_runs"] = session.query(AIExtractionRun).filter(
                AIExtractionRun.id.in_(run_ids or [0])
            ).delete(synchronize_session=False)

            session.query(ProposalReview).filter(
                ProposalReview.draft_id.in_(draft_ids or [0])
            ).delete(synchronize_session=False)
            session.query(ProposalEvidence).filter(
                ProposalEvidence.draft_id.in_(draft_ids or [0])
            ).delete(synchronize_session=False)
            for draft in session.scalars(
                select(ProposalDraft).where(ProposalDraft.id.in_(draft_ids or [0]))
            ):
                draft.baseline_status_event_id = None
            session.flush()
            deleted["proposal_drafts"] = session.query(ProposalDraft).filter(
                ProposalDraft.id.in_(draft_ids or [0])
            ).delete(synchronize_session=False)
            session.query(ProposalActor).filter(
                ProposalActor.proposal_id.in_(proposal_ids or [0])
            ).delete(synchronize_session=False)
            session.query(ProposalStatusEvent).filter(
                ProposalStatusEvent.proposal_id.in_(proposal_ids or [0])
            ).delete(synchronize_session=False)
            session.query(ProposalSourceIdentifier).filter(
                ProposalSourceIdentifier.proposal_id.in_(proposal_ids or [0])
            ).delete(synchronize_session=False)
            deleted["proposals"] = session.query(Proposal).filter(
                Proposal.id.in_(proposal_ids or [0])
            ).delete(synchronize_session=False)

            chunk_ids = [
                item.id
                for item in session.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.raw_document_id.in_(
                            [document.id for document in documents] or [0]
                        )
                    )
                )
            ]
            deleted["document_chunks"] = session.query(DocumentChunk).filter(
                DocumentChunk.id.in_(chunk_ids or [0])
            ).delete(synchronize_session=False)
            storage_root = Path(runtime.raw_storage_path)
            remaining_keys = {
                item
                for item in session.scalars(
                    select(RawDocument.storage_key).where(
                        RawDocument.id.notin_(document_ids or [0])
                    )
                )
            }
            seen_keys: set[str] = set()
            for document in documents:
                if document.storage_key in seen_keys:
                    continue
                seen_keys.add(document.storage_key)
                if document.storage_key in remaining_keys:
                    continue
                target = storage_root / document.storage_key
                if target.is_file():
                    target.unlink()
                    deleted["storage_files"] += 1
            deleted["raw_documents"] = session.query(RawDocument).filter(
                RawDocument.id.in_(document_ids or [0])
            ).delete(synchronize_session=False)
            if upload_root.is_dir():
                for item in upload_root.iterdir():
                    if item.is_file():
                        item.unlink()
                        deleted["upload_files"] += 1
            session.commit()
            return {
                "dry_run": False,
                "source_url": source_url,
                **deleted,
                **inventory,
            }
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    summary = reset_ceo_ai_demo(source_url=args.source_url, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
