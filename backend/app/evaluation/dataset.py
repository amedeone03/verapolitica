import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from backend.app.ai import ExtractionChunk
from backend.app.pipeline.document_chunking import DocumentChunkData, chunk_document
from backend.app.pipeline.document_extraction import extract_document
from backend.app.schemas.ai_evaluation import GoldEvaluationDataset, GoldExtractionCase
from backend.app.services.proposal_extraction_service import ProposalExtractionService


class EvaluationDatasetError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LoadedEvaluationCase:
    gold: GoldExtractionCase
    document_path: Path
    chunks: tuple[DocumentChunkData, ...]

    def provider_chunks(self) -> tuple[ExtractionChunk, ...]:
        return tuple(
            ExtractionChunk(
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
            )
            for chunk in self.chunks
        )


@dataclass(frozen=True, slots=True)
class LoadedEvaluationDataset:
    manifest: GoldEvaluationDataset
    root: Path
    cases: tuple[LoadedEvaluationCase, ...]


def _resolve_under(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise EvaluationDatasetError(f"dataset path escapes root: {relative_path}")
    if not candidate.is_file():
        raise EvaluationDatasetError(f"dataset document does not exist: {relative_path}")
    return candidate


def load_gold_dataset(dataset_root: Path) -> LoadedEvaluationDataset:
    root = dataset_root.expanduser().resolve()
    manifest_path = root / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = GoldEvaluationDataset.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise EvaluationDatasetError(f"invalid evaluation manifest: {exc}") from exc

    loaded_cases: list[LoadedEvaluationCase] = []
    for case in manifest.cases:
        document_path = _resolve_under(root, case.document)
        content_type = (
            "application/pdf"
            if document_path.suffix.lower() == ".pdf"
            else "text/html"
        )
        try:
            extracted = extract_document(document_path.read_bytes(), content_type)
            chunks = chunk_document(
                extracted,
                max_chunk_chars=manifest.max_chunk_chars,
                max_chunks=manifest.max_chunks,
            )
        except Exception as exc:
            raise EvaluationDatasetError(
                f"case {case.case_id} document extraction failed: {exc}"
            ) from exc
        chunk_by_index = {chunk.chunk_index: chunk for chunk in chunks}
        for claim in case.claims:
            for evidence in claim.evidence:
                chunk = chunk_by_index.get(evidence.chunk_index)
                if chunk is None:
                    raise EvaluationDatasetError(
                        f"case {case.case_id} claim {claim.claim_id} references "
                        f"missing chunk {evidence.chunk_index}"
                    )
                normalized_excerpt = ProposalExtractionService._normalized_evidence(
                    evidence.supporting_text
                )
                normalized_chunk = ProposalExtractionService._normalized_evidence(
                    chunk.text
                )
                if normalized_excerpt not in normalized_chunk:
                    raise EvaluationDatasetError(
                        f"case {case.case_id} claim {claim.claim_id} has evidence "
                        "that is absent from its chunk"
                    )
                if evidence.page is not None and not (
                    chunk.page_start is not None
                    and chunk.page_end is not None
                    and chunk.page_start <= evidence.page <= chunk.page_end
                ):
                    raise EvaluationDatasetError(
                        f"case {case.case_id} claim {claim.claim_id} has invalid page"
                    )
        loaded_cases.append(
            LoadedEvaluationCase(
                gold=case,
                document_path=document_path,
                chunks=chunks,
            )
        )
    return LoadedEvaluationDataset(
        manifest=manifest,
        root=root,
        cases=tuple(loaded_cases),
    )
