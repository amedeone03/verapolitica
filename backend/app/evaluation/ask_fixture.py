"""Self-contained published world for Ask VeraPolitica evaluation.

Never writes production data. IDs are assigned by the local SQLite schema and
exposed through stable keys used by the gold cases.
"""

from __future__ import annotations

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
from backend.app.models.pledge import PledgeAssessmentOrigin
from backend.app.schemas.pledge import (
    PledgeAssessmentProposal,
    PledgeClassificationRequest,
)
from backend.app.scoring.types import (
    CommitmentType,
    EvidenceLabel,
    FulfillmentVerdict,
    HolderRole,
    PledgeSpecificity,
)
from backend.app.services.pledge_service import NewAssessmentDraft, PledgeService


NOW = datetime(2026, 10, 7, 9, tzinfo=timezone.utc)
MANDATE_START = date(2022, 10, 13)
MANDATE_END = date(2027, 10, 13)

GAZETTA_AUTONOMIA = "https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg"
GAZETTA_SANITA = "https://www.gazzettaufficiale.it/eli/id/2024/09/01/24G00120/sg"
GAZETTA_FISCO = "https://www.gazzettaufficiale.it/eli/id/2024/05/02/24G00080/sg"
GAZETTA_CASA = "https://www.gazzettaufficiale.it/eli/id/2024/11/12/24G00140/sg"
SENATO_GIUSTIZIA = "https://www.senato.it/legge/giustizia"
SENATO_REDDITO = "https://www.senato.it/legge/reddito"
SENATO_PENSIONI = "https://www.senato.it/legge/1"


@dataclass(frozen=True, slots=True)
class AskEvalCatalog:
    politician_ids: dict[str, int]
    politician_names: dict[str, str]
    pledge_ids: dict[str, int]
    pledge_titles: dict[str, str]
    source_urls: dict[str, str]
    published_source_urls: tuple[str, ...]
    unpublished_titles: tuple[str, ...]


def _publish_politician(
    session: Session, given: str, family: str, *, published: bool
) -> Politician:
    politician = Politician(
        canonical_given_name=given,
        canonical_family_name=family,
        normalized_name=f"{given} {family}".casefold(),
        birth_date=date(1977, 1, 15),
    )
    session.add(politician)
    session.flush()
    if published:
        version = PoliticianVersion(
            politician_id=politician.id,
            version_number=1,
            profile_schema_version=1,
            profile_data={
                "given_name": given,
                "family_name": family,
                "mandates": [
                    {
                        "institution": "Governo",
                        "office": "presidente del consiglio",
                        "legislature": "Governo",
                    }
                ],
            },
            published_at=NOW,
        )
        session.add(version)
        session.flush()
        politician.current_version = version
    return politician


def _pledge(
    session: Session,
    title: str,
    statement: str,
    *,
    politician: Politician,
    party: PoliticalParty,
    published: bool = True,
) -> Proposal:
    proposal = Proposal(
        canonical_title=title,
        exact_statement=statement,
        proposal_type=ProposalType.EXPLICIT_PROMISE,
        published_at=NOW if published else None,
    )
    session.add(proposal)
    session.flush()
    session.add_all(
        [
            ProposalActor(
                proposal_id=proposal.id,
                actor_type=ProposalActorType.POLITICIAN,
                role=ProposalActorRole.COMMITMENT_OWNER,
                politician_id=politician.id,
                display_name=f"{politician.canonical_given_name} {politician.canonical_family_name}",
                identity_key=f"pol-{proposal.id}",
            ),
            ProposalActor(
                proposal_id=proposal.id,
                actor_type=ProposalActorType.POLITICAL_PARTY,
                role=ProposalActorRole.COMMITMENT_OWNER,
                political_party_id=party.id,
                display_name=party.canonical_name,
                identity_key=f"party-{proposal.id}",
            ),
        ]
    )
    return proposal


def _document(session: Session, source_id: int, url: str, text: str) -> tuple[int, int]:
    document = RawDocument(
        source_id=source_id,
        retrieved_at=NOW,
        source_url=url,
        content_type="text/html",
        storage_key=url.rsplit("/", 1)[-1],
        raw_sha256="a" * 64,
        normalized_sha256="b" * 64,
        structured_records=[],
        normalized_text=text,
        process_status=RawDocumentStatus.PARSED,
        change_detected=True,
        collector_version="eval",
        parser_version="eval",
    )
    session.add(document)
    session.flush()
    chunk = DocumentChunk(
        raw_document_id=document.id,
        chunk_index=0,
        text=text,
        chunk_hash=("c" + url)[:64].ljust(64, "0"),
    )
    session.add(chunk)
    session.flush()
    return document.id, chunk.id


def _classify(service: PledgeService, pledge_id: int, topic: str) -> None:
    service.classify(
        pledge_id,
        PledgeClassificationRequest(
            specificity=PledgeSpecificity.HIGH,
            commitment_type=CommitmentType.ACTION,
            holder_role=HolderRole.GOVERNMENT_COALITION,
            cap_topic_code=topic,
            mandate_start=MANDATE_START,
            mandate_end=MANDATE_END,
        ),
        classified_by="eval-editor",
    )


