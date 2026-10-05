from datetime import date, datetime
from hashlib import sha256
from typing import Any

from backend.app.models import ProposalActorRole, ProposalStatus, ProposalType
from backend.app.schemas import (
    ObservedActorType,
    ProposalActorObservation,
    ProposalEvidenceObservation,
    ProposalObservation,
)


class ProposalMappingError(ValueError):
    pass


class SenatoProposalMapper:
    """Map source-specific DDL rows to generic proposal observations."""

    status_map = {
        "D-L decaduto": ProposalStatus.LAPSED,
        "all'esame assemblea": ProposalStatus.UNDER_REVIEW,
        "appr. con modificaz": ProposalStatus.APPROVED,
        "appr. def. non pubbl": ProposalStatus.APPROVED,
        "appr. definit. Legge": ProposalStatus.ENACTED,
        "appr. in t.u.": ProposalStatus.SUPERSEDED,
        "approvato": ProposalStatus.APPROVED,
        "assegnato (no esame)": ProposalStatus.ASSIGNED,
        "assorbito": ProposalStatus.SUPERSEDED,
        "cancellato dall'OdG": ProposalStatus.WITHDRAWN,
        "concl. anomala stral": ProposalStatus.WITHDRAWN,
        "concluso l'esame": ProposalStatus.COMPLETED,
        "da assegn. a commis.": ProposalStatus.INTRODUCED,
        "esame in comm.": ProposalStatus.UNDER_REVIEW,
        "in relazione": ProposalStatus.UNDER_REVIEW,
        "respinto": ProposalStatus.REJECTED,
        "restit. al Governo": ProposalStatus.RETURNED,
        "rinviato ass.->comm.": ProposalStatus.UNDER_REVIEW,
        "ritirato": ProposalStatus.WITHDRAWN,
    }

    def map_records(
        self,
        records: list[dict[str, Any]],
        *,
        source_key: str,
        raw_document_id: int,
        observed_at: datetime,
    ) -> tuple[ProposalObservation, ...]:
        observations = []
        for index, record in enumerate(records):
            try:
                source_label = self._required(record, "source_status_label")
                normalized_status = self.status_map[source_label]
                proposal_uri = self._required(record, "proposal_uri")
                title = self._required(record, "title")
                introduced_at = date.fromisoformat(
                    self._required(record, "introduced_at")
                )
                status_at = date.fromisoformat(self._required(record, "status_at"))
                actors = self._actors(record.get("actors", []))
            except (KeyError, TypeError, ValueError) as exc:
                raise ProposalMappingError(
                    f"Senato proposal record {index} "
                    f"({record.get('proposal_uri', 'unknown')}) cannot be mapped: {exc}"
                ) from exc

            evidence = [
                ProposalEvidenceObservation(
                    field_path="title",
                    source_url=proposal_uri,
                    source_field="osr:titolo",
                    source_value=title,
                ),
                ProposalEvidenceObservation(
                    field_path="introduced_at",
                    source_url=proposal_uri,
                    source_field="osr:dataPresentazione",
                    source_value=introduced_at.isoformat(),
                ),
                ProposalEvidenceObservation(
                    field_path="proposal_type",
                    source_url=proposal_uri,
                    source_field="rdf:type",
                    source_value="osr:Ddl",
                ),
                ProposalEvidenceObservation(
                    field_path="current_status",
                    source_url=proposal_uri,
                    source_field="osr:statoDdl",
                    source_value=source_label,
                ),
            ]
            evidence.extend(
                ProposalEvidenceObservation(
                    field_path=f"actors[{actor_index}]",
                    source_url=proposal_uri,
                    source_field=actor.source_field,
                    source_value=actor.source_identifier or actor.display_name,
                )
                for actor_index, actor in enumerate(actors)
            )
            status_token = sha256(
                f"{source_label}\0{status_at.isoformat()}".encode("utf-8")
            ).hexdigest()[:16]
            observations.append(
                ProposalObservation(
                    source_key=source_key,
                    raw_document_id=raw_document_id,
                    proposal_identifier=proposal_uri,
                    title=title,
                    proposal_type=ProposalType.LEGISLATIVE_PROPOSAL,
                    introduced_at=introduced_at,
                    source_status_label=source_label,
                    normalized_status=normalized_status,
                    status_effective_at=status_at,
                    status_source_identifier=f"{proposal_uri}#status-{status_token}",
                    official_url=proposal_uri,
                    source_field="osr:statoDdl",
                    observed_at=observed_at,
                    actors=actors,
                    evidence=tuple(evidence),
                    metadata={
                        "official_id": record.get("official_id"),
                        "nature": record.get("nature"),
                    },
                )
            )
        return tuple(observations)

    @staticmethod
    def _actors(records: Any) -> tuple[ProposalActorObservation, ...]:
        if not isinstance(records, list):
            raise ValueError("actors must be a list")
        mapped: list[ProposalActorObservation] = []
        government_added = False
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("actor record must be an object")
            initiative_type = str(record.get("initiative_type") or "").casefold()
            presenter = str(record.get("presenter") or "").strip()
            senator_uri = str(record.get("senator_uri") or "").strip()
            if initiative_type == "governativa":
                if not government_added:
                    mapped.append(
                        ProposalActorObservation(
                            actor_type=ObservedActorType.INSTITUTION,
                            role=ProposalActorRole.GOVERNMENT,
                            display_name="Governo Italiano",
                            institution_name="Governo Italiano",
                            source_field="osr:tipoIniziativa",
                        )
                    )
                    government_added = True
                continue
            role = (
                ProposalActorRole.PROPOSER
                if str(record.get("first_signer") or "") == "1"
                else ProposalActorRole.CO_SPONSOR
            )
            if senator_uri:
                mapped.append(
                    ProposalActorObservation(
                        actor_type=ObservedActorType.POLITICIAN,
                        role=role,
                        display_name=presenter or senator_uri,
                        authority_key="senato-repubblica",
                        source_identifier=senator_uri,
                        source_field="osr:senatore",
                    )
                )
            elif presenter:
                mapped.append(
                    ProposalActorObservation(
                        actor_type=ObservedActorType.UNRESOLVED,
                        role=role,
                        display_name=presenter,
                        source_field="osr:presentatore",
                    )
                )
        return tuple(mapped)

    @staticmethod
    def _required(record: dict[str, Any], key: str) -> str:
        value = record.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"missing required field {key!r}")
        return value.strip()
