"""Shared seed data for pledge service and API tests."""

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    DocumentChunk,
    PoliticalParty,
    Politician,
    PoliticianVersion,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalActorType,
    ProposalType,
    RawDocument,
    RawDocumentStatus,
    Source,
)

NOW = datetime(2026, 10, 7, 9, tzinfo=timezone.utc)

ACT_TEXT = (
    "Il Senato ha approvato in via definitiva la legge che aumenta le pensioni "
    "minime a 1.000 euro mensili a decorrere dal 1 gennaio 2026."
)
NOISE_TEXT = "Calendario dei lavori della commissione agricoltura per il mese di marzo."


@dataclass(frozen=True)
class Seed:
    source_id: int
    raw_document_id: int
    chunk_id: int
    noise_chunk_id: int
    politician_id: int
    party_id: int
    pledge_id: int
    outcome_pledge_id: int
    unpublished_id: int
    bill_id: int


def _proposal(session: Session, title: str, statement: str | None, *, kind, published=True) -> Proposal:
    proposal = Proposal(
        canonical_title=title,
        exact_statement=statement,
        proposal_type=kind,
        published_at=NOW if published else None,
    )
    session.add(proposal)
    session.flush()
    return proposal


def _owner(session: Session, proposal: Proposal, politician: Politician, party: PoliticalParty) -> None:
    session.add_all(
        [
            ProposalActor(
                proposal_id=proposal.id,
                actor_type=ProposalActorType.POLITICIAN,
                role=ProposalActorRole.COMMITMENT_OWNER,
                politician_id=politician.id,
                display_name="Mario Rossi",
                identity_key=f"pol-{proposal.id}",
            ),
            ProposalActor(
                proposal_id=proposal.id,
                actor_type=ProposalActorType.POLITICAL_PARTY,
                role=ProposalActorRole.COMMITMENT_OWNER,
                political_party_id=party.id,
                display_name="Partito Esempio",
                identity_key=f"party-{proposal.id}",
            ),
        ]
    )


def seed(session_factory: sessionmaker[Session], *, publish_politician: bool = True) -> Seed:
    with session_factory() as session:
        source = Source(key="senato-repubblica", name="Senato", base_url="https://dati.senato.it")
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=NOW,
            source_url="https://www.senato.it/legge/1",
            content_type="text/html",
            storage_key="act.html",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[],
            normalized_text=f"{ACT_TEXT}\n\n{NOISE_TEXT}",
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="v1",
            parser_version="v1",
        )
        session.add(document)
        session.flush()
        chunk = DocumentChunk(
            raw_document_id=document.id, chunk_index=0, text=ACT_TEXT, chunk_hash="c" * 64
        )
        noise = DocumentChunk(
            raw_document_id=document.id, chunk_index=1, text=NOISE_TEXT, chunk_hash="d" * 64
        )
        session.add_all([chunk, noise])
        politician = Politician(
            canonical_given_name="Mario",
            canonical_family_name="Rossi",
            normalized_name="mario rossi",
            birth_date=date(1970, 1, 1),
        )
        party = PoliticalParty(canonical_name="Partito Esempio")
        session.add_all([politician, party])
        session.flush()
        if publish_politician:
            version = PoliticianVersion(
                politician_id=politician.id,
                version_number=1,
                profile_schema_version=1,
                profile_data={"given_name": "Mario", "family_name": "Rossi", "mandates": []},
                published_at=NOW,
            )
            session.add(version)
            session.flush()
            politician.current_version = version

        pledge = _proposal(
            session,
            "Aumentare le pensioni minime",
            "Aumenteremo le pensioni minime a 1.000 euro al mese.",
            kind=ProposalType.EXPLICIT_PROMISE,
        )
        outcome = _proposal(
            session,
            "Ridurre la disoccupazione giovanile",
            "Ridurremo la disoccupazione giovanile sotto il 15%.",
            kind=ProposalType.EXPLICIT_PROMISE,
        )
        unpublished = _proposal(
            session, "Bozza", "Faremo qualcosa.", kind=ProposalType.EXPLICIT_PROMISE, published=False
        )
        bill = _proposal(session, "DDL 123", None, kind=ProposalType.LEGISLATIVE_PROPOSAL)
        for item in (pledge, outcome, unpublished):
            _owner(session, item, politician, party)
        session.commit()
        return Seed(
            source_id=source.id,
            raw_document_id=document.id,
            chunk_id=chunk.id,
            noise_chunk_id=noise.id,
            politician_id=politician.id,
            party_id=party.id,
            pledge_id=pledge.id,
            outcome_pledge_id=outcome.id,
            unpublished_id=unpublished.id,
            bill_id=bill.id,
        )


def add_extra_pledges(
    session_factory: sessionmaker[Session], seed_data: Seed, count: int
) -> list[int]:
    ids = []
    with session_factory() as session:
        politician = session.get(Politician, seed_data.politician_id)
        party = session.get(PoliticalParty, seed_data.party_id)
        for index in range(count):
            proposal = _proposal(
                session,
                f"Impegno numero {index}",
                f"Approveremo la legge numero {index}.",
                kind=ProposalType.EXPLICIT_PROMISE,
            )
            _owner(session, proposal, politician, party)
            ids.append(proposal.id)
        session.commit()
    return ids
