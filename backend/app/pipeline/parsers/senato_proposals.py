import json
import re
import unicodedata
from datetime import date
from typing import Any

from backend.app.pipeline.parsers.base import ParsedDocument, ParserError


class SenatoProposalParser:
    """Normalize current Senato DDL metadata and initiative actors."""

    version = "senato_proposal_parser_v1"
    required_fields = (
        "ddlUri",
        "idDdl",
        "title",
        "introducedAt",
        "sourceStatus",
        "statusAt",
    )

    def parse(self, content: bytes) -> ParsedDocument:
        payload = self._load_payload(content)
        bindings = self._bindings(payload)
        grouped: dict[str, dict[str, Any]] = {}
        actor_keys: dict[str, set[tuple[str, ...]]] = {}

        for index, binding in enumerate(bindings):
            values = {
                field: self._value(binding, field, index)
                for field in (
                    *self.required_fields,
                    "nature",
                    "initiativeUri",
                    "initiativeType",
                    "presenter",
                    "senatorUri",
                    "firstSigner",
                )
            }
            missing = [field for field in self.required_fields if values[field] is None]
            if missing:
                raise ParserError(
                    f"Senato proposal record {index} is missing required fields: "
                    + ", ".join(missing)
                )
            introduced_at = self._date(values["introducedAt"], index, "introducedAt")
            status_at = self._date(values["statusAt"], index, "statusAt")
            if status_at < introduced_at:
                raise ParserError(
                    f"Senato proposal record {index} has statusAt before introducedAt"
                )
            proposal_uri = values["ddlUri"]
            core = {
                "proposal_uri": proposal_uri,
                "official_id": values["idDdl"],
                "title": values["title"],
                "introduced_at": introduced_at.isoformat(),
                "source_status_label": values["sourceStatus"],
                "status_at": status_at.isoformat(),
                "nature": values["nature"],
                "actors": [],
            }
            existing = grouped.get(proposal_uri)
            if existing is None:
                grouped[proposal_uri] = core
                actor_keys[proposal_uri] = set()
            elif {key: value for key, value in existing.items() if key != "actors"} != {
                key: value for key, value in core.items() if key != "actors"
            }:
                raise ParserError(
                    f"Senato proposal {proposal_uri!r} has conflicting metadata"
                )

            if values["initiativeUri"] is not None:
                actor = {
                    "initiative_uri": values["initiativeUri"],
                    "initiative_type": values["initiativeType"],
                    "presenter": values["presenter"],
                    "senator_uri": values["senatorUri"],
                    "first_signer": values["firstSigner"],
                }
                key = tuple(str(actor[name] or "") for name in sorted(actor))
                if key not in actor_keys[proposal_uri]:
                    actor_keys[proposal_uri].add(key)
                    grouped[proposal_uri]["actors"].append(actor)

        records = list(grouped.values())
        for record in records:
            record["actors"].sort(
                key=lambda actor: (
                    actor["initiative_uri"] or "",
                    actor["senator_uri"] or "",
                    actor["presenter"] or "",
                )
            )
        records.sort(
            key=lambda record: (record["introduced_at"], record["proposal_uri"]),
            reverse=True,
        )
        canonical_json = json.dumps(
            records,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        normalized_text = "\n".join(
            f"{record['official_id']} | {record['title']} | "
            f"{record['source_status_label']}"
            for record in records
        )
        return ParsedDocument(
            structured_records=records,
            normalized_text=normalized_text,
            canonical_json=canonical_json,
            parser_version=self.version,
        )

    @staticmethod
    def _load_payload(content: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParserError(f"Invalid Senato proposal SPARQL JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ParserError("Senato proposal response must be a JSON object")
        return payload

    @staticmethod
    def _bindings(payload: dict[str, Any]) -> list[dict[str, Any]]:
        results = payload.get("results")
        bindings = results.get("bindings") if isinstance(results, dict) else None
        if not isinstance(bindings, list):
            raise ParserError("Senato proposal response is missing results.bindings")
        if not bindings:
            raise ParserError("Senato proposal response contains no DDL records")
        if not all(isinstance(binding, dict) for binding in bindings):
            raise ParserError("Every Senato proposal binding must be an object")
        return bindings

    @staticmethod
    def _value(binding: dict[str, Any], field: str, index: int) -> str | None:
        node = binding.get(field)
        if node is None:
            return None
        if not isinstance(node, dict) or not isinstance(node.get("value"), str):
            raise ParserError(
                f"Senato proposal record {index} has an invalid {field!r} binding"
            )
        value = unicodedata.normalize("NFC", node["value"])
        value = re.sub(r"\s+", " ", value).strip()
        return value or None

    @staticmethod
    def _date(value: str | None, index: int, field: str) -> date:
        try:
            return date.fromisoformat(value or "")
        except ValueError as exc:
            raise ParserError(
                f"Senato proposal record {index} has invalid {field} date {value!r}"
            ) from exc
