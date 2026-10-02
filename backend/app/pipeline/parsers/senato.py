import json
import re
import unicodedata
from typing import Any

from backend.app.pipeline.parsers.base import ParsedDocument, ParserError


class SenatoParser:
    """Parse and canonically normalize Senato SPARQL JSON results."""

    version = "senato_parser_v1"

    field_map = {
        "senator_uri": "senatorUri",
        "first_name": "firstName",
        "last_name": "lastName",
        "gender": "gender",
        "birth_date": "birthDate",
        "birth_city": "birthCity",
        "birth_province": "birthProvince",
        "birth_country": "birthCountry",
        "profession": "profession",
        "photo_url": "photoUrl",
        "homepage": "homepage",
        "mandate_uri": "mandateUri",
        "mandate_type": "mandateType",
        "mandate_start": "mandateStart",
        "legislature": "legislature",
        "election_region": "electionRegion",
    }
    required_fields = {
        "senator_uri",
        "first_name",
        "last_name",
        "mandate_uri",
        "mandate_type",
        "mandate_start",
        "legislature",
    }

    def parse(self, content: bytes) -> ParsedDocument:
        payload = self._load_payload(content)
        bindings = self._get_bindings(payload)
        records = [self._parse_binding(binding, index) for index, binding in enumerate(bindings)]
        records.sort(key=self._record_sort_key)

        canonical_json = json.dumps(
            records,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        normalized_text = "\n".join(self._record_text(record) for record in records)
        return ParsedDocument(
            structured_records=records,
            normalized_text=normalized_text,
            canonical_json=canonical_json,
            parser_version=self.version,
        )

    def _load_payload(self, content: bytes) -> dict[str, Any]:
        try:
            decoded = content.decode("utf-8-sig")
            payload = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParserError(f"Invalid Senato SPARQL JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ParserError("Senato SPARQL response must be a JSON object")
        return payload

    def _get_bindings(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        results = payload.get("results")
        if not isinstance(results, dict):
            raise ParserError("Senato SPARQL response is missing results")
        bindings = results.get("bindings")
        if not isinstance(bindings, list):
            raise ParserError("Senato SPARQL response is missing results.bindings")
        if not bindings:
            raise ParserError("Senato SPARQL response contains no senator records")
        if not all(isinstance(binding, dict) for binding in bindings):
            raise ParserError("Every Senato SPARQL binding must be an object")
        return bindings

    def _parse_binding(self, binding: dict[str, Any], index: int) -> dict[str, str | None]:
        record = {
            output_name: self._binding_value(binding, input_name, index)
            for output_name, input_name in self.field_map.items()
        }
        missing = sorted(field for field in self.required_fields if record[field] is None)
        if missing:
            raise ParserError(
                f"Senato record {index} is missing required fields: {', '.join(missing)}"
            )
        return record

    def _binding_value(
        self, binding: dict[str, Any], input_name: str, index: int
    ) -> str | None:
        value_node = binding.get(input_name)
        if value_node is None:
            return None
        if not isinstance(value_node, dict) or not isinstance(value_node.get("value"), str):
            raise ParserError(
                f"Senato record {index} has an invalid {input_name!r} binding"
            )
        value = unicodedata.normalize("NFC", value_node["value"])
        value = re.sub(r"\s+", " ", value).strip()
        return value or None

    @staticmethod
    def _record_sort_key(record: dict[str, str | None]) -> tuple[str, ...]:
        return (
            record["senator_uri"] or "",
            record["mandate_uri"] or "",
            record["mandate_start"] or "",
        )

    @staticmethod
    def _record_text(record: dict[str, str | None]) -> str:
        name = " ".join(
            value for value in (record["first_name"], record["last_name"]) if value
        )
        details = [
            f"name={name}",
            f"senator_uri={record['senator_uri']}",
            f"legislature={record['legislature']}",
            f"mandate_start={record['mandate_start']}",
        ]
        return " | ".join(details)
