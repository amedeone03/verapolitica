from datetime import datetime, timezone

import httpx

from backend.app.pipeline.collectors.base import (
    CollectedDocument,
    CollectorError,
    encode_sparql_bundle,
)


class CameraCollector:
    """Collect current Camera deputies as a SPARQL JSON result document."""

    version = "camera_collector_v2"
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
        legislature_uri = (
            "http://dati.camera.it/ocd/legislatura.rdf/"
            f"repubblica_{self.legislature}"
        )
        return f"""
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX bio: <http://purl.org/vocab/bio/0.1/>

SELECT DISTINCT
    ?deputyUri ?personUri ?firstName ?lastName ?gender
    ?birthDate ?birthCity ?birthProvince
    ?profession ?photoUrl ?homepage
    ?mandateUri ?mandateType ?mandateStart ?legislature ?electionArea
WHERE {{
    ?deputyUri a ocd:deputato ;
        ocd:rif_leg <{legislature_uri}> ;
        foaf:firstName ?firstName ;
        foaf:surname ?lastName ;
        ocd:rif_mandatoCamera ?mandateUri .

    ?mandateUri ocd:rif_leg <{legislature_uri}> ;
        ocd:startDate ?mandateStart ;
        ocd:rif_elezione ?electionUri .
    FILTER NOT EXISTS {{ ?mandateUri ocd:endDate ?mandateEnd . }}

    ?personUri a foaf:Person ;
        ocd:rif_mandatoCamera ?mandateUri .

    OPTIONAL {{ ?deputyUri foaf:gender ?gender . }}
    OPTIONAL {{ ?deputyUri dc:description ?profession . }}
    OPTIONAL {{ ?deputyUri foaf:depiction ?photoUrl . }}
    OPTIONAL {{ ?deputyUri dcterms:isReferencedBy ?homepage . }}
    OPTIONAL {{
        ?personUri bio:Birth ?birth .
        ?birth bio:date ?birthDate .
        OPTIONAL {{ ?birth ocd:rif_luogo ?birthPlace .
            OPTIONAL {{ ?birthPlace dc:title ?birthCity . }}
            OPTIONAL {{ ?birthPlace ocd:parentADM1 ?birthProvince . }}
        }}
    }}
    OPTIONAL {{ ?electionUri ocd:tipoElezione ?mandateType . }}
    OPTIONAL {{ ?electionUri dc:coverage ?electionArea . }}
    BIND("{self.legislature}" AS ?legislature)
}}
ORDER BY ?deputyUri
""".strip()

    @property
    def parliamentary_groups_query(self) -> str:
        legislature_uri = (
            "http://dati.camera.it/ocd/legislatura.rdf/"
            f"repubblica_{self.legislature}"
        )
        return f"""
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX dcterms: <http://purl.org/dc/terms/>

SELECT DISTINCT
    ?deputyUri ?groupUri ?groupName ?groupAbbreviation
    ?membershipStart ?membershipEnd
WHERE {{
    ?deputyUri a ocd:deputato ;
        ocd:rif_leg <{legislature_uri}> ;
        ocd:rif_mandatoCamera ?mandateUri ;
        ocd:aderisce ?membership .
    ?mandateUri ocd:rif_leg <{legislature_uri}> .
    FILTER NOT EXISTS {{ ?mandateUri ocd:endDate ?mandateEnd . }}

    ?membership ocd:rif_gruppoParlamentare ?groupUri ;
        ocd:startDate ?membershipStart .
    OPTIONAL {{ ?membership ocd:endDate ?membershipEnd . }}
    ?groupUri dc:title ?groupName ;
        ocd:rif_leg <{legislature_uri}> .
    OPTIONAL {{ ?groupUri dcterms:alternative ?groupAbbreviation . }}
}}
ORDER BY ?deputyUri ?membershipStart ?groupUri
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
            raise CollectorError(f"Camera collection failed: {exc}") from exc

        return CollectedDocument(
            content=encode_sparql_bundle(
                schema="verapolitica_camera_bundle_v1",
                people_response=people_response.content,
                parliamentary_groups_response=groups_response.content,
            ),
            source_url=self.endpoint,
            content_type="application/json",
            retrieved_at=datetime.now(timezone.utc),
            collector_version=self.version,
        )
