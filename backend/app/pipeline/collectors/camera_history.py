"""Historical Camera roster: every deputy mandate of the chosen legislatures.

Unlike ``CameraCollector`` (current deputies only, feeding reviewed profiles),
this keeps ended mandates too. Every official response body is stored
byte-for-byte in one raw document, like the other SPARQL collectors.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable
from datetime import datetime, timezone

import httpx

from backend.app.pipeline.collectors.base import CollectedDocument, CollectorError

BUNDLE_SCHEMA = "verapolitica_camera_history_v1"
LEGISLATURE_URI = "http://dati.camera.it/ocd/legislatura.rdf/repubblica_{number}"

LEGISLATURES_QUERY = """
PREFIX ocd: <http://dati.camera.it/ocd/>

SELECT DISTINCT ?legislatureUri ?startDate ?endDate
WHERE {
    ?legislatureUri a ocd:legislatura ;
        ocd:startDate ?startDate .
    OPTIONAL { ?legislatureUri ocd:endDate ?endDate . }
}
ORDER BY ?legislatureUri
""".strip()


def mandates_query(number: int) -> str:
    legislature = LEGISLATURE_URI.format(number=number)
    return f"""
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>

SELECT DISTINCT
    ?personUri ?deputyUri ?mandateUri ?firstName ?lastName ?gender
    ?mandateStart ?mandateEnd ?electionArea ?legislature
WHERE {{
    ?deputyUri a ocd:deputato ;
        ocd:rif_leg <{legislature}> ;
        foaf:firstName ?firstName ;
        foaf:surname ?lastName ;
        ocd:rif_mandatoCamera ?mandateUri .
    ?mandateUri ocd:rif_leg <{legislature}> ;
        ocd:startDate ?mandateStart .
    OPTIONAL {{ ?mandateUri ocd:endDate ?mandateEnd . }}
    ?personUri a foaf:Person ;
        ocd:rif_mandatoCamera ?mandateUri .
    OPTIONAL {{ ?deputyUri foaf:gender ?gender . }}
    OPTIONAL {{
        ?mandateUri ocd:rif_elezione ?electionUri .
        ?electionUri dc:coverage ?electionArea .
    }}
    BIND("{number}" AS ?legislature)
}}
ORDER BY ?mandateUri
""".strip()


def encode_history_bundle(legislatures: bytes, mandates: dict[int, bytes]) -> bytes:
    return json.dumps(
        {
            "schema": BUNDLE_SCHEMA,
            "legislatures_response_base64": base64.b64encode(legislatures).decode("ascii"),
            "mandate_responses_base64": {
                str(number): base64.b64encode(body).decode("ascii")
                for number, body in sorted(mandates.items())
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class CameraHistoryCollector:
    version = "camera_history_collector_v1"
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
        legislatures = self._get(client, LEGISLATURES_QUERY)
        mandates = {number: self._get(client, mandates_query(number)) for number in self.legislatures}
        return encode_history_bundle(legislatures, mandates)

    def collect(self) -> CollectedDocument:
        try:
            if self.client is not None:
                content = self._collect(self.client)
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    content = self._collect(client)
        except httpx.HTTPError as exc:
            raise CollectorError(f"Camera history collection failed: {exc}") from exc
        return CollectedDocument(
            content=content,
            source_url=self.endpoint,
            content_type="application/json",
            retrieved_at=datetime.now(timezone.utc),
            collector_version=self.version,
        )
