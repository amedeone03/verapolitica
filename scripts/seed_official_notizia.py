"""Publish one four-eyes political news item from URLs already in the repo.

This is a Modello Notizia card, not a pubblicazione ufficiale: it needs an
institutional page plus one centrodestra and one centrosinistra article.
Every URL is copied from the Meloni / Conte reference fixtures.

    python -m scripts.seed_official_notizia --author "Amedeo" --approver "Verificatore"

Does not invent newspaper URLs. Idempotent: the same institutional page is
not published twice.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.services.redazione.service import RedazioneError, RedazioneService
from scripts.seed_official_feed import _known_urls, _published_id


AUTHOR_DEFAULT = "Sincronizzazione notizia ufficiale"

INSTITUTIONAL_URL = "https://www.senato.it/show-doc?id=1361012&leg=19&tipodoc=Resaula"
CENTRODESTRA_URL = "https://tg24.sky.it/politica/2025/10/18/manovra-meloni"
CENTROSINISTRA_URL = (
    "https://www.ilfattoquotidiano.it/2024/01/29/"
    "ius-soli-giuseppe-conte-a-che-tempo-che-fa-non-sono-favorevole-"
    "serve-lo-ius-scholae-e-lo-ius-culturae/7425636/"
)

TITLE = "Il Senato pubblica le dichiarazioni programmatiche del Governo"

BLOCKS = {
    "sommario": (
        "Il 25 ottobre 2022 Giorgia Meloni ha illustrato al Senato le dichiarazioni "
        "programmatiche del Governo. Il resoconto stenografico è pubblicato sul sito "
        "del Senato. VeraPolitica riporta quel documento ufficiale e due articoli di "
        "stampa già presenti in archivio, senza aggiungere fatti assenti da quelle pagine."
    ),
    "perche": (
        "Quel resoconto è la fonte ufficiale delle promesse di inizio mandato. Senza "
        "quella pagina le schede pubbliche non avrebbero un testo da citare. La stampa "
        "successiva ha discusso singoli punti del programma: la manovra economica e le "
        "regole di cittadinanza. Mettere accanto il documento e due articoli già "
        "archiviati permette di vedere cosa è stato dichiarato e come è stato raccontato."
    ),
    "fatto": (
        "Il Senato della Repubblica pubblica il resoconto stenografico delle "
        "dichiarazioni programmatiche rese dalla presidente del Consiglio Giorgia Meloni "
        "il 25 ottobre 2022. Il documento, alla pagina show-doc del Senato per la "
        "diciannovesima legislatura, riporta il testo letto in Aula e le promesse di "
        "inizio mandato, tra cui la sostituzione del Reddito di cittadinanza. "
        "VeraPolitica usa quella pagina come fonte istituzionale della scheda e della "
        "promessa pubblicata, senza aggiungere incarichi o impegni assenti dal resoconto. "
        "La data e il testo restano quelli del Senato."
    ),
    "cosa_cambia": (
        "Chi apre VeraPolitica trova le dichiarazioni programmatiche collegate al "
        "resoconto ufficiale, non a un riassunto senza fonte. La scheda di Giorgia Meloni "
        "cita quella pagina per la promessa sul reddito di cittadinanza. Un aggiornamento "
        "del resoconto sul sito del Senato è la base per un aggiornamento successivo. "
        "Gli articoli di stampa collegati restano quelli già presenti nelle schede di "
        "riferimento: Sky TG24 sulla manovra e Il Fatto Quotidiano su una dichiarazione "
        "di Giuseppe Conte in materia di cittadinanza."
    ),
    "destra": (
        "Sky TG24, il 18 ottobre 2025, ha pubblicato un articolo sulla manovra presentata "
        "dal Governo Meloni. Il pezzo, già citato nella scheda di riferimento, riguarda "
        "la legge di bilancio e le scelte di finanza pubblica successive alle "
        "dichiarazioni del 2022. VeraPolitica riporta il titolo e il link di quella "
        "pagina, senza attribuire a Sky giudizi assenti dall'articolo."
    ),
    "sinistra": (
        "Il Fatto Quotidiano, il 29 gennaio 2024, ha pubblicato le dichiarazioni di "
        "Giuseppe Conte a Che tempo che fa sulla cittadinanza: non favorevole allo ius "
        "soli, favorevole allo ius scholae e allo ius culturae. L'articolo è già in "
        "archivio nella scheda di Conte. VeraPolitica lo cita come voce di opposizione "
        "su un tema istituzionale, senza estendere il testo oltre quella pagina."
    ),
    "altri": (
        "Nessun'altra testata viene aggiunta qui. Le uniche pagine usate sono il "
        "resoconto del Senato e i due articoli già presenti nelle schede di riferimento."
    ),
    "numeri": (
        "Il resoconto è del 25 ottobre 2022, legislatura 19. L'articolo di Sky è del "
        "18 ottobre 2025. L'articolo de Il Fatto Quotidiano è del 29 gennaio 2024. "
        "Tre date, tre URL, nessuno stralcio inventato."
    ),
    "cosa_succede": (
        "La redazione può aggiornare la scheda se il Senato pubblica un nuovo resoconto "
        "o se arriva uno stralcio ufficiale per lo stato di una promessa. La stampa "
        "resta citata solo se il link è già in archivio."
    ),
}


@dataclass
class Report:
    published: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def seed(
    service: RedazioneService,
    session_factory: sessionmaker[Session],
    *,
    author: str,
    approver: str,
) -> Report:
    if author.strip() == approver.strip():
        raise ValueError("chi approva deve essere diverso da chi scrive")
    report = Report()
    with session_factory() as session:
        already = _known_urls(session)
    if INSTITUTIONAL_URL in already:
        report.skipped.append(f"{TITLE} (fonte già in una notizia)")
        return report
    politician_ids = [
        politician_id
        for politician_id in (
            _published_id(session_factory, "Giorgia", "Meloni"),
            _published_id(session_factory, "Giuseppe", "Conte"),
        )
        if politician_id is not None
    ]
    payload = {
        "title": TITLE,
        "scope": "national",
        "blocks": BLOCKS,
        "sources": [
            {
                "name": "Senato della Repubblica",
                "url": INSTITUTIONAL_URL,
                "date": "2022-10-25",
                "area": "istituzionale",
            },
            {
                "name": "Sky TG24",
                "url": CENTRODESTRA_URL,
                "date": "2025-10-18",
                "area": "centrodestra",
            },
            {
                "name": "Il Fatto Quotidiano",
                "url": CENTROSINISTRA_URL,
                "date": "2024-01-29",
                "area": "centrosinistra",
            },
        ],
        "politician_ids": politician_ids,
        "card": {
            "category": "notizia",
            "badge": {"label": "Aggiornamento", "tone": "navy", "date": "2022-10-25"},
            "aside": "Dichiarazioni programmatiche",
            "people": [
                {"politician_id": politician_id, "use_portrait": True}
                for politician_id in politician_ids
            ],
            "institution": "Senato della Repubblica",
            "link": {"label": "Resoconto sul sito del Senato", "url": INSTITUTIONAL_URL},
        },
    }
    try:
        created = service.save_news(payload, member=author)
        service.approve(
            "news",
            created["id"],
            member=approver,
            note="Tre fonti già in archivio: resoconto Senato, Sky TG24, Il Fatto Quotidiano.",
        )
        report.published.append(TITLE)
    except RedazioneError as error:
        report.errors.append(f"{TITLE} ({error})")
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
