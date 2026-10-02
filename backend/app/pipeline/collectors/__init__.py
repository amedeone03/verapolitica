from backend.app.pipeline.collectors.base import (
    CollectedDocument,
    Collector,
    CollectorError,
)
from backend.app.pipeline.collectors.senato import SenatoCollector

__all__ = ["CollectedDocument", "Collector", "CollectorError", "SenatoCollector"]
