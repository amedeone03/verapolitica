from backend.app.pipeline.collectors.base import (
    CollectedDocument,
    Collector,
    CollectorError,
)
from backend.app.pipeline.collectors.camera import CameraCollector
from backend.app.pipeline.collectors.governo import GovernoCollector
from backend.app.pipeline.collectors.senato import SenatoCollector

__all__ = [
    "CameraCollector",
    "CollectedDocument",
    "Collector",
    "CollectorError",
    "GovernoCollector",
    "SenatoCollector",
]
