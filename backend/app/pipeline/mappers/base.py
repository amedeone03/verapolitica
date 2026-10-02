from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from backend.app.schemas import CandidateProfile, SourceDocumentProvenance


class CandidateMappingError(ValueError):
    pass


class CandidateProfileMapper(Protocol):
    def map_records(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        document: SourceDocumentProvenance,
    ) -> tuple[CandidateProfile, ...]: ...
