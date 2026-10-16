"""Review and publish valid Meloni reference pledge drafts in the unified demo.

Approves only explicit, non-duplicate promises through ProposalReviewService,
classifies them through PledgeService, and reconciles legacy 2022-10-22
classification windows to the canonical public mandate start 2022-10-21.

Never publishes fulfilment verdicts from the PDF. Never creates assessments
from commentary. Never touches proceedings, Ask, Spiegami, scoring, or Draft 2.

  python -m scripts.review_reference_pledges giorgia-meloni --dry-run
  python -m scripts.review_reference_pledges giorgia-meloni --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import AppEnvironment, configured_environment
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    PledgeAssessment,
    PledgeAssessmentDraft,
    PledgeClassification,
    PledgeEvidenceCandidate,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalDraft,
    ProposalDraftStatus,
    ProposalType,
    RawDocument,
)
from backend.app.models.politician_profile import (
    PoliticianProceeding,
    ProfileContentStatus,
)
from backend.app.schemas.pledge import PledgeClassificationRequest
from backend.app.schemas.politician_profile import PledgeEvidenceReadiness
from backend.app.scoring.types import CommitmentType, HolderRole, PledgeSpecificity
from backend.app.services.pledge_service import PledgeService
from backend.app.services.proposal_review_service import ProposalReviewService
from backend.app.services.reference_profile_audit import (
    DEFAULT_FIXTURE,
    existing_mandate_end,
    published_pdc_start,
    resolve_politician,
)
from scripts.audit_reference_profile import resolve_database_url
from scripts.prepare_demo import DemoSafetyError
from scripts.prepare_reference_profile import (
    PROTECTED_ASSESSMENT_TITLE_PREFIX,
    _load_fixture,
    _match_existing,
)
from scripts.unified_demo import UnifiedDemoPaths, assert_settings_are_unified


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REVIEWER = "reference-pledge-editor"
APPROVE_NOTE = (
    "Approved as an explicit non-duplicate promise. "
    "No fulfilment assessment is published from the reference PDF."
)
LEGACY_MANDATE_START = date(2022, 10, 22)
CAMPAIGN_OR_GOVERNMENT_START = date(2022, 8, 1)
FACT_CHECK_HOSTS = frozenset({"pagellapolitica.it", "www.pagellapolitica.it"})
FIXTURE_STORAGE_MARKERS = ("reference-profiles/", "giorgia_meloni_v1")
PROMISSORY_RE = re.compile(
    r"\b("
    r"abolire|sostituire|ridurre|estendere|introdurre|separare|rivedere|"
    r"aumentare|abbattere|realizzare|rendere|incentivare|recuperare|"
    r"lavoreremo|intendiamo|vogliamo|impegniamo"
    r")\b",
    re.IGNORECASE,
)

APPROVE_PLEDGE = "APPROVE_PLEDGE"
KEEP_PENDING_NEEDS_REVIEW = "KEEP_PENDING_NEEDS_REVIEW"
REJECT_DUPLICATE = "REJECT_DUPLICATE"
REJECT_NOT_EXPLICIT_PROMISE = "REJECT_NOT_EXPLICIT_PROMISE"
BLOCK_SOURCE_ISSUE = "BLOCK_SOURCE_ISSUE"
BLOCK_OTHER = "BLOCK_OTHER"
ALREADY_SKIPPED_DUPLICATE = "ALREADY_SKIPPED_DUPLICATE"


def _identity_key(payload: dict[str, Any]) -> str:
    identifier = str(payload.get("proposal_identifier") or "")
    if "pledge:" in identifier:
        return identifier.rsplit(":", 1)[-1]
    return ""


def _host(url: str | None) -> str:
    if not url:
        return ""
    return (urlsplit(url).hostname or "").casefold()


def _is_explicit_promise(title: str, statement: str, proposal_type: str | None) -> bool:
    if str(proposal_type or "").casefold() not in {"explicit_promise", ""}:
        return False
    blob = f"{title} {statement}".strip()
    if len(blob) < 12:
        return False
    return bool(PROMISSORY_RE.search(blob))


def _fixture_by_identity(fixture: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["identity_key"]: item for item in fixture.get("pledges") or []}


def decide_pledge_action(
    fixture_pledge: dict[str, Any],
    *,
    draft_payload: dict[str, Any] | None,
    published: list[Proposal],
    already_approved_titles: set[str] | None = None,
) -> dict[str, Any]:
    """Deterministic editorial decision. No LLM/fuzzy identity matching."""

    title = str(fixture_pledge.get("title") or "")
    statement = str(fixture_pledge.get("exact_statement") or "")
    introduced = fixture_pledge.get("introduced_at")
    source_url = fixture_pledge.get("declaration_url")
    proposal_type = "explicit_promise"
    if draft_payload is not None:
        title = str(draft_payload.get("title") or title)
        statement = str(draft_payload.get("exact_statement") or statement)
        introduced = draft_payload.get("introduced_at") or introduced
        source_url = draft_payload.get("official_url") or source_url
        proposal_type = str(draft_payload.get("proposal_type") or proposal_type)
    match = _match_existing(fixture_pledge, published)
    explicit = _is_explicit_promise(title, statement, proposal_type)
    row = {
        "pdf_number": fixture_pledge.get("number"),
        "identity_key": fixture_pledge.get("identity_key"),
        "title": title,
        "promise_text": statement,
        "declaration_date": str(introduced)[:10] if introduced else None,
        "declaration_source": fixture_pledge.get("origin_label") or "",
        "declaration_url": source_url,
        "actor": "Giorgia Meloni",
        "proposed_topic_cap": fixture_pledge.get("cap_topic_code"),
        "explicit_promise": explicit,
        "duplicate_status": "near_duplicate" if match is not None else "distinct",
        "existing_similar_published_pledge": (
            match.canonical_title if match is not None else None
        ),
        "existing_similar_published_id": match.id if match is not None else None,
        "publication_readiness": "not_ready",
        "classification_readiness": "not_ready",
        "assessment_evidence_readiness": (
            PledgeEvidenceReadiness.ASSESSMENT_NEEDS_OFFICIAL_EVIDENCE.value
        ),
        "recommended_action": BLOCK_OTHER,
        "reason": "",
    }
    approved_titles = already_approved_titles or set()
    if match is not None:
        row["recommended_action"] = (
            ALREADY_SKIPPED_DUPLICATE if draft_payload is None else REJECT_DUPLICATE
        )
        row["reason"] = (
            "Near-duplicate of an already published pledge; leave skipped."
            if draft_payload is None
            else "Near-duplicate of an already published pledge; do not approve."
        )
        row["publication_readiness"] = "blocked_duplicate"
        return row
    if draft_payload is None:
        row["recommended_action"] = BLOCK_OTHER
        row["reason"] = "No pending draft exists for this reference item."
        return row
    if title in approved_titles or statement in approved_titles:
        row["duplicate_status"] = "near_duplicate"
        row["recommended_action"] = REJECT_DUPLICATE
        row["reason"] = "Semantically duplicate of another draft in this review batch."
        row["publication_readiness"] = "blocked_duplicate"
        return row
    if not explicit:
        row["recommended_action"] = REJECT_NOT_EXPLICIT_PROMISE
        row["reason"] = "Wording is not an explicit, trackable commitment."
        return row
    actors = (draft_payload.get("metadata") or {}).get("_resolved_actors") or []
    actor_ok = any(
        isinstance(item, dict) and item.get("politician_id") for item in actors
    )
    if not actor_ok:
        row["recommended_action"] = BLOCK_OTHER
        row["reason"] = "Draft is not linked to Giorgia Meloni as commitment owner."
        return row
    if not source_url or not introduced:
        row["recommended_action"] = BLOCK_SOURCE_ISSUE
        row["reason"] = "Declaration date or declaration source URL is missing."
        return row
    if fixture_pledge.get("date_unverified"):
        row["recommended_action"] = KEEP_PENDING_NEEDS_REVIEW
        row["reason"] = "Fixture marks the declaration date as unverified."
        row["publication_readiness"] = "kept_pending"
        return row
    if _host(str(source_url)) in FACT_CHECK_HOSTS:
        row["recommended_action"] = BLOCK_SOURCE_ISSUE
        row["reason"] = (
            "Declaration URL is a third-party fact-check, not the original statement, "
            "and the date is a year-level placeholder."
        )
        row["publication_readiness"] = "blocked_source"
        return row
    row["recommended_action"] = APPROVE_PLEDGE
    row["reason"] = "Explicit, distinct promise with declaration date and source."
    row["publication_readiness"] = "ready"
    row["classification_readiness"] = "ready"
    return row


def classification_request_for(
    fixture_pledge: dict[str, Any],
    *,
    introduced_at: date | None,
    mandate_start: date | None,
    mandate_end: date | None,
) -> PledgeClassificationRequest:
    holder = HolderRole.GOVERNMENT_COALITION
    start = mandate_start
    end = mandate_end
    note = "Editorial classification after reference-pledge approval; not yet assessed."
    if introduced_at is not None and introduced_at < CAMPAIGN_OR_GOVERNMENT_START:
        holder = HolderRole.OPPOSITION
        start = introduced_at
        end = None
        note = (
            "Opposition-era pledge. Mandate end left empty; a new end date is not invented."
        )
    return PledgeClassificationRequest(
        specificity=PledgeSpecificity(fixture_pledge.get("specificity") or "medium"),
        commitment_type=CommitmentType(fixture_pledge.get("commitment_type") or "action"),
        holder_role=holder,
        cap_topic_code=fixture_pledge.get("cap_topic_code"),
        mandate_start=start,
        mandate_end=end,
        note=note,
    )


def _reference_drafts(session: Session) -> list[ProposalDraft]:
    rows = []
    for draft in session.scalars(select(ProposalDraft).order_by(ProposalDraft.id)):
        payload = draft.proposed_data or {}
        metadata = payload.get("metadata") or {}
        identifier = str(payload.get("proposal_identifier") or "")
        if metadata.get("fixture") == "giorgia_meloni_v1" or "reference-profile:" in identifier:
            rows.append(draft)
    return rows


def _published_pledges(session: Session, politician_id: int) -> list[Proposal]:
    return list(
        session.scalars(
            select(Proposal)
            .join(ProposalActor, ProposalActor.proposal_id == Proposal.id)
            .where(
                ProposalActor.politician_id == politician_id,
                ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
                Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
                Proposal.published_at.is_not(None),
            )
            .order_by(Proposal.id)
            .distinct()
        )
    )


def _evidence_readiness(
    session: Session, proposal_id: int | None, statement: str
) -> str:
    if proposal_id is None:
        return PledgeEvidenceReadiness.ASSESSMENT_NEEDS_OFFICIAL_EVIDENCE.value
    drafts = list(
        session.scalars(
            select(PledgeAssessmentDraft).where(
                PledgeAssessmentDraft.proposal_id == proposal_id
            )
        )
    )
    if any((row.quoted_excerpt or "").strip() for row in drafts):
        return PledgeEvidenceReadiness.ASSESSMENT_EVIDENCE_AVAILABLE.value
    candidates = list(
        session.scalars(
            select(PledgeEvidenceCandidate).where(
                PledgeEvidenceCandidate.proposal_id == proposal_id
            )
        )
    )
    if candidates:
        if any((row.exact_excerpt or "").strip() for row in candidates):
            return PledgeEvidenceReadiness.ASSESSMENT_EVIDENCE_AVAILABLE.value
        return PledgeEvidenceReadiness.ASSESSMENT_SOURCE_PRESENT_BUT_NO_VERBATIM_EXCERPT.value
    statement_fold = (statement or "").strip()
    for document in session.scalars(select(RawDocument)):
        key = document.storage_key or ""
        url = document.source_url or ""
        if any(marker in key or marker in url for marker in FIXTURE_STORAGE_MARKERS):
            continue
        text = document.normalized_text or ""
        if statement_fold and statement_fold in text:
            # Programme/declaration text is not fulfilment evidence.
            continue
    return PledgeEvidenceReadiness.ASSESSMENT_NEEDS_OFFICIAL_EVIDENCE.value


def _protected_assessments(session: Session, politician_id: int) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(PledgeAssessment)
            .join(Proposal, PledgeAssessment.proposal_id == Proposal.id)
            .join(ProposalActor, ProposalActor.proposal_id == Proposal.id)
            .where(
                ProposalActor.politician_id == politician_id,
                ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
            )
            .distinct()
        )
    )
    return [
        {
            "id": row.id,
            "proposal_id": row.proposal_id,
            "verdict": row.verdict.value,
            "protected": True,
        }
        for row in rows
    ]


def _proceedings_snapshot(session: Session, politician_id: int) -> list[dict[str, Any]]:
    return [
        {"id": row.id, "title": row.title, "status": row.status.value}
        for row in session.scalars(
            select(PoliticianProceeding)
            .where(PoliticianProceeding.politician_id == politician_id)
            .order_by(PoliticianProceeding.id)
        )
    ]


def _assessment_drafts_snapshot(session: Session) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "proposal_id": row.proposal_id,
            "status": row.status.value,
            "proposed_verdict": row.proposed_verdict.value,
        }
        for row in session.scalars(
            select(PledgeAssessmentDraft).order_by(PledgeAssessmentDraft.id)
        )
    ]


def _should_reconcile(
    row: PledgeClassification,
    *,
    politician_pledge_ids: set[int],
    canonical_start: date,
) -> bool:
    if row.proposal_id not in politician_pledge_ids:
        return False
    if row.holder_role is not HolderRole.GOVERNMENT_COALITION:
        return False
    if row.mandate_start != LEGACY_MANDATE_START:
        return False
    if canonical_start != date(2022, 10, 21):
        return False
    return True


def review_reference_pledges(
    slug: str,
    *,
    session_factory: sessionmaker[Session] | None = None,
    fixture_path: Path = DEFAULT_FIXTURE,
    dry_run: bool = True,
    allow_non_unified: bool = False,
    database_url: str | None = None,
    reviewer: str = REVIEWER,
) -> dict[str, Any]:
    if configured_environment() is AppEnvironment.PRODUCTION:
        raise DemoSafetyError("review_reference_pledges refuses VERAPOLITICA_ENV=production")
    engine = None
    if session_factory is None:

        class _Args:
            unified_demo = True

        _Args.database_url = database_url
        url = resolve_database_url(_Args())
        if not allow_non_unified:
            paths = UnifiedDemoPaths.for_workspace(REPOSITORY_ROOT)
            assert_settings_are_unified(url, paths.raw_storage, REPOSITORY_ROOT)
        engine = create_db_engine(url)
        session_factory = create_session_factory(engine)

    fixture = _load_fixture(fixture_path)
    report: dict[str, Any] = {
        "slug": slug,
        "dry_run": dry_run,
        "politician_id": None,
        "politician_name": None,
        "canonical_mandate_start": None,
        "mandate_end_reused": None,
        "review_table": [],
        "approved": [],
        "already_published": [],
        "rejected": [],
        "kept_pending": [],
        "duplicate": [],
        "classified": [],
        "already_classified": [],
        "mandate_windows_reconciled": [],
        "evidence_ready": [],
        "no_evidence": [],
        "assessment_drafts_created": [],
        "assessments_untouched": [],
        "proceedings_untouched": True,
        "autonomia_untouched": True,
        "notes": [
            "Does not publish PDF implied verdicts as assessments.",
            "Does not convert PDF commentary into evidence.",
            "Does not alter proceedings, Ask, Spiegami, scoring, or Draft 2.",
            "broken still requires two distinct reviewers.",
        ],
    }
    try:
        with session_factory() as session:
            politician = resolve_politician(session, slug)
            canonical_start = published_pdc_start(session, politician) or date(2022, 10, 21)
            mandate_end = existing_mandate_end(session, politician.id)
            published = _published_pledges(session, politician.id)
            drafts = _reference_drafts(session)
            proceedings_before = _proceedings_snapshot(session, politician.id)
            assessment_drafts_before = _assessment_drafts_snapshot(session)
            assessments_before = _protected_assessments(session, politician.id)
            report["politician_id"] = politician.id
            report["politician_name"] = (
                f"{politician.canonical_given_name} {politician.canonical_family_name}"
            )
            report["canonical_mandate_start"] = canonical_start.isoformat()
            report["mandate_end_reused"] = mandate_end.isoformat() if mandate_end else None
            report["assessments_untouched"] = assessments_before
            report["assessment_drafts_before"] = assessment_drafts_before
            report["proceedings_before"] = proceedings_before

        drafts_by_identity = {}
        with session_factory() as session:
            for draft in _reference_drafts(session):
                key = _identity_key(draft.proposed_data or {})
                if key:
                    drafts_by_identity[key] = {
                        "id": draft.id,
                        "proposal_id": draft.proposal_id,
                        "status": draft.status.value,
                        "payload": draft.proposed_data or {},
                    }
            published = _published_pledges(session, report["politician_id"])
            published_ids = {item.id for item in published}

        table: list[dict[str, Any]] = []
        approve_ids: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
        approved_titles: set[str] = set()
        for fixture_pledge in fixture["pledges"]:
            pending = drafts_by_identity.get(fixture_pledge["identity_key"])
            payload = pending["payload"] if pending else None
            if pending and pending["status"] != ProposalDraftStatus.PENDING.value:
                decision = decide_pledge_action(
                    fixture_pledge,
                    draft_payload=payload,
                    published=published,
                    already_approved_titles=approved_titles,
                )
                if pending["status"] == ProposalDraftStatus.APPROVED.value:
                    decision["recommended_action"] = "ALREADY_PUBLISHED"
                    decision["reason"] = "Pledge draft already approved."
                    decision["publication_readiness"] = "already_published"
                    decision["classification_readiness"] = "ready"
                decision["draft_id"] = pending["id"]
                decision["proposal_id"] = pending["proposal_id"]
            else:
                decision = decide_pledge_action(
                    fixture_pledge,
                    draft_payload=payload,
                    published=published,
                    already_approved_titles=approved_titles,
                )
                if pending is not None:
                    decision["draft_id"] = pending["id"]
                    decision["proposal_id"] = pending["proposal_id"]
                else:
                    decision["draft_id"] = None
                    decision["proposal_id"] = decision.get("existing_similar_published_id")
            with session_factory() as session:
                decision["assessment_evidence_readiness"] = _evidence_readiness(
                    session, decision.get("proposal_id"), decision.get("promise_text") or ""
                )
            table.append(decision)
            action = decision["recommended_action"]
            if action == APPROVE_PLEDGE and pending is not None:
                approve_ids.append((pending["id"], fixture_pledge, decision))
                approved_titles.add(decision["title"])
                approved_titles.add(decision["promise_text"])
            elif action == ALREADY_SKIPPED_DUPLICATE:
                report["duplicate"].append(decision)
            elif action == REJECT_DUPLICATE:
                report["rejected"].append(decision)
                report["duplicate"].append(decision)
            elif action in {KEEP_PENDING_NEEDS_REVIEW, BLOCK_SOURCE_ISSUE, BLOCK_OTHER}:
                report["kept_pending"].append(decision)
            elif action == REJECT_NOT_EXPLICIT_PROMISE:
                report["rejected"].append(decision)
            elif action == "ALREADY_PUBLISHED":
                report["already_published"].append(decision)

        report["review_table"] = table
        reviews = ProposalReviewService(session_factory)
        pledges = PledgeService(session_factory)

        for draft_id, fixture_pledge, decision in approve_ids:
            if dry_run:
                decision["applied"] = False
                report["approved"].append(decision)
                report["classified"].append(
                    {
                        "proposal_id": decision.get("proposal_id"),
                        "title": decision["title"],
                        "action": "would_classify",
                    }
                )
                continue
            result = reviews.approve(
                draft_id, reviewer=reviewer, note=APPROVE_NOTE
            )
            decision["applied"] = True
            decision["proposal_id"] = result.proposal_id
            report["approved"].append(decision)
            introduced = date.fromisoformat(str(decision["declaration_date"]))
            request = classification_request_for(
                fixture_pledge,
                introduced_at=introduced,
                mandate_start=canonical_start,
                mandate_end=mandate_end,
            )
            classified = pledges.classify(
                result.proposal_id, request, classified_by=reviewer
            )
            report["classified"].append(
                {
                    "proposal_id": classified.proposal_id,
                    "title": decision["title"],
                    "holder_role": classified.holder_role.value,
                    "cap_topic_code": classified.cap_topic_code,
                    "specificity": classified.specificity.value,
                    "commitment_type": classified.commitment_type.value,
                    "mandate_start": classified.mandate_start.isoformat()
                    if classified.mandate_start
                    else None,
                    "mandate_end": classified.mandate_end.isoformat()
                    if classified.mandate_end
                    else None,
                    "action": "classified",
                }
            )

        reconcile_targets: list[dict[str, Any]] = []
        with session_factory() as session:
            politician_id = report["politician_id"]
            published_ids = {item.id for item in _published_pledges(session, politician_id)}
            rows = list(
                session.scalars(
                    select(PledgeClassification).order_by(PledgeClassification.proposal_id)
                )
            )
            for row in rows:
                if _should_reconcile(
                    row,
                    politician_pledge_ids=published_ids,
                    canonical_start=canonical_start,
                ):
                    reconcile_targets.append(
                        {
                            "proposal_id": row.proposal_id,
                            "specificity": row.specificity,
                            "commitment_type": row.commitment_type,
                            "holder_role": row.holder_role,
                            "cap_topic_code": row.cap_topic_code,
                            "mandate_start": row.mandate_start,
                            "mandate_end": row.mandate_end,
                            "note": row.note,
                        }
                    )
            report["unrelated_classifications_untouched"] = [
                row.proposal_id for row in rows if row.proposal_id not in published_ids
            ]

        for row in reconcile_targets:
            payload = {
                "proposal_id": row["proposal_id"],
                "from": row["mandate_start"].isoformat() if row["mandate_start"] else None,
                "to": canonical_start.isoformat(),
                "mandate_end_unchanged": row["mandate_end"].isoformat()
                if row["mandate_end"]
                else None,
            }
            if dry_run:
                payload["action"] = "would_reconcile"
                report["mandate_windows_reconciled"].append(payload)
                continue
            pledges.classify(
                row["proposal_id"],
                PledgeClassificationRequest(
                    specificity=row["specificity"],
                    commitment_type=row["commitment_type"],
                    holder_role=row["holder_role"],
                    cap_topic_code=row["cap_topic_code"],
                    mandate_start=canonical_start,
                    mandate_end=row["mandate_end"],
                    note=row["note"],
                ),
                classified_by=reviewer,
            )
            payload["action"] = "reconciled"
            report["mandate_windows_reconciled"].append(payload)

        with session_factory() as session:
            for decision in table:
                if decision["recommended_action"] not in {APPROVE_PLEDGE, "ALREADY_PUBLISHED"}:
                    if decision["recommended_action"] == ALREADY_SKIPPED_DUPLICATE:
                        continue
                    report["no_evidence"].append(
                        {
                            "proposal_id": decision.get("proposal_id"),
                            "title": decision["title"],
                            "readiness": decision["assessment_evidence_readiness"],
                        }
                    )
                    continue
                readiness = _evidence_readiness(
                    session, decision.get("proposal_id"), decision.get("promise_text") or ""
                )
                decision["assessment_evidence_readiness"] = readiness
                bucket = (
                    report["evidence_ready"]
                    if readiness == PledgeEvidenceReadiness.ASSESSMENT_EVIDENCE_AVAILABLE.value
                    else report["no_evidence"]
                )
                bucket.append(
                    {
                        "proposal_id": decision.get("proposal_id"),
                        "title": decision["title"],
                        "readiness": readiness,
                    }
                )
            report["assessments_untouched"] = _protected_assessments(
                session, report["politician_id"]
            )
            report["assessment_drafts_after"] = _assessment_drafts_snapshot(session)
            proceedings_after = _proceedings_snapshot(session, report["politician_id"])
            report["proceedings_after"] = proceedings_after
            report["proceedings_untouched"] = proceedings_after == report["proceedings_before"]
            report["assessment_drafts_untouched"] = (
                report["assessment_drafts_after"] == report["assessment_drafts_before"]
            )
            autonomia = next(
                (
                    item
                    for item in report["assessments_untouched"]
                    if item["proposal_id"]
                    and any(
                        title.startswith(PROTECTED_ASSESSMENT_TITLE_PREFIX)
                        for title in [
                            session.get(Proposal, item["proposal_id"]).canonical_title
                            if session.get(Proposal, item["proposal_id"]) is not None
                            else ""
                        ]
                    )
                ),
                None,
            )
            if autonomia is None:
                for item in report["assessments_untouched"]:
                    proposal = session.get(Proposal, item["proposal_id"])
                    if proposal is not None and "autonomia" in (
                        proposal.canonical_title or ""
                    ).casefold():
                        autonomia = item
                        break
            report["autonomia"] = autonomia
            report["published_pledge_count"] = len(
                _published_pledges(session, report["politician_id"])
            )
            report["pending_reference_drafts"] = [
                {
                    "draft_id": draft.id,
                    "proposal_id": draft.proposal_id,
                    "title": (draft.proposed_data or {}).get("title"),
                    "status": draft.status.value,
                }
                for draft in _reference_drafts(session)
                if draft.status is ProposalDraftStatus.PENDING
            ]
        return report
    finally:
        if engine is not None:
            engine.dispose()


def format_review_text(report: dict[str, Any]) -> str:
    mode = "DRY-RUN" if report["dry_run"] else "APPLY"
    lines = [
        f"{mode}  {report['politician_name']} (id {report['politician_id']})",
        f"canonical mandate start: {report['canonical_mandate_start']}",
        f"mandate end reused: {report['mandate_end_reused']}",
        "",
        "REVIEW TABLE",
    ]
    for item in report["review_table"]:
        lines.append(
            f"  PDF {item.get('pdf_number')}  draft {item.get('draft_id')}  "
            f"{item['recommended_action']}  {item['title']}"
        )
        lines.append(f"    reason: {item['reason']}")
        lines.append(
            f"    evidence: {item['assessment_evidence_readiness']}  "
            f"duplicate: {item['duplicate_status']}"
        )
    lines.extend(
        [
            "",
            f"approved: {len(report['approved'])}",
            f"already_published: {len(report['already_published'])}",
            f"rejected: {len(report['rejected'])}",
            f"kept_pending: {len(report['kept_pending'])}",
            f"duplicate: {len(report['duplicate'])}",
            f"classified: {len(report['classified'])}",
            f"mandate_windows_reconciled: {len(report['mandate_windows_reconciled'])}",
            f"evidence_ready: {len(report['evidence_ready'])}",
            f"no_evidence: {len(report['no_evidence'])}",
            f"assessment_drafts_created: {len(report['assessment_drafts_created'])}",
            f"proceedings_untouched: {report['proceedings_untouched']}",
            f"published_pledge_count: {report.get('published_pledge_count')}",
            "",
        ]
    )
    for item in report["mandate_windows_reconciled"]:
        lines.append(
            f"  mandate {item['proposal_id']}: {item['from']} -> {item['to']} "
            f"(end {item['mandate_end_unchanged']}) {item['action']}"
        )
    if report.get("autonomia"):
        item = report["autonomia"]
        lines.append(
            f"autonomia assessment {item['id']} proposal {item['proposal_id']} "
            f"{item['verdict']}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review and approve valid Meloni reference pledge drafts."
    )
    parser.add_argument("slug", help="politician slug, e.g. giorgia-meloni")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--unified-demo", action="store_true")
    parser.add_argument("--database-url")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.apply and args.dry_run:
        print("choose either --dry-run or --apply", file=sys.stderr)
        return 2
    dry_run = not args.apply
    try:
        report = review_reference_pledges(
            args.slug,
            fixture_path=args.fixture,
            dry_run=dry_run,
            allow_non_unified=False,
            database_url=args.database_url,
        )
    except (DemoSafetyError, LookupError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_review_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
