import argparse
import json
import sys
from pathlib import Path

from backend.app.core.config import Settings, get_settings
from backend.app.pipeline.official_document_pipeline import OfficialDocumentPipelineError
from backend.app.services.official_extraction_runner import (
    content_type_for_path,
    run_official_extraction,
)
from backend.app.services.proposal_extraction_service import ProposalExtractionError
from backend.app.storage import StorageError


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
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Local/demo-only: create a new AIExtractionRun even if the inference "
            "fingerprint matches a completed run. Does not delete previous runs."
        ),
    )
    return parser


def run(args: argparse.Namespace, *, settings: Settings | None = None) -> dict:
    runtime = settings or get_settings()
    file_path = args.file.expanduser().resolve()
    if not file_path.is_file():
        raise ValueError(f"document does not exist: {file_path}")
    return run_official_extraction(
        settings=runtime,
        content=file_path.read_bytes(),
        source_url=args.source_url,
        source_name=args.source_name,
        content_type=content_type_for_path(file_path),
        source_key=args.source_key,
        fake_response=args.fake_response,
        force_rerun=bool(getattr(args, "force", False)),
    )


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
