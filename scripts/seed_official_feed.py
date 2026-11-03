"""Put the first official-list cards on the public Home feed.

These are not political news analyses. Each card announces an official list
VeraPolitica already ingested (Governo, Camera, Senato) and cites that page
only. Another redazione member must approve, as with every other post.

    python -m scripts.seed_official_feed --author "Amedeo" --approver "Verificatore"

Does not invent newspaper URLs. Idempotent: the same official page is not
published twice.
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
from backend.app.models import EditorialPost, Politician
from backend.app.services.matching_service import normalize_person_name
from backend.app.services.redazione.service import RedazioneError, RedazioneService

AUTHOR_DEFAULT = "Sincronizzazione fonti ufficiali"


@dataclass(frozen=True)
class OfficialCard:
    title: str
    sommario: str
    fatto: str
    cosa_cambia: str
    source_name: str
    source_url: str
    source_date: str
    institution: str
    link_label: str
    badge_date: str
    people: tuple[tuple[str, str], ...] = ()


CARDS = (
    OfficialCard(
        title="Pubblicato l'elenco dei titolari del Governo in carica",
        sommario=(
            "La Presidenza del Consiglio pubblica l'elenco dei vicepresidenti, "
            "dei ministri e dei sottosegretari in carica, con la scheda di ciascun titolare."
        ),
        fatto=(
            "Sul sito governo.it, alla pagina «Vice Presidenti, Ministri e Sottosegretari», "
            "è consultabile l'elenco ufficiale dei titolari del Governo in carica. Ogni nome "
            "rimanda alla scheda istituzionale della persona e all'incarico indicato da "
            "Palazzo Chigi. VeraPolitica ha ripreso quell'elenco come fonte ufficiale per le "
            "schede pubbliche, senza aggiungere incarichi non scritti sulla pagina."
        ),
        cosa_cambia=(
            "Chi consulta VeraPolitica trova i titolari del Governo collegati alla pagina "
            "ufficiale, non a un riassunto senza fonte. I nomi e gli uffici restano quelli "
            "pubblicati dalla Presidenza. Un aggiornamento dell'elenco su governo.it è la "
            "base per un aggiornamento successivo delle schede."
        ),
        source_name="Presidenza del Consiglio dei ministri",
        source_url="https://www.governo.it/it/ministri-e-sottosegretari",
        source_date="2022-10-22",
        institution="Presidenza del Consiglio dei Ministri",
        link_label="Elenco su governo.it",
        badge_date="2022-10-22",
        people=(("Giorgia", "Meloni"),),
    ),
    OfficialCard(
        title="Pubblicato l'elenco dei deputati della XIX legislatura",
        sommario=(
            "La Camera dei deputati pubblica l'elenco dei deputati in carica nella "
            "diciannovesima legislatura."
        ),
        fatto=(
            "Sul sito della Camera, alla pagina «Elenco deputati» della legislatura 19, "
            "è consultabile l'elenco ufficiale delle persone elette. I dati aperti della "
            "Camera (dati.camera.it) riportano le stesse identità con identificativo, "
            "mandato e data di nascita. VeraPolitica ha importato quell'elenco ufficiale "
            "per le schede pubbliche dei deputati."
        ),
        cosa_cambia=(
            "Nell'app i deputati della legislatura in corso sono quelli dell'elenco della "
            "Camera, non una selezione di redazione. Chi manca da quella pagina non viene "
            "aggiunto qui. Un aggiornamento dell'elenco ufficiale è la base per un "
            "aggiornamento successivo."
        ),
        source_name="Camera dei deputati",
        source_url="https://www.camera.it/leg19/28",
        source_date="2022-10-13",
        institution="Camera dei deputati",
        link_label="Elenco su camera.it",
        badge_date="2022-10-13",
    ),
    OfficialCard(
        title="Pubblicato l'elenco dei senatori della XIX legislatura",
        sommario=(
            "Il Senato della Repubblica pubblica i dati aperti dei senatori in carica "
            "nella diciannovesima legislatura."
        ),
        fatto=(
            "Il portale dati.senato.it espone l'ontologia e il punto SPARQL da cui si "
            "leggono identità, mandato e data di nascita dei senatori. VeraPolitica ha "
            "importato quell'elenco ufficiale per le schede pubbliche, senza inventare "
            "incarichi o date non presenti nei dati del Senato."
        ),
        cosa_cambia=(
            "Nell'app i senatori della legislatura in corso sono quelli dei dati aperti "
            "del Senato. Chi non è in quell'elenco non viene aggiunto. Un aggiornamento "
            "del portale ufficiale è la base per un aggiornamento successivo delle schede."
        ),
        source_name="Senato della Repubblica",
        source_url="https://dati.senato.it/sito/21",
        source_date="2022-10-13",
        institution="Senato della Repubblica",
        link_label="Dati aperti del Senato",
        badge_date="2022-10-13",
    ),
)


@dataclass
class Report:
    published: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _known_urls(session: Session) -> set[str]:
    urls: set[str] = set()
    for post in session.scalars(select(EditorialPost)):
        for item in post.citations or []:
            if item.get("url"):
                urls.add(item["url"])
        for item in (post.blocks or {}).get("fonti") or []:
            if item.get("url"):
                urls.add(item["url"])
    return urls


def _published_id(
    session_factory: sessionmaker[Session],
    given_name: str,
    family_name: str,
) -> int | None:
    key = normalize_person_name(given_name, family_name)
    with session_factory() as session:
        return session.scalar(
            select(Politician.id).where(
                Politician.normalized_name == key,
                Politician.current_version_id.is_not(None),
            )
        )


def seed(
    service: RedazioneService,
    session_factory: sessionmaker[Session],
    *,
    author: str,
    approver: str,
    cards: tuple[OfficialCard, ...] = CARDS,
) -> Report:
    if author.strip() == approver.strip():
        raise ValueError("chi approva deve essere diverso da chi scrive")
    report = Report()
    with session_factory() as session:
        already = _known_urls(session)
    for card in cards:
        if card.source_url in already:
            report.skipped.append(f"{card.title} (fonte già in una notizia)")
            continue
        people = []
        politician_ids = []
        for given, family in card.people:
            politician_id = _published_id(session_factory, given, family)
            if politician_id is None:
                continue
            people.append({"politician_id": politician_id, "use_portrait": True})
            politician_ids.append(politician_id)
        payload = {
            "title": card.title,
            "scope": "national",
            "blocks": {
                "sommario": card.sommario,
                "fatto": card.fatto,
                "cosa_cambia": card.cosa_cambia,
            },
            "sources": [
                {
                    "name": card.source_name,
                    "url": card.source_url,
                    "date": card.source_date,
                    "area": "istituzionale",
                }
            ],
            "politician_ids": politician_ids,
            "card": {
                "category": "pubblicazione",
                "badge": {
                    "label": "Nuova pubblicazione",
                    "tone": "navy",
                    "date": card.badge_date,
                },
                "aside": "Elenco ufficiale",
                "people": people,
                "institution": card.institution,
                "link": {"label": card.link_label, "url": card.source_url},
            },
        }
        try:
            created = service.save_news(payload, member=author)
            service.approve(
                "news",
                created["id"],
                member=approver,
                note="Elenco ufficiale già importato; nessun articolo di stampa inventato.",
            )
            report.published.append(card.title)
            already.add(card.source_url)
        except RedazioneError as error:
            report.errors.append(f"{card.title} ({error})")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--author", default=AUTHOR_DEFAULT)
    parser.add_argument("--approver", required=True)
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
        )
    finally:
        engine.dispose()
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 2 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
