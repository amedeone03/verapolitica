from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from backend.app.pipeline.collectors.senato_history import BUNDLE_SCHEMA
from backend.app.pipeline.parsers.base import ParsedDocument, ParserError
from backend.app.pipeline.parsers.camera import CameraParser


def _decode(value: Any, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(base64.b64decode(value, validate=True).decode("utf-8-sig"))
    except (TypeError, ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ParserError(f"Invalid Senato history {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ParserError(f"Invalid Senato history {label}")
    return payload


class SenatoHistoryParser:
    """Normalize the historical Senate bundle into mandate records."""

    version = "senato_history_parser_v1"
    _value = staticmethod(CameraParser._binding_value)
    _date = staticmethod(CameraParser._normalize_date)
    _bindings = staticmethod(CameraParser._get_bindings)

    def parse(self, content: bytes) -> ParsedDocument:
        try:
            bundle = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParserError(f"Invalid Senato history bundle: {exc}") from exc
        if not isinstance(bundle, dict) or bundle.get("schema") != BUNDLE_SCHEMA:
            raise ParserError("Unexpected Senato history bundle schema")
        responses = bundle.get("mandate_responses_base64")
        if not isinstance(responses, dict) or not responses:
            raise ParserError("Senato history bundle has no mandate responses")

        mandates: list[dict[str, Any]] = []
        for number, encoded in sorted(responses.items(), key=lambda pair: int(pair[0])):
            mandates.extend(self._mandates(_decode(encoded, f"legislature {number}"), int(number)))
        return ParsedDocument(
            structured_records=mandates,
            normalized_text="\n".join(
                f"{item['legislature']} {item['family_name']} {item['given_name']}"
                for item in mandates
            ),
            canonical_json=json.dumps(
                mandates, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            parser_version=self.version,
        )

    def _mandates(self, payload: dict[str, Any], number: int) -> list[dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for index, binding in enumerate(self._bindings(payload, allow_empty=True)):
            value = lambda name: self._value(binding, name, index)  # noqa: E731
            mandate = value("mandateUri")
            person = value("senatorUri")
            given, family = value("firstName"), value("lastName")
            if not (mandate and person and given and family):
                raise ParserError(f"Senato history record {index} misses identity fields")
            start, end = value("mandateStart"), value("mandateEnd")
            records.setdefault(
                mandate,
                {
                    "kind": "mandate",
                    "chamber": "senato",
                    "legislature": number,
                    "official_identifier": mandate,
                    "person_identifier": person,
                    "given_name": given.title(),
                    "family_name": family.title(),
                    "gender": value("gender"),
                    "start_date": self._date(start, "mandateStart", index) if start else None,
                    "end_date": self._date(end, "mandateEnd", index) if end else None,
                    "election_area": value("electionRegion"),
                },
            )
        return sorted(records.values(), key=lambda item: item["official_identifier"])
