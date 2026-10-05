from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.app.pipeline.collectors.base import CollectedDocument, CollectorError


ISTAT_MUNICIPALITIES_XLSX_URL = (
    "https://www.istat.it/storage/codici-unita-amministrative/"
    "Elenco-comuni-italiani.xlsx"
)
DAIT_CURRENT_MAYORS_CSV_URL = (
    "https://dait.interno.gov.it/documenti/sindaciincarica.csv"
)


class _OfficialFileCollector:
    version = "official_file_collector_v1"
    content_type = "application/octet-stream"

    def __init__(
        self,
        source_url: str,
        *,
        fixture_path: str | Path | None = None,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.source_url = source_url
        self.fixture_path = Path(fixture_path) if fixture_path is not None else None
        self.timeout_seconds = timeout_seconds
        self.client = client

    def collect(self) -> CollectedDocument:
        try:
            if self.fixture_path is not None:
                content = self.fixture_path.read_bytes()
            elif self.client is not None:
                content = self._download(self.client)
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    content = self._download(client)
            source_url = self.source_url
        except (OSError, httpx.HTTPError) as exc:
            raise CollectorError(f"{type(self).__name__} failed: {exc}") from exc
        if not content:
            raise CollectorError(f"{type(self).__name__} returned an empty document")
        return CollectedDocument(
            content=content,
            source_url=source_url,
            content_type=self.content_type,
            retrieved_at=datetime.now(timezone.utc),
            collector_version=self.version,
        )

    def _download(self, client: httpx.Client) -> bytes:
        response = client.get(
            self.source_url,
            headers={
                "User-Agent": (
                    "VeraPolitica/0.1 (official open-data research; "
                    "https://www.istat.it/classificazione/"
                    "codici-dei-comuni-delle-province-e-delle-regioni/)"
                ),
                "Accept": "*/*",
            },
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.content


class IstatTerritoryCollector(_OfficialFileCollector):
    """Collect ISTAT's stable municipality workbook, preserving its raw bytes."""

    version = "istat_territory_collector_v1"
    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def __init__(self, source_url: str = ISTAT_MUNICIPALITIES_XLSX_URL, **kwargs) -> None:
        super().__init__(source_url, **kwargs)


class DaitMayorCollector(_OfficialFileCollector):
    """Collect DAIT's current-administrators semicolon-delimited export."""

    version = "dait_mayor_collector_v1"
    content_type = "text/csv; charset=utf-8"

    def __init__(self, source_url: str = DAIT_CURRENT_MAYORS_CSV_URL, **kwargs) -> None:
        super().__init__(source_url, **kwargs)
