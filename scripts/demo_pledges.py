"""Synthetic pledge-tracker data for the local demo.

Every record is clearly synthetic and goes through the real services: promises
are published through ProposalService + ProposalReviewService, classified and
assessed through PledgeService (editor proposal + separate approval, two
approvals for "broken"). One matcher draft is left pending for the editorial
API demo. Nothing here is suitable for production data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    DocumentChunk,
    PledgeAssessmentOrigin,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.schemas import (
    ProposalActorObservation,
    ProposalEvidenceObservation,
    ProposalObservation,
)
from backend.app.schemas.pledge import PledgeAssessmentProposal, PledgeClassificationRequest
from backend.app.scoring import (
    CommitmentType,
    EvidenceLabel,
    FulfillmentVerdict,
    HolderRole,
    PledgeSpecificity,
)
from backend.app.services import ProposalReviewService, ProposalService
from backend.app.services.pledge_service import NewAssessmentDraft, PledgeService

PROGRAMME_SOURCE_KEY = "demo-programma"
ACTS_SOURCE_KEY = "demo-atti-ufficiali"
OBSERVED_AT = datetime(2026, 9, 30, 9, tzinfo=timezone.utc)
MANDATE_START = date(2022, 10, 13)
MANDATE_END = date(2027, 10, 13)

K, P, B = FulfillmentVerdict.KEPT, FulfillmentVerdict.PARTIALLY_KEPT, FulfillmentVerdict.BROKEN
IP, ST = FulfillmentVerdict.IN_PROGRESS, FulfillmentVerdict.STALLED


@dataclass(frozen=True)
class DemoPledge:
    key: str
    title: str
    statement: str
    topic: str
    verdict: FulfillmentVerdict | None
    act: str | None
    effective_at: date | None
    specificity: PledgeSpecificity = PledgeSpecificity.HIGH
    commitment_type: CommitmentType = CommitmentType.ACTION


PLEDGES: tuple[DemoPledge, ...] = (
    DemoPledge("pensioni", "Minimum pensions to €1,000 (demo)",
               "Porteremo le pensioni minime a 1.000 euro al mese.", "13", K,
               "Approvata in via definitiva la legge che porta le pensioni minime a 1.000 euro mensili.",
               date(2024, 12, 18)),
    DemoPledge("affitti", "Rent support for under-35s (demo)",
               "Introdurremo un contributo per l'affitto dedicato agli under 35.", "14", K,
               "Istituito il fondo nazionale per il contributo affitti destinato ai giovani under 35.",
               date(2023, 12, 29)),
    DemoPledge("infermieri", "Hire 5,000 nurses (demo)",
               "Assumeremo 5.000 nuovi infermieri nel servizio sanitario pubblico.", "3", P,
               "Autorizzata l'assunzione di 3.000 infermieri nel triennio 2024-2026.",
               date(2024, 3, 7)),
    DemoPledge("mense", "Free school meals (demo)",
               "Renderemo gratuite le mense delle scuole primarie statali.", "6", K,
               "Estesa la gratuità delle mense scolastiche a tutte le scuole primarie statali.",
               date(2025, 8, 1)),
    DemoPledge("treni", "New regional trains (demo)",
               "Finanzieremo l'acquisto di nuovi treni regionali per i pendolari.", "10", K,
               "Stanziati i fondi per l'acquisto di 120 nuovi treni regionali destinati ai pendolari.",
               date(2024, 6, 12)),
    DemoPledge("cuneo", "Cut the tax wedge by two points (demo)",
               "Ridurremo di due punti il cuneo contributivo sui redditi da lavoro.", "5", K,
               "Ridotto di due punti percentuali il cuneo contributivo sui redditi da lavoro dipendente.",
               date(2023, 12, 30)),
    DemoPledge("lobby", "Public lobbying register (demo)",
               "Approveremo una legge per un registro pubblico dei rappresentanti di interessi.", "20", B,
               "La commissione ha archiviato il disegno di legge sul registro dei rappresentanti di interessi.",
               date(2025, 5, 21)),
    DemoPledge("banda", "Ultra-broadband in every municipality (demo)",
               "Porteremo la banda ultralarga in tutti i comuni italiani.", "17", P,
               "Completata la copertura in banda ultralarga nel 60 per cento dei comuni.",
               date(2025, 11, 4)),
    DemoPledge("alloggi", "Public housing plan, 10,000 homes (demo)",
               "Approveremo un piano casa per 10.000 alloggi di edilizia pubblica.", "14", K,
               "Approvato il piano nazionale per la realizzazione di 10.000 alloggi di edilizia pubblica.",
               date(2025, 2, 14)),
    DemoPledge("giustizia", "Civil justice reform (demo)",
               "Presenteremo una riforma per dimezzare i tempi della giustizia civile.", "12", IP,
               "Avviato l'esame in commissione del disegno di legge di riforma della giustizia civile.",
               date(2026, 2, 3)),
    DemoPledge("suolo", "Land consumption law (demo)",
               "Approveremo una legge per azzerare il consumo di suolo.", "7", ST,
               "Il disegno di legge sul consumo di suolo è fermo in commissione da oltre un anno.",
               date(2026, 4, 9)),
    DemoPledge("ricerca", "Research fund (demo)",
               "Creeremo un fondo pluriennale per la ricerca universitaria.", "17", IP,
               "Presentato in Senato il disegno di legge istitutivo del fondo per la ricerca universitaria.",
               date(2026, 5, 19)),
    DemoPledge("rilancio", "Relaunch the country (demo, vague)",
               "Rilanceremo il Paese e lo renderemo più forte.", "1", None, None, None,
               specificity=PledgeSpecificity.VAGUE),
)

PENDING_MATCHER_ACT = (
    "Approvata in prima lettura la legge istitutiva del fondo pluriennale per la ricerca universitaria."
)


def _document(session: Session, source_key: str, name: str, url: str, text: str, marker: str) -> RawDocument:
    source = Source(key=source_key, name=name, base_url="https://example.test")
    session.add(source)
    session.flush()
    document = RawDocument(
        source_id=source.id,
        retrieved_at=OBSERVED_AT,
        source_url=url,
        content_type="text/plain",
        storage_key=f"demo-pledges/{source_key}.txt",
        raw_sha256=marker * 64,
        normalized_sha256=marker * 64,
        structured_records=[],
        normalized_text=text,
        process_status=RawDocumentStatus.PARSED,
        change_detected=True,
        collector_version="synthetic_demo_v1",
        parser_version="synthetic_demo_v1",
    )
    session.add(document)
    session.flush()
    return document


def seed_demo_pledges(
    session_factory: sessionmaker[Session],
    *,
    politician_source_key: str,
    politician_source_identifier: str,
) -> list[int]:
    """Publish, classify and assess the synthetic pledges. Returns proposal ids."""

    acts = [pledge.act for pledge in PLEDGES if pledge.act] + [PENDING_MATCHER_ACT]
    with session_factory() as session:
        programme = _document(
            session,
            PROGRAMME_SOURCE_KEY,
            "Synthetic electoral programme (demo only)",
            "https://example.test/demo/programma-elettorale",
            "\n".join(pledge.statement for pledge in PLEDGES),
            "a",
        )
        digest = _document(
            session,
            ACTS_SOURCE_KEY,
            "Synthetic digest of official acts (demo only)",
            "https://example.test/demo/atti-ufficiali",
            "\n".join(acts),
            "b",
        )
        chunk_ids: dict[str, int] = {}
        for index, text in enumerate(acts):
            chunk = DocumentChunk(
                raw_document_id=digest.id,
                chunk_index=index,
                text=text,
                chunk_hash=f"{index:064x}",
            )
            session.add(chunk)
            session.flush()
            chunk_ids[text] = chunk.id
        session.commit()
        programme_id, digest_id = programme.id, digest.id

    proposals = ProposalService(session_factory)
    reviews = ProposalReviewService(session_factory)
    pledges = PledgeService(session_factory, clock=lambda: OBSERVED_AT)
    proposal_ids: list[int] = []
    for pledge in PLEDGES:
        url = f"https://example.test/demo/programma-elettorale#{pledge.key}"
        observation = ProposalObservation(
            source_key=PROGRAMME_SOURCE_KEY,
            raw_document_id=programme_id,
            proposal_identifier=url,
            title=pledge.title,
            exact_statement=pledge.statement,
            proposal_type="explicit_promise",
            source_status_label="annunciata",
            normalized_status="announced",
            official_url=url,
            source_field="programma:impegno",
            observed_at=OBSERVED_AT,
            actors=(
                ProposalActorObservation(
                    actor_type="politician",
                    role="commitment_owner",
                    display_name="Sen. Anna Rossi",
                    authority_key=politician_source_key,
                    source_identifier=politician_source_identifier,
                    source_field="programma:candidato",
                ),
            ),
            evidence=tuple(
                ProposalEvidenceObservation(
                    field_path=path, source_url=url, source_field=field, source_value=value
                )
                for path, field, value in (
                    ("title", "programma:titolo", pledge.title),
                    ("proposal_type", "programma:tipo", "impegno esplicito"),
                    ("current_status", "programma:stato", "annunciata"),
                    ("exact_statement", "programma:testo", pledge.statement),
                )
            ),
            metadata={"fixture": "synthetic_demo_only"},
        )
        detail = proposals.sync((observation,)).details[0]
        reviews.approve(detail.draft_id, reviewer="demo-setup", note="Synthetic pledge fixture")
        proposal_id = detail.proposal_id
        proposal_ids.append(proposal_id)

        pledges.classify(
            proposal_id,
            PledgeClassificationRequest(
                specificity=pledge.specificity,
                commitment_type=pledge.commitment_type,
                holder_role=HolderRole.GOVERNMENT_COALITION,
                cap_topic_code=pledge.topic,
                mandate_start=MANDATE_START,
                mandate_end=MANDATE_END,
                note="Synthetic demo classification",
            ),
            classified_by="demo-editor",
        )
        if pledge.verdict is None:
            continue
        label = (
            EvidenceLabel.REFUTES
            if pledge.verdict in (B, ST)
            else EvidenceLabel.SUPPORTS
        )
        draft, _ = pledges.propose(
            NewAssessmentDraft(
                proposal_id=proposal_id,
                proposal=PledgeAssessmentProposal(
                    verdict=pledge.verdict,
                    evidence_label=label,
                    rationale="Synthetic demo assessment based on the cited act.",
                    quoted_excerpt=pledge.act,
                    raw_document_id=digest_id,
                    document_chunk_id=chunk_ids[pledge.act],
                    effective_at=pledge.effective_at,
                ),
                origin=PledgeAssessmentOrigin.EDITOR,
                created_by="demo-editor",
            )
        )
        pledges.approve(draft.id, reviewer="demo-desk")
        if pledge.verdict is B:
            pledges.approve(draft.id, reviewer="demo-desk-2")

    research_id = proposal_ids[[p.key for p in PLEDGES].index("ricerca")]
    pledges.propose(
        NewAssessmentDraft(
            proposal_id=research_id,
            proposal=PledgeAssessmentProposal(
                verdict=K,
                evidence_label=EvidenceLabel.SUPPORTS,
                rationale="Synthetic matcher suggestion left pending for the editorial demo.",
                quoted_excerpt=PENDING_MATCHER_ACT,
                raw_document_id=digest_id,
                document_chunk_id=chunk_ids[PENDING_MATCHER_ACT],
                effective_at=date(2026, 9, 24),
            ),
            origin=PledgeAssessmentOrigin.EVIDENCE_MATCHER,
            created_by="system:pledge-evidence-matcher",
            judge_name="synthetic-demo-judge",
            judge_version="v1",
        )
    )
    return proposal_ids
