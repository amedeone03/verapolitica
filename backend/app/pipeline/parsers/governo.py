from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from backend.app.pipeline.parsers.base import ParsedDocument, ParserError


ITALIAN_MONTHS = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}


class _ProfileHTMLParser(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.meta: dict[str, str] = {}
        self.canonical_url: str | None = None
        self.shortlink_url: str | None = None
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []
        self.role_parts: list[str] = []
        self.appointment_links: list[tuple[str, str]] = []
        self.image_url: str | None = None
        self._in_title = False
        self._body_depth = 0
        self._role_depth = 0
        self._thumb_depth = 0
        self._link_href: str | None = None
        self._link_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())
        if tag == "meta":
            key = attributes.get("name") or attributes.get("property")
            content = attributes.get("content")
            if key and content:
                self.meta[key] = content
        elif tag == "link":
            rel = attributes.get("rel", "").casefold()
            href = attributes.get("href")
            if href and rel == "canonical":
                self.canonical_url = urljoin(self.page_url, href)
            elif href and rel == "shortlink":
                self.shortlink_url = urljoin(self.page_url, href)
        elif tag == "h1" and "title_small" in classes:
            self._in_title = True
        elif tag == "div":
            if self._body_depth:
                self._body_depth += 1
            elif "field-name-body" in classes:
                self._body_depth = 1
            if self._thumb_depth:
                self._thumb_depth += 1
            elif "thumb_container" in classes:
                self._thumb_depth = 1
        elif tag == "blockquote" and self._body_depth:
            self._role_depth = 1
        elif tag == "img" and self._thumb_depth and not self.image_url:
            src = attributes.get("src")
            if src:
                self.image_url = urljoin(self.page_url, src)
        elif tag == "a":
            self._link_href = attributes.get("href")
            self._link_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1":
            self._in_title = False
        elif tag == "blockquote" and self._role_depth:
            self._role_depth = 0
        elif tag == "div":
            if self._body_depth:
                self._body_depth -= 1
            if self._thumb_depth:
                self._thumb_depth -= 1
        elif tag == "a" and self._link_href is not None:
            href = urljoin(self.page_url, self._link_href.strip())
            text = _normalize_text(" ".join(self._link_parts))
            if "gazzettaufficiale.it" in href and text:
                self.appointment_links.append((href, text))
            self._link_href = None
            self._link_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._body_depth:
            self.body_parts.append(data)
        if self._role_depth:
            self.role_parts.append(data)
        if self._link_href is not None:
            self._link_parts.append(data)


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return re.sub(r"\s+", " ", normalized).strip()


