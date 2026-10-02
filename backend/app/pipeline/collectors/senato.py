from datetime import datetime, timezone

import httpx

from backend.app.pipeline.collectors.base import CollectedDocument, CollectorError


class SenatoCollector:
    """Collect current senators as a SPARQL JSON result document."""

    version = "senato_collector_v1"
    response_media_type = "application/sparql-results+json"

    def __init__(
        self,
        endpoint: str,
        legislature: int,
        *,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.legislature = legislature
        self.timeout_seconds = timeout_seconds
        self.client = client

    @property
    def query(self) -> str:
        return f"""
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX osr: <http://dati.senato.it/osr/>

SELECT DISTINCT
    ?senatorUri ?firstName ?lastName ?gender
    ?birthDate ?birthCity ?birthProvince ?birthCountry
    ?profession ?photoUrl ?homepage
    ?mandateUri ?mandateType ?mandateStart ?legislature ?electionRegion
WHERE {{
    ?senatorUri a osr:Senatore ;
        foaf:firstName ?firstName ;
        foaf:lastName ?lastName ;
        osr:mandato ?mandateUri .

    ?mandateUri osr:legislatura ?legislature ;
        osr:inizio ?mandateStart ;
        osr:tipoMandato ?mandateType .

    OPTIONAL {{ ?mandateUri osr:fine ?mandateEnd . }}
    FILTER(?legislature = {self.legislature})
    FILTER(!BOUND(?mandateEnd))

    OPTIONAL {{ ?senatorUri foaf:gender ?gender . }}
    OPTIONAL {{ ?senatorUri osr:dataNascita ?birthDate . }}
    OPTIONAL {{ ?senatorUri osr:cittaNascita ?birthCity . }}
    OPTIONAL {{ ?senatorUri osr:provinciaNascita ?birthProvince . }}
    OPTIONAL {{ ?senatorUri osr:nazioneNascita ?birthCountry . }}
    OPTIONAL {{ ?senatorUri dc:description ?profession . }}
    OPTIONAL {{ ?senatorUri foaf:depiction ?photoUrl . }}
    OPTIONAL {{ ?senatorUri foaf:homepage ?homepage . }}
    OPTIONAL {{ ?mandateUri osr:regioneElezione ?electionRegion . }}
}}
ORDER BY ?senatorUri
""".strip()

    def collect(self) -> CollectedDocument:
        request_params = {"query": self.query, "format": self.response_media_type}
        headers = {
            "Accept": self.response_media_type,
            "User-Agent": "VeraPolitica/0.1 (+official-data-ingestion)",
        }

        try:
            if self.client is not None:
                response = self.client.get(
                    self.endpoint, params=request_params, headers=headers
                )
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.get(
                        self.endpoint, params=request_params, headers=headers
                    )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CollectorError(f"Senato collection failed: {exc}") from exc

        content_type = response.headers.get("content-type", self.response_media_type)
        return CollectedDocument(
            content=response.content,
            source_url=self.endpoint,
            content_type=content_type,
            retrieved_at=datetime.now(timezone.utc),
            collector_version=self.version,
        )
