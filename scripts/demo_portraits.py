"""Build the demo portrait dataset for published politicians.

Order of preference for each politician:

1. the official portrait from the profile's own source (e.g. governo.it);
2. a freely licensed photo from Wikimedia Commons, found through Wikidata,
   accepted only when exactly one entity matches the exact name, is a human
   with Italian citizenship and is described as a politician;
3. nothing: the interface draws a monogram in the same glass style.

Every photo keeps its author, licence and source link so the app can credit
it. Wrong-person photos are worse than no photo, so ambiguity means skip.
"""

from __future__ import annotations

import html
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

USER_AGENT = (
    "VeraPolitica/0.1 (local civic-data demo; https://github.com/amedeone03/verapolitica)"
)
MIN_INTERVAL_SECONDS = 1.0
MAX_ATTEMPTS = 4
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
HUMAN, ITALY, POLITICIAN = "Q5", "Q38", "Q82955"

JsonGetter = Callable[[str, dict[str, str]], dict[str, Any]]


_last_request = 0.0


def http_get_json(url: str, params: dict[str, str]) -> dict[str, Any]:
    """Polite client for the Wikimedia APIs: spaced requests, honours 429 Retry-After."""

    global _last_request
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request)
            if wait > 0:
                time.sleep(wait)
            _last_request = time.monotonic()
            response = client.get(url, params=params, headers={"User-Agent": USER_AGENT})
            if response.status_code == 429 and attempt < MAX_ATTEMPTS:
                retry_after = response.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.isdigit() else 5.0 * attempt
                time.sleep(min(delay, 60.0))
                continue
            response.raise_for_status()
            return response.json()
    raise httpx.HTTPError("unreachable")


@dataclass(frozen=True)
class Portrait:
    url: str
    credit: str
    license: str
    source_url: str
    origin: str


