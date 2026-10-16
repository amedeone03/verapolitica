"""Read-only source-completeness and showcase-readiness classification.

This module never publishes, never invents URLs, and never turns PDF
commentary into pledge-assessment evidence.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    PledgeAssessment,
    PledgeAssessmentDraft,
    PledgeClassification,
    Politician,
    PoliticianVersion,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalDraft,
    ProposalDraftStatus,
    ProposalType,
)
from backend.app.models.politician_profile import (
    PoliticianBiography,
    PoliticianCareerEntry,
    PoliticianPosition,
    PoliticianProceeding,
    PoliticianProfileSource,
    ProceedingType,
    ProfileContentKind,
    ProfileContentStatus,
    ProfileSourceKind,
)
from backend.app.schemas.politician_profile import (
    PledgeEvidenceReadiness,
    ProceedingNature,
    SourceCompleteness,
)
from backend.app.scoring.types import HolderRole


CEO_REFERENCE_WARNING = (
    "Contenuto derivato dal documento di riferimento del CEO. "
    "Verificare fonti e formulazione prima della pubblicazione."
)
EDITORIAL_PREVIEW_BANNER = "ANTEPRIMA EDITORIALE — NON PUBBLICATO"
REFERENCE_CREATED_BY = "reference-profile-operator"
DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "fixtures"
    / "reference_profiles"
    / "giorgia_meloni_v1.json"
)
PERSONAL_JUDICIAL_TYPES = frozenset(
    {ProceedingType.JUDICIAL_PROCEEDING, ProceedingType.INVESTIGATION}
)
CONTROVERSY_TYPES = frozenset(
    {
        ProceedingType.POLITICAL_CONTROVERSY,
        ProceedingType.LEGAL_CONTROVERSY,
        ProceedingType.MEDIA_CONTROVERSY,
    }
)
CONTENT_MODELS = {
    ProfileContentKind.BIOGRAPHY: PoliticianBiography,
    ProfileContentKind.CAREER_ENTRY: PoliticianCareerEntry,
    ProfileContentKind.POSITION: PoliticianPosition,
    ProfileContentKind.PROCEEDING: PoliticianProceeding,
}


def is_complete_source_url(url: str | None) -> bool:
    if url is None:
        return False
    raw = str(url).strip()
    if not raw:
        return False
    parsed = urlsplit(raw)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def proceeding_nature(types: tuple[ProceedingType, ...] | list[str] | None) -> ProceedingNature | None:
    if not types:
        return None
    parsed = tuple(
        item if isinstance(item, ProceedingType) else ProceedingType(item) for item in types
    )
    personal = any(item in PERSONAL_JUDICIAL_TYPES for item in parsed)
    controversy = any(item in CONTROVERSY_TYPES for item in parsed)
    if personal and controversy:
        return ProceedingNature.MIXED_JUDICIAL_AND_CONTROVERSY
    if personal:
        return ProceedingNature.PERSONAL_JUDICIAL_PROCEEDING
    if controversy:
        return ProceedingNature.POLITICAL_LEGAL_MEDIA_CONTROVERSY
    return None


def ceo_warning_for(created_by: str | None) -> str | None:
    if (created_by or "").strip() == REFERENCE_CREATED_BY:
        return CEO_REFERENCE_WARNING
    return None


@dataclass(frozen=True)
class SourceAuditRow:
    name: str
    url: str | None
    kind: str
    complete: bool


@dataclass(frozen=True)
class ProfileItemAudit:
    content_type: str
    item: str
    identity_key: str
    status: str
    source_completeness: str
    source: str
    source_url: str
    blocker: str
    flags: tuple[str, ...] = ()
    publication_status: str = ProfileContentStatus.PENDING.value
    id: int | None = None


@dataclass(frozen=True)
class PledgeItemAudit:
    pdf_number: int
    title: str
    identity_key: str
    declaration_date: str | None
    declaration_source: str
    declaration_url: str | None
    matched_existing_pledge: str | None
    matched_proposal_id: int | None
    duplicate_safe: bool
    action: str
    cap_topic_code: str | None
    specificity: str | None
    commitment_type: str | None
    suggested_holder_role: str | None
    suggested_mandate_start: str | None
    suggested_mandate_end: str | None
    publication_status: str
    assessment_status: str
    evidence_readiness: tuple[str, ...]
    draft_id: int | None = None
    proposal_id: int | None = None
    notes: tuple[str, ...] = ()


@dataclass
class ShowcaseReadiness:
    politician_id: int
    politician_name: str
    biography: dict[str, int]
    career: dict[str, int]
    positions: dict[str, int]
    proceedings: dict[str, int]
    pledges: dict[str, int]
    assessments: dict[str, int]


@dataclass
class ReferenceProfileAudit:
    politician_id: int
    politician_name: str
    profile_items: list[ProfileItemAudit] = field(default_factory=list)
    pledges: list[PledgeItemAudit] = field(default_factory=list)
    readiness: ShowcaseReadiness | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


def classify_profile_item(
    *,
    kind: ProfileContentKind,
    identity_key: str,
    title: str,
    sources: list[SourceAuditRow],
    body: str | None = None,
    role: str | None = None,
    institution: str | None = None,
    start_date: date | None = None,
    position_statement: str | None = None,
    verifiable_statement: str | None = None,
    statement_date: date | None = None,
    summary: str | None = None,
    proceeding_types: tuple[ProceedingType, ...] | list[str] | None = None,
    pdc_mandate_start: date | None = None,
    publication_status: str = ProfileContentStatus.PENDING.value,
    content_id: int | None = None,
) -> ProfileItemAudit:
    named = [row for row in sources if row.name.strip()]
    complete_urls = [row for row in named if row.complete]
    incomplete = [row for row in named if not row.complete]
    source_label = "; ".join(row.name for row in named) or "(none)"
    source_url_label = "; ".join(row.url for row in complete_urls if row.url) or "(none)"
    flags: list[str] = []
    blockers: list[str] = []
    completeness = SourceCompleteness.READY_FOR_EDITORIAL_REVIEW

    if kind is ProfileContentKind.BIOGRAPHY:
        if not (body or "").strip():
            completeness = SourceCompleteness.OTHER_BLOCKER
            blockers.append("biography body is empty")
        elif not named:
            completeness = SourceCompleteness.MISSING_SOURCE_METADATA
            blockers.append("no named biography source")
        elif not complete_urls:
            completeness = SourceCompleteness.MISSING_SOURCE_URL
            blockers.append("no complete biography source URL")
        else:
            for row in incomplete:
                flags.append(f"incomplete secondary source: {row.name}")
            if incomplete:
                flags.append(
                    "at least one complete URL is present; secondary sources remain incomplete"
                )
    elif kind is ProfileContentKind.CAREER_ENTRY:
        if not (role or "").strip() or not (institution or "").strip() or start_date is None:
            completeness = SourceCompleteness.OTHER_BLOCKER
            blockers.append("career row is missing role, institution, or start_date")
        elif not named:
            completeness = SourceCompleteness.MISSING_SOURCE_METADATA
            blockers.append("no named career source")
        elif not complete_urls:
            completeness = SourceCompleteness.MISSING_SOURCE_URL
            blockers.append("no complete career source URL")
        elif _is_pdc_row(identity_key, role) and pdc_mandate_start is not None:
            if start_date != pdc_mandate_start:
                completeness = SourceCompleteness.NEEDS_FACT_CHECK
                blockers.append(
                    "career start_date "
                    f"{start_date.isoformat()} conflicts with collected PdC mandate "
                    f"{pdc_mandate_start.isoformat()}; collected mandate remains authoritative"
                )
    elif kind is ProfileContentKind.POSITION:
        if not (position_statement or "").strip() or not (verifiable_statement or "").strip():
            completeness = SourceCompleteness.OTHER_BLOCKER
            blockers.append("position is missing a statement or verifiable act")
        elif not named:
            completeness = SourceCompleteness.MISSING_SOURCE_METADATA
            blockers.append("no named position source")
        elif not complete_urls:
            completeness = SourceCompleteness.MISSING_SOURCE_URL
            blockers.append("no complete position source URL")
        elif statement_date is None:
            completeness = SourceCompleteness.NEEDS_FACT_CHECK
            blockers.append("position is missing a statement date")
    elif kind is ProfileContentKind.PROCEEDING:
        if not (summary or "").strip() or not proceeding_types:
            completeness = SourceCompleteness.OTHER_BLOCKER
            blockers.append("proceeding is missing summary or type")
        elif not named:
            completeness = SourceCompleteness.MISSING_SOURCE_METADATA
            blockers.append("no named proceeding source")
        elif not complete_urls:
            completeness = SourceCompleteness.MISSING_SOURCE_URL
            blockers.append("source URL missing; do not invent ANSA, Camera, CGUE, Governo, or Fanpage URLs")

    if completeness is SourceCompleteness.READY_FOR_EDITORIAL_REVIEW and not blockers:
        blocker = "none"
    else:
        blocker = "; ".join(blockers or flags) or completeness.value
    return ProfileItemAudit(
        content_type=kind.value,
        item=title,
        identity_key=identity_key,
        status=completeness.value,
        source_completeness=completeness.value,
        source=source_label,
        source_url=source_url_label,
        blocker=blocker,
        flags=tuple(flags),
        publication_status=publication_status,
        id=content_id,
    )


def audit_politician(
    session: Session,
    politician: Politician,
    *,
    fixture_path: Path = DEFAULT_FIXTURE,
) -> ReferenceProfileAudit:
    pdc_start = published_pdc_start(session, politician)
    mandate_end = existing_mandate_end(session, politician.id)
    items: list[ProfileItemAudit] = []
    for kind, model in CONTENT_MODELS.items():
        rows = session.scalars(
            select(model)
            .where(model.politician_id == politician.id)
            .order_by(model.id)
        )
        for row in rows:
            sources = [
                SourceAuditRow(
                    name=item.name,
                    url=item.url,
                    kind=item.kind.value if isinstance(item.kind, ProfileSourceKind) else str(item.kind),
                    complete=is_complete_source_url(item.url),
                )
                for item in _sources(session, kind, row.id)
            ]
            items.append(
                classify_profile_item(
                    kind=kind,
                    identity_key=row.identity_key,
                    title=_title(kind, row),
                    sources=sources,
                    body=getattr(row, "body", None),
                    role=getattr(row, "role", None),
                    institution=getattr(row, "institution", None),
                    start_date=getattr(row, "start_date", None),
                    position_statement=getattr(row, "position_statement", None),
                    verifiable_statement=getattr(row, "verifiable_statement", None),
                    statement_date=getattr(row, "statement_date", None),
                    summary=getattr(row, "summary", None),
                    proceeding_types=getattr(row, "proceeding_types", None),
                    pdc_mandate_start=pdc_start,
                    publication_status=row.status.value,
                    content_id=row.id,
                )
            )

    fixture = _load_fixture(fixture_path) if fixture_path.exists() else None
    pledges = audit_pledges(
        session,
        politician,
        fixture=fixture,
        suggested_mandate_start=pdc_start,
        suggested_mandate_end=mandate_end,
    )
    readiness = build_readiness(politician, items, pledges, session)
    notes = [
        "Read-only audit. No records were approved or published.",
        "Declaration sources are not assessment evidence.",
        "PDF explanatory prose is not a verbatim official excerpt.",
        "The published autonomia assessment is not modified.",
        "broken still requires two distinct reviewers.",
    ]
    return ReferenceProfileAudit(
        politician_id=politician.id,
        politician_name=f"{politician.canonical_given_name} {politician.canonical_family_name}",
        profile_items=items,
        pledges=pledges,
        readiness=readiness,
        notes=notes,
    )


def audit_pledges(
    session: Session,
    politician: Politician,
    *,
    fixture: dict[str, Any] | None,
    suggested_mandate_start: date | None,
    suggested_mandate_end: date | None,
) -> list[PledgeItemAudit]:
    published = _published_pledges(session, politician.id)
    drafts = _reference_pledge_drafts(session)
    assessments = {
        row.proposal_id: row
        for row in session.scalars(select(PledgeAssessment))
    }
    classifications = {
        row.proposal_id: row
        for row in session.scalars(select(PledgeClassification))
    }
    assessment_drafts = list(session.scalars(select(PledgeAssessmentDraft)))
    rows: list[PledgeItemAudit] = []
    spec = (fixture or {}).get("pledges") or []
    for pledge in spec:
        match = _match_published(pledge, published)
        identity = pledge["identity_key"]
        draft = drafts.get(identity)
        publication = "pending_draft"
        assessment_status = "none"
        action = "create_proposal_draft"
        matched_title = None
        matched_id = None
        duplicate_safe = True
        if match is not None:
            matched_title = match.canonical_title
            matched_id = match.id
            duplicate_safe = False
            action = "matched_skip_duplicate"
            publication = "published_existing"
            stored = assessments.get(match.id)
            assessment_status = stored.verdict.value if stored else "not_yet_rated"
        elif draft is not None:
            publication = "pending_draft"
            action = "proposal_draft_pending"
            stored = assessments.get(draft.proposal_id)
            assessment_status = stored.verdict.value if stored else "none"
        readiness: list[str] = []
        notes: list[str] = [
            "Keep the declaration source separate from assessment evidence.",
            "Do not treat a campaign statement as proof of fulfilment.",
        ]
        if match is not None:
            readiness.append(PledgeEvidenceReadiness.ASSESSMENT_NEEDS_OFFICIAL_EVIDENCE.value)
            notes.append("Near-duplicate of an already published pledge; do not create another.")
        else:
            readiness.append(PledgeEvidenceReadiness.PLEDGE_READY_FOR_REVIEW.value)
            if draft is not None and draft.proposal_id in classifications:
                pass
            else:
                readiness.append(PledgeEvidenceReadiness.PLEDGE_NEEDS_CLASSIFICATION.value)
            evidence_available = _assessment_evidence_available(
                assessment_drafts, draft.proposal_id if draft else None
            )
            if evidence_available:
                readiness.append(PledgeEvidenceReadiness.ASSESSMENT_EVIDENCE_AVAILABLE.value)
            else:
                readiness.append(
                    PledgeEvidenceReadiness.ASSESSMENT_NEEDS_OFFICIAL_EVIDENCE.value
                )
            notes.append(
                "After pledge approval, classify using the suggested CAP/topic fields. "
                "Do not create an assessment from PDF commentary."
            )
        if pledge.get("date_unverified"):
            notes.append("declaration date marked unverified in the fixture")
        declaration_url = pledge.get("declaration_url")
        rows.append(
            PledgeItemAudit(
                pdf_number=pledge["number"],
                title=pledge["title"],
                identity_key=identity,
                declaration_date=pledge.get("introduced_at"),
                declaration_source=pledge.get("origin_label") or "",
                declaration_url=declaration_url,
                matched_existing_pledge=matched_title,
                matched_proposal_id=matched_id,
                duplicate_safe=duplicate_safe,
                action=action,
                cap_topic_code=pledge.get("cap_topic_code"),
                specificity=pledge.get("specificity"),
                commitment_type=pledge.get("commitment_type"),
                suggested_holder_role=HolderRole.GOVERNMENT_COALITION.value,
                suggested_mandate_start=(
                    suggested_mandate_start.isoformat() if suggested_mandate_start else None
                ),
                suggested_mandate_end=(
                    suggested_mandate_end.isoformat() if suggested_mandate_end else None
                ),
                publication_status=publication,
                assessment_status=assessment_status,
                evidence_readiness=tuple(readiness),
                draft_id=draft.id if draft else None,
                proposal_id=draft.proposal_id if draft else matched_id,
                notes=tuple(notes),
            )
        )
    return rows


def build_readiness(
    politician: Politician,
    items: list[ProfileItemAudit],
    pledges: list[PledgeItemAudit],
    session: Session,
) -> ShowcaseReadiness:
    def bucket(kind: str) -> dict[str, int]:
        subset = [item for item in items if item.content_type == kind]
        pending = [item for item in subset if item.publication_status == "pending"]
        published = [item for item in subset if item.publication_status == "published"]
        ready = [
            item
            for item in pending
            if item.source_completeness == SourceCompleteness.READY_FOR_EDITORIAL_REVIEW.value
        ]
        missing_url = [
            item
            for item in pending
            if item.source_completeness == SourceCompleteness.MISSING_SOURCE_URL.value
        ]
        missing_meta = [
            item
            for item in pending
            if item.source_completeness == SourceCompleteness.MISSING_SOURCE_METADATA.value
        ]
        fact_check = [
            item
            for item in pending
            if item.source_completeness == SourceCompleteness.NEEDS_FACT_CHECK.value
        ]
        other = [
            item
            for item in pending
            if item.source_completeness == SourceCompleteness.OTHER_BLOCKER.value
        ]
        return {
            "pending": len(pending),
            "review_ready": len(ready),
            "missing_sources": len(missing_url),
            "missing_source_metadata": len(missing_meta),
            "needs_fact_check": len(fact_check),
            "other_blocker": len(other),
            "published": len(published),
        }

    published_pledges = _published_pledges(session, politician.id)
    pending_drafts = [row for row in pledges if row.action == "proposal_draft_pending"]
    skipped = [row for row in pledges if row.action == "matched_skip_duplicate"]
    assessments = list(
        session.scalars(
            select(PledgeAssessment).where(
                PledgeAssessment.proposal_id.in_([row.id for row in published_pledges] or [0])
            )
        )
    )
    new_assessment_drafts = 0
    return ShowcaseReadiness(
        politician_id=politician.id,
        politician_name=f"{politician.canonical_given_name} {politician.canonical_family_name}",
        biography=bucket("biography"),
        career=bucket("career_entry"),
        positions=bucket("position"),
        proceedings=bucket("proceeding"),
        pledges={
            "published": len(published_pledges),
            "pending_drafts": len(pending_drafts),
            "reference_duplicates_skipped": len(skipped),
        },
        assessments={
            "published": len(assessments),
            "new_drafts": new_assessment_drafts,
            "require_evidence": len(
                [
                    row
                    for row in pledges
                    if PledgeEvidenceReadiness.ASSESSMENT_NEEDS_OFFICIAL_EVIDENCE.value
                    in row.evidence_readiness
                    and row.action != "matched_skip_duplicate"
                ]
            ),
        },
    )


def format_audit_text(audit: ReferenceProfileAudit) -> str:
    lines = [
        f"Politician: {audit.politician_name} (id {audit.politician_id})",
        "",
        f"{'CONTENT TYPE':<16} {'ITEM':<62} {'STATUS':<32} {'SOURCE':<42} {'SOURCE URL':<48} BLOCKER",
        "-" * 220,
    ]
    for item in audit.profile_items:
        lines.append(
            f"{item.content_type:<16} {_clip(item.item, 62):<62} "
            f"{item.status:<32} {_clip(item.source, 42):<42} "
            f"{_clip(item.source_url, 48):<48} {item.blocker}"
        )
        for flag in item.flags:
            lines.append(f"{'':<16}  flag: {flag}")
    lines.extend(["", "PLEDGES", "-" * 80])
    for row in audit.pledges:
        lines.append(
            f"PDF {row.pdf_number:>2}  {row.title}  [{row.action}]  "
            f"declaration={row.declaration_url or '(none)'}  "
            f"evidence={','.join(row.evidence_readiness)}"
        )
    lines.extend(["", *audit.notes])
    return "\n".join(lines)


def format_report_text(audit: ReferenceProfileAudit) -> str:
    ready = audit.readiness
    if ready is None:
        return "No readiness data."
    bio = ready.biography
    career = ready.career
    positions = ready.positions
    proceedings = ready.proceedings
    pledges = ready.pledges
    assessments = ready.assessments
    return "\n".join(
        [
            f"Politician: {ready.politician_name} (id {ready.politician_id})",
            "",
            "Biography:",
            f"{bio['pending']} pending",
            f"{bio['review_ready']} review-ready",
            f"{bio['published']} published",
            "",
            "Career:",
            f"{career['pending']} pending",
            f"{career['review_ready']} review-ready",
            f"{career['missing_sources']} missing sources",
            f"{career['needs_fact_check']} needs fact check",
            f"{career['published']} published",
            "",
            "Positions:",
            f"{positions['pending']} pending",
            f"{positions['review_ready']} review-ready",
            f"{positions['published']} published",
            "",
            "Proceedings:",
            f"{proceedings['pending']} pending",
            f"{proceedings['review_ready']} review-ready",
            f"{proceedings['missing_sources']} missing source URLs",
            f"{proceedings['published']} published",
            "",
            "Pledges:",
            f"{pledges['published']} published",
            f"{pledges['pending_drafts']} pending drafts",
            f"{pledges['reference_duplicates_skipped']} reference duplicates skipped",
            "",
            "Assessments:",
            f"{assessments['published']} published",
            f"{assessments['new_drafts']} new drafts",
            f"{assessments['require_evidence']} require evidence",
        ]
    )


def resolve_politician(session: Session, slug: str) -> Politician:
    folded = slug.strip().casefold().replace("_", "-")
    given, family = "Giorgia", "Meloni"
    if folded not in {"giorgia-meloni", "giorgia-meloni-v1", "giorgia"}:
        parts = [part for part in folded.split("-") if part]
        if len(parts) >= 2:
            given, family = parts[0].title(), parts[-1].title()
    query = select(Politician).where(
        Politician.canonical_given_name == given,
        Politician.canonical_family_name == family,
    )
    rows = list(session.scalars(query))
    if len(rows) != 1:
        raise LookupError(f"expected one politician for {slug!r}, found {len(rows)}")
    return rows[0]


def published_pdc_start(session: Session, politician: Politician) -> date | None:
    if politician.current_version_id is None:
        return None
    version = session.get(PoliticianVersion, politician.current_version_id)
    if version is None:
        return None
    for mandate in version.profile_data.get("mandates") or []:
        blob = " ".join(
            str(mandate.get(key) or "")
            for key in ("office", "mandate_type", "role", "institution")
        ).casefold()
        if "presidente del consiglio" in blob:
            raw = mandate.get("start_date")
            if raw:
                return date.fromisoformat(str(raw)[:10])
    return None


def existing_mandate_end(session: Session, politician_id: int) -> date | None:
    published = _published_pledges(session, politician_id)
    if not published:
        return None
    row = session.scalar(
        select(PledgeClassification).where(
            PledgeClassification.proposal_id.in_([item.id for item in published]),
            PledgeClassification.mandate_end.is_not(None),
        )
    )
    return row.mandate_end if row is not None else None


def audit_from_factory(
    session_factory: sessionmaker[Session],
    slug: str,
    *,
    fixture_path: Path = DEFAULT_FIXTURE,
) -> ReferenceProfileAudit:
    with session_factory() as session:
        politician = resolve_politician(session, slug)
        return audit_politician(session, politician, fixture_path=fixture_path)


def _sources(
    session: Session, kind: ProfileContentKind, content_id: int
) -> list[PoliticianProfileSource]:
    return list(
        session.scalars(
            select(PoliticianProfileSource)
            .where(
                PoliticianProfileSource.content_kind == kind,
                PoliticianProfileSource.content_id == content_id,
            )
            .order_by(PoliticianProfileSource.sort_index, PoliticianProfileSource.id)
        )
    )


def _title(kind: ProfileContentKind, row: Any) -> str:
    if kind is ProfileContentKind.BIOGRAPHY:
        return "Biografia"
    if kind is ProfileContentKind.CAREER_ENTRY:
        return row.role
    if kind is ProfileContentKind.POSITION:
        return row.topic
    return row.title


def _is_pdc_row(identity_key: str, role: str | None) -> bool:
    blob = f"{identity_key} {role or ''}".casefold()
    return "consiglio" in blob and "presidente" in blob


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
            .distinct()
        )
    )


def _reference_pledge_drafts(session: Session) -> dict[str, ProposalDraft]:
    found: dict[str, ProposalDraft] = {}
    for draft in session.scalars(
        select(ProposalDraft).where(ProposalDraft.status == ProposalDraftStatus.PENDING)
    ):
        payload = draft.proposed_data or {}
        metadata = payload.get("metadata") or {}
        identifier = str(payload.get("proposal_identifier") or "")
        if metadata.get("fixture") != "giorgia_meloni_v1" and "reference-profile:" not in identifier:
            continue
        key = identifier.rsplit(":", 1)[-1] if "pledge:" in identifier else ""
        if key:
            found[key] = draft
    return found


def _match_published(pledge: dict[str, Any], existing: list[Proposal]) -> Proposal | None:
    phrases = [str(item).casefold() for item in pledge.get("match_phrases") or []]
    for proposal in existing:
        haystack = f"{proposal.canonical_title} {proposal.exact_statement or ''}".casefold()
        if any(phrase and phrase in haystack for phrase in phrases):
            return proposal
    return None


def _assessment_evidence_available(
    drafts: list[PledgeAssessmentDraft], proposal_id: int | None
) -> bool:
    if proposal_id is None:
        return False
    return any(
        row.proposal_id == proposal_id and (row.quoted_excerpt or "").strip()
        for row in drafts
    )


def _load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _clip(value: str, width: int) -> str:
    text = value.replace("\n", " ")
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"
