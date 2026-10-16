from datetime import date, datetime, timezone

from sqlalchemy import select

from backend.app.models import (
    PledgeAssessment,
    Politician,
    PoliticianSourceIdentifier,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalDraft,
    ProposalDraftStatus,
    ProposalType,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.models.politician_profile import (
    PoliticianBiography,
    PoliticianProceeding,
    ProfileContentStatus,
)
from backend.app.models.politician_version import PoliticianVersion
from backend.app.models.pledge import PledgeAssessmentOrigin
from backend.app.schemas.pledge import PledgeAssessmentProposal, PledgeClassificationRequest
from backend.app.scoring.types import (
    CommitmentType,
    EvidenceLabel,
    FulfillmentVerdict,
    HolderRole,
    PledgeSpecificity,
)
from backend.app.services import normalize_person_name
from backend.app.services.pledge_service import NewAssessmentDraft, PledgeService
from scripts.prepare_reference_profile import (
    DEFAULT_FIXTURE,
    prepare_reference_profile,
)


NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)

EXISTING_PLEDGES = (
    "Tutelare le infrastrutture strategiche nazionali assicurando la proprietà pubblica",
    "Introdurre una clausola di salvaguardia dell’interesse nazionale",
    "Lavoreremo per restituire ai cittadini la garanzia di vivere in una Nazione sicura",
    "Rivedremo anche la riforma dell’ordinamento giudiziario",
    "Partire da una modifica dei criteri di valutazione dei risultati dell’Agenzia",
    "Dare seguito al processo virtuoso di autonomia differenziata già avviato da diverse",
    "Mantenere e, laddove possibile, migliorare il doveroso sostegno economico per i",
    "Incentivare in ogni modo l’occupazione femminile, premiando quelle aziende che adottano politiche che offrono soluzioni efficaci per conciliare i tempi casa-lavoro e sostenendo i comuni per garantire asili nido gratuiti",
    "La nostra intenzione è sempre la stessa, ma, se non volete che si parli di blocco navale, lo dico così: è nostra intenzione recuperare la proposta originaria della missione navale Sophia",
)


def _seed_meloni(session_factory, *, with_pledges: bool = True) -> dict[str, int]:
    with session_factory() as session:
        source = Source(key="governo-italiano", name="Governo Italiano", base_url="https://www.governo.it")
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=NOW,
            source_url="https://www.governo.it/programma",
            content_type="text/plain",
            storage_key="programme.txt",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[],
            normalized_text="\n".join(EXISTING_PLEDGES),
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="v1",
            parser_version="v1",
        )
        session.add(document)
        politician = Politician(
            canonical_given_name="Giorgia",
            canonical_family_name="Meloni",
            normalized_name=normalize_person_name("Giorgia", "Meloni"),
            birth_date=date(1977, 1, 15),
        )
        session.add(politician)
        session.flush()
        version = PoliticianVersion(
            politician_id=politician.id,
            version_number=1,
            profile_schema_version=1,
            profile_data={
                "given_name": "Giorgia",
                "family_name": "Meloni",
                "mandates": [
                    {
                        "institution": "Presidenza del Consiglio dei Ministri",
                        "office": "Presidente del Consiglio",
                        "legislature": "Governo Meloni",
                        "mandate_type": "Presidente del Consiglio dei Ministri",
                        "start_date": "2022-10-21",
                        "end_date": None,
                    }
                ],
            },
            published_at=NOW,
        )
        session.add(version)
        session.flush()
        politician.current_version = version
        session.add(
            PoliticianSourceIdentifier(
                politician_id=politician.id,
                source_id=source.id,
                value="https://www.governo.it/it/node/20681",
            )
        )
        proposal_ids = []
        if with_pledges:
            for title in EXISTING_PLEDGES:
                proposal = Proposal(
                    canonical_title=title,
                    exact_statement=title,
                    proposal_type=ProposalType.EXPLICIT_PROMISE,
                    introduced_at=date(2022, 10, 25),
                    published_at=NOW,
                )
                session.add(proposal)
                session.flush()
                session.add(
                    ProposalActor(
                        proposal_id=proposal.id,
                        actor_type="politician",
                        role=ProposalActorRole.COMMITMENT_OWNER,
                        politician_id=politician.id,
                        display_name="Giorgia Meloni",
                        identity_key=f"pol-{proposal.id}",
                    )
                )
                proposal_ids.append(proposal.id)
        session.commit()
        ids = {
            "politician_id": politician.id,
            "source_id": source.id,
            "document_id": document.id,
            "autonomia_id": proposal_ids[5] if proposal_ids else None,
        }
        return ids