def _claim_ids(entity: dict[str, Any], prop: str) -> set[str]:
    values = set()
    for claim in entity.get("claims", {}).get(prop, []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and "id" in value:
            values.add(value["id"])
    return values


def _image_name(entity: dict[str, Any]) -> str | None:
    for claim in entity.get("claims", {}).get("P18", []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, str) and value:
            return value
    return None


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", value))).strip()


def find_wikidata_image(name: str, get_json: JsonGetter) -> str | None:
    search = get_json(
        WIKIDATA_API,
        {
            "action": "wbsearchentities",
            "search": name,
            "language": "it",
            "type": "item",
            "limit": "5",
            "format": "json",
        },
    )
    target = name.casefold()
    ids = [
        item["id"]
        for item in search.get("search", [])
        if str(item.get("label", "")).casefold() == target
    ]
    if not ids:
        return None
    entities = get_json(
        WIKIDATA_API,
        {
            "action": "wbgetentities",
            "ids": "|".join(ids),
            "props": "claims|descriptions",
            "languages": "it|en",
            "format": "json",
        },
    ).get("entities", {})
    accepted = []
    for entity in entities.values():
        if HUMAN not in _claim_ids(entity, "P31") or ITALY not in _claim_ids(entity, "P27"):
            continue
        descriptions = " ".join(
            value.get("value", "") for value in entity.get("descriptions", {}).values()
        ).casefold()
        if POLITICIAN not in _claim_ids(entity, "P106") and "politic" not in descriptions:
            continue
        image = _image_name(entity)
        if image:
            accepted.append(image)
    return accepted[0] if len(accepted) == 1 else None


def commons_portrait(file_name: str, get_json: JsonGetter) -> Portrait | None:
    data = get_json(
        COMMONS_API,
        {
            "action": "query",
            "titles": f"File:{file_name}",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiurlwidth": "720",
            "format": "json",
        },
    )
    for page in data.get("query", {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            continue
        meta = info.get("extmetadata", {})
        license_name = _strip_html(meta.get("LicenseShortName", {}).get("value", ""))
        if not license_name:
            return None
        artist = _strip_html(meta.get("Artist", {}).get("value", "")) or "Unknown author"
        return Portrait(
            url=info.get("thumburl") or info["url"],
            credit=artist,
            license=license_name,
            source_url=info.get("descriptionurl")
            or f"https://commons.wikimedia.org/wiki/File:{quote(file_name)}",
            origin="Wikimedia Commons",
        )
    return None


def build_portraits(
    politicians: list[dict[str, Any]],
    *,
    get_json: JsonGetter = http_get_json,
    warnings: list[str] | None = None,
    cache: dict[str, dict[str, str] | None] | None = None,
) -> dict[str, dict[str, str]]:
    """``politicians``: dicts with id, name, given_name, family_name, image_url, source_name, source_url.

    ``cache`` maps a person's name to a previous Commons result (``None`` = known
    to have no acceptable photo) and is updated in place; failed lookups are not
    cached so they are retried on the next run.
    """

    cache = cache if cache is not None else {}
    result: dict[str, dict[str, str]] = {}
    for person in politicians:
        if person.get("image_url"):
            result[str(person["id"])] = asdict(
                Portrait(
                    url=person["image_url"],
                    credit=person.get("source_name") or "Official source",
                    license="Official institutional portrait",
                    source_url=person.get("source_url") or person["image_url"],
                    origin=person.get("source_name") or "Official source",
                )
            )
            continue
        if person["name"] in cache:
            if cache[person["name"]]:
                result[str(person["id"])] = cache[person["name"]]
            continue
        names = [person["name"]]
        short = f"{person['given_name'].split()[0]} {person['family_name']}"
        if short != person["name"]:
            names.append(short)
        try:
            image = None
            for name in names:
                image = find_wikidata_image(name, get_json)
                if image:
                    break
            portrait = commons_portrait(image, get_json) if image else None
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            if warnings is not None:
                warnings.append(f"portrait lookup failed for {person['name']}: {str(exc).splitlines()[0]}")
            continue
        cache[person["name"]] = asdict(portrait) if portrait else None
        if portrait:
            result[str(person["id"])] = asdict(portrait)
    return result


def load_cache(path: Path) -> dict[str, dict[str, str] | None]:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


BytesFetcher = Callable[[str], tuple[bytes, str]]
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 5_000_000


def http_get_bytes(url: str) -> tuple[bytes, str]:
    global _last_request
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request)
            if wait > 0:
                time.sleep(wait)
            _last_request = time.monotonic()
            response = client.get(url, headers={"User-Agent": USER_AGENT})
            if response.status_code == 429 and attempt < MAX_ATTEMPTS:
                retry_after = response.headers.get("Retry-After", "")
                time.sleep(min(float(retry_after) if retry_after.isdigit() else 5.0 * attempt, 60.0))
                continue
            response.raise_for_status()
            return response.content, response.headers.get("content-type", "").split(";")[0].strip()
    raise httpx.HTTPError("unreachable")


def store_portrait_files(
    portraits: dict[str, dict[str, str]],
    directory: Path,
    *,
    fetch_bytes: BytesFetcher = http_get_bytes,
    warnings: list[str] | None = None,
) -> None:
    """Download each portrait once and record its local file name.

    Serving the files from the app avoids hot-linking third-party hosts and
    keeps the demo working offline. Files are named by a hash of the source
    URL, so later runs reuse them.
    """

    import hashlib

    directory.mkdir(parents=True, exist_ok=True)
    for key, entry in portraits.items():
        digest = hashlib.sha256(entry["url"].encode("utf-8")).hexdigest()[:24]
        existing = next(iter(sorted(directory.glob(f"{digest}.*"))), None)
        if existing is not None:
            entry["file"] = existing.name
            continue
        try:
            content, content_type = fetch_bytes(entry["url"])
        except (httpx.HTTPError, ValueError) as exc:
            if warnings is not None:
                warnings.append(f"portrait download failed for id {key}: {str(exc).splitlines()[0]}")
            continue
        suffix = IMAGE_TYPES.get(content_type)
        if suffix is None or not content or len(content) > MAX_IMAGE_BYTES:
            if warnings is not None:
                warnings.append(f"portrait for id {key} skipped: {content_type or 'unknown'} file")
            continue
        (directory / f"{digest}{suffix}").write_bytes(content)
        entry["file"] = f"{digest}{suffix}"


def write_portraits(path: Path, portraits: dict[str, dict[str, str]]) -> None:
    path.write_text(json.dumps(portraits, ensure_ascii=False, indent=2), "utf-8")
