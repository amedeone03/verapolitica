"""Assign the Reddito di cittadinanza verdict from the Gazzetta excerpt.

Uses the verbatim sentence stored in
``data/fixtures/pledge_evidence/legge_85_2023_assegno_inclusione.html``.
Goes through RedazioneService.propose_status (author ≠ approver). Does not
invent the excerpt.

    python -m scripts.seed_rdc_verdict --author "Amedeo" --approver "Verificatore"

Idempotent: skipped if that promise already has a published assessment.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import Politician, Proposal, ProposalActor, ProposalActorRole
from backend.app.models.pledge import PledgeAssessment
from backend.app.services.matching_service import normalize_person_name
from backend.app.services.redazione.service import RedazioneError, RedazioneService


AUTHOR_DEFAULT = "Sincronizzazione stato RDC"
PROMISE_TITLE = "Abolire e sostituire il Reddito di cittadinanza"
GU_URL = "https://www.gazzettaufficiale.it/eli/id/2023/07/03/23G00087/sg"
EXCERPT = (
    "E' istituito l'Assegno di inclusione, quale misura nazionale di contrasto "
    "alla poverta', alla fragilita' e all'esclusione sociale"
)
RATIONALE = (
    "Con la legge 3 luglio 2023, n. 85, pubblicata in Gazzetta Ufficiale, "
    "è istituito l'Assegno di inclusione in sostituzione del Reddito di "
    "cittadinanza. Lo stralcio è copiato dal testo ufficiale già in archivio."
)
EVIDENCE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "fixtures"
    / "pledge_evidence"
    / "legge_85_2023_assegno_inclusione.html"
)


@dataclass
class Report:
    proposal_id: int | None = None
    published: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _published_promise(session: Session) -> Proposal | None:
    key = normalize_person_name("Giorgia", "Meloni")
    return session.scalar(
        select(Proposal)
        .join(ProposalActor, ProposalActor.proposal_id == Proposal.id)
        .join(Politician, Politician.id == ProposalActor.politician_id)
        .where(
            Politician.normalized_name == key,
            ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
            Proposal.canonical_title == PROMISE_TITLE,
            Proposal.published_at.is_not(None),
        )
    )


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
    if EXCERPT not in EVIDENCE.read_text(encoding="utf-8"):
        report.errors.append("stralcio assente dal file ufficiale in archivio")
        return report
    with session_factory() as session:
        proposal = _published_promise(session)
        if proposal is None:
            report.errors.append(
                "promessa RDC non trovata: esegui seed_meloni_showcase prima"
            )
            return report
        report.proposal_id = proposal.id
        if session.scalar(
            select(PledgeAssessment.id).where(
                PledgeAssessment.proposal_id == proposal.id
            )
        ):
            report.skipped.append("stato già pubblicato")
            return report
        proposal_id = proposal.id
    try:
        created = service.propose_status(
            proposal_id,
            {
                "verdict": "kept",
                "rationale": RATIONALE,
                "quoted_excerpt": EXCERPT,
                "effective_at": "2023-07-03",
                "source": {
                    "name": "Gazzetta Ufficiale — Legge 3 luglio 2023, n. 85",
                    "url": GU_URL,
                },
            },
            member=author,
        )
        service.approve(
            "status",
            created["draft_id"],
            member=approver,
            note="Stralcio verbatim della legge 85/2023 già in archivio.",
        )
        report.published.append("stato mantenuta (legge 85/2023)")
    except RedazioneError as error:
        report.errors.append(str(error))
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
