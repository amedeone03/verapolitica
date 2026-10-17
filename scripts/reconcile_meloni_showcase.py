"""Reconcile the public Giorgia Meloni pledge showcase to the CEO 16-promise set.

Idempotent editorial operator. First run applies required publication, unpublish,
classification and assessment changes. Second run creates no duplicates.

Uses the normal Proposal / PledgeService workflows. Never deletes rows. Never
bypasses the two-reviewer rule for broken. Never publishes accise (fact-check
URL) or bollo auto (unverified declaration date).

  python -m scripts.reconcile_meloni_showcase --dry-run
  python -m scripts.reconcile_meloni_showcase --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import AppEnvironment, Settings, configured_environment
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    PledgeAssessment,
    PledgeAssessmentDraft,
    PledgeAssessmentDraftStatus,
    PledgeAssessmentOrigin,
    PledgeClassification,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalDraft,
    ProposalDraftStatus,
    ProposalType,
    RawDocument,
)
from backend.app.schemas.pledge import PledgeAssessmentProposal, PledgeClassificationRequest
from backend.app.scoring.official_sources import classify_source_url
from backend.app.scoring.types import (
    CommitmentType,
    EvidenceLabel,
    FulfillmentVerdict,
    HolderRole,
    PledgeSpecificity,
)
from backend.app.services.official_extraction_runner import (
    content_type_for_path,
    ingest_official_document,
)
from backend.app.services.pledge_service import NewAssessmentDraft, PledgeService
from backend.app.services.reference_profile_audit import (
    DEFAULT_FIXTURE,
    resolve_politician,
)
from scripts.prepare_demo import DemoSafetyError
from scripts.prepare_reference_profile import _load_fixture
from scripts.unified_demo import UnifiedDemoPaths, assert_settings_are_unified


WORKSPACE = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = WORKSPACE / "data" / "fixtures" / "pledge_evidence"
POLITICIAN_ID = 206
EDITOR = "reference-assessment-editor"
REVIEWER = "reference-assessment-reviewer"
REVIEWER_2 = "reference-assessment-reviewer-2"
APPROVE_NOTE = "CEO-reference editorial assessment against official public-act evidence."
UNPUBLISH_NOTE = (
    "Removed from the active Meloni pledge showcase; historical row preserved."
)

REUSE_EXISTING = "REUSE_EXISTING"
UPDATE_CLASSIFICATION = "UPDATE_CLASSIFICATION"
CREATE_ASSESSMENT = "CREATE_ASSESSMENT"
SUPERSEDE_DUPLICATE = "SUPERSEDE_DUPLICATE"
PUBLISH_EXISTING_DRAFT = "PUBLISH_EXISTING_DRAFT"
BLOCKED_SOURCE = "BLOCKED_SOURCE"
NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"

SHOWCASE_EXTRAS = (
    101,
    102,
    103,
    104,
    105,
    106,
    107,
)

# Frozen unified-demo IDs for the 14 publishable CEO promises.
# Accise (119) and bollo (124) stay pending drafts.
CEO_PROPOSAL_IDS: dict[int, int] = {
    1: 111,
    2: 112,
    3: 113,
    4: 114,
    5: 115,
    6: 116,
    7: 117,
    8: 118,
    9: 109,
    11: 120,
    12: 121,
    13: 122,
    14: 108,
    15: 123,
}

CEO_CLASSIFICATIONS: dict[int, dict[str, Any]] = {
    14: {
        "specificity": PledgeSpecificity.HIGH,
        "commitment_type": CommitmentType.ACTION,
        "holder_role": HolderRole.GOVERNMENT_COALITION,
        "cap_topic_code": "6",
        "mandate_start": date(2022, 10, 21),
        "mandate_end": date(2027, 10, 12),
        "note": "CEO showcase maps this published near-duplicate to the asili-nido promise.",
    },
    9: {
        "specificity": PledgeSpecificity.HIGH,
        "commitment_type": CommitmentType.ACTION,
        "holder_role": HolderRole.GOVERNMENT_COALITION,
        "cap_topic_code": "9",
        "mandate_start": date(2022, 10, 21),
        "mandate_end": date(2027, 10, 12),
        "note": "CEO showcase maps this published near-duplicate to the blocco-navale promise.",
    },
}

EVIDENCE_FILES: tuple[dict[str, Any], ...] = (
    {
        "key": "rdc",
        "file": EVIDENCE_DIR / "legge_85_2023_assegno_inclusione.html",
        "url": "https://www.gazzettaufficiale.it/eli/id/2023/07/03/23G00087/sg",
        "name": "Gazzetta Ufficiale — Legge 3 luglio 2023, n. 85",
        "published_at": date(2023, 7, 3),
    },
    {
        "key": "cuneo",
        "file": EVIDENCE_DIR / "legge_213_2023_cuneo.html",
        "url": "https://www.gazzettaufficiale.it/eli/id/2023/12/30/23G00223/sg",
        "name": "Gazzetta Ufficiale — Legge 30 dicembre 2023, n. 213",
        "published_at": date(2023, 12, 30),
    },
    {
        "key": "irpef_assunzioni",
        "file": EVIDENCE_DIR / "legge_213_2023_irpef_e_assunzioni.html",
        "url": "https://www.gazzettaufficiale.it/eli/id/2023/12/30/23G00223/sg",
        "name": "Gazzetta Ufficiale — Legge 30 dicembre 2023, n. 213",
        "published_at": date(2023, 12, 30),
    },
    {
        "key": "asili",
        "file": EVIDENCE_DIR / "legge_197_2022_asili_nido.html",
        "url": "https://www.gazzettaufficiale.it/eli/id/2022/12/29/22G00211/sg",
        "name": "Gazzetta Ufficiale — Legge 29 dicembre 2022, n. 197",
        "published_at": date(2022, 12, 29),
    },
    {
        "key": "fisco_pensioni",
        "file": EVIDENCE_DIR / "legge_197_2022_flat_tax_e_fornero.html",
        "url": "https://www.gazzettaufficiale.it/eli/id/2022/12/29/22G00211/sg",
        "name": "Gazzetta Ufficiale — Legge 29 dicembre 2022, n. 197",
        "published_at": date(2022, 12, 29),
    },
    {
        "key": "carriere",
        "file": EVIDENCE_DIR / "legge_114_2024_ordinamento.html",
        "url": "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:2024-08-09;114",
        "name": "Normattiva — Legge 9 agosto 2024, n. 114",
        "published_at": date(2024, 8, 9),
    },
    {
        "key": "navale",
        "file": EVIDENCE_DIR / "legge_missione_navale_2023.html",
        "url": "https://www.gazzettaufficiale.it/eli/id/2023/07/15/23G00102/sg",
        "name": "Gazzetta Ufficiale — proroga missione navale 2023",
        "published_at": date(2023, 7, 15),
    },
    {
        "key": "liste",
        "file": EVIDENCE_DIR / "dl_73_2024_liste_attesa.html",
        "url": "https://www.gazzettaufficiale.it/eli/id/2024/06/07/24G00095/sg",
        "name": "Gazzetta Ufficiale — Decreto-legge 7 giugno 2024, n. 73",
        "published_at": date(2024, 6, 7),
    },
)

ASSESSMENTS: tuple[dict[str, Any], ...] = (
    {
        "ceo_number": 1,
        "verdict": FulfillmentVerdict.KEPT,
        "label": EvidenceLabel.SUPPORTS,
        "evidence_key": "rdc",
        "needle": "Assegno di inclusione",
        "effective_at": date(2023, 7, 3),
        "rationale": (
            "Il Reddito di cittadinanza e' stato sostituito dall'Assegno di inclusione "
            "e dal Supporto per la formazione e il lavoro."
        ),
    },
    {
        "ceo_number": 2,
        "verdict": FulfillmentVerdict.BROKEN,
        "label": EvidenceLabel.REFUTES,
        "evidence_key": "cuneo",
        "needle": "ridotto il cuneo fiscale",
        "effective_at": date(2023, 12, 30),
        "rationale": (
            "L'atto ufficiale riduce il cuneo fiscale, ma non attua il taglio di "
            "almeno cinque punti indicato nella promessa."
        ),
    },
    {
        "ceo_number": 3,
        "verdict": FulfillmentVerdict.KEPT,
        "label": EvidenceLabel.SUPPORTS,
        "evidence_key": "irpef_assunzioni",
        "needle": "aliquote IRPEF sono ridotte a tre scaglioni",
        "effective_at": date(2023, 12, 30),
        "rationale": "Gli scaglioni IRPEF sono stati ridotti da quattro a tre.",
    },
    {
        "ceo_number": 4,
        "verdict": FulfillmentVerdict.PARTIALLY_KEPT,
        "label": EvidenceLabel.SUPPORTS,
        "evidence_key": "fisco_pensioni",
        "needle": "elevata da 65.000 euro a 85.000 euro",
        "effective_at": date(2022, 12, 29),
        "rationale": (
            "La soglia del regime forfetario e' salita da 65.000 a 85.000 euro, "
            "non ai 100.000 euro promessi."
        ),
    },
    {
        "ceo_number": 5,
        "verdict": FulfillmentVerdict.KEPT,
        "label": EvidenceLabel.SUPPORTS,
        "evidence_key": "irpef_assunzioni",
        "needle": "sgravi contributivi per le nuove assunzioni",
        "effective_at": date(2023, 12, 30),
        "rationale": (
            "Sono stati introdotti sgravi contributivi per le nuove assunzioni "
            "secondo il principio «piu' assumi, meno paghi»."
        ),
    },
    {
        "ceo_number": 6,
        "verdict": FulfillmentVerdict.KEPT,
        "label": EvidenceLabel.SUPPORTS,
        "evidence_key": "fisco_pensioni",
        "needle": "tassa piatta incrementale",
        "effective_at": date(2022, 12, 29),
        "rationale": "E' stata introdotta una tassa piatta incrementale.",
    },
    {
        "ceo_number": 7,
        "verdict": FulfillmentVerdict.BROKEN,
        "label": EvidenceLabel.REFUTES,
        "evidence_key": "carriere",
        "needle": "Modifiche all'ordinamento giudiziario",
        "effective_at": date(2024, 8, 9),
        "rationale": (
            "La riforma dell'ordinamento giudiziario approvata non separa le "
            "carriere dei magistrati."
        ),
    },
    {
        "ceo_number": 8,
        "verdict": FulfillmentVerdict.STALLED,
        "label": EvidenceLabel.REFUTES,
        "existing_source_url": "https://www.senato.it/leggi-e-documenti/disegni-di-legge/scheda-ddl?did=60485",
        "needle": "avete perso quattro anni di tempo per il premierato",
        "effective_at": date(2026, 9, 29),
        "rationale": (
            "Il disegno di legge sull'elezione diretta del Presidente del Consiglio "
            "e' in corso ma l'iter e' fermo."
        ),
    },
    {
        "ceo_number": 9,
        "verdict": FulfillmentVerdict.BROKEN,
        "label": EvidenceLabel.REFUTES,
        "evidence_key": "navale",
        "needle": "proroga della missione navale italiana",
        "effective_at": date(2023, 7, 15),
        "rationale": (
            "Il blocco navale europeo annunciato non e' stato attuato. Le altre "
            "misure migratorie, inclusa la proroga di missioni navali, non ne "
            "costituiscono l'attuazione."
        ),
    },
    {
        "ceo_number": 11,
        "verdict": FulfillmentVerdict.PARTIALLY_KEPT,
        "label": EvidenceLabel.SUPPORTS,
        "evidence_key": "fisco_pensioni",
        "needle": "quota 103",
        "effective_at": date(2022, 12, 29),
        "rationale": (
            "Sono state introdotte correzioni parziali e sperimentali alla legge "
            "Fornero, senza una revisione organica."
        ),
    },
    {
        "ceo_number": 12,
        "verdict": FulfillmentVerdict.IN_PROGRESS,
        "label": EvidenceLabel.SUPPORTS,
        "existing_source_url": (
            "https://www.governo.it/it/articolo/le-dichiarazioni-programmatiche-"
            "del-governo-meloni/20770"
        ),
        "needle": "progressiva introduzione del quoziente familiare",
        "effective_at": date(2022, 10, 25),
        "rationale": (
            "Il governo ha avviato il percorso verso l'introduzione progressiva "
            "del quoziente familiare, senza averlo ancora reso generale."
        ),
    },
    {
        "ceo_number": 13,
        "verdict": FulfillmentVerdict.PARTIALLY_KEPT,
        "label": EvidenceLabel.SUPPORTS,
        "existing_source_url": (
            "https://www.governo.it/it/articolo/le-dichiarazioni-programmatiche-"
            "del-governo-meloni/20770"
        ),
        "needle": "aumentare gli importi dell",
        "effective_at": date(2022, 10, 25),
        "rationale": (
            "Gli importi dell'Assegno unico sono stati aumentati, ma non del 50 "
            "per cento indicato nella promessa."
        ),
    },
    {
        "ceo_number": 14,
        "verdict": FulfillmentVerdict.BROKEN,
        "label": EvidenceLabel.REFUTES,
        "evidence_key": "asili",
        "needle": "riduzione delle rette a carico delle famiglie",
        "effective_at": date(2022, 12, 29),
        "rationale": (
            "Sono state incrementate le risorse e previste riduzioni di retta, "
            "senza rendere gratuiti gli asili nido ne' ampliarne in via generale "
            "gli orari."
        ),
    },
    {
        "ceo_number": 15,
        "verdict": FulfillmentVerdict.IN_PROGRESS,
        "label": EvidenceLabel.SUPPORTS,
        "evidence_key": "liste",
        "needle": "riduzione delle liste di attesa",
        "effective_at": date(2024, 6, 7),
        "rationale": (
            "Sono state introdotte misure per monitorare e aumentare l'attivita' "
            "sanitaria, ma cio' da solo non dimostra una riduzione generalizzata "
            "dei tempi di attesa."
        ),
    },
)


@dataclass(frozen=True, slots=True)
class AuditRow:
    ceo_number: int
    ceo_promise: str
    existing_proposal_id: int | None
    publication_state: str
    classification: str
    assessment_state: str
    target_verdict: str
    action: str
    reason: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile the Meloni public showcase to the CEO 16-promise set."
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--dry-run", action="store_true")
    target.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def _settings(paths: UnifiedDemoPaths) -> Settings:
    settings = Settings().model_copy(update=paths.settings_kwargs())
    assert_settings_are_unified(settings.database_url, settings.raw_storage_path, paths.workspace_root)
    return settings


def _meloni_pledges(session: Session, politician_id: int) -> list[Proposal]:
    return list(
        session.scalars(
            select(Proposal)
            .join(ProposalActor, ProposalActor.proposal_id == Proposal.id)
            .where(
                ProposalActor.politician_id == politician_id,
                ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
                Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
            )
            .order_by(Proposal.id)
            .distinct()
        )
    )


def _latest_verdict(session: Session, proposal_id: int) -> str:
    latest = PledgeService._latest_assessments(session, [proposal_id]).get(proposal_id)
    if latest is None:
        return "none"
    return latest.verdict.value


def _classification_state(session: Session, proposal_id: int) -> str:
    row = session.scalar(
        select(PledgeClassification).where(PledgeClassification.proposal_id == proposal_id)
    )
    if row is None:
        return "unclassified"
    return f"{row.specificity.value}/{row.cap_topic_code or '-'}"


def _publication_state(proposal: Proposal | None) -> str:
    if proposal is None:
        return "missing"
    if proposal.published_at is None:
        return "unpublished"
    return "published"


def _fixture_pledges() -> list[dict[str, Any]]:
    return list(_load_fixture(DEFAULT_FIXTURE).get("pledges") or [])


def build_audit_table(session: Session, politician_id: int) -> list[AuditRow]:
    published = {
        row.id: row
        for row in _meloni_pledges(session, politician_id)
    }
    drafts = {
        str((row.proposed_data or {}).get("proposal_identifier") or ""): row
        for row in session.scalars(select(ProposalDraft))
    }
    rows: list[AuditRow] = []
    for item in _fixture_pledges():
        number = int(item["number"])
        title = str(item["title"])
        target = str(item["suggested_verdict"])
        proposal_id = CEO_PROPOSAL_IDS.get(number)
        proposal = published.get(proposal_id) if proposal_id else None
        identifier = f"reference-profile:giorgia_meloni_v1:pledge:{item['identity_key']}"
        draft = drafts.get(identifier)
        actions: list[str] = []
        reason = "Reuse the published canonical proposal."
        if number == 10:
            actions.append(BLOCKED_SOURCE)
            reason = (
                "Declaration URL is a third-party fact-check on pagellapolitica.it; "
                "no verified original statement URL is stored."
            )
        elif number == 16:
            actions.append(NEEDS_MANUAL_REVIEW)
            reason = (
                "Fixture marks 2026-09-17 as date_unverified and the declaration "
                "URL is a news video, not an official act."
            )
        else:
            actions.append(REUSE_EXISTING)
            if number in CEO_CLASSIFICATIONS:
                actions.append(UPDATE_CLASSIFICATION)
            if proposal is not None and _latest_verdict(session, proposal.id) != target:
                actions.append(CREATE_ASSESSMENT)
            if number in {9, 14}:
                actions.append(SUPERSEDE_DUPLICATE)
                reason = (
                    "Reuse the existing published near-duplicate; do not create a "
                    "second public promise."
                )
        if draft is not None and draft.status is ProposalDraftStatus.PENDING and number not in {10, 16}:
            actions.append(PUBLISH_EXISTING_DRAFT)
        rows.append(
            AuditRow(
                ceo_number=number,
                ceo_promise=title,
                existing_proposal_id=proposal_id if proposal is not None else (
                    int(str(draft.id)) if draft is not None else None
                ),
                publication_state=(
                    _publication_state(proposal)
                    if proposal is not None
                    else (
                        f"draft:{draft.status.value}"
                        if draft is not None
                        else "missing"
                    )
                ),
                classification=(
                    _classification_state(session, proposal.id)
                    if proposal is not None
                    else "-"
                ),
                assessment_state=(
                    _latest_verdict(session, proposal.id)
                    if proposal is not None
                    else "none"
                ),
                target_verdict=target,
                action="+".join(actions),
                reason=reason,
            )
        )
    return rows


def excerpt_containing(text: str, needle: str) -> str:
    lowered = text.casefold()
    idx = lowered.find(needle.casefold())
    if idx < 0:
        raise ValueError(f"official document does not contain {needle!r}")
    start = text.rfind("\n\n", 0, idx)
    start = 0 if start < 0 else start + 2
    end = text.find("\n\n", idx)
    end = len(text) if end < 0 else end
    excerpt = " ".join(text[start:end].split())
    if len(excerpt) < 12:
        excerpt = " ".join(text[idx : idx + 240].split())
    return excerpt[:4000]


def _document_by_url(session: Session, source_url: str, *, sha256_hex: str | None = None) -> RawDocument | None:
    rows = list(
        session.scalars(
            select(RawDocument)
            .where(RawDocument.source_url == source_url)
            .order_by(RawDocument.id.desc())
        )
    )
    if sha256_hex:
        for row in rows:
            if row.raw_sha256 == sha256_hex and row.normalized_text:
                return row
        return None
    for row in rows:
        if row.normalized_text:
            return row
    return rows[0] if rows else None


def ingest_evidence(settings: Settings, session_factory: sessionmaker[Session]) -> dict[str, int]:
    ids: dict[str, int] = {}
    for item in EVIDENCE_FILES:
        path: Path = item["file"]
        content = path.read_bytes()
        digest = sha256(content).hexdigest()
        decision = classify_source_url(item["url"])
        if not decision.official:
            raise DemoSafetyError(f"refusing non-official evidence URL {item['url']}")
        with session_factory() as session:
            existing = _document_by_url(session, item["url"], sha256_hex=digest)
            if existing is not None and existing.normalized_text:
                ids[item["key"]] = existing.id
                continue
        result = ingest_official_document(
            settings=settings,
            content=content,
            source_url=item["url"],
            source_name=item["name"],
            content_type=content_type_for_path(path),
            source_key=None,
        )
        ids[item["key"]] = int(result["raw_document_id"])
    return ids


def _resolve_document_id(
    session: Session,
    spec: dict[str, Any],
    evidence_ids: dict[str, int],
) -> int:
    if spec.get("evidence_key"):
        return evidence_ids[spec["evidence_key"]]
    url = spec["existing_source_url"]
    document = _document_by_url(session, url)
    if document is None:
        raise ValueError(f"no ingested official document for {url}")
    return document.id


def unpublish_extras(
    session_factory: sessionmaker[Session],
    *,
    dry_run: bool,
) -> list[int]:
    unpublished: list[int] = []
    with session_factory.begin() as session:
        for proposal_id in SHOWCASE_EXTRAS:
            proposal = session.get(Proposal, proposal_id)
            if proposal is None or proposal.published_at is None:
                continue
            unpublished.append(proposal_id)
            if dry_run:
                continue
            proposal.published_at = None
            proposal.updated_at = datetime.now(timezone.utc)
    return unpublished


def classify_if_needed(
    pledges: PledgeService,
    session_factory: sessionmaker[Session],
    *,
    dry_run: bool,
) -> list[int]:
    updated: list[int] = []
    for number, request in CEO_CLASSIFICATIONS.items():
        proposal_id = CEO_PROPOSAL_IDS[number]
        with session_factory() as session:
            row = session.scalar(
                select(PledgeClassification).where(
                    PledgeClassification.proposal_id == proposal_id
                )
            )
            if (
                row is not None
                and row.specificity is request["specificity"]
                and row.commitment_type is request["commitment_type"]
                and row.holder_role is request["holder_role"]
                and row.cap_topic_code == request["cap_topic_code"]
                and row.mandate_start == request["mandate_start"]
                and row.mandate_end == request["mandate_end"]
            ):
                continue
        updated.append(proposal_id)
        if dry_run:
            continue
        pledges.classify(
            proposal_id,
            PledgeClassificationRequest(**request),
            classified_by=EDITOR,
        )
    return updated


def approve_assessment(
    pledges: PledgeService,
    draft_id: int,
    verdict: FulfillmentVerdict,
) -> bool:
    _, published = pledges.approve(draft_id, reviewer=REVIEWER, note=APPROVE_NOTE)
    if published is not None:
        return True
    if verdict is FulfillmentVerdict.BROKEN:
        _, published = pledges.approve(draft_id, reviewer=REVIEWER_2, note=APPROVE_NOTE)
        return published is not None
    return False


def create_assessments(
    pledges: PledgeService,
    session_factory: sessionmaker[Session],
    evidence_ids: dict[str, int],
    *,
    dry_run: bool,
) -> tuple[list[int], list[int]]:
    created: list[int] = []
    reused: list[int] = []
    for spec in ASSESSMENTS:
        proposal_id = CEO_PROPOSAL_IDS[spec["ceo_number"]]
        with session_factory() as session:
            latest = PledgeService._latest_assessments(session, [proposal_id]).get(proposal_id)
            if latest is not None and latest.verdict is spec["verdict"]:
                reused.append(proposal_id)
                continue
            raw_document_id = _resolve_document_id(session, spec, evidence_ids)
            document = session.get(RawDocument, raw_document_id)
            if document is None or not document.normalized_text:
                raise ValueError(f"official document {raw_document_id} has no normalized text")
            excerpt = excerpt_containing(document.normalized_text, spec["needle"])
        _ = raw_document_id, excerpt
        if dry_run:
            created.append(proposal_id)
            continue
        draft, was_created = pledges.propose(
            NewAssessmentDraft(
                proposal_id=proposal_id,
                proposal=PledgeAssessmentProposal(
                    verdict=spec["verdict"],
                    evidence_label=spec["label"],
                    rationale=spec["rationale"],
                    quoted_excerpt=excerpt,
                    raw_document_id=raw_document_id,
                    effective_at=spec["effective_at"],
                ),
                origin=PledgeAssessmentOrigin.EDITOR,
                created_by=EDITOR,
            )
        )
        if draft.status == PledgeAssessmentDraftStatus.APPROVED.value:
            reused.append(proposal_id)
            continue
        published = approve_assessment(pledges, draft.id, spec["verdict"])
        if not published:
            raise RuntimeError(f"assessment for proposal {proposal_id} was not published")
        if was_created:
            created.append(proposal_id)
        else:
            reused.append(proposal_id)
    return created, reused


def reconcile_meloni_showcase(
    *,
    session_factory: sessionmaker[Session] | None = None,
    settings: Settings | None = None,
    dry_run: bool = True,
    allow_non_unified: bool = False,
) -> dict[str, Any]:
    if configured_environment() is AppEnvironment.PRODUCTION:
        raise DemoSafetyError("reconcile_meloni_showcase refuses VERAPOLITICA_ENV=production")
    engine = None
    dispose = False
    if session_factory is None or settings is None:
        paths = UnifiedDemoPaths.for_workspace(WORKSPACE)
        runtime = settings or _settings(paths)
        if not allow_non_unified:
            assert_settings_are_unified(
                runtime.database_url, runtime.raw_storage_path, paths.workspace_root
            )
        engine = create_db_engine(runtime.database_url)
        prepare_runtime_schema(engine, runtime)
        session_factory = session_factory or create_session_factory(engine)
        settings = runtime
        dispose = engine is not None
    assert settings is not None
    try:
        with session_factory() as session:
            politician = resolve_politician(session, "giorgia-meloni")
            politician_id = politician.id
            audit = [asdict(row) for row in build_audit_table(session, politician_id)]
        if dry_run:
            return {
                "dry_run": True,
                "politician_id": politician_id,
                "audit": audit,
                "unpublished": list(SHOWCASE_EXTRAS),
                "classified": [],
                "assessments_created": [],
                "assessments_reused": [],
                "blocked": [10, 16],
                "created": 0,
                "reused": 0,
                "superseded": len(SHOWCASE_EXTRAS),
                "approved": 0,
            }
        evidence_ids = ingest_evidence(settings, session_factory)
        unpublished = unpublish_extras(session_factory, dry_run=False)
        pledges = PledgeService(session_factory)
        classified = classify_if_needed(pledges, session_factory, dry_run=False)
        created, reused = create_assessments(
            pledges, session_factory, evidence_ids, dry_run=False
        )
        with session_factory() as session:
            audit = [asdict(row) for row in build_audit_table(session, politician_id)]
            public = [
                row
                for row in _meloni_pledges(session, politician_id)
                if row.published_at is not None
            ]
            latest = PledgeService._latest_assessments(session, [row.id for row in public])
            distribution: dict[str, int] = {}
            for row in public:
                assessment = latest.get(row.id)
                key = (
                    assessment.verdict.value
                    if assessment is not None
                    else FulfillmentVerdict.NOT_YET_RATED.value
                )
                distribution[key] = distribution.get(key, 0) + 1
        return {
            "dry_run": False,
            "politician_id": politician_id,
            "audit": audit,
            "unpublished": unpublished,
            "classified": classified,
            "assessments_created": created,
            "assessments_reused": reused,
            "blocked": [10, 16],
            "created": len(created),
            "reused": len(reused),
            "superseded": len(unpublished),
            "approved": len(created),
            "public_pledge_count": len(public),
            "distribution": distribution,
            "evidence_document_ids": evidence_ids,
        }
    finally:
        if dispose and engine is not None:
            engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.dry_run and not args.apply:
        print("pass --dry-run or --apply", file=sys.stderr)
        return 2
    try:
        report = reconcile_meloni_showcase(dry_run=not args.apply)
    except (DemoSafetyError, ValueError, RuntimeError) as exc:
        print(f"meloni showcase reconcile failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
