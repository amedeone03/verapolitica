"""Put the parties of the current Government in the list, with their logos.

The parties with members in the Meloni Government (Fratelli d'Italia, Lega per
Salvini Premier, Forza Italia, Noi Moderati) and the main opposition lists
(Partito Democratico, Movimento 5 Stelle, Alleanza Verdi e Sinistra) are looked
up on Wikidata (name, abbreviation, official website, logo). Each one goes
through the redazione flow — proposed by "Sincronizzazione Wikidata", approved
by ``--approver`` — so the log records who decided it. A logo is used only if
Wikimedia Commons reports a free licence; otherwise the report says so and the
redazione uploads the official file from the console. The redazione can change
name, abbreviation, website and logo at any time from "Partiti e territori".

Needs internet. Run on the machine with the demo database:

    python -m scripts.seed_government_parties --approver "Direzione VeraPolitica"
"""

from __future__ import annotations

import argparse
import base64
import sys

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.services.redazione.service import RedazioneError, RedazioneService
from scripts import sync_symbols
from scripts.sync_symbols import AUTHOR, Getter, MAX_BYTES, Report, commons_file, commons_info, fold, licence_of, plain, sparql

GOVERNMENT_PARTIES = ("Fratelli d'Italia", "Lega per Salvini Premier", "Forza Italia", "Noi Moderati")
OPPOSITION_PARTIES = ("Partito Democratico", "Movimento 5 Stelle", "Alleanza Verdi e Sinistra")
PARLIAMENT_PARTIES = GOVERNMENT_PARTIES + OPPOSITION_PARTIES

# Q7278 = political party; Q388602 = electoral list (AVS is an alliance, not Q7278).
QUERY = """
    SELECT ?item ?label ?short ?site ?logo WHERE {
      VALUES ?label { %s }
      VALUES ?class { wd:Q7278 wd:Q388602 }
      ?item rdfs:label ?label; wdt:P31/wdt:P279* ?class; wdt:P17 wd:Q38.
      FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }
      OPTIONAL { ?item wdt:P1813 ?short. FILTER(LANG(?short) = "it") }
      OPTIONAL { ?item wdt:P856 ?site. }
      OPTIONAL { ?item wdt:P154 ?logo. }
    }"""


def _literal(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"@it'


def _pick(rows: list[dict]) -> dict | None:
    # Several current items with the same label: prefer the one with a logo and a site.
    rows = sorted(rows, key=lambda row: ("logo" not in row, "site" not in row, row["item"]["value"]))
    return rows[0] if rows else None


def seed(service: RedazioneService, get: Getter, *, approver: str, names: tuple[str, ...] = PARLIAMENT_PARTIES) -> Report:
    if approver == AUTHOR:
        raise ValueError("chi approva deve essere diverso da chi propone")
    report = Report()
    rows = sparql(get, QUERY % " ".join(_literal(name) for name in names))
    by_name: dict[str, list[dict]] = {}
    for row in rows:
        by_name.setdefault(fold(row["label"]["value"]), []).append(row)

    for name in names:
        row = _pick(by_name.get(fold(name), []))
        if row is None:
            report.unmatched.append(f"{name} (non trovato su Wikidata)")
            continue
        state = service.symbols()
        party = next((item for item in state["party"] if fold(item["name"]) == fold(name)), None)
        try:
            if party is None:
                pending = next((item for item in state["new_parties"] if fold(item["payload"]["name"]) == fold(name)), None)
                if pending is None:
                    site = row.get("site", {}).get("value", "")
                    pending = service.propose_party(
                        {
                            "name": name,
                            "abbreviation": row.get("short", {}).get("value") or None,
                            "website": site if site.startswith("https://") else None,
                            "source_url": row["item"]["value"].replace("http://www.wikidata.org/entity/", "https://www.wikidata.org/wiki/"),
                        },
                        member=AUTHOR,
                    )
                note = (
                    "Partito dell'opposizione in Parlamento."
                    if name in OPPOSITION_PARTIES
                    else "Partito del Governo in carica."
                )
                service.approve("change", pending["id"], member=approver, note=note)
                report.proposed.append(f"partito: {name}")
                party = next(item for item in service.symbols()["party"] if fold(item["name"]) == fold(name))
            else:
                report.skipped.append(f"partito: {name} (già nell'elenco)")

            if party["symbol"]:
                report.skipped.append(f"logo: {name} (già pubblicato)")
                continue
            if party["pending"]:
                service.approve("change", party["pending"][0]["id"], member=approver, note="Logo del partito di Governo.")
                report.proposed.append(f"logo: {name}")
                continue
            if "logo" not in row:
                report.unmatched.append(f"logo: {name} (Wikidata non ha un logo: caricalo dalla console)")
                continue
            file = commons_file(row["logo"]["value"])
            info = commons_info(get, file)
            meta = (info or {}).get("extmetadata") or {}
            licence = licence_of(meta)
            if info is None or licence is None:
                found = (meta.get("LicenseShortName") or {}).get("value", "file non trovato")
                report.unmatched.append(f"logo: {name} (File:{file}, licenza «{found}»: caricalo dalla console con l'autorizzazione o dalla fonte ufficiale)")
                continue
            data = get(info.get("thumburl") or info["url"])
            if len(data) > MAX_BYTES:
                report.unmatched.append(f"logo: {name} (immagine troppo grande)")
                continue
            credit = plain((meta.get("Artist") or {}).get("value", "")) or name
            image = service.upload_image({"data": base64.b64encode(data).decode(), "credit": credit, "alt": f"Logo: {name}"}, member=AUTHOR)
            proposal = service.propose_symbol(
                {"kind": "party", "key": party["key"], "image_id": image["id"], "credit": credit, "license": licence, "source_url": info["descriptionurl"]},
                member=AUTHOR,
            )
            service.approve("change", proposal["id"], member=approver, note="Logo del partito di Governo.")
            report.proposed.append(f"logo: {name} [{licence}]")
        except RedazioneError as error:
            report.skipped.append(f"{name} ({error})")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--approver", default="Direzione VeraPolitica")
    parser.add_argument("--database-url")
    args = parser.parse_args(argv)
    settings = get_settings()
    runtime = settings.model_copy(update={"database_url": args.database_url}) if args.database_url else settings
    engine = create_db_engine(runtime.database_url)
    prepare_runtime_schema(engine, runtime)
    Base.metadata.create_all(engine)
    service = RedazioneService(create_session_factory(engine))
    try:
        report = seed(service, sync_symbols.quick_get, approver=args.approver)
    except OSError as error:
        print(f"Rete non raggiungibile: {error}", file=sys.stderr)
        return 2
    for line in report.proposed:
        print(f"  + {line}")
    for line in report.skipped:
        print(f"  = {line}")
    for line in report.unmatched:
        print(f"  ! {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
