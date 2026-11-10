"""Historical Senate roster: every senator mandate of the chosen legislatures.

Unlike ``SenatoCollector`` (current senators only), this keeps ended mandates
too. Every official response body is stored byte-for-byte in one raw document.
Legislature dates stay on the Camera/fixture table; this job only adds Senato
mandates and never invents a legislatura.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable
from datetime import datetime, timezone

import httpx

from backend.app.pipeline.collectors.base import CollectedDocument, CollectorError

BUNDLE_SCHEMA = "verapolitica_senato_history_v1"


def mandates_query(number: int) -> str:
    return f"""
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX osr: <http://dati.senato.it/osr/>

SELECT DISTINCT
    ?senatorUri ?firstName ?lastName ?gender
    ?mandateUri ?mandateType ?mandateStart ?mandateEnd ?legislature ?electionRegion
WHERE {{
    ?senatorUri a osr:Senatore ;
        foaf:firstName ?firstName ;
        foaf:lastName ?lastName ;
        osr:mandato ?mandateUri .

    ?mandateUri osr:legislatura ?legislature ;
        osr:inizio ?mandateStart ;
        osr:tipoMandato ?mandateType .

    OPTIONAL {{ ?mandateUri osr:fine ?mandateEnd . }}
    FILTER(?legislature = {number})

    OPTIONAL {{ ?senatorUri foaf:gender ?gender . }}
    OPTIONAL {{ ?mandateUri osr:regioneElezione ?electionRegion . }}
}}
ORDER BY ?mandateUri
""".strip()


def encode_senato_history_bundle(mandates: dict[int, bytes]) -> bytes:
    return json.dumps(
        {
            "schema": BUNDLE_SCHEMA,
            "mandate_responses_base64": {
                str(number): base64.b64encode(body).decode("ascii")
                for number, body in sorted(mandates.items())
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class SenatoHistoryCollector:
    version = "senato_history_collector_v1"
    response_media_type = "application/sparql-results+json"

    def __init__(
        self,
        endpoint: str,
        legislatures: Iterable[int],
        *,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.legislatures = sorted(set(legislatures))
        if not self.legislatures or min(self.legislatures) < 1:
            raise ValueError("legislatures must be republic legislature numbers (1 or more)")
        self.timeout_seconds = timeout_seconds
        self.client = client

    def _get(self, client: httpx.Client, query: str) -> bytes:
        response = client.get(
            self.endpoint,
            params={"query": query, "format": self.response_media_type},
            headers={
                "Accept": self.response_media_type,
                "User-Agent": "VeraPolitica/0.1 (+official-data-ingestion)",
            },
        )
        response.raise_for_status()
        return response.content

    def _collect(self, client: httpx.Client) -> bytes:
        mandates = {number: self._get(client, mandates_query(number)) for number in self.legislatures}
        return encode_senato_history_bundle(mandates)

    def collect(self) -> CollectedDocument:
        try:
            if self.client is not None:
                content = self._collect(self.client)
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    content = self._collect(client)
        except httpx.HTTPError as exc:
            raise CollectorError(f"Senato history collection failed: {exc}") from exc
        return CollectedDocument(
            content=content,
            source_url=self.endpoint,
            content_type="application/json",
            retrieved_at=datetime.now(timezone.utc),
            collector_version=self.version,
        )