def _classify_and_assess_autonomia(session_factory, ids):
    pledges = PledgeService(session_factory, clock=lambda: NOW)
    pledges.classify(
        ids["autonomia_id"],
        PledgeClassificationRequest(
            specificity=PledgeSpecificity.HIGH,
            commitment_type=CommitmentType.ACTION,
            holder_role=HolderRole.GOVERNMENT_COALITION,
            cap_topic_code="20",
            mandate_start=date(2022, 10, 22),
            mandate_end=date(2027, 10, 12),
        ),
        classified_by="demo-editor",
    )
    draft, _ = pledges.propose(
        NewAssessmentDraft(
            proposal_id=ids["autonomia_id"],
            proposal=PledgeAssessmentProposal(
                verdict=FulfillmentVerdict.IN_PROGRESS,
                evidence_label=EvidenceLabel.SUPPORTS,
                rationale="Official act language names the same policy instrument as the commitment.",
                quoted_excerpt=EXISTING_PLEDGES[5],
                raw_document_id=ids["document_id"],
                effective_at=date(2024, 6, 26),
            ),
            origin=PledgeAssessmentOrigin.EDITOR,
            created_by="demo-editor",
        )
    )
    draft_response, published = pledges.approve(draft.id, reviewer="demo-desk")
    assert published is not None
    return published.id


def test_reference_fixture_dry_run_does_not_write(session_factory):
    ids = _seed_meloni(session_factory)
    report = prepare_reference_profile(
        session_factory=session_factory, dry_run=True, allow_non_unified=True
    )
    assert report["dry_run"] is True
    assert report["politician_id"] == ids["politician_id"]
    assert "requires editorial verification" in report["disclaimer"]
    matched_numbers = {item["pdf_number"] for item in report["matched"]}
    assert matched_numbers == {9, 14}
    missing = [item for item in report["reconciliation"] if item["match"] == "missing"]
    assert len(missing) == 14
    with session_factory() as session:
        assert session.scalar(select(PoliticianBiography)) is None
        assert session.scalar(select(ProposalDraft)) is None


def test_apply_is_idempotent_and_does_not_publish(session_factory):
    ids = _seed_meloni(session_factory)
    assessment_id = _classify_and_assess_autonomia(session_factory, ids)
    first = prepare_reference_profile(
        session_factory=session_factory, dry_run=False, allow_non_unified=True
    )
    second = prepare_reference_profile(
        session_factory=session_factory, dry_run=False, allow_non_unified=True
    )
    created_pledges = [item for item in first["created"] if item.get("kind") == "pledge"]
    skipped_pledges = [item for item in second["skipped"] if item.get("kind") == "pledge"]
    assert len(created_pledges) == 14
    assert len(skipped_pledges) == 14
    assert first["assessment_drafts_created"] == []
    assert first["protected"][0]["assessment_id"] == assessment_id
    assert first["protected"][0]["verdict"] == "in_progress"
    with session_factory() as session:
        bios = list(session.scalars(select(PoliticianBiography)))
        assert bios and all(row.status is ProfileContentStatus.PENDING for row in bios)
        proceedings = list(session.scalars(select(PoliticianProceeding)))
        assert len(proceedings) == 4
        assert all(row.status is ProfileContentStatus.PENDING for row in proceedings)
        almasri = next(row for row in proceedings if "Almasri" in row.title)
        assert almasri.proceeding_types == ["judicial_proceeding"]
        assert almasri.outcome.value == "archived"
        drafts = list(session.scalars(select(ProposalDraft)))
        assert drafts
        assert all(row.status is ProposalDraftStatus.PENDING for row in drafts)
        published_new = list(
            session.scalars(
                select(Proposal).where(
                    Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
                    Proposal.published_at.is_not(None),
                )
            )
        )
        assert len(published_new) == 9
        assessment = session.get(PledgeAssessment, assessment_id)
        assert assessment.verdict is FulfillmentVerdict.IN_PROGRESS
        assert assessment.rationale.startswith("Official act language")


def test_fixture_file_declares_editorial_verification():
    text = DEFAULT_FIXTURE.read_text(encoding="utf-8")
    assert "derived from CEO reference PDF; requires editorial verification" in text
    assert '"number": 16' in text
