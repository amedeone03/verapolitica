"""Propose logos of parties and coats of arms of regions and provinces from Wikidata.

For every party, region and province already in the database (parties from the
redazione's list and the parliamentary data; regions and provinces from ISTAT),
this script looks up the item on Wikidata, takes its logo (P154) or coat of arms
(P94) from Wikimedia Commons, and keeps it only if Commons reports a free licence
(public domain, CC0, CC BY, CC BY-SA). Each logo becomes a *proposal* in the
redazione queue, signed "Sincronizzazione Wikidata": nothing is public until a
redazione member checks it and approves it.

Needs internet access to query.wikidata.org and commons.wikimedia.org.

    python -m scripts.sync_symbols                 # all kinds
    python -m scripts.sync_symbols --kinds region  # only regions
    python -m scripts.sync_symbols --dry-run       # show matches, write nothing
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.services.redazione.service import RedazioneError, RedazioneService

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "VeraPolitica/1.0 (redazione; symbol sync)"
AUTHOR = "Sincronizzazione Wikidata"
MAX_BYTES = 400_000

# Italian regions (Q16110), provinces (Q15089), metropolitan cities (Q15110),
# free provinces of Sicily (Q21190155), autonomous provinces (Q1710033);
# parties (Q7278, any subclass) in Italy (Q38) without a dissolution date.
QUERIES = {
    "region": """
        SELECT ?item ?label ?image WHERE {
          ?item wdt:P31 wd:Q16110; wdt:P94 ?image.
          ?item rdfs:label ?label. FILTER(LANG(?label) = "it")
        }""",
    "province": """
        SELECT ?item ?label ?code ?image WHERE {
          VALUES ?type { wd:Q15089 wd:Q15110 wd:Q21190155 wd:Q1710033 }
          ?item wdt:P31 ?type; wdt:P395 ?code; wdt:P94 ?image.
          FILTER NOT EXISTS { ?item wdt:P576 ?end }
          ?item rdfs:label ?label. FILTER(LANG(?label) = "it")
        }""",
    "party": """
        SELECT ?item ?label ?short ?image WHERE {
          ?item wdt:P31/wdt:P279* wd:Q7278; wdt:P17 wd:Q38; wdt:P154 ?image.
          FILTER NOT EXISTS { ?item wdt:P576 ?end }
          ?item rdfs:label ?label. FILTER(LANG(?label) = "it")
          OPTIONAL { ?item wdt:P1813 ?short. }
        }""",
}

FREE_LICENSES = (
    (re.compile(r"^(public domain|pd\b|pd-)", re.I), "pubblico-dominio"),
    (re.compile(r"^cc0", re.I), "cc0"),
    (re.compile(r"^cc[ -]by[ -]sa", re.I), "cc-by-sa"),
    (re.compile(r"^cc[ -]by(?![ -](nc|nd))", re.I), "cc-by"),
)

Getter = Callable[[str], bytes]


def http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, image/*"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 — fixed https hosts
        return response.read(MAX_BYTES + 1)


def fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().casefold()
    text = re.sub(r"\b(regione|provincia|autonoma|citta metropolitana|libero consorzio comunale) (di |del |della |dell')?", "", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def region_keys(name: str) -> set[str]:
    # ISTAT writes bilingual names ("Trentino-Alto Adige/Südtirol").
    return {fold(part) for part in re.split(r"[/]", name)} | {fold(name)}


@dataclass
class Candidate:
    kind: str
    key: str
    name: str
    file: str


@dataclass
class Report:
    proposed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)


def sparql(get: Getter, query: str) -> list[dict]:
    url = f"{WIKIDATA_SPARQL}?{urllib.parse.urlencode({'query': query, 'format': 'json'})}"
    return json.loads(get(url))["results"]["bindings"]


def commons_file(image_uri: str) -> str:
    # http://commons.wikimedia.org/wiki/Special:FilePath/Stemma%20della%20Lombardia.svg
    return urllib.parse.unquote(image_uri.rsplit("/", 1)[-1])


def match(kind: str, rows: list[dict], targets: list[dict]) -> tuple[list[Candidate], list[str]]:
    by_key: dict[str, list[dict]] = {}
    for row in rows:
        names = {fold(row["label"]["value"])}
        if kind == "party" and "short" in row:
            names.add(fold(row["short"]["value"]))
        if kind == "province":
            names = {row["code"]["value"].upper()}
        for name in names:
            by_key.setdefault(name, []).append(row)
    found, missing = [], []
    for target in targets:
        if kind == "province":
            keys = {target["key"].upper()}
        elif kind == "region":
            keys = region_keys(target["name"])
        else:
            keys = {fold(target["name"])} | ({fold(target["abbreviation"])} if target.get("abbreviation") else set())
        hits = {row["item"]["value"]: row for key in keys for row in by_key.get(key, [])}
        if len(hits) == 1:
            row = next(iter(hits.values()))
            found.append(Candidate(kind, target["key"], target["name"], commons_file(row["image"]["value"])))
        else:
            missing.append(f"{target['name']} ({'nessun risultato' if not hits else 'più risultati'})")
    return found, missing


def commons_info(get: Getter, file: str) -> dict | None:
    params = {
        "action": "query", "format": "json", "prop": "imageinfo", "titles": f"File:{file}",
        "iiprop": "url|extmetadata", "iiurlwidth": "256",
    }
    pages = json.loads(get(f"{COMMONS_API}?{urllib.parse.urlencode(params)}"))["query"]["pages"]
    info = next(iter(pages.values())).get("imageinfo")
    return info[0] if info else None


def licence_of(meta: dict) -> str | None:
    short = (meta.get("LicenseShortName") or {}).get("value", "")
    for pattern, key in FREE_LICENSES:
        if pattern.search(short.strip()):
            return key
    return None


def plain(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())[:300]


def sync(service: RedazioneService, get: Getter, kinds: tuple[str, ...], *, dry_run: bool = False) -> Report:
    report = Report()
    state = service.symbols()
    for kind in kinds:
        targets = [item for item in state[kind] if not item["symbol"] and not item["pending"]]
        if not targets:
            continue
        candidates, missing = match(kind, sparql(get, QUERIES[kind]), targets)
        report.unmatched += [f"{kind}: {item}" for item in missing]
        for candidate in candidates:
            label = f"{kind}: {candidate.name} ← File:{candidate.file}"
            info = commons_info(get, candidate.file)
            if info is None:
                report.skipped.append(f"{label} (file non trovato su Commons)")
                continue
            meta = info.get("extmetadata") or {}
            licence = licence_of(meta)
            if licence is None:
                report.skipped.append(f"{label} (licenza non libera: {(meta.get('LicenseShortName') or {}).get('value', '?')})")
                continue
            if dry_run:
                report.proposed.append(f"{label} [{licence}]")
                continue
            data = get(info.get("thumburl") or info["url"])
            if len(data) > MAX_BYTES:
                report.skipped.append(f"{label} (immagine troppo grande)")
                continue
            credit = plain((meta.get("Artist") or {}).get("value", "")) or "Wikimedia Commons"
            try:
                image = service.upload_image(
                    {"data": base64.b64encode(data).decode(), "credit": credit, "alt": f"Simbolo: {candidate.name}"},
                    member=AUTHOR,
                )
                service.propose_symbol(
                    {
                        "kind": kind, "key": candidate.key, "image_id": image["id"], "credit": credit,
                        "license": licence, "source_url": info["descriptionurl"],
                    },
                    member=AUTHOR,
                )
            except RedazioneError as error:
                report.skipped.append(f"{label} ({error})")
                continue
            report.proposed.append(f"{label} [{licence}]")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--kinds", default="party,region,province")
    parser.add_argument("--database-url")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    kinds = tuple(kind for kind in args.kinds.split(",") if kind in QUERIES)
    settings = get_settings()
    runtime = settings.model_copy(update={"database_url": args.database_url}) if args.database_url else settings
    engine = create_db_engine(runtime.database_url)
    prepare_runtime_schema(engine, runtime)
    Base.metadata.create_all(engine)
    service = RedazioneService(create_session_factory(engine))
    try:
        report = sync(service, http_get, kinds, dry_run=args.dry_run)
    except OSError as error:
        print(f"Rete non raggiungibile: {error}", file=sys.stderr)
        return 2
    print(f"Proposti alla redazione: {len(report.proposed)}")
    for line in report.proposed:
        print(f"  + {line}")
    if report.skipped:
        print(f"Scartati: {len(report.skipped)}")
        for line in report.skipped:
            print(f"  - {line}")
    if report.unmatched:
        print(f"Senza corrispondenza su Wikidata: {len(report.unmatched)}")
        for line in report.unmatched:
            print(f"  ? {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
