import argparse
import json
import sys
from collections.abc import Sequence

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.schemas import MatchedResult
from backend.app.services import (
    CandidateIdentityCoordinator,
    CandidateRebuildError,
    DraftService,
    DraftServiceError,
    IdentityServiceError,
    RawDocumentCandidateRebuilder,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create one reviewable profile draft from a stored source record."
    )
    parser.add_argument(
        "--candidate-index",
        required=True,
        type=int,
        help="zero-based structured-record index to process",
    )
    parser.add_argument(
        "--raw-document-id",
        type=int,
        help="successfully parsed RawDocument (defaults to latest for source)",
    )
    parser.add_argument(
        "--source-key",
        default="senato-repubblica",
        help="source authority (default: senato-repubblica)",
    )
    return parser


def _error_payload(message: str, error_type: str) -> str:
    return json.dumps(
        {"error": message, "error_type": error_type},
        indent=2,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.candidate_index < 0:
        print(
            _error_payload("--candidate-index must be non-negative", "ValueError"),
            file=sys.stderr,
        )
        return 1
    if args.raw_document_id is not None and args.raw_document_id <= 0:
        print(
            _error_payload("--raw-document-id must be positive", "ValueError"),
            file=sys.stderr,
        )
        return 1

    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    try:
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)
        rebuilt = RawDocumentCandidateRebuilder(session_factory).rebuild(
            raw_document_id=args.raw_document_id,
            source_key=args.source_key,
        )
        indexed = next(
            (
                item
                for item in rebuilt.candidates
                if item.candidate_index == args.candidate_index
            ),
            None,
        )
        if indexed is None:
            invalid = next(
                (
                    item
                    for item in rebuilt.invalid
                    if item.candidate_index == args.candidate_index
                ),
                None,
            )
            detail = f": {invalid.error}" if invalid else ""
            print(
                _error_payload(
                    f"candidate index {args.candidate_index} is unavailable{detail}",
                    "CandidateSelectionError",
                ),
                file=sys.stderr,
            )
            return 1

        resolution = CandidateIdentityCoordinator(session_factory).match_and_link(
            indexed.profile
        )
        match = resolution.match
        if not isinstance(match, MatchedResult):
            print(
                json.dumps(
                    {
                        "error": "candidate does not have one deterministic match",
                        "error_type": "CandidateNotMatchedError",
                        "matching_result": match.model_dump(mode="json"),
                    },
                    indent=2,
                )
            )
            return 2

        result = DraftService(session_factory).create(indexed.profile, match)
        print(result.model_dump_json(indent=2))
        return 0
    except (CandidateRebuildError, DraftServiceError, IdentityServiceError) as exc:
        print(
            _error_payload(str(exc), type(exc).__name__),
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
