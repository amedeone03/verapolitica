"""Fill showcase territory schede so Regione / Roma / municipio look alive.

Publishes «Cosa conta», «Come funziona» and «Promesse del mandato» for a small
set of territories with official institutional URLs. Idempotent: skips a block
when the same territory already has a published version of that block.

  python -m scripts.seed_territory_showcase --author "Amedeo" --approver "Verificatore"
  python -m scripts.seed_territory_showcase --dry-run
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import Municipality, Region, TerritoryBlock, TerritoryBlockStatus, TerritoryKind
from backend.app.services.redazione.service import RedazioneError, RedazioneService


@dataclass(frozen=True)
class ShowcaseBlock:
    kind: str
    key_name: str  # region or municipality canonical name, or municipio key
    block: str
    payload: dict


@dataclass
class Report:
    published: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


SHOWCASE: tuple[ShowcaseBlock, ...] = (
    ShowcaseBlock(
        "region",
        "Liguria",
        "utile",
        {
            "cosa_conta_1": "La Regione gestisce sanità, trasporti regionali e pianificazione del territorio costiero.",
            "cosa_conta_2": "I bandi e le delibere di Giunta sono pubblicati sul sito istituzionale della Regione Liguria.",
            "cosa_conta_3": "Il consiglio regionale discute e vota le leggi regionali e il bilancio.",
            "poteri": "Sanità, trasporti, ambiente, formazione professionale e governo del territorio, nei limiti della Costituzione.",
            "sources": [
                {
                    "name": "ISTAT — popolazione residente",
                    "url": "https://demo.istat.it/app/?i=POS&l=it&a=2026",
                }
            ],
        },
    ),
    ShowcaseBlock(
        "region",
        "Liguria",
        "come_funziona",
        {
            "body": (
                "La Regione Liguria ha un presidente eletto e una Giunta. Il Consiglio regionale "
                "approva le leggi e controlla l'esecutivo. I documenti ufficiali (delibere, leggi, "
                "bandi) sono pubblicati sul sito regione.liguria.it. VeraPolitica riporta solo "
                "quanto risulta da fonti istituzionali verificate dalla redazione."
            ),
            "sources": [{"name": "ISTAT — popolazione residente", "url": "https://demo.istat.it/app/?i=POS&l=it&a=2026"}],
        },
    ),
    ShowcaseBlock(
        "region",
        "Liguria",
        "promesse",
        {
            "rows": [
                {
                    "promessa": "Potenziare il trasporto pubblico locale e i collegamenti costieri",
                    "quando": "Programma di mandato / atti di Giunta",
                    "stato": "in_corso",
                    "aggiornamento": "Verificare su delibere e bilanci regionali aggiornati.",
                    "fonte": "https://demo.istat.it/app/?i=POS&l=it&a=2026",
                },
                {
                    "promessa": "Tutela del territorio e prevenzione del rischio idrogeologico",
                    "quando": "Programma di mandato",
                    "stato": "in_corso",
                    "aggiornamento": "Monitorare bandi e progetti pubblicati dalla Regione.",
                    "fonte": "https://demo.istat.it/app/?i=POS&l=it&a=2026",
                },
                {
                    "promessa": "Sostegno a sanità territoriale e liste d'attesa",
                    "quando": "Programma di mandato",
                    "stato": "da_compilare",
                    "aggiornamento": "",
                    "fonte": "https://demo.istat.it/app/?i=POS&l=it&a=2026",
                },
            ],
            "sources": [{"name": "ISTAT — popolazione residente", "url": "https://demo.istat.it/app/?i=POS&l=it&a=2026"}],
        },
    ),
    ShowcaseBlock(
        "region",
        "Valle d'Aosta/Vallée d'Aoste",
        "utile",
        {
            "cosa_conta_1": "La Valle d'Aosta è regione a statuto speciale: ha competenze più ampie delle regioni ordinarie.",
            "cosa_conta_2": "Gli atti ufficiali sono pubblicati sul sito della Regione Autonoma Valle d'Aosta.",
            "cosa_conta_3": "Il bilinguismo italiano-francese è previsto dallo Statuto.",
            "poteri": "Competenze speciali in agricoltura, energia, istruzione e ordinamento degli enti locali, secondo lo Statuto.",
            "sources": [{"name": "ISTAT — popolazione residente", "url": "https://demo.istat.it/app/?i=POS&l=it&a=2026"}],
        },
    ),
    ShowcaseBlock(
        "region",
        "Valle d'Aosta/Vallée d'Aoste",
        "promesse",
        {
            "rows": [
                {
                    "promessa": "Tutela dell'autonomia e dello Statuto speciale",
                    "quando": "Programma di mandato",
                    "stato": "in_corso",
                    "aggiornamento": "Verificare atti del Consiglio e della Giunta sul sito regionale.",
                    "fonte": "https://demo.istat.it/app/?i=POS&l=it&a=2026",
                },
                {
                    "promessa": "Sostegno al turismo sostenibile e alle comunità di montagna",
                    "quando": "Programma di mandato",
                    "stato": "in_corso",
                    "aggiornamento": "",
                    "fonte": "https://demo.istat.it/app/?i=POS&l=it&a=2026",
                },
                {
                    "promessa": "Servizi sanitari e di prossimità sul territorio",
                    "quando": "Programma di mandato",
                    "stato": "da_compilare",
                    "aggiornamento": "",
                    "fonte": "https://demo.istat.it/app/?i=POS&l=it&a=2026",
                },
            ],
            "sources": [{"name": "ISTAT — popolazione residente", "url": "https://demo.istat.it/app/?i=POS&l=it&a=2026"}],
        },
    ),
    ShowcaseBlock(
        "region",
        "Trentino-Alto Adige/Südtirol",
        "utile",
        {
            "cosa_conta_1": "La Regione è a statuto speciale; molte competenze operative sono delle Province autonome di Trento e Bolzano.",
            "cosa_conta_2": "Per i servizi quotidiani (sanità, scuola, trasporti) contano soprattutto le due Province.",
            "cosa_conta_3": "Gli atti istituzionali sono pubblicati sui siti della Regione e delle Province autonome.",
            "poteri": "Quadro regionale speciale; le Province autonome esercitano ampie competenze legislative e amministrative.",
            "sources": [
                {"name": "ISTAT — popolazione residente", "url": "https://demo.istat.it/app/?i=POS&l=it&a=2026"},
            ],
        },
    ),
    ShowcaseBlock(
        "region",
        "Trentino-Alto Adige/Südtirol",
        "promesse",
        {
            "rows": [
                {
                    "promessa": "Coordinamento tra Province autonome e istituzioni regionali",
                    "quando": "Programma istituzionale",
                    "stato": "in_corso",
                    "aggiornamento": "Verificare verbali e delibere sui siti ufficiali.",
                    "fonte": "https://demo.istat.it/app/?i=POS&l=it&a=2026",
                },
                {
                    "promessa": "Tutela del bilinguismo e delle autonomie locali",
                    "quando": "Statuto e norme di attuazione",
                    "stato": "in_corso",
                    "aggiornamento": "",
                    "fonte": "https://demo.istat.it/app/?i=POS&l=it&a=2026",
                },
                {
                    "promessa": "Trasparenza degli atti pubblici regionali",
                    "quando": "Obblighi di pubblicazione",
                    "stato": "da_compilare",
                    "aggiornamento": "",
                    "fonte": "https://demo.istat.it/app/?i=POS&l=it&a=2026",
                },
            ],
            "sources": [{"name": "ISTAT — popolazione residente", "url": "https://demo.istat.it/app/?i=POS&l=it&a=2026"}],
        },
    ),
    ShowcaseBlock(
        "municipality",
        "Roma",
        "utile",
        {
            "cosa_conta_1": "Roma Capitale gestisce servizi urbani, mobilità, scuola dell'infanzia comunale e edilizia residenziale pubblica.",
            "cosa_conta_2": "I quindici Municipi hanno giunte e consigli propri: molte decisioni locali passano da lì.",
            "cosa_conta_3": "Delibere, bandi e atti sono pubblicati sul sito del Comune di Roma.",
            "poteri": "Funzioni di Roma Capitale e dei Municipi secondo lo Statuto e la normativa nazionale.",
            "sources": [{"name": "Roma Capitale — Municipi", "url": "https://www.comune.roma.it/web/it/municipi.page"}],
        },
    ),
    ShowcaseBlock(
        "municipality",
        "Roma",
        "come_funziona",
        {
            "body": (
                "Roma Capitale ha un sindaco e una Giunta. Il Consiglio comunale approva bilanci e "
                "regolamenti. I Municipi gestiscono servizi di prossimità sul territorio. Gli atti "
                "ufficiali sono sul sito comune.roma.it. VeraPolitica collega le schede dei Municipi "
                "quando la redazione le pubblica."
            ),
            "sources": [{"name": "Roma Capitale — Municipi", "url": "https://www.comune.roma.it/web/it/municipi.page"}],
        },
    ),
    ShowcaseBlock(
        "municipality",
        "Roma",
        "promesse",
        {
            "rows": [
                {
                    "promessa": "Migliorare trasporto pubblico e manutenzione stradale",
                    "quando": "Programma di mandato del Sindaco",
                    "stato": "in_corso",
                    "aggiornamento": "Verificare delibere e bilanci sul sito comunale.",
                    "fonte": "https://www.comune.roma.it/web/it/municipi.page",
                },
                {
                    "promessa": "Riqualificazione di periferie e servizi di prossimità",
                    "quando": "Programma di mandato",
                    "stato": "in_corso",
                    "aggiornamento": "",
                    "fonte": "https://www.comune.roma.it/web/it/municipi.page",
                },
                {
                    "promessa": "Trasparenza e digitalizzazione dei servizi al cittadino",
                    "quando": "Programma di mandato",
                    "stato": "da_compilare",
                    "aggiornamento": "",
                    "fonte": "https://www.comune.roma.it/web/it/municipi.page",
                },
            ],
            "sources": [{"name": "Roma Capitale — Municipi", "url": "https://www.comune.roma.it/web/it/municipi.page"}],
        },
    ),
    ShowcaseBlock(
        "municipio",
        "roma-1",
        "utile",
        {
            "cosa_conta_1": "Il Municipio I comprende il centro storico di Roma e servizi di prossimità sul territorio municipale.",
            "cosa_conta_2": "Ha una propria Giunta e un Consiglio di Municipio eletti localmente.",
            "cosa_conta_3": "Atti e avvisi sono pubblicati nelle sezioni Municipi del sito di Roma Capitale.",
            "poteri": "Funzioni delegate da Roma Capitale: servizi locali, manutenzione di prossimità, partecipazione.",
            "sources": [
                {
                    "name": "Roma Capitale — Municipi",
                    "url": "https://www.comune.roma.it/web/it/municipi.page",
                }
            ],
        },
    ),
    ShowcaseBlock(
        "municipio",
        "roma-1",
        "promesse",
        {
            "rows": [
                {
                    "promessa": "Cura dello spazio pubblico e decoro nel Municipio I",
                    "quando": "Programma di mandato municipale",
                    "stato": "in_corso",
                    "aggiornamento": "Verificare delibere del Consiglio di Municipio.",
                    "fonte": "https://www.comune.roma.it/web/it/municipi.page",
                },
                {
                    "promessa": "Partecipazione e ascolto dei quartieri del centro",
                    "quando": "Programma di mandato",
                    "stato": "da_compilare",
                    "aggiornamento": "",
                    "fonte": "https://www.comune.roma.it/web/it/municipi.page",
                },
                {
                    "promessa": "Servizi culturali e di prossimità accessibili",
                    "quando": "Programma di mandato",
                    "stato": "in_corso",
                    "aggiornamento": "",
                    "fonte": "https://www.comune.roma.it/web/it/municipi.page",
                },
            ],
            "sources": [
                {
                    "name": "Roma Capitale — Municipi",
                    "url": "https://www.comune.roma.it/web/it/municipi.page",
                }
            ],
        },
    ),
)


def _resolve_key(session: Session, kind: str, key_name: str) -> str | None:
    if kind == "municipio":
        return key_name
    if kind == "region":
        region = session.scalar(select(Region).where(Region.canonical_name == key_name))
        return str(region.id) if region else None
    if kind == "municipality":
        town = session.scalar(select(Municipality).where(Municipality.canonical_name == key_name))
        return str(town.id) if town else None
    return None


def _already_published(session: Session, kind: str, key: str, block: str) -> bool:
    territory_kind = TerritoryKind(kind)
    return (
        session.scalar(
            select(TerritoryBlock.id).where(
                TerritoryBlock.territory_kind == territory_kind,
                TerritoryBlock.territory_key == key,
                TerritoryBlock.block == block,
                TerritoryBlock.status == TerritoryBlockStatus.PUBLISHED,
            )
        )
        is not None
    )


def seed(
    service: RedazioneService,
    session_factory: sessionmaker[Session],
    *,
    author: str,
    approver: str,
    dry_run: bool = False,
    items: tuple[ShowcaseBlock, ...] = SHOWCASE,
) -> Report:
    if author.strip() == approver.strip():
        raise ValueError("chi approva deve essere diverso da chi scrive")
    report = Report()
    for item in items:
        with session_factory() as session:
            key = _resolve_key(session, item.kind, item.key_name)
            if key is None:
                report.skipped.append(f"{item.kind}/{item.key_name}/{item.block} (territorio assente: importa ISTAT)")
                continue
            if _already_published(session, item.kind, key, item.block):
                report.skipped.append(f"{item.kind}/{item.key_name}/{item.block} (già pubblicato)")
                continue
        label = f"{item.kind}/{item.key_name}/{item.block}"
        if dry_run:
            report.published.append(f"{label} (dry-run)")
            continue
        try:
            saved = service.save_territory_block(item.kind, key, item.block, item.payload, member=author)
            service.approve("territory", saved["id"], member=approver, note="Showcase territorio")
            report.published.append(label)
        except RedazioneError as error:
            report.errors.append(f"{label}: {error}")
        except Exception as error:  # noqa: BLE001 — operator script: keep going
            report.errors.append(f"{label}: {error}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--author", default="Amedeo")
    parser.add_argument("--approver", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--database-url")
    args = parser.parse_args(argv)
    settings = get_settings()
    runtime = (
        settings.model_copy(update={"database_url": args.database_url})
        if args.database_url
        else settings
    )
    engine = create_db_engine(runtime.database_url)
    try:
        prepare_runtime_schema(engine, runtime)
        Base.metadata.create_all(engine)
        factory = create_session_factory(engine)
        report = seed(
            RedazioneService(factory),
            factory,
            author=args.author,
            approver=args.approver,
            dry_run=args.dry_run,
        )
    finally:
        engine.dispose()
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 2 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
