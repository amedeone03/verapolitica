from datetime import datetime, timezone

import httpx

from backend.app.pipeline.collectors.base import CollectedDocument, CollectorError


class SenatoProposalCollector:
    """Collect a bounded, deterministic window of official Senato DDL records."""

    version = "senato_proposal_collector_v1"
    response_media_type = "application/sparql-results+json"

    def __init__(
        self,
        endpoint: str,
        legislature: int,
        *,
        record_limit: int = 100,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if record_limit < 1 or record_limit > 1000:
            raise ValueError("record_limit must be between 1 and 1000")
        self.endpoint = endpoint
        self.legislature = legislature
        self.record_limit = record_limit
        self.timeout_seconds = timeout_seconds
        self.client = client

    @property
    def query(self) -> str:
        return f"""
PREFIX osr: <http://dati.senato.it/osr/>

SELECT DISTINCT
    ?ddlUri ?idDdl ?title ?introducedAt ?sourceStatus ?statusAt ?nature
    ?initiativeUri ?initiativeType ?presenter ?senatorUri ?firstSigner
WHERE {{
    {{
        SELECT ?ddlUri ?introducedAt
        WHERE {{
            ?ddlUri a osr:Ddl ;
                osr:legislatura {self.legislature} ;
                osr:dataPresentazione ?introducedAt .
        }}
        ORDER BY DESC(?introducedAt) ?ddlUri
        LIMIT {self.record_limit}
    }}

    ?ddlUri osr:idDdl ?idDdl ;
        osr:titolo ?title ;
        osr:statoDdl ?sourceStatus ;
        osr:dataStatoDdl ?statusAt .
    OPTIONAL {{ ?ddlUri osr:natura ?nature . }}
    OPTIONAL {{
        ?ddlUri osr:iniziativa ?initiativeUri .
        OPTIONAL {{ ?initiativeUri osr:tipoIniziativa ?initiativeType . }}
        OPTIONAL {{ ?initiativeUri osr:presentatore ?presenter . }}
        OPTIONAL {{ ?initiativeUri osr:senatore ?senatorUri . }}
        OPTIONAL {{ ?initiativeUri osr:primoFirmatario ?firstSigner . }}
    }}
}}
ORDER BY DESC(?introducedAt) ?ddlUri ?initiativeUri
""".strip()

    def collect(self) -> CollectedDocument:
        headers = {
            "Accept": self.response_media_type,
            "User-Agent": "VeraPolitica/0.1 (+official-data-ingestion)",
        }
        params = {"query": self.query, "format": self.response_media_type}
        try:
            if self.client is not None:
                response = self.client.get(self.endpoint, params=params, headers=headers)
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.get(self.endpoint, params=params, headers=headers)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CollectorError(f"Senato proposal collection failed: {exc}") from exc

        return CollectedDocument(
            content=response.content,
            source_url=self.endpoint,
            content_type=self.response_media_type,
            retrieved_at=datetime.now(timezone.utc),
            collector_version=self.version,
        )