class GovernoParser:
    """Parse the official Governo HTML bundle into canonical holder records."""

    version = "governo_parser_v1"

    def parse(self, content: bytes) -> ParsedDocument:
        bundle = self._load_bundle(content)
        parsed_pages = [
            self._parse_profile(item, index)
            for index, item in enumerate(bundle["profiles"])
        ]
        records = self._group_person_pages(parsed_pages)
        records.sort(key=lambda record: (record["display_name"].casefold(), record["source_identifiers"]))
        canonical_json = json.dumps(
            records,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        normalized_text = "\n".join(
            f"name={record['display_name']} | roles={len(record['mandates'])} | "
            f"identifier={record['source_identifiers'][0]}"
            for record in records
        )
        return ParsedDocument(
            structured_records=records,
            normalized_text=normalized_text,
            canonical_json=canonical_json,
            parser_version=self.version,
        )

    @staticmethod
    def _load_bundle(content: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParserError(f"Invalid Governo collection bundle: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("bundle_version") != 1:
            raise ParserError("Governo bundle has an unsupported structure")
        if not isinstance(payload.get("index_url"), str):
            raise ParserError("Governo bundle is missing index_url")
        if not isinstance(payload.get("index_html"), str):
            raise ParserError("Governo bundle is missing index_html")
        profiles = payload.get("profiles")
        if not isinstance(profiles, list) or not profiles:
            raise ParserError("Governo bundle contains no profile pages")
        return payload

    def _parse_profile(self, item: Any, index: int) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise ParserError(f"Governo profile {index} is not an object")
        page_url, html = item.get("url"), item.get("html")
        if not isinstance(page_url, str) or not isinstance(html, str):
            raise ParserError(f"Governo profile {index} is missing URL or HTML")
        extractor = _ProfileHTMLParser(page_url)
        extractor.feed(html)
        display_name = _normalize_text(" ".join(extractor.title_parts))
        role_title = _normalize_text(" ".join(extractor.role_parts))
        profile_url = extractor.canonical_url or page_url
        source_identifier = extractor.shortlink_url or profile_url
        if not display_name or not role_title:
            raise ParserError(
                f"Governo profile {index} ({page_url}) is missing name or role"
            )
        name_parts = display_name.split()
        if len(name_parts) < 2:
            raise ParserError(
                f"Governo profile {index} ({page_url}) has an unsplittable name"
            )
        body_text = _normalize_text(" ".join(extractor.body_parts))
        birth_date, birth_city = self._extract_birth(body_text)
        mandate_start, appointment_url = self._extract_mandate_start(
            role_title, body_text, extractor.appointment_links
        )
        appointment_text = " ".join(label for _, label in extractor.appointment_links)
        return {
            "display_name": display_name,
            "given_name": name_parts[0],
            "family_name": " ".join(name_parts[1:]),
            "birth_date": birth_date,
            "birth_city": birth_city,
            "profile_url": profile_url,
            "source_identifier": source_identifier,
            "photo_url": extractor.image_url,
            "role_title": role_title,
            "office": self._classify_office(
                role_title, f"{body_text} {appointment_text}"
            ),
            "institution": self._institution(role_title, page_url),
            "government": "Governo Meloni",
            "mandate_start": mandate_start,
            "appointment_url": appointment_url,
        }

    @staticmethod
    def _extract_birth(text: str) -> tuple[str | None, str | None]:
        match = re.search(
            r"\bnat[oa]\s+a\s+(.+?)\s+il\s+(\d{1,2})\s+"
            r"(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|"
            r"settembre|ottobre|novembre|dicembre)\s+(?:del\s+)?(\d{4})\b",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None, None
        city, day, month_name, year = match.groups()
        try:
            parsed = date(int(year), ITALIAN_MONTHS[month_name.casefold()], int(day))
        except ValueError as exc:
            raise ParserError(f"invalid Governo biography birth date: {match.group(0)!r}") from exc
        return parsed.isoformat(), _normalize_text(city)

    def _extract_mandate_start(
        self,
        role_title: str,
        body_text: str,
        appointment_links: list[tuple[str, str]],
    ) -> tuple[str | None, str | None]:
        direct = re.search(r"\bdal\s+([^.,;]+)", f"{role_title} {body_text}", re.I)
        if direct:
            parsed = self._parse_date_fragment(direct.group(1))
            if parsed:
                return parsed, None
        for url, label in appointment_links:
            if re.search(r"nomina|conferimento|sottosegretar", label, re.I):
                parsed = self._parse_date_fragment(label)
                if parsed:
                    return parsed, url
        return None, None

    @staticmethod
    def _parse_date_fragment(value: str) -> str | None:
        numeric = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", value)
        if numeric:
            day, month, year = map(int, numeric.groups())
        else:
            textual = re.search(
                r"\b(\d{1,2})\s+"
                r"(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|"
                r"settembre|ottobre|novembre|dicembre)\s+(\d{4})\b",
                value,
                re.I,
            )
            if not textual:
                return None
            day = int(textual.group(1))
            month = ITALIAN_MONTHS[textual.group(2).casefold()]
            year = int(textual.group(3))
        try:
            return date(year, month, day).isoformat()
        except ValueError as exc:
            raise ParserError(f"invalid Governo appointment date in {value!r}") from exc

    @staticmethod
    def _classify_office(role_title: str, body_text: str) -> str:
        normalized = role_title.casefold()
        if "vice presidente" in normalized or "vicepresidente" in normalized:
            return "Vice Presidente del Consiglio"
        if "presidente del consiglio" in normalized:
            return "Presidente del Consiglio"
        if "vice ministro" in normalized or "viceministro" in normalized:
            return "Viceministro"
        if "sottosegret" in normalized:
            return "Sottosegretario"
        if "ministro" in normalized:
            if "ministro senza portafoglio" in body_text.casefold():
                return "Ministro senza portafoglio"
            return "Ministro"
        return role_title

    @staticmethod
    def _institution(role_title: str, page_url: str) -> str:
        if (
            "presidenza del consiglio" in role_title.casefold()
            or "/sottosegretari-pcm/" in page_url
            or "presidente del consiglio" in role_title.casefold()
        ):
            return "Presidenza del Consiglio dei Ministri"
        return "Governo Italiano"

    @staticmethod
    def _group_person_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for page in pages:
            key = _normalize_text(page["display_name"]).casefold()
            groups.setdefault(key, []).append(page)
        records = []
        for pages_for_person in groups.values():
            pages_for_person.sort(key=lambda page: page["profile_url"])
            primary = next(
                (page for page in pages_for_person if page["birth_date"]),
                pages_for_person[0],
            )
            mandate_values: dict[tuple[Any, ...], dict[str, Any]] = {}
            for page in pages_for_person:
                mandate = {
                    key: page[key]
                    for key in (
                        "profile_url",
                        "source_identifier",
                        "role_title",
                        "office",
                        "institution",
                        "government",
                        "mandate_start",
                        "appointment_url",
                    )
                }
                key = (
                    mandate["role_title"],
                    mandate["institution"],
                    mandate["mandate_start"],
                )
                mandate_values.setdefault(key, mandate)
            records.append(
                {
                    "display_name": primary["display_name"],
                    "given_name": primary["given_name"],
                    "family_name": primary["family_name"],
                    "birth_date": primary["birth_date"],
                    "birth_city": primary["birth_city"],
                    "source_identifiers": sorted(
                        {page["source_identifier"] for page in pages_for_person}
                    ),
                    "source_identifier_pages": sorted(
                        (
                            {
                                "value": page["source_identifier"],
                                "profile_url": page["profile_url"],
                            }
                            for page in pages_for_person
                        ),
                        key=lambda item: (item["value"], item["profile_url"]),
                    ),
                    "profile_urls": sorted(
                        {page["profile_url"] for page in pages_for_person}
                    ),
                    "photo_url": next(
                        (page["photo_url"] for page in pages_for_person if page["photo_url"]),
                        None,
                    ),
                    "mandates": sorted(
                        mandate_values.values(),
                        key=lambda mandate: (
                            mandate["institution"],
                            mandate["office"],
                            mandate["role_title"],
                        ),
                    ),
                }
            )
        return records