def _publish(
    service: PledgeService,
    pledge_id: int,
    verdict: FulfillmentVerdict,
    label: EvidenceLabel,
    *,
    rationale: str,
    excerpt: str,
    raw_document_id: int,
    chunk_id: int,
) -> None:
    draft, _ = service.propose(
        NewAssessmentDraft(
            proposal_id=pledge_id,
            proposal=PledgeAssessmentProposal(
                verdict=verdict,
                evidence_label=label,
                rationale=rationale,
                quoted_excerpt=excerpt,
                raw_document_id=raw_document_id,
                document_chunk_id=chunk_id,
            ),
            origin=PledgeAssessmentOrigin.EDITOR,
            created_by="eval-editor",
        )
    )
    reviewers = ("rev-1", "rev-2") if verdict is FulfillmentVerdict.BROKEN else ("rev",)
    for reviewer in reviewers:
        service.approve(draft.id, reviewer=reviewer)


def build_ask_eval_world(session_factory: sessionmaker[Session]) -> AskEvalCatalog:
    texts = {
        "autonomia": (
            GAZETTA_AUTONOMIA,
            "È stata pubblicata in Gazzetta Ufficiale la legge sull'autonomia differenziata.",
        ),
        "liste-attesa": (
            GAZETTA_SANITA,
            "Il decreto riduce i tempi delle liste di attesa nelle strutture pubbliche.",
        ),
        "tasse": (
            GAZETTA_FISCO,
            "La legge taglia il cuneo fiscale per i lavoratori dipendenti.",
        ),
        "giustizia": (
            SENATO_GIUSTIZIA,
            "Il disegno di legge sulla riforma della giustizia resta assegnato in commissione.",
        ),
        "reddito": (
            SENATO_REDDITO,
            "Il Parlamento ha abrogato la disciplina del reddito di cittadinanza.",
        ),
        "casa": (
            GAZETTA_CASA,
            "Il piano casa è stato adottato solo per una parte dei comuni previsti.",
        ),
        "pensioni": (
            SENATO_PENSIONI,
            "Il Senato ha approvato in via definitiva la legge che aumenta le pensioni minime.",
        ),
    }
    with session_factory() as session:
        source = Source(
            key="eval-official",
            name="Fonti ufficiali di valutazione",
            base_url="https://www.gazzettaufficiale.it",
        )
        session.add(source)
        party = PoliticalParty(canonical_name="Fratelli d'Italia")
        session.add(party)
        session.flush()

        meloni = _publish_politician(session, "Giorgia", "Meloni", published=True)
        mario = _publish_politician(session, "Mario", "Rossi", published=True)
        anna = _publish_politician(session, "Anna", "Rossi", published=True)
        _publish_politician(session, "Luca", "Bianchi", published=False)

        docs: dict[str, tuple[int, int, str, str]] = {}
        for key, (url, text) in texts.items():
            doc_id, chunk_id = _document(session, source.id, url, text)
            docs[key] = (doc_id, chunk_id, url, text)

        autonomia = _pledge(
            session,
            "Autonomia differenziata",
            "Approveremo la legge sull'autonomia differenziata.",
            politician=meloni,
            party=party,
        )
        liste = _pledge(
            session,
            "Ridurre le liste d'attesa",
            "Ridurremo i tempi delle liste d'attesa in sanità.",
            politician=meloni,
            party=party,
        )
        tasse = _pledge(
            session,
            "Taglio del cuneo fiscale",
            "Taglieremo il cuneo fiscale per i lavoratori.",
            politician=meloni,
            party=party,
        )
        giustizia = _pledge(
            session,
            "Riforma della giustizia",
            "Presenteremo una riforma della giustizia.",
            politician=meloni,
            party=party,
        )
        reddito = _pledge(
            session,
            "Superamento del reddito di cittadinanza",
            "Supereremo il reddito di cittadinanza.",
            politician=meloni,
            party=party,
        )
        casa = _pledge(
            session,
            "Piano casa nazionale",
            "Adotteremo un piano casa nazionale.",
            politician=meloni,
            party=party,
        )
        scuola = _pledge(
            session,
            "Nuove scuole dell'infanzia",
            "Costruiremo nuove scuole dell'infanzia.",
            politician=meloni,
            party=party,
        )
        pensioni = _pledge(
            session,
            "Aumentare le pensioni minime",
            "Aumenteremo le pensioni minime a 1.000 euro al mese.",
            politician=mario,
            party=party,
        )
        lavoro = _pledge(
            session,
            "Ridurre la disoccupazione giovanile",
            "Ridurremo la disoccupazione giovanile sotto il 15%.",
            politician=mario,
            party=party,
        )
        bozza = _pledge(
            session,
            "Bozza",
            "Faremo qualcosa di non pubblicato.",
            politician=meloni,
            party=party,
            published=False,
        )
        catalog = {
            "giorgia-meloni": meloni.id,
            "mario-rossi": mario.id,
            "anna-rossi": anna.id,
        }
        pledges = {
            "autonomia": autonomia.id,
            "liste-attesa": liste.id,
            "tasse": tasse.id,
            "giustizia": giustizia.id,
            "reddito": reddito.id,
            "casa": casa.id,
            "scuola": scuola.id,
            "pensioni": pensioni.id,
            "lavoro": lavoro.id,
            "bozza": bozza.id,
        }
        titles = {
            "autonomia": autonomia.canonical_title,
            "liste-attesa": liste.canonical_title,
            "tasse": tasse.canonical_title,
            "giustizia": giustizia.canonical_title,
            "reddito": reddito.canonical_title,
            "casa": casa.canonical_title,
            "scuola": scuola.canonical_title,
            "pensioni": pensioni.canonical_title,
            "lavoro": lavoro.canonical_title,
            "bozza": bozza.canonical_title,
        }
        session.commit()

    service = PledgeService(session_factory)
    _classify(service, pledges["autonomia"], "20")
    _classify(service, pledges["liste-attesa"], "3")
    _classify(service, pledges["tasse"], "1")
    _classify(service, pledges["giustizia"], "12")
    _classify(service, pledges["reddito"], "13")
    _classify(service, pledges["casa"], "14")
    _classify(service, pledges["scuola"], "6")
    _classify(service, pledges["pensioni"], "13")
    _classify(service, pledges["lavoro"], "5")

    _publish(
        service,
        pledges["autonomia"],
        FulfillmentVerdict.IN_PROGRESS,
        EvidenceLabel.SUPPORTS,
        rationale="È stato avviato un atto ufficiale, ma l'attuazione non è conclusa.",
        excerpt=texts["autonomia"][1],
        raw_document_id=docs["autonomia"][0],
        chunk_id=docs["autonomia"][1],
    )
    _publish(
        service,
        pledges["liste-attesa"],
        FulfillmentVerdict.IN_PROGRESS,
        EvidenceLabel.SUPPORTS,
        rationale="Un decreto ufficiale ha avviato la riduzione delle liste d'attesa.",
        excerpt=texts["liste-attesa"][1],
        raw_document_id=docs["liste-attesa"][0],
        chunk_id=docs["liste-attesa"][1],
    )
    _publish(
        service,
        pledges["tasse"],
        FulfillmentVerdict.KEPT,
        EvidenceLabel.SUPPORTS,
        rationale="La legge approvata realizza il taglio del cuneo fiscale.",
        excerpt=texts["tasse"][1],
        raw_document_id=docs["tasse"][0],
        chunk_id=docs["tasse"][1],
    )
    _publish(
        service,
        pledges["giustizia"],
        FulfillmentVerdict.STALLED,
        EvidenceLabel.REFUTES,
        rationale="Il testo resta fermo in commissione senza avanzamento.",
        excerpt=texts["giustizia"][1],
        raw_document_id=docs["giustizia"][0],
        chunk_id=docs["giustizia"][1],
    )
    _publish(
        service,
        pledges["reddito"],
        FulfillmentVerdict.BROKEN,
        EvidenceLabel.REFUTES,
        rationale="L'impegno dichiarato non corrisponde all'atto approvato.",
        excerpt=texts["reddito"][1],
        raw_document_id=docs["reddito"][0],
        chunk_id=docs["reddito"][1],
    )
    _publish(
        service,
        pledges["casa"],
        FulfillmentVerdict.PARTIALLY_KEPT,
        EvidenceLabel.SUPPORTS,
        rationale="Il piano è stato adottato solo in parte.",
        excerpt=texts["casa"][1],
        raw_document_id=docs["casa"][0],
        chunk_id=docs["casa"][1],
    )
    _publish(
        service,
        pledges["pensioni"],
        FulfillmentVerdict.IN_PROGRESS,
        EvidenceLabel.SUPPORTS,
        rationale="La legge è stata approvata e l'attuazione è in corso.",
        excerpt=texts["pensioni"][1],
        raw_document_id=docs["pensioni"][0],
        chunk_id=docs["pensioni"][1],
    )
    service.propose(
        NewAssessmentDraft(
            proposal_id=pledges["scuola"],
            proposal=PledgeAssessmentProposal(
                verdict=FulfillmentVerdict.KEPT,
                evidence_label=EvidenceLabel.SUPPORTS,
                rationale="Bozza editoriale non pubblicata sulla scuola.",
                quoted_excerpt=texts["tasse"][1],
                raw_document_id=docs["tasse"][0],
                document_chunk_id=docs["tasse"][1],
            ),
            origin=PledgeAssessmentOrigin.EDITOR,
            created_by="eval-editor",
        )
    )

    source_urls = {key: docs[key][2] for key in docs}
    return AskEvalCatalog(
        politician_ids=catalog,
        politician_names={
            "giorgia-meloni": "Giorgia Meloni",
            "mario-rossi": "Mario Rossi",
            "anna-rossi": "Anna Rossi",
        },
        pledge_ids={key: value for key, value in pledges.items() if key != "bozza"},
        pledge_titles=titles,
        source_urls=source_urls,
        published_source_urls=tuple(sorted({item[2] for item in docs.values()})),
        unpublished_titles=("Bozza",),
    )
