from backend.app.pipeline.parsers.base import ParsedDocument, Parser, ParserError
from backend.app.pipeline.parsers.camera import CameraParser
from backend.app.pipeline.parsers.governo import GovernoParser
from backend.app.pipeline.parsers.senato import SenatoParser
from backend.app.pipeline.parsers.senato_proposals import SenatoProposalParser
from backend.app.pipeline.parsers.territorial import (
    DaitMayorParser,
    IstatTerritoryParser,
)

__all__ = [
    "CameraParser",
    "GovernoParser",
    "ParsedDocument",
    "Parser",
    "ParserError",
    "SenatoParser",
    "SenatoProposalParser",
    "DaitMayorParser",
    "IstatTerritoryParser",
]
