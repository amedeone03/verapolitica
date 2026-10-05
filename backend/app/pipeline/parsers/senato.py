import json
import re
import unicodedata
from datetime import date
from typing import Any

from backend.app.pipeline.parsers.base import (
    ParsedDocument,
    ParserError,
    split_sparql_bundle,
)


class SenatoParser:
    """Parse and canonically normalize Senato SPARQL JSON results."""

    version = "senato_parser_v2"
    bundle_schema = "verapolitica_senato_bundle_v1"

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
    group_field_map = {
        "senator_uri": "senatorUri",
        "group_uri": "groupUri",
        "group_name": "groupName",
        "group_abbreviation": "groupAbbreviation",
        "membership_start": "membershipStart",
        "membership_end": "membershipEnd",
        "membership_role": "membershipRole",
        "legislature": "legislature",
    }
    group_required_fields = {
        "senator_uri",
        "group_uri",
        "group_name",
        "membership_start",
        "legislature",
    }

    def parse(self, content: bytes) -> ParsedDocument:
        payload = self._load_payload(content)
        people_payload, groups_payload = split_sparql_bundle(
            payload,
            expected_schema=self.bundle_schema,
            source_name="Senato",
        )
        bindings = self._get_bindings(people_payload)
        records = [self._parse_binding(binding, index) for index, binding in enumerate(bindings)]
        records.sort(key=self._record_sort_key)
        group_records = self._parse_group_payload(groups_payload)

        canonical_json = json.dumps(
            {"people": records, "parliamentary_groups": group_records},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        normalized_text = "\n".join(
            [*(self._record_text(record) for record in records),
             *(self._group_record_text(record) for record in group_records)]
        )
        return ParsedDocument(
            structured_records=records,
            normalized_text=normalized_text,
            canonical_json=canonical_json,
            parser_version=self.version,
            parliamentary_group_records=group_records,
        )

    def _parse_group_payload(
        self, payload: dict[str, Any] | None
    ) -> list[dict[str, str | None]]:
        if payload is None:
            return []
        bindings = self._get_bindings(payload, allow_empty=True)
        records: list[dict[str, str | None]] = []
        seen: set[tuple[str, ...]] = set()
        for index, binding in enumerate(bindings):
            record = {
                output: self._binding_value(binding, source, index)
                for output, source in self.group_field_map.items()
            }
            missing = sorted(
                field for field in self.group_required_fields if record[field] is None
            )
            if missing:
                raise ParserError(
                    f"Senato group record {index} is missing required fields: "
                    + ", ".join(missing)
                )
            for field in ("membership_start", "membership_end"):
                value = record[field]
                if value is not None:
                    try:
                        record[field] = date.fromisoformat(value).isoformat()
                    except ValueError as exc:
                        raise ParserError(
                            f"Senato group record {index} has invalid {field!r} "
                            f"date {value!r}"
                        ) from exc
            key = self._group_sort_key(record)
            if key not in seen:
                seen.add(key)
                records.append(record)
        records.sort(key=self._group_sort_key)
        return records

    def _load_payload(self, content: bytes) -> dict[str, Any]:
        try:
            decoded = content.decode("utf-8-sig")
            payload = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParserError(f"Invalid Senato SPARQL JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ParserError("Senato SPARQL response must be a JSON object")
        return payload

    def _get_bindings(
        self, payload: dict[str, Any], *, allow_empty: bool = False
    ) -> list[dict[str, Any]]:
        results = payload.get("results")
        if not isinstance(results, dict):
            raise ParserError("Senato SPARQL response is missing results")
        bindings = results.get("bindings")
        if not isinstance(bindings, list):
            raise ParserError("Senato SPARQL response is missing results.bindings")
        if not bindings and not allow_empty:
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

    @staticmethod
    def _group_sort_key(record: dict[str, str | None]) -> tuple[str, ...]:
        return (
            record["senator_uri"] or "",
            record["membership_start"] or "",
            record["group_uri"] or "",
            record["membership_role"] or "",
            record["membership_end"] or "",
        )

    @staticmethod
    def _group_record_text(record: dict[str, str | None]) -> str:
        return " | ".join(
            (
                f"group={record['group_name']}",
                f"senator_uri={record['senator_uri']}",
                f"start={record['membership_start']}",
                f"end={record['membership_end']}",
            )
        )
