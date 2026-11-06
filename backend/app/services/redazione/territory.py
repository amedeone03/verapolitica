"""Territory schede: Regione, Provincia and Città (Comune).

The blocks follow the redazione's «Modelli di scrittura» (Modello Regione and
Modello Città; the province uses the same rules with the blocks that exist for
a province). The official base (ISTAT names and counts, office holders from
the DAIT registry) is read-only and always returned next to the blocks: it is
the reference every block is written against.

Every save is a new version. A pending version waits for an admin (or, with
no admin named, for a second member); publishing it supersedes the previous
published version. The redazione can always propose a change to any block,
published or not.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    EditorialPost,
    EditorialPostStatus,
    FeedScope,
    Municipality,
    Region,
)
from backend.app.models.territory_block import TerritoryBlock, TerritoryBlockStatus, TerritoryKind
from backend.app.services.public_territory_service import PublicTerritoryQueryService
from backend.app.services.redazione import style


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _clean(value: Any, limit: int = 4000) -> str:
    """One line of text: collapsed spaces, trimmed to the limit."""

    return " ".join(str(value or "").split())[:limit]


PROMISE_STATES = {
    "da_compilare": "Da compilare",
    "in_corso": "In corso",
    "mantenuta": "Mantenuta",
    "parzialmente_mantenuta": "Mantenuta parzialmente",
    "non_mantenuta": "Non mantenuta",
}

PROMISES = {
    "type": "rows",
    "columns": [
        {"key": "promessa", "label": "Promessa"},
        {"key": "quando", "label": "Quando e dove"},
        {"key": "stato", "label": "Stato", "options": PROMISE_STATES},
        {"key": "aggiornamento", "label": "Aggiornamento"},
        {"key": "fonte", "label": "Fonte"},
    ],
}
GIUNTA = {
    "type": "rows",
    "columns": [
        {"key": "nome", "label": "Assessore o assessora"},
        {"key": "delega", "label": "Deleghe"},
    ],
}

# Block definitions, in the order of the model. "notizie" and "fonti" are not
# written here: news come from the feed (local news) and sources are gathered
# from every published block plus the official base.
DEFINITIONS: dict[str, list[dict[str, Any]]] = {
    "region": [
        {
            "key": "rapida", "n": 0, "title": "Scheda rapida", "type": "fields",
            "fields": [
                {"key": "capoluogo", "label": "Capoluogo"},
                {"key": "tipo", "label": "Tipo", "options": {"ordinaria": "Regione a statuto ordinario", "speciale": "Regione a statuto speciale"}},
                {"key": "popolazione", "label": "Popolazione (ISTAT)"},
                {"key": "popolazione_anno", "label": "Anno del dato"},
                {"key": "ultime_elezioni", "label": "Ultime elezioni"},
                {"key": "prossime_elezioni", "label": "Prossime elezioni"},
            ],
            "guide": {"what": "Capoluogo, numero di province e di comuni (dato ISTAT), popolazione, tipo (ordinaria o statuto speciale), presidente, ultime e prossime elezioni.", "length": "Riquadro", "avoid": "Dati senza anno di riferimento."},
        },
        {"key": "presidente", "n": 1, "title": "Il presidente", "type": "text",
         "guide": {"what": "Partito o coalizione, in carica dal, percorso politico, eventuale rielezione.", "length": "40–70 parole", "avoid": "Giudizi sul suo operato."}, "words": [40, 70]},
        {"key": "giunta", "n": 2, "title": "La giunta", **GIUNTA,
         "guide": {"what": "Assessori principali con le deleghe che toccano di più i cittadini (sanità, trasporti, ambiente, istruzione).", "length": "Elenco", "avoid": "Elencare tutti gli incarichi minori."}},
        {"key": "consiglio", "n": 3, "title": "Il consiglio regionale", "type": "text",
         "guide": {"what": "Composizione: partiti di maggioranza e di opposizione, capigruppo principali, numero di consiglieri.", "length": "40–70 parole", "avoid": "Seggi senza data di riferimento."}, "words": [40, 70]},
        {"key": "promesse", "n": 4, "title": "Promesse del mandato", **PROMISES,
         "guide": {"what": "3–5 impegni del programma elettorale, in tabella come per i Politici: stato, aggiornamento, fonte.", "length": "Tabella", "avoid": "Promesse generiche non verificabili."}},
        {"key": "elezioni", "n": 5, "title": "Elezioni", "type": "text",
         "guide": {"what": "Ultime regionali: data, candidati, coalizioni, risultati, affluenza. Poi la data delle prossime, se nota.", "length": "Tabella + 2 righe", "avoid": "Previsioni sul prossimo voto."}},
    ],
    "province": [
        {
            "key": "rapida", "n": 0, "title": "Scheda rapida", "type": "fields",
            "fields": [
                {"key": "capoluogo", "label": "Capoluogo"},
                {"key": "tipo", "label": "Tipo di ente", "options": {"provincia": "Provincia", "citta_metropolitana": "Città metropolitana", "libero_consorzio": "Libero consorzio comunale", "ente_regionale": "Ente con ordinamento regionale"}},
                {"key": "popolazione", "label": "Popolazione (ISTAT)"},
                {"key": "popolazione_anno", "label": "Anno del dato"},
                {"key": "ultime_elezioni", "label": "Ultime elezioni provinciali"},
                {"key": "prossime_elezioni", "label": "Prossime elezioni provinciali"},
            ],
            "guide": {"what": "Capoluogo, regione, numero di comuni (dato ISTAT), popolazione, tipo di ente, presidente, ultime e prossime elezioni provinciali.", "length": "Riquadro", "avoid": "Dati senza anno di riferimento."},
        },
        {"key": "presidente", "n": 1, "title": "Il presidente", "type": "text",
         "guide": {"what": "Chi è (spesso il sindaco del capoluogo o un sindaco eletto dai consiglieri), in carica dal, partito o lista, come è stato eletto.", "length": "40–70 parole", "avoid": "Giudizi sul suo operato."}, "words": [40, 70]},
        {"key": "consiglio", "n": 2, "title": "Il consiglio provinciale", "type": "text",
         "guide": {"what": "Composizione per liste, maggioranza e opposizione, numero di consiglieri; ricorda che li eleggono sindaci e consiglieri comunali.", "length": "40–70 parole", "avoid": "Seggi senza data di riferimento."}, "words": [40, 70]},
        {"key": "elezioni", "n": 3, "title": "Elezioni", "type": "text",
         "guide": {"what": "Ultime elezioni provinciali (di secondo livello): data, liste, eletti, affluenza degli aventi diritto. Poi la data delle prossime, se nota.", "length": "60–100 parole", "avoid": "Previsioni sul prossimo voto."}},
    ],
    "municipality": [
        {
            "key": "rapida", "n": 0, "title": "Scheda rapida", "type": "fields",
            "fields": [
                {"key": "abitanti", "label": "Abitanti (ISTAT)"},
                {"key": "abitanti_anno", "label": "Anno del dato"},
                {"key": "coalizione", "label": "Coalizione del sindaco"},
                {"key": "ultime_elezioni", "label": "Ultime elezioni"},
                {"key": "prossime_elezioni", "label": "Prossime elezioni"},
            ],
            "guide": {"what": "Provincia, regione, abitanti (ISTAT), sindaco, in carica dal, coalizione, ultime e prossime elezioni.", "length": "Riquadro", "avoid": "Dati senza anno di riferimento."},
        },
        {"key": "sindaco", "n": 1, "title": "Il sindaco", "type": "text",
         "guide": {"what": "Partito o lista, in carica dal, percorso, eventuale rielezione.", "length": "40–70 parole", "avoid": "Giudizi sul suo operato."}, "words": [40, 70]},
        {"key": "giunta", "n": 2, "title": "La giunta", **GIUNTA,
         "guide": {"what": "Assessori principali e deleghe che toccano di più i cittadini.", "length": "Elenco", "avoid": "Elencare tutte le deleghe minori."}},
        {"key": "consiglio", "n": 3, "title": "Consiglio e opposizione", "type": "text",
         "guide": {"what": "Maggioranza, principali forze di opposizione, capigruppo: le «altre voci della politica locale».", "length": "40–70 parole", "avoid": "Dare spazio solo alla maggioranza."}, "words": [40, 70]},
        {"key": "promesse", "n": 4, "title": "Promesse del mandato", **PROMISES,
         "guide": {"what": "3–5 impegni del programma elettorale in tabella, con stato, aggiornamento e fonte.", "length": "Tabella", "avoid": "Promesse senza fonte."}},
        {"key": "elezioni", "n": 5, "title": "Elezioni (storico e prossime)", "type": "text",
         "guide": {"what": "Esito delle ultime comunali. Per i comuni al voto: data (quando fissata), candidati emersi, regole del ballottaggio (sopra i 15.000 abitanti se nessuno supera il 50%).", "length": "60–100 parole", "avoid": "Indicare «favoriti»; candidati non dichiarati."}, "words": [60, 100]},
    ],
}
KIND_TITLES = {"region": "Regione", "province": "Provincia", "municipality": "Comune"}
NEWS_TITLES = {"region": "Notizie regionali", "province": "Notizie della provincia", "municipality": "Notizie locali"}


class TerritoryError(RuntimeError):
    status_code = 400

    def __init__(self, message: str, findings: list[dict] | None = None) -> None:
        super().__init__(message)
        self.findings = findings or []


class TerritoryNotFound(TerritoryError):
    status_code = 404


def definition(kind: str, block: str) -> dict:
    for item in DEFINITIONS.get(kind, []):
        if item["key"] == block:
            return item
    raise TerritoryNotFound("Blocco sconosciuto per questo territorio.")


def _kind(kind: str) -> TerritoryKind:
    try:
        return TerritoryKind(kind)
    except ValueError as error:
        raise TerritoryNotFound("Tipo di territorio sconosciuto.") from error


def sanitize(kind: str, block: str, payload: dict) -> tuple[dict, list[dict]]:
    """Keep only the fields the model defines; trim text."""

    spec = definition(kind, block)
    data: dict[str, Any] = {}
    if spec["type"] == "fields":
        values = payload.get("fields") if isinstance(payload.get("fields"), dict) else payload
        for field in spec["fields"]:
            value = _clean(values.get(field["key"]), 300)
            if field.get("options") and value and value not in field["options"]:
                value = ""
            data[field["key"]] = value
        data["note"] = _clean(payload.get("note"), 600)
    elif spec["type"] == "text":
        data["body"] = str(payload.get("body") or "").strip()[:4000]
    else:
        rows = []
        for row in payload.get("rows") or []:
            if not isinstance(row, dict):
                continue
            clean = {}
            for column in spec["columns"]:
                value = _clean(row.get(column["key"]), 600)
                if column.get("options") and value not in column["options"]:
                    value = next(iter(column["options"]))
                clean[column["key"]] = value
            if any(clean.get(column["key"]) for column in spec["columns"] if not column.get("options")):
                rows.append(clean)
            if len(rows) >= 30:
                break
        data["rows"] = rows
        data["body"] = str(payload.get("body") or "").strip()[:1500]
    sources = []
    for item in payload.get("sources") or []:
        if not isinstance(item, dict):
            continue
        url = _clean(item.get("url"), 500)
        name = _clean(item.get("name"), 200)
        if url or name:
            sources.append({"name": name, "url": url, "date": _clean(item.get("date"), 20) or None})
        if len(sources) >= 12:
            break
    return data, sources


def findings(kind: str, block: str, data: dict, sources: list[dict]) -> list[dict]:
    spec = definition(kind, block)
    found: list[style.Finding] = []
    texts: list[tuple[str, str]] = []
    if spec["type"] == "fields":
        texts = [(field["label"], data.get(field["key"]) or "") for field in spec["fields"]] + [("Nota", data.get("note") or "")]
        if not any(data.get(field["key"]) for field in spec["fields"]):
            found.append(style.Finding("error", "blocco_vuoto", "Compila almeno un dato della scheda rapida.", "dati"))
        if data.get("popolazione") and not data.get("popolazione_anno"):
            found.append(style.Finding("error", "anno_mancante", "La popolazione va scritta con l'anno del dato ISTAT.", "popolazione_anno"))
        if data.get("abitanti") and not data.get("abitanti_anno"):
            found.append(style.Finding("error", "anno_mancante", "Gli abitanti vanno scritti con l'anno del dato ISTAT.", "abitanti_anno"))
    elif spec["type"] == "text":
        texts = [("Testo", data.get("body") or "")]
        if not (data.get("body") or "").strip():
            found.append(style.Finding("error", "blocco_vuoto", "Il blocco è vuoto.", "testo"))
        low, high = spec.get("words") or (0, 0)
        count = style.words(data.get("body"))
        if high and data.get("body") and not (low * 0.6 <= count <= high * 1.5):
            found.append(style.Finding("warning", "lunghezza", f"{count} parole: l'indicazione è {low}–{high}.", "testo"))
    else:
        rows = data.get("rows") or []
        if not rows:
            found.append(style.Finding("error", "blocco_vuoto", "Aggiungi almeno una riga.", "righe"))
        for row in rows:
            texts.extend((column["label"], row.get(column["key"]) or "") for column in spec["columns"] if not column.get("options"))
        if block == "promesse":
            if rows and not 3 <= len(rows) <= 5:
                found.append(style.Finding("warning", "numero_promesse", f"{len(rows)} promesse: il modello ne chiede 3–5.", "righe"))
            unsourced = next((row for row in rows if not row.get("fonte")), None)
            if unsourced:
                found.append(style.Finding("error", "fonte_mancante", f"La promessa «{unsourced.get('promessa') or '…'}» non ha una fonte.", "fonte"))
            if any(row.get("stato") == "non_mantenuta" and not row.get("aggiornamento") for row in rows):
                found.append(style.Finding("error", "motivo_mancante", "«Non mantenuta» solo con il fatto e la data nell'aggiornamento (scadenza passata, mandato finito, rinuncia).", "aggiornamento"))
        texts.append(("Testo", data.get("body") or ""))
    for label, text in texts:
        found.extend(style.text_findings(text, field=label))
    found.extend(style.source_findings(sources))
    # One finding per code is enough for the writer.
    seen: set[tuple[str, str | None]] = set()
    unique = []
    for item in found:
        key = (item.code, item.field)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item.as_dict())
    return unique


class TerritorySchede:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    # ----------------------------------------------------------------- base
    def base(self, session: Session, kind: str, key: str) -> dict:
        territory = PublicTerritoryQueryService(session)
        if kind == "region":
            if not key.isdigit() or session.get(Region, int(key)) is None:
                raise TerritoryNotFound("Regione non trovata.")
            region = territory.get_region(int(key))
            provinces = list(session.execute(
                select(Municipality.province_abbreviation, func.min(Municipality.province_name), func.count(Municipality.id))
                .where(Municipality.region_id == int(key))
                .group_by(Municipality.province_abbreviation)
                .order_by(func.min(Municipality.province_name))
            ))
            return {
                "kind": kind, "key": key, "name": region.name, "title": f"Regione {region.name}",
                "istat_code": region.istat_code,
                "municipality_count": region.municipality_count,
                "province_count": len(provinces),
                "provinces": [{"abbreviation": abbr, "name": name, "municipalities": count} for abbr, name, count in provinces],
                "holder": _holder(region.current_president, "Presidente della Regione"),
                "region": {"id": region.id, "name": region.name},
                "source": {"name": region.source.name, "url": region.source.url},
            }
        if kind == "province":
            first = session.scalar(select(Municipality).where(Municipality.province_abbreviation == key.upper()).limit(1))
            if first is None:
                raise TerritoryNotFound("Provincia non trovata.")
            region = session.get(Region, first.region_id)
            count = session.scalar(select(func.count(Municipality.id)).where(Municipality.province_abbreviation == key.upper())) or 0
            return {
                "kind": kind, "key": key.upper(), "name": first.province_name, "title": f"Provincia di {first.province_name}",
                "abbreviation": key.upper(),
                "municipality_count": count,
                "holder": None,
                "region": {"id": region.id, "name": region.canonical_name} if region else None,
                "source": {"name": first.source.name if first.source else "ISTAT", "url": first.source_url},
            }
        if kind == "municipality":
            if not key.isdigit() or session.get(Municipality, int(key)) is None:
                raise TerritoryNotFound("Comune non trovato.")
            municipality = territory.get_municipality(int(key))
            return {
                "kind": kind, "key": key, "name": municipality.name, "title": f"Comune di {municipality.name}",
                "istat_code": municipality.istat_code,
                "province": {"abbreviation": municipality.province_abbreviation, "name": municipality.province_name},
                "holder": _holder(municipality.current_mayor, "Sindaco"),
                "region": {"id": municipality.region_id, "name": municipality.region_name},
                "source": {"name": municipality.source.name, "url": municipality.source.url},
            }
        raise TerritoryNotFound("Tipo di territorio sconosciuto.")

    # ---------------------------------------------------------------- reads
    def scheda(self, kind: str, key: str, *, member: str | None = None) -> dict:
        """Everything the console shows: base, definitions, published and pending versions."""

        territory_kind = _kind(kind)
        with self.session_factory() as session:
            base = self.base(session, kind, key)
            rows = list(session.scalars(
                select(TerritoryBlock)
                .where(TerritoryBlock.territory_kind == territory_kind, TerritoryBlock.territory_key == base["key"])
                .order_by(TerritoryBlock.created_at, TerritoryBlock.id)
            ))
            blocks = {}
            for spec in DEFINITIONS[kind]:
                mine = [row for row in rows if row.block == spec["key"]]
                published = next((row for row in reversed(mine) if row.status is TerritoryBlockStatus.PUBLISHED), None)
                pending = [row for row in mine if row.status is TerritoryBlockStatus.PENDING]
                rejected = [row for row in mine if row.status is TerritoryBlockStatus.REJECTED][-1:]
                blocks[spec["key"]] = {
                    "published": self._item(published, kind, member) if published else None,
                    "pending": [self._item(row, kind, member) for row in pending],
                    "rejected": [self._item(row, kind, member) for row in rejected if not pending and (published is None or row.created_at > published.created_at)],
                }
            return {
                "base": base,
                "definitions": DEFINITIONS[kind],
                "blocks": blocks,
                "news": self._news(session, kind, base),
                "news_title": NEWS_TITLES[kind],
                "public_url": _public_url(kind, base["key"]),
            }

    def public(self, kind: str, key: str) -> dict:
        """What the citizen sees: the base and the published version of each block."""

        territory_kind = _kind(kind)
        with self.session_factory() as session:
            base = self.base(session, kind, key)
            rows = list(session.scalars(
                select(TerritoryBlock)
                .where(
                    TerritoryBlock.territory_kind == territory_kind,
                    TerritoryBlock.territory_key == base["key"],
                    TerritoryBlock.status == TerritoryBlockStatus.PUBLISHED,
                )
                .order_by(TerritoryBlock.published_at, TerritoryBlock.id)
            ))
            latest = {row.block: row for row in rows}
            blocks = []
            for spec in DEFINITIONS[kind]:
                row = latest.get(spec["key"])
                blocks.append({
                    "key": spec["key"], "n": spec["n"], "title": spec["title"], "type": spec["type"],
                    "fields": spec.get("fields"), "columns": spec.get("columns"),
                    "data": row.data if row else None,
                    "sources": row.sources if row else [],
                    "written_by": row.created_by if row else None,
                    "published_by": row.reviewed_by if row else None,
                    "published_at": _iso(row.published_at) if row else None,
                })
            sources = [base["source"]] + [source for row in latest.values() for source in row.sources]
            unique, seen = [], set()
            for source in sources:
                marker = source.get("url") or source.get("name")
                if marker and marker not in seen:
                    seen.add(marker)
                    unique.append(source)
            updated = max((row.published_at for row in latest.values() if row.published_at), default=None)
            return {
                "base": base,
                "blocks": blocks,
                "sources": unique,
                "updated_at": _iso(updated),
                "writers": sorted({row.created_by for row in latest.values()}),
                "publishers": sorted({row.reviewed_by for row in latest.values() if row.reviewed_by}),
                "news_title": NEWS_TITLES[kind],
            }

    def search(self, query: str = "", *, limit: int = 30) -> list[dict]:
        text = query.strip()
        with self.session_factory() as session:
            done: dict[tuple[str, str], dict] = {}
            for row in session.scalars(select(TerritoryBlock).where(TerritoryBlock.status.in_((TerritoryBlockStatus.PUBLISHED, TerritoryBlockStatus.PENDING)))):
                entry = done.setdefault((row.territory_kind.value, row.territory_key), {"published": set(), "pending": 0})
                if row.status is TerritoryBlockStatus.PUBLISHED:
                    entry["published"].add(row.block)
                else:
                    entry["pending"] += 1
            results: list[dict] = []
            regions = select(Region).order_by(Region.canonical_name)
            if text:
                regions = regions.where(func.lower(Region.canonical_name).contains(text.casefold()))
            for region in session.scalars(regions.limit(limit)):
                results.append(_search_row("region", str(region.id), f"Regione {region.canonical_name}", "", done))
            provinces = (
                select(Municipality.province_abbreviation, func.min(Municipality.province_name), func.min(Municipality.region_id))
                .group_by(Municipality.province_abbreviation)
                .order_by(func.min(Municipality.province_name))
            )
            if text:
                provinces = provinces.having(
                    func.lower(func.min(Municipality.province_name)).contains(text.casefold())
                    | (func.lower(Municipality.province_abbreviation) == text.casefold())
                )
            region_names = {row.id: row.canonical_name for row in session.scalars(select(Region))}
            for abbr, name, region_id in session.execute(provinces.limit(limit if text else 200)):
                results.append(_search_row("province", abbr, f"Provincia di {name}", region_names.get(region_id, ""), done))
            if text:
                towns = (
                    select(Municipality)
                    .where(func.lower(Municipality.canonical_name).contains(text.casefold()))
                    .order_by(func.length(Municipality.canonical_name), Municipality.canonical_name)
                    .limit(limit)
                )
                for town in session.scalars(towns):
                    results.append(_search_row("municipality", str(town.id), f"Comune di {town.canonical_name}", f"{town.province_abbreviation} · {region_names.get(town.region_id, '')}", done))
            else:
                # Without a query: the comuni that already have a scheda.
                ids = [int(key) for (kind, key) in done if kind == "municipality" and key.isdigit()]
                for town in session.scalars(select(Municipality).where(Municipality.id.in_(ids)).order_by(Municipality.canonical_name)):
                    results.append(_search_row("municipality", str(town.id), f"Comune di {town.canonical_name}", f"{town.province_abbreviation} · {region_names.get(town.region_id, '')}", done))
            return results

    # --------------------------------------------------------------- writes
    def save(self, kind: str, key: str, block: str, payload: dict, *, member: str) -> dict:
        territory_kind = _kind(kind)
        data, sources = sanitize(kind, block, payload)
        with self.session_factory.begin() as session:
            base = self.base(session, kind, key)
            # A new save replaces the writer's own pending version of the same block.
            for row in session.scalars(select(TerritoryBlock).where(
                TerritoryBlock.territory_kind == territory_kind,
                TerritoryBlock.territory_key == base["key"],
                TerritoryBlock.block == block,
                TerritoryBlock.status == TerritoryBlockStatus.PENDING,
                TerritoryBlock.created_by == member,
            )):
                row.status = TerritoryBlockStatus.SUPERSEDED
                row.review_note = "Sostituita da una nuova versione dello stesso autore."
            row = TerritoryBlock(
                territory_kind=territory_kind, territory_key=base["key"], block=block,
                data=data, sources=sources, status=TerritoryBlockStatus.PENDING, created_by=member,
            )
            session.add(row)
            session.flush()
            return {**self._item(row, kind, member), "title": f"{base['title']} — {definition(kind, block)['title']}"}

    def pending(self) -> list[dict]:
        with self.session_factory() as session:
            rows = list(session.scalars(
                select(TerritoryBlock).where(TerritoryBlock.status == TerritoryBlockStatus.PENDING).order_by(TerritoryBlock.created_at, TerritoryBlock.id)
            ))
            items = []
            names: dict[tuple[str, str], dict] = {}
            for row in rows:
                marker = (row.territory_kind.value, row.territory_key)
                if marker not in names:
                    try:
                        names[marker] = self.base(session, *marker)
                    except TerritoryNotFound:
                        continue
                base = names[marker]
                items.append({
                    **self._item(row, row.territory_kind.value, None),
                    "title": f"{base['title']} — {definition(row.territory_kind.value, row.block)['title']}",
                    "territory": {"kind": marker[0], "key": marker[1], "title": base["title"]},
                })
            return items

    def publish(self, item_id: int, *, reviewer: str, note: str | None = None) -> TerritoryBlock:
        with self.session_factory.begin() as session:
            row = session.get(TerritoryBlock, item_id)
            if row is None or row.status is not TerritoryBlockStatus.PENDING:
                raise TerritoryError("Versione non più in attesa.")
            for previous in session.scalars(select(TerritoryBlock).where(
                TerritoryBlock.territory_kind == row.territory_kind,
                TerritoryBlock.territory_key == row.territory_key,
                TerritoryBlock.block == row.block,
                TerritoryBlock.status == TerritoryBlockStatus.PUBLISHED,
            )):
                previous.status = TerritoryBlockStatus.SUPERSEDED
            row.status = TerritoryBlockStatus.PUBLISHED
            row.reviewed_by = reviewer
            row.review_note = note
            row.published_at = _now()
            session.flush()
            return row

    def reject(self, item_id: int, *, reviewer: str, note: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(TerritoryBlock, item_id)
            if row is None or row.status is not TerritoryBlockStatus.PENDING:
                raise TerritoryError("Versione non più in attesa.")
            row.status = TerritoryBlockStatus.REJECTED
            row.reviewed_by = reviewer
            row.review_note = note

    # -------------------------------------------------------------- helpers
    def _item(self, row: TerritoryBlock, kind: str, member: str | None) -> dict:
        return {
            "id": row.id,
            "block": row.block,
            "status": row.status.value,
            "data": row.data,
            "sources": row.sources,
            "created_by": row.created_by,
            "created_at": _iso(row.created_at),
            "reviewed_by": row.reviewed_by,
            "review_note": row.review_note,
            "published_at": _iso(row.published_at),
            "own": member is not None and row.created_by == member,
            "findings": findings(kind, row.block, row.data or {}, row.sources or []),
        }

    @staticmethod
    def _news(session: Session, kind: str, base: dict) -> list[dict]:
        query = select(EditorialPost).where(EditorialPost.status.in_((EditorialPostStatus.PUBLISHED, EditorialPostStatus.PENDING)))
        if kind == "region":
            query = query.where(EditorialPost.scope == FeedScope.REGION, EditorialPost.region_id == int(base["key"]))
        elif kind == "province":
            query = query.where(EditorialPost.scope == FeedScope.PROVINCE, EditorialPost.province_abbreviation == base["key"])
        else:
            query = query.where(EditorialPost.scope == FeedScope.MUNICIPALITY, EditorialPost.municipality_id == int(base["key"]))
        posts = session.scalars(query.order_by(EditorialPost.created_at.desc()).limit(8))
        return [{"id": post.id, "title": post.title, "status": post.status.value} for post in posts]


def _holder(holder: Any, role: str) -> dict | None:
    if holder is None:
        return None
    return {
        "role": role,
        "politician_id": holder.politician_id,
        "name": f"{holder.given_name} {holder.family_name}".strip(),
        "since": _iso(holder.start_date),
    }


def _public_url(kind: str, key: str) -> str:
    return f"/app/?{kind}={key}"


def _search_row(kind: str, key: str, title: str, detail: str, done: dict) -> dict:
    entry = done.get((kind, key), {"published": set(), "pending": 0})
    total = len(DEFINITIONS[kind])
    return {
        "kind": kind,
        "key": key,
        "title": title,
        "detail": detail,
        "published_blocks": len(entry["published"]),
        "total_blocks": total,
        "pending": entry["pending"],
    }

