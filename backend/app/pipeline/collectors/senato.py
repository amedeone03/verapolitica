from datetime import datetime, timezone

import httpx

from backend.app.pipeline.collectors.base import (
    CollectedDocument,
    CollectorError,
    encode_sparql_bundle,
)


class SenatoCollector:
    """Collect current senators as a SPARQL JSON result document."""

    version = "senato_collector_v2"
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

    @property
    def parliamentary_groups_query(self) -> str:
        return f"""
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX osr: <http://dati.senato.it/osr/>

SELECT DISTINCT
    ?senatorUri ?groupUri ?groupName ?groupAbbreviation
    ?membershipStart ?membershipEnd ?membershipRole ?legislature
WHERE {{
    ?senatorUri a osr:Senatore ;
        osr:mandato ?mandateUri ;
        ocd:aderisce ?membership .
    ?mandateUri osr:legislatura ?legislature .
    OPTIONAL {{ ?mandateUri osr:fine ?mandateEnd . }}
    FILTER(?legislature = {self.legislature})
    FILTER(!BOUND(?mandateEnd))

    ?membership a ocd:adesioneGruppo ;
        osr:gruppo ?groupUri ;
        osr:inizio ?membershipStart ;
        osr:legislatura ?legislature .
    OPTIONAL {{ ?membership osr:fine ?membershipEnd . }}
    OPTIONAL {{ ?membership osr:carica ?membershipRole . }}

    ?groupUri osr:denominazione ?denomination .
    ?denomination osr:titolo ?groupName .
    OPTIONAL {{ ?denomination osr:titoloBreve ?groupAbbreviation . }}
    OPTIONAL {{ ?denomination osr:fine ?denominationEnd . }}
    FILTER(!BOUND(?denominationEnd))
}}
ORDER BY ?senatorUri ?membershipStart ?groupUri
""".strip()

    def collect(self) -> CollectedDocument:
        headers = {
            "Accept": self.response_media_type,
            "User-Agent": "VeraPolitica/0.1 (+official-data-ingestion)",
        }

        try:
            if self.client is not None:
                people_response = self.client.get(
                    self.endpoint,
                    params={"query": self.query, "format": self.response_media_type},
                    headers=headers,
                )
                groups_response = self.client.get(
                    self.endpoint,
                    params={
                        "query": self.parliamentary_groups_query,
                        "format": self.response_media_type,
                    },
                    headers=headers,
                )
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    people_response = client.get(
                        self.endpoint,
                        params={"query": self.query, "format": self.response_media_type},
                        headers=headers,
                    )
                    groups_response = client.get(
                        self.endpoint,
                        params={
                            "query": self.parliamentary_groups_query,
                            "format": self.response_media_type,
                        },
                        headers=headers,
                    )
            people_response.raise_for_status()
            groups_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CollectorError(f"Senato collection failed: {exc}") from exc

        return CollectedDocument(
            content=encode_sparql_bundle(
                schema="verapolitica_senato_bundle_v1",
                people_response=people_response.content,
                parliamentary_groups_response=groups_response.content,
            ),
            source_url=self.endpoint,
            content_type="application/json",
            retrieved_at=datetime.now(timezone.utc),
            collector_version=self.version,
        )
