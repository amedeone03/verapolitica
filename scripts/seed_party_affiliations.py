"""Put explicit party affiliations on published schede.

Parliamentary groups are not parties. Registrati lists the redazione catalog.
This writes ``PoliticalPartyAffiliation`` rows so the public scheda can show
the party next to the person. It only uses people who already have an official
source identifier, a stored raw document, and a party already in the catalog
(from ``seed_government_parties``).

    python -m scripts.seed_party_affiliations

Does not invent source URLs. Idempotent.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    PoliticalParty,
    PoliticalPartySourceIdentifier,
    Politician,
    PoliticianSourceIdentifier,
    RawDocument,
)
from backend.app.schemas import PoliticalPartyObservation
from backend.app.services import PoliticalPartyService, normalize_person_name


@dataclass(frozen=True)
class AffiliationSpec:
    given_name: str
    family_name: str
    party_name: str
    source_field: str
    aliases: tuple[tuple[str, str], ...] = ()


SPECS = (
    AffiliationSpec("Giorgia", "Meloni", "Fratelli d'Italia", "scheda.partito_esplicito"),
    AffiliationSpec(
        "Elly",
        "Schlein",
        "Partito Democratico",
        "scheda.partito_esplicito",
        aliases=(("Elena Ethel", "Schlein"), ("Elena", "Schlein")),
    ),
    AffiliationSpec("Giuseppe", "Conte", "Movimento 5 Stelle", "scheda.partito_esplicito"),
)


@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _published(
    session: Session, given: str, family: str, aliases: tuple[tuple[str, str], ...] = ()
) -> Politician | None:
    for first, last in ((given, family), *aliases):
        found = session.scalar(
            select(Politician).where(
                Politician.normalized_name == normalize_person_name(first, last),
                Politician.current_version_id.is_not(None),
            )
        )
        if found is not None:
            return found
    return None


def _party(session: Session, name: str) -> PoliticalParty | None:
    folded = name.casefold()
    return session.scalar(
        select(PoliticalParty).where(func.lower(PoliticalParty.canonical_name) == folded)
    )


def _identifier(
    session: Session, politician_id: int
) -> PoliticianSourceIdentifier | None:
    return session.scalar(
        select(PoliticianSourceIdentifier)
        .where(PoliticianSourceIdentifier.politician_id == politician_id)
        .order_by(PoliticianSourceIdentifier.id)
    )


def _raw_document(session: Session, source_id: int) -> RawDocument | None:
    return session.scalar(
        select(RawDocument)
        .where(RawDocument.source_id == source_id)
        .order_by(RawDocument.id.desc())
    )


def _ensure_party_identifier(
    session: Session, *, source_id: int, party: PoliticalParty
) -> str:
    value = party.official_website_url or f"catalog:{party.id}"
    existing = session.scalar(
        select(PoliticalPartySourceIdentifier).where(
            PoliticalPartySourceIdentifier.source_id == source_id,
            PoliticalPartySourceIdentifier.value == value,
        )
    )
    if existing is None:
        session.add(
            PoliticalPartySourceIdentifier(
                political_party_id=party.id,
                source_id=source_id,
                value=value,
            )
        )
        session.flush()
    return value


def seed(
    session_factory: sessionmaker[Session],
    *,
    specs: tuple[AffiliationSpec, ...] = SPECS,
) -> Report:
    report = Report()
    observations: list[PoliticalPartyObservation] = []
    labels: list[str] = []
    with session_factory() as session:
        for spec in specs:
            label = f"{spec.given_name} {spec.family_name} → {spec.party_name}"
            politician = _published(
                session, spec.given_name, spec.family_name, spec.aliases
            )
            if politician is None:
                report.skipped.append(f"{label} (scheda pubblica assente)")
                continue
            party = _party(session, spec.party_name)
            if party is None:
                report.skipped.append(
                    f"{label} (partito assente: esegui seed_government_parties)"
                )
                continue
            identifier = _identifier(session, politician.id)
            if identifier is None:
                report.skipped.append(f"{label} (nessun identificativo ufficiale)")
                continue
            document = _raw_document(session, identifier.source_id)
            if document is None:
                report.skipped.append(f"{label} (nessun documento grezzo della fonte)")
                continue
            source_key = identifier.source.key
            source_id = identifier.source_id
            identifier_value = identifier.value
            document_id = document.id
            document_url = document.source_url
            party_name = party.canonical_name
            party_abbreviation = party.abbreviation
            party_website = party.official_website_url
            party_key = _ensure_party_identifier(
                session, source_id=source_id, party=party
            )
            session.commit()
            source_url = identifier_value
            if not str(source_url).startswith("http"):
                source_url = party_website or document_url
            if not str(source_url).startswith("http"):
                report.skipped.append(f"{label} (nessun URL ufficiale da citare)")
                continue
            observations.append(
                PoliticalPartyObservation(
                    source_key=source_key,
                    raw_document_id=document_id,
                    politician_source_identifier=identifier_value,
                    party_source_identifier=party_key,
                    party_name=party_name,
                    abbreviation=party_abbreviation,
                    official_website_url=party_website,
                    affiliation_type="member",
                    source_url=source_url,
                    source_field=spec.source_field,
                )
            )
            labels.append(label)

    if not observations:
        return report
    result = PoliticalPartyService(session_factory).sync(tuple(observations))
    for detail, label in zip(result.details, labels, strict=True):
        status = detail.status.value
        if status == "unresolved_politician":
            report.unresolved.append(label)
        elif status == "created":
            report.created.append(label)
        else:
            report.skipped.append(f"{label} (già presente)")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
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
        report = seed(create_session_factory(engine))
    finally:
        engine.dispose()
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 2 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
