"""Prepare the demo database for a presentation to the redazione.

Three steps, each one independent (a failure is reported and the next step runs):

1. Party of each published member of the Government. Current party
   memberships (Wikidata P102 with no end date) for the four parties of the
   Government already in the list. Proposed by "Sincronizzazione Wikidata",
   approved by ``--approver``, written to the log. Ministers without a party
   on Wikidata stay without one (independent ministers have none).
2. The latest bills from the Senato open data (dati.senato.it). Each one is a
   draft from the import and is approved by ``--approver``.
3. The news items in ``scripts/presentazione_notizie.json``: written by
   ``--author``, approved by ``--approver`` (whoever writes is not whoever
   verifies). Items already in the console with the same title are skipped.

A copy of the database is saved first. Needs internet for steps 1 and 2.

    python -m scripts.prepara_presentazione
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    EditorialPost,
    PoliticalParty,
    PoliticalPartyAffiliation,
    Politician,
    PoliticianVersion,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.services.redazione.service import RedazioneError, RedazioneService
from backend.app.storage import LocalRawStorage
from scripts import sync_symbols
from scripts.sync_symbols import AUTHOR, Getter, fold, sparql

ROOT = Path(__file__).resolve().parents[1]
NEWS_FILE = ROOT / "scripts" / "presentazione_notizie.json"
WIKIDATA_SOURCE = ("wikidata", "Wikidata", "https://www.wikidata.org")
# Wikidata labels that name one of the Government parties in the list.
PARTY_ALIASES = {"lega": "lega per salvini premier"}

AFFILIATION_QUERY = """
    SELECT ?person ?name ?party ?partyLabel ?start WHERE {
      VALUES ?name { %s }
      ?person rdfs:label ?name; wdt:P31 wd:Q5; wdt:P27 wd:Q38; p:P102 ?statement.
      ?statement ps:P102 ?party.
      FILTER NOT EXISTS { ?statement pq:P582 ?end }
      OPTIONAL { ?statement pq:P580 ?start }
      ?party rdfs:label ?partyLabel. FILTER(LANG(?partyLabel) = "it")
    }"""


def _literal(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"@it'


def _wiki(uri: str) -> str:
    return uri.replace("http://www.wikidata.org/entity/", "https://www.wikidata.org/wiki/")


def backup(database_url: str) -> Path | None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database:
        return None
    path = Path(url.database)
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    target = path.with_name(f"{path.stem}.prima-della-presentazione-{stamp}{path.suffix}")
    shutil.copy2(path, target)
    return target


def _published_people(session) -> dict[int, str]:
    rows = session.execute(
        select(Politician.id, PoliticianVersion.profile_data)
        .join(PoliticianVersion, PoliticianVersion.id == Politician.current_version_id)
        .where(PoliticianVersion.published_at.is_not(None))
    ).all()
    return {pid: f"{data.get('given_name', '')} {data.get('family_name', '')}".strip() for pid, data in rows}


def _source(session) -> Source:
    key, name, base_url = WIKIDATA_SOURCE
    source = session.scalar(select(Source).where(Source.key == key))
    if source is None:
        source = Source(key=key, name=name, base_url=base_url)
        session.add(source)
        session.flush()
    return source


def seed_affiliations(service: RedazioneService, storage: LocalRawStorage, get: Getter, *, approver: str) -> list[str]:
    if approver == AUTHOR:
        raise ValueError("chi approva deve essere diverso da chi propone")
    lines: list[str] = []
    with service.session_factory() as session:
        people = _published_people(session)
        parties = {fold(party.canonical_name): party for party in session.scalars(select(PoliticalParty))}
    if not people:
        return ["nessun profilo pubblicato"]
    # Wikidata often drops a middle name ("Eugenia Roccella"): ask for both forms.
    aliases: dict[str, str] = {}
    for name in people.values():
        aliases[fold(name)] = name
        parts = name.split()
        if len(parts) > 2:
            aliases.setdefault(fold(f"{parts[0]} {parts[-1]}"), name)
    query = AFFILIATION_QUERY % " ".join(
        _literal(label) for label in sorted({*people.values(), *(" ".join([n.split()[0], n.split()[-1]]) for n in people.values())})
    )
    rows = sparql(get, query)
    body = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()

    found: dict[str, dict[str, set]] = {}
    for row in rows:
        label = fold(row["partyLabel"]["value"])
        party = parties.get(PARTY_ALIASES.get(label, label))
        if party is None:
            continue
        name = aliases.get(fold(row["name"]["value"]))
        if name is None:
            continue
        entry = found.setdefault(fold(name), {"persons": set(), "parties": set(), "rows": set()})
        entry["persons"].add(row["person"]["value"])
        entry["parties"].add(party.id)
        entry["rows"].add((row["person"]["value"], party.id, (row.get("start") or {}).get("value", "")[:10]))

    with service.session_factory.begin() as session:
        source = _source(session)
        digest = hashlib.sha256(body).hexdigest()
        document = session.scalar(
            select(RawDocument).where(RawDocument.source_id == source.id, RawDocument.raw_sha256 == digest)
        )
        if document is None:
            document = RawDocument(
                source_id=source.id,
                retrieved_at=datetime.now(timezone.utc),
                source_url="https://query.wikidata.org/sparql",
                content_type="application/json",
                storage_key=storage.put(source.key, digest, body),
                raw_sha256=digest,
                normalized_sha256=digest,
                structured_records=[],
                normalized_text=None,
                process_status=RawDocumentStatus.PARSED,
                change_detected=True,
                collector_version="presentazione-v1",
                parser_version="presentazione-v1",
            )
            session.add(document)
            session.flush()

        for politician_id, name in sorted(people.items(), key=lambda item: item[1]):
            entry = found.get(fold(name))
            if entry is None:
                lines.append(f"  · {name}: nessun partito di Governo su Wikidata (resta senza logo)")
                continue
            if len(entry["persons"]) != 1 or len(entry["parties"]) != 1:
                lines.append(f"  ! {name}: dati ambigui su Wikidata, da decidere in redazione")
                continue
            person, party_id, start = sorted(entry["rows"])[0]
            party = session.get(PoliticalParty, party_id)
            identity = hashlib.sha256(f"{person}|{party_id}|P102".encode()).hexdigest()[:64]
            existing = session.scalar(
                select(PoliticalPartyAffiliation).where(
                    PoliticalPartyAffiliation.source_id == source.id,
                    PoliticalPartyAffiliation.identity_key == identity,
                )
            )
            if existing is not None:
                lines.append(f"  = {name}: {party.canonical_name} (già presente)")
                continue
            affiliation = PoliticalPartyAffiliation(
                politician_id=politician_id,
                political_party_id=party_id,
                source_id=source.id,
                raw_document_id=document.id,
                identity_key=identity,
                source_identifier=person.rsplit("/", 1)[-1],
                source_url=_wiki(person),
                source_field="P102 membro del partito politico (senza data di fine)",
                start_date=date.fromisoformat(start) if start else None,
                affiliation_type="iscrizione al partito",
            )
            session.add(affiliation)
            session.flush()
            summary = f"Partito di {name}: {party.canonical_name} (fonte: Wikidata)."
            service._log(
                session, actor=AUTHOR, action="scrittura", object_kind="affiliation", object_id=affiliation.id,
                politician_id=politician_id, summary=f"Proposto. {summary}", details={"source_url": _wiki(person)},
            )
            service._log(
                session, actor=approver, action="approvazione", object_kind="affiliation", object_id=affiliation.id,
                politician_id=politician_id, summary=f"Approvato. {summary}",
                details={"note": "Partito del Governo in carica, preparazione della presentazione.", "author": AUTHOR},
            )
            lines.append(f"  + {name}: {party.canonical_name}")
    return lines


def seed_senato(service: RedazioneService, *, approver: str, limit: int) -> list[str]:
    import os

    os.environ["VERAPOLITICA_SENATO_PROPOSAL_RECORD_LIMIT"] = str(limit)
    get_settings.cache_clear()
    from scripts import run_proposal_ingestion

    if run_proposal_ingestion.main() != 0:
        return ["  ! importazione dal Senato non riuscita (vedi sopra)"]
    lines = []
    for item in service.queue(member=approver):
        if item["kind"] != "proposal" or item["own"] or item["blocked"]:
            continue
        try:
            service.approve("proposal", item["id"], member=approver, note="Atto ufficiale del Senato, preparazione della presentazione.")
            lines.append(f"  + {item['title'][:90]}")
        except RedazioneError as error:
            lines.append(f"  ! {item['title'][:60]}: {error}")
    return lines or ["  = nessun nuovo atto da approvare"]


def seed_news(service: RedazioneService, *, author: str, approver: str, path: Path = NEWS_FILE) -> list[str]:
    if author == approver:
        raise ValueError("chi scrive non è chi verifica")
    items = json.loads(path.read_text(encoding="utf-8"))
    with service.session_factory() as session:
        titles = {fold(title) for title in session.scalars(select(EditorialPost.title))}
        people = {fold(name): pid for pid, name in _published_people(session).items()}
    lines = []
    for item in items:
        if fold(item["title"]) in titles:
            lines.append(f"  = {item['title']} (già presente)")
            continue
        payload = {
            "title": item["title"],
            "blocks": item["blocks"],
            "sources": item["sources"],
            "scope": "national",
            "politician_ids": [people[fold(name)] for name in item.get("people", []) if fold(name) in people],
        }
        try:
            post = service.save_news(payload, member=author)
            service.approve("news", post["id"], member=approver, note="Verificata sulle fonti indicate.")
            lines.append(f"  + {item['title']}")
        except RedazioneError as error:
            details = getattr(error, "findings", None) or getattr(error, "details", None) or ""
            lines.append(f"  ! {item['title']}: {error} {details}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--author", default="Redazione VeraPolitica")
    parser.add_argument("--approver", default="Direzione VeraPolitica")
    parser.add_argument("--senato-limit", type=int, default=40)
    parser.add_argument("--skip-network", action="store_true", help="solo le notizie")
    args = parser.parse_args(argv)
    settings = get_settings()
    saved = backup(settings.database_url)
    if saved:
        print(f"Copia di sicurezza: {saved}")
    engine = create_db_engine(settings.database_url)
    prepare_runtime_schema(engine, settings)
    Base.metadata.create_all(engine)
    service = RedazioneService(create_session_factory(engine))
    storage = LocalRawStorage(Path(settings.raw_storage_path))

    steps = [("Notizie della redazione", lambda: seed_news(service, author=args.author, approver=args.approver))]
    if not args.skip_network:
        steps = [
            ("Partito dei membri del Governo", lambda: seed_affiliations(service, storage, sync_symbols.quick_get, approver=args.approver)),
            ("Atti del Senato", lambda: seed_senato(service, approver=args.approver, limit=args.senato_limit)),
            *steps,
        ]
    failed = False
    for title, step in steps:
        print(f"\n=== {title} ===")
        try:
            for line in step():
                print(line)
        except Exception as error:  # one step failing must not stop the others
            failed = True
            print(f"  ! non riuscito: {error}", file=sys.stderr)
    engine.dispose()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
