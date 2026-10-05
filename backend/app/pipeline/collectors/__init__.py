from backend.app.pipeline.collectors.base import (
    CollectedDocument,
    Collector,
    CollectorError,
)
from backend.app.pipeline.collectors.camera import CameraCollector
from backend.app.pipeline.collectors.governo import GovernoCollector
from backend.app.pipeline.collectors.senato import SenatoCollector
from backend.app.pipeline.collectors.senato_proposals import SenatoProposalCollector
from backend.app.pipeline.collectors.territorial import (
    DAIT_CURRENT_MAYORS_CSV_URL,
    ISTAT_MUNICIPALITIES_XLSX_URL,
    DaitMayorCollector,
    IstatTerritoryCollector,
)

__all__ = [
    "CameraCollector",
    "CollectedDocument",
    "Collector",
    "CollectorError",
    "GovernoCollector",
    "SenatoCollector",
    "SenatoProposalCollector",
    "DAIT_CURRENT_MAYORS_CSV_URL",
    "ISTAT_MUNICIPALITIES_XLSX_URL",
    "DaitMayorCollector",
    "IstatTerritoryCollector",
]
