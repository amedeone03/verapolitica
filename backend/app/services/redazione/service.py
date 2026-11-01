"""The redazione console's single entry point.

Everything an editor does goes through here, so three rules hold everywhere:

1. **Nothing reaches the citizen without a second person.** Every block of a
   profile, every promise, every promise status, every news item and every
   withdrawal or re-classification is first a draft or a change request; a
   member other than its author approves it (rule 8 of the "Modelli di
   scrittura": chi scrive non è chi verifica). "Non mantenuta" needs two
   approvers, neither of them the author.
2. **Every change is logged.** One append-only ``EditorialLogEntry`` per write,
   edit, approval, rejection, withdrawal and status assignment.
3. **The writing rules are checked.** ``style`` findings are attached to every
   draft; findings at level ``error`` (open square brackets, missing sources,
   no sources from both sides in a news item) block approval.

The service reuses the domain services (profile content, proposals, pledges,
editorial posts): it adds the people, the log and the checks, not a parallel
publication path.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    ChangeRequestStatus,
    EditorialChangeRequest,
    EditorialImage,
    EditorialLogEntry,
    EditorialPost,
    EditorialPostStatus,
    FeedScope,
    PledgeAssessment,
    PledgeAssessmentDraft,
    PledgeAssessmentDraftStatus,
    PledgeAssessmentOrigin,
    PledgeClassification,
    PoliticalParty,
    Politician,
    PoliticianSourceIdentifier,
    PoliticianVersion,
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
    DatePrecision,
    PoliticianBiography,
    PoliticianCareerEntry,
    PoliticianPosition,
    PoliticianProceeding,
    PoliticianProfileSource,
    ProceedingOutcome,
    ProceedingType,
    ProfileContentKind,
    ProfileContentStatus,
    ProfileSourceKind,
)
from backend.app.schemas import ProposalObservation
from backend.app.schemas.feed import Citation, EditorialPostRequest
from backend.app.schemas.pledge import PledgeAssessmentProposal, PledgeClassificationRequest
from backend.app.schemas.politician_profile import (
    BiographyDraftInput,
    CareerEntryDraftInput,
    PositionDraftInput,
    ProceedingDraftInput,
    ProfileSourceInput,
)
from backend.app.scoring.types import (
    CommitmentType,
    EvidenceLabel,
    FulfillmentVerdict,
    HolderRole,
    PledgeSpecificity,
)
from backend.app.services.editorial_service import (
    EditorialConflictError,
    EditorialService,
    EditorialValidationError,
)
from backend.app.services.pledge_service import (
    NewAssessmentDraft,
    PledgeConflictError,
    PledgeService,
    PledgeServiceError,
    approvals_required,
)
from backend.app.services.politician_profile_service import (
    PoliticianProfileService,
    PoliticianProfileServiceError,
)
from backend.app.services.proposal_review_service import (
    ProposalReviewService,
    ProposalReviewServiceError,
)
from backend.app.services.proposal_service import ProposalService, ProposalServiceError
from backend.app.services.public_politician_service import PublicPoliticianQueryService
from backend.app.services.redazione import card as card_module
from backend.app.services.redazione import style


# --------------------------------------------------------------------- errors
class RedazioneError(RuntimeError):
    status_code = 400

    def __init__(self, message: str, findings: list[dict] | None = None) -> None:
        super().__init__(message)
        self.findings = findings or []


class RedazioneNotFound(RedazioneError):
    status_code = 404


class RedazioneConflict(RedazioneError):
    status_code = 409


class RedazioneValidation(RedazioneError):
    status_code = 422


# ------------------------------------------------------------------ vocabulary
PROFILE_KINDS = {
    "biography": ProfileContentKind.BIOGRAPHY,
    "career_entry": ProfileContentKind.CAREER_ENTRY,
    "position": ProfileContentKind.POSITION,
    "proceeding": ProfileContentKind.PROCEEDING,
}
PROFILE_MODELS = {
    "biography": PoliticianBiography,
    "career_entry": PoliticianCareerEntry,
    "position": PoliticianPosition,
    "proceeding": PoliticianProceeding,
}
KIND_LABELS = {
    "biography": "Chi è",
    "career_entry": "Cosa ha fatto",
    "position": "Posizione su tema chiave",
    "proceeding": "Procedimento o controversia",
    "promise": "Promessa",
    "proposal": "Proposta",
    "status": "Stato di una promessa",
    "news": "Notizia",
    "change": "Modifica a contenuto pubblico",
    "image": "Immagine",
}
VERDICT_LABELS = {
    "kept": "Mantenuta",
    "partially_kept": "Parzialmente mantenuta",
    "in_progress": "In corso",
    "stalled": "Iter bloccato",
    "broken": "Non mantenuta",
    "not_yet_rated": "Da valutare",
}
# What evidence label each status implies (see scoring.types).
VERDICT_EVIDENCE = {
    FulfillmentVerdict.KEPT: EvidenceLabel.SUPPORTS,
    FulfillmentVerdict.PARTIALLY_KEPT: EvidenceLabel.SUPPORTS,
    FulfillmentVerdict.IN_PROGRESS: EvidenceLabel.SUPPORTS,
    FulfillmentVerdict.STALLED: EvidenceLabel.REFUTES,
    FulfillmentVerdict.BROKEN: EvidenceLabel.REFUTES,
}
# "Non mantenuta: solo se la scadenza dichiarata è passata senza risultato, o il
# mandato è finito, o c'è una rinuncia esplicita."
BROKEN_REASONS = {
    "scadenza_passata": "La scadenza dichiarata è passata senza risultato",
    "mandato_concluso": "Il mandato è finito",
    "rinuncia_esplicita": "Rinuncia esplicita",
}
SOURCE_KIND_BY_AREA = {
    "istituzionale": ProfileSourceKind.INSTITUTIONAL,
    "ufficiale": ProfileSourceKind.OFFICIAL,
    "agenzia": ProfileSourceKind.NEWS,
    "stampa": ProfileSourceKind.NEWS,
    "centrodestra": ProfileSourceKind.NEWS,
    "centrosinistra": ProfileSourceKind.NEWS,
    "tecnica": ProfileSourceKind.OTHER,
    "partito": ProfileSourceKind.PARTY_POLITICIAN,
    "altro": ProfileSourceKind.OTHER,
}
SYSTEM_AUTHOR = "Importazione"
COLLECTOR = "redazione/v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_MONTHS = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
           "agosto", "settembre", "ottobre", "novembre", "dicembre")


def _long_date(value: date) -> str:
    """Dates are written in full (Modelli di scrittura): «16 settembre 2026»."""

    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return text[:60] or "voce"


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_date(value: Any, field: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise RedazioneValidation(f"{field}: data non valida") from error


def _clean(value: Any) -> str:
    return str(value or "").strip()


class RedazioneService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.profiles = PoliticianProfileService(session_factory)
        self.pledges = PledgeService(session_factory, clock=clock)
        self.proposals = ProposalService(session_factory)
        self.proposal_review = ProposalReviewService(session_factory)
        self.editorial = EditorialService(session_factory, clock=clock)

    # ------------------------------------------------------------------- log
    def _log(
        self,
        session: Session,
        *,
        actor: str,
        action: str,
        object_kind: str,
        object_id: int | None,
        summary: str,
        politician_id: int | None = None,
        details: dict | None = None,
    ) -> None:
        session.add(
            EditorialLogEntry(
                created_at=self.clock(),
                actor=actor,
                action=action,
                object_kind=object_kind,
                object_id=object_id,
                politician_id=politician_id,
                summary=summary[:2000],
                details=details,
            )
        )

    def log(self, **entry: Any) -> None:
        with self.session_factory.begin() as session:
            self._log(session, **entry)

    def log_entries(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        politician_id: int | None = None,
        actor: str | None = None,
    ) -> dict:
        with self.session_factory() as session:
            query = select(EditorialLogEntry)
            count = select(func.count()).select_from(EditorialLogEntry)
            if politician_id is not None:
                query = query.where(EditorialLogEntry.politician_id == politician_id)
                count = count.where(EditorialLogEntry.politician_id == politician_id)
            if actor:
                query = query.where(EditorialLogEntry.actor == actor)
                count = count.where(EditorialLogEntry.actor == actor)
            rows = session.scalars(
                query.order_by(EditorialLogEntry.created_at.desc(), EditorialLogEntry.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            names = self._politician_names(session, {row.politician_id for row in rows if row.politician_id})
            return {
                "total": session.scalar(count) or 0,
                "items": [
                    {
                        "id": row.id,
                        "at": _iso(row.created_at),
                        "actor": row.actor,
                        "action": row.action,
                        "object_kind": row.object_kind,
                        "object_label": KIND_LABELS.get(row.object_kind, row.object_kind),
                        "object_id": row.object_id,
                        "politician_id": row.politician_id,
                        "politician_name": names.get(row.politician_id),
                        "summary": row.summary,
                        "details": row.details,
                    }
                    for row in rows
                ],
            }

    # ---------------------------------------------------------- politicians
    @staticmethod
    def _politician_names(session: Session, ids: set[int]) -> dict[int, str]:
        if not ids:
            return {}
        return {
            row.id: f"{row.canonical_given_name} {row.canonical_family_name}"
            for row in session.scalars(select(Politician).where(Politician.id.in_(ids)))
        }

    @staticmethod
    def _require_politician(session: Session, politician_id: int) -> Politician:
        politician = session.get(Politician, politician_id)
        if politician is None:
            raise RedazioneNotFound("politico non trovato")
        return politician

    def search_politicians(self, query: str = "", *, limit: int = 30) -> list[dict]:
        with self.session_factory() as session:
            statement = select(Politician)
            text = query.strip()
            if text:
                like = f"%{text.casefold()}%"
                statement = statement.where(
                    or_(
                        func.lower(Politician.canonical_family_name).like(like),
                        func.lower(Politician.canonical_given_name).like(like),
                        func.lower(
                            Politician.canonical_given_name + " " + Politician.canonical_family_name
                        ).like(like),
                    )
                )
            rows = session.scalars(
                statement.order_by(Politician.canonical_family_name, Politician.canonical_given_name).limit(limit)
            ).all()
            pending = self._pending_by_politician(session)
            parties = card_module.current_parties(session, [row.id for row in rows])
            return [
                {
                    "id": row.id,
                    "name": f"{row.canonical_given_name} {row.canonical_family_name}",
                    "party": card_module.party_dict(parties[row.id]) if row.id in parties else None,
                    "birth_date": _iso(row.birth_date),
                    "public": row.current_version_id is not None,
                    "pending": pending.get(row.id, 0),
                }
                for row in rows
            ]

    def _pending_by_politician(self, session: Session) -> dict[int, int]:
        counts: dict[int, int] = {}
        for model in PROFILE_MODELS.values():
            for politician_id, count in session.execute(
                select(model.politician_id, func.count())
                .where(model.status == ProfileContentStatus.PENDING)
                .group_by(model.politician_id)
            ):
                counts[politician_id] = counts.get(politician_id, 0) + count
        for draft, politician_id in self._pending_proposal_drafts(session):
            if politician_id:
                counts[politician_id] = counts.get(politician_id, 0) + 1
        return counts

    # ---------------------------------------------------------------- scheda
    def scheda(self, politician_id: int, *, member: str) -> dict:
        with self.session_factory() as session:
            politician = self._require_politician(session, politician_id)
            public = PublicPoliticianQueryService(session).get(politician_id)
            version = (
                session.get(PoliticianVersion, politician.current_version_id)
                if politician.current_version_id
                else None
            )
            profile_data = dict(version.profile_data or {}) if version else {}
            blocks = {
                kind: self._profile_items(session, kind, politician_id, member)
                for kind in PROFILE_MODELS
            }
            promises = self._promises(session, politician_id, member)
            people = self._people(blocks, promises)
            news = self._related_news(session, politician_id)
            changes = self._change_requests(session, politician_id=politician_id, member=member)
            office = None
            party = None
            if public is not None:
                mandates = [item for item in public.profile.mandates if item.end_date is None]
                if mandates:
                    current = max(mandates, key=lambda item: item.start_date)
                    office = f"{current.office}, {current.institution}"
                    office_since = current.start_date
                else:
                    office_since = None
                parties = [item for item in public.political_parties if item.end_date is None]
                party = parties[0].name if parties else None
            else:
                office_since = None
            updated = max(
                [
                    *(item["published_at"] for kind in blocks for item in blocks[kind] if item["published_at"]),
                    *(item["verdict_at"] for item in promises if item.get("verdict_at")),
                ],
                default=None,
            )
            return {
                "id": politician.id,
                "name": f"{politician.canonical_given_name} {politician.canonical_family_name}",
                "public_url": f"/app/?politician={politician.id}" if public is not None else None,
                "is_public": public is not None,
                "scheda_rapida": {
                    "birth_date": _iso(politician.birth_date),
                    "birth_place": _place(profile_data.get("birth_place")),
                    "party": party,
                    "office": office,
                    "office_since": _iso(office_since),
                    "updated_at": updated,
                    "writers": people["writers"],
                    "verifiers": people["verifiers"],
                },
                "blocks": blocks,
                "promises": promises,
                "news": news,
                "changes": changes,
                "checklist": self._scheda_checklist(blocks, promises),
            }

    def _profile_items(self, session: Session, kind: str, politician_id: int, member: str) -> list[dict]:
        model = PROFILE_MODELS[kind]
        rows = session.scalars(
            select(model)
            .where(
                model.politician_id == politician_id,
                model.status.in_((ProfileContentStatus.PUBLISHED, ProfileContentStatus.PENDING)),
            )
            .order_by(model.id)
        ).all()
        return [self._profile_item(session, kind, row, member) for row in rows]

    def _profile_item(self, session: Session, kind: str, row: Any, member: str) -> dict:
        data = self._profile_fields(kind, row)
        data["sources"] = self._sources(session, PROFILE_KINDS[kind], row.id)
        findings = [item.as_dict() for item in style.profile_findings(kind, data)]
        return {
            "kind": kind,
            "id": row.id,
            "identity_key": row.identity_key,
            "status": row.status.value,
            "created_by": row.created_by,
            "reviewed_by": row.reviewed_by,
            "published_at": _iso(row.published_at),
            "created_at": _iso(row.created_at),
            "data": data,
            "findings": findings,
            "can_approve": row.status is ProfileContentStatus.PENDING and row.created_by != member,
        }

    @staticmethod
    def _profile_fields(kind: str, row: Any) -> dict:
        if kind == "biography":
            return {"body": row.body}
        if kind == "career_entry":
            return {
                "role": row.role,
                "institution": row.institution,
                "party_or_group": row.party_or_group,
                "start_date": _iso(row.start_date),
                "end_date": _iso(row.end_date),
                "is_current": row.is_current,
                "start_precision": row.start_precision.value if row.start_precision else None,
            }
        if kind == "position":
            return {
                "topic": row.topic,
                "position_statement": row.position_statement,
                "verifiable_statement": row.verifiable_statement,
                "statement_date": _iso(row.statement_date),
            }
        return {
            "title": row.title,
            "proceeding_types": list(row.proceeding_types or []),
            "event_date": _iso(row.event_date),
            "outcome": row.outcome.value if row.outcome else None,
            "outcome_date": _iso(row.outcome_date),
            "summary": row.summary,
            "outcome_summary": row.outcome_summary,
        }

    @staticmethod
    def _sources(session: Session, kind: ProfileContentKind, content_id: int) -> list[dict]:
        return [
            {
                "name": row.name,
                "title": row.title,
                "url": row.url,
                "kind": row.kind.value,
                "excerpt": row.excerpt,
            }
            for row in session.scalars(
                select(PoliticianProfileSource)
                .where(
                    PoliticianProfileSource.content_kind == kind,
                    PoliticianProfileSource.content_id == content_id,
                )
                .order_by(PoliticianProfileSource.sort_index)
            )
        ]

    @staticmethod
    def _people(blocks: dict, promises: list[dict]) -> dict:
        writers: list[str] = []
        verifiers: list[str] = []
        for items in blocks.values():
            for item in items:
                if item["status"] != "published":
                    continue
                if item["created_by"] and item["created_by"] not in writers:
                    writers.append(item["created_by"])
                if item["reviewed_by"] and item["reviewed_by"] not in verifiers:
                    verifiers.append(item["reviewed_by"])
        for promise in promises:
            for name in promise.get("verdict_approved_by") or []:
                if name not in verifiers:
                    verifiers.append(name)
        return {"writers": writers, "verifiers": verifiers}

    @staticmethod
    def _scheda_checklist(blocks: dict, promises: list[dict]) -> list[dict]:
        published = {kind: [item for item in items if item["status"] == "published"] for kind, items in blocks.items()}
        positions = len(published["position"])
        return [
            {"key": "chi_e", "label": "«Chi è» pubblicato (50–80 parole di fatti)", "ok": bool(published["biography"])},
            {"key": "carriera", "label": "«Cosa ha fatto»: incarichi con data", "ok": bool(published["career_entry"])},
            {"key": "posizioni", "label": f"Posizioni su temi chiave: {positions} di 3–5", "ok": 3 <= positions <= 5},
            {
                "key": "promesse",
                "label": "Promesse con data, fonte e stato",
                "ok": bool(promises) and all(item["published"] and item["classified"] for item in promises),
            },
            {
                "key": "parentesi",
                "label": "Nessuna parentesi quadra aperta",
                "ok": not any(
                    finding["code"] == "parentesi_aperte"
                    for items in blocks.values()
                    for item in items
                    for finding in item["findings"]
                ),
            },
        ]

    # ------------------------------------------------------- profile blocks
    def save_profile_block(self, politician_id: int, kind: str, payload: dict, *, member: str) -> dict:
        if kind not in PROFILE_MODELS:
            raise RedazioneNotFound("blocco sconosciuto")
        sources = self._source_inputs(payload.get("sources") or [])
        identity = _clean(payload.get("identity_key"))
        with self.session_factory() as session:
            self._require_politician(session, politician_id)
        try:
            if kind == "biography":
                body = _clean(payload.get("body"))
                if not body:
                    raise RedazioneValidation("Il testo di «Chi è» è vuoto.")
                identity = identity or "primary"
                fields = {"body": body}
                draft = BiographyDraftInput(identity_key=identity, body=body, sources=sources, created_by=member)
            elif kind == "career_entry":
                start = _parse_date(payload.get("start_date"), "inizio")
                if start is None:
                    raise RedazioneValidation("Ogni incarico ha una data di inizio.")
                fields = {
                    "role": _clean(payload.get("role")),
                    "institution": _clean(payload.get("institution")),
                    "party_or_group": _clean(payload.get("party_or_group")) or None,
                    "start_date": start,
                    "end_date": _parse_date(payload.get("end_date"), "fine"),
                    "is_current": bool(payload.get("is_current")),
                    "start_precision": DatePrecision(payload.get("start_precision") or "day"),
                }
                identity = identity or _slug(f"{fields['role']}-{fields['institution']}-{start.year}")
                draft = CareerEntryDraftInput(identity_key=identity, sources=sources, created_by=member, **fields)
            elif kind == "position":
                fields = {
                    "topic": _clean(payload.get("topic")),
                    "position_statement": _clean(payload.get("position_statement")),
                    "verifiable_statement": _clean(payload.get("verifiable_statement")),
                    "statement_date": _parse_date(payload.get("statement_date"), "data"),
                    "statement_precision": DatePrecision.DAY if payload.get("statement_date") else None,
                }
                identity = identity or _slug(fields["topic"])
                draft = PositionDraftInput(identity_key=identity, sources=sources, created_by=member, **fields)
            else:
                types = tuple(ProceedingType(item) for item in (payload.get("proceeding_types") or []))
                fields = {
                    "title": _clean(payload.get("title")),
                    "proceeding_types": types,
                    "event_date": _parse_date(payload.get("event_date"), "data"),
                    "event_precision": DatePrecision.DAY if payload.get("event_date") else None,
                    "outcome": ProceedingOutcome(payload["outcome"]) if payload.get("outcome") else None,
                    "outcome_date": _parse_date(payload.get("outcome_date"), "data esito"),
                    "summary": _clean(payload.get("summary")),
                    "outcome_summary": _clean(payload.get("outcome_summary")) or None,
                }
                identity = identity or _slug(fields["title"])
                draft = ProceedingDraftInput(identity_key=identity, sources=sources, created_by=member, **fields)
        except (ValueError, TypeError) as error:
            if isinstance(error, RedazioneError):
                raise
            raise RedazioneValidation(f"Dati non validi: {error}") from error

        model = PROFILE_MODELS[kind]
        with self.session_factory.begin() as session:
            pending = session.scalar(
                select(model).where(
                    model.politician_id == politician_id,
                    model.identity_key == identity,
                    model.status == ProfileContentStatus.PENDING,
                )
            )
            if pending is not None:
                before = self._profile_fields(kind, pending)
                for name, value in fields.items():
                    if name == "proceeding_types":
                        value = [item.value for item in value]
                    setattr(pending, name, value)
                previous_author = pending.created_by
                pending.created_by = member
                pending.updated_at = self.clock()
                for old in session.scalars(
                    select(PoliticianProfileSource).where(
                        PoliticianProfileSource.content_kind == PROFILE_KINDS[kind],
                        PoliticianProfileSource.content_id == pending.id,
                    )
                ):
                    session.delete(old)
                session.flush()
                self.profiles._store_sources(session, PROFILE_KINDS[kind], pending.id, sources)
                session.flush()
                content_id = pending.id
                self._log(
                    session,
                    actor=member,
                    action="modifica",
                    object_kind=kind,
                    object_id=content_id,
                    politician_id=politician_id,
                    summary=f"Modificata la bozza «{KIND_LABELS[kind]}» ({identity}).",
                    details={
                        "before": _jsonable(before),
                        "after": _jsonable(self._profile_fields(kind, pending)),
                        "previous_author": previous_author,
                    },
                )
                action = "updated"
            else:
                action = None
        if action is None:
            upsert = {
                "biography": self.profiles.upsert_biography,
                "career_entry": self.profiles.upsert_career_entry,
                "position": self.profiles.upsert_position,
                "proceeding": self.profiles.upsert_proceeding,
            }[kind]
            try:
                content_id, _ = upsert(politician_id, draft)
            except PoliticianProfileServiceError as error:
                raise RedazioneValidation(str(error)) from error
            with self.session_factory.begin() as session:
                published = session.scalar(
                    select(model).where(
                        model.politician_id == politician_id,
                        model.identity_key == identity,
                        model.status == ProfileContentStatus.PUBLISHED,
                    )
                )
                self._log(
                    session,
                    actor=member,
                    action="scrittura",
                    object_kind=kind,
                    object_id=content_id,
                    politician_id=politician_id,
                    summary=(
                        f"Nuova versione di «{KIND_LABELS[kind]}» ({identity}) in attesa di verifica."
                        if published is not None
                        else f"Nuova bozza «{KIND_LABELS[kind]}» ({identity}) in attesa di verifica."
                    ),
                    details={"after": _jsonable(fields), "replaces_published_id": published.id if published else None},
                )
        with self.session_factory() as session:
            return self._profile_item(session, kind, session.get(model, content_id), member)

    @staticmethod
    def _source_inputs(items: list[dict]) -> tuple[ProfileSourceInput, ...]:
        result = []
        for item in items:
            name = _clean(item.get("name"))
            url = _clean(item.get("url")) or None
            if not name and not url:
                continue
            area = _clean(item.get("area") or item.get("kind") or "altro")
            kind = SOURCE_KIND_BY_AREA.get(area)
            if kind is None:
                try:
                    kind = ProfileSourceKind(area)
                except ValueError:
                    kind = ProfileSourceKind.OTHER
            try:
                result.append(
                    ProfileSourceInput(
                        name=name or urlsplit(url or "").netloc or "Fonte",
                        title=_clean(item.get("title")) or None,
                        url=url,
                        kind=kind,
                        excerpt=_clean(item.get("excerpt")) or None,
                    )
                )
            except ValueError as error:
                raise RedazioneValidation(f"Fonte non valida: {name or url}") from error
        return tuple(result)

    def request_withdrawal(self, kind: str, content_id: int, *, reason: str, member: str) -> dict:
        if kind not in PROFILE_MODELS:
            raise RedazioneNotFound("blocco sconosciuto")
        reason = _clean(reason)
        if not reason:
            raise RedazioneValidation("Scrivi il motivo del ritiro: comparirà nel registro.")
        with self.session_factory.begin() as session:
            row = session.get(PROFILE_MODELS[kind], content_id)
            if row is None or row.status is not ProfileContentStatus.PUBLISHED:
                raise RedazioneConflict("Si può ritirare solo un contenuto pubblicato.")
            request = EditorialChangeRequest(
                kind="ritiro",
                target_kind=kind,
                target_id=content_id,
                politician_id=row.politician_id,
                summary=f"Ritirare «{KIND_LABELS[kind]}» dal profilo pubblico. Motivo: {reason}",
                payload={"reason": reason},
                status=ChangeRequestStatus.PENDING,
                created_by=member,
                created_at=self.clock(),
            )
            session.add(request)
            session.flush()
            self._log(
                session,
                actor=member,
                action="richiesta_ritiro",
                object_kind="change",
                object_id=request.id,
                politician_id=row.politician_id,
                summary=request.summary,
                details={"target_kind": kind, "target_id": content_id},
            )
            return self._change_response(session, request, member)

    # ----------------------------------------------------------- promises
    def _pending_proposal_drafts(self, session: Session) -> list[tuple[ProposalDraft, int | None]]:
        identifiers = {
            row.value: row.politician_id
            for row in session.scalars(select(PoliticianSourceIdentifier))
        }
        result = []
        for draft in session.scalars(
            select(ProposalDraft)
            .where(ProposalDraft.status.in_((ProposalDraftStatus.PENDING, ProposalDraftStatus.IN_REVIEW)))
            .order_by(ProposalDraft.id)
        ):
            actors = (draft.proposed_data or {}).get("actors") or []
            politician_id = next(
                (
                    identifiers.get(actor.get("source_identifier"))
                    for actor in actors
                    if actor.get("source_identifier") in identifiers
                ),
                None,
            )
            result.append((draft, politician_id))
        return result

    def _promises(self, session: Session, politician_id: int, member: str) -> list[dict]:
        published = session.scalars(
            select(Proposal)
            .join(ProposalActor, ProposalActor.proposal_id == Proposal.id)
            .where(
                ProposalActor.politician_id == politician_id,
                ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
                Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
                Proposal.published_at.is_not(None),
            )
            .distinct()
            .order_by(Proposal.introduced_at, Proposal.id)
        ).all()
        ids = [row.id for row in published]
        classifications = {
            row.proposal_id: row
            for row in session.scalars(select(PledgeClassification).where(PledgeClassification.proposal_id.in_(ids)))
        } if ids else {}
        latest = PledgeService._latest_assessments(session, ids)
        drafts_by_proposal: dict[int, list[PledgeAssessmentDraft]] = {}
        if ids:
            for draft in session.scalars(
                select(PledgeAssessmentDraft)
                .where(
                    PledgeAssessmentDraft.proposal_id.in_(ids),
                    PledgeAssessmentDraft.status.in_(
                        (PledgeAssessmentDraftStatus.PENDING, PledgeAssessmentDraftStatus.AWAITING_SECOND_APPROVAL)
                    ),
                )
                .order_by(PledgeAssessmentDraft.id)
            ):
                drafts_by_proposal.setdefault(draft.proposal_id, []).append(draft)
        items = []
        for proposal in published:
            meta = self._proposal_meta(session, proposal)
            classification = classifications.get(proposal.id)
            assessment = latest.get(proposal.id)
            items.append(
                {
                    "proposal_id": proposal.id,
                    "draft_id": None,
                    "published": True,
                    "title": proposal.canonical_title,
                    "exact_statement": proposal.exact_statement,
                    "introduced_at": _iso(proposal.introduced_at),
                    "where": meta.get("where"),
                    "source": meta.get("source"),
                    "classified": classification is not None,
                    "classification": self._classification_dict(classification),
                    "verdict": assessment.verdict.value if assessment else "not_yet_rated",
                    "verdict_label": VERDICT_LABELS[assessment.verdict.value if assessment else "not_yet_rated"],
                    "verdict_rationale": assessment.rationale if assessment else None,
                    "verdict_source_url": assessment.source_url if assessment else None,
                    "verdict_effective_at": _iso(assessment.effective_at) if assessment else None,
                    "verdict_at": _iso(assessment.created_at) if assessment else None,
                    "verdict_approved_by": list(assessment.approved_by or []) if assessment else [],
                    "pending_statuses": [
                        self._status_draft_dict(draft, member) for draft in drafts_by_proposal.get(proposal.id, [])
                    ],
                }
            )
        for draft, owner in self._pending_proposal_drafts(session):
            data = draft.proposed_data or {}
            if owner != politician_id or data.get("proposal_type") != ProposalType.EXPLICIT_PROMISE.value:
                continue
            redazione = (data.get("metadata") or {}).get("redazione") or {}
            items.append(
                {
                    "proposal_id": draft.proposal_id,
                    "draft_id": draft.id,
                    "published": False,
                    "title": data.get("title"),
                    "exact_statement": data.get("exact_statement"),
                    "introduced_at": data.get("introduced_at"),
                    "where": redazione.get("where") or data.get("source_status_label"),
                    "source": redazione.get("source") or {"name": None, "url": data.get("official_url")},
                    "classified": bool(redazione.get("classification")),
                    "classification": redazione.get("classification"),
                    "verdict": "not_yet_rated",
                    "verdict_label": "In attesa di verifica",
                    "author": redazione.get("author") or SYSTEM_AUTHOR,
                    "suggested_verdict": (data.get("metadata") or {}).get("suggested_verdict"),
                    "pending_statuses": [],
                    "can_approve": (redazione.get("author") or SYSTEM_AUTHOR) != member,
                }
            )
        return items

    @staticmethod
    def _proposal_meta(session: Session, proposal: Proposal) -> dict:
        draft = session.scalar(
            select(ProposalDraft)
            .where(ProposalDraft.proposal_id == proposal.id, ProposalDraft.status == ProposalDraftStatus.APPROVED)
            .order_by(ProposalDraft.id.desc())
        )
        data = draft.proposed_data if draft is not None else {}
        redazione = (data.get("metadata") or {}).get("redazione") or {}
        return {
            "where": redazione.get("where") or data.get("source_status_label"),
            "source": redazione.get("source") or {"name": None, "url": data.get("official_url")},
            "author": redazione.get("author"),
        }

    @staticmethod
    def _classification_dict(row: PledgeClassification | None) -> dict | None:
        if row is None:
            return None
        return {
            "specificity": row.specificity.value,
            "commitment_type": row.commitment_type.value,
            "holder_role": row.holder_role.value,
            "cap_topic_code": row.cap_topic_code,
            "mandate_start": _iso(row.mandate_start),
            "mandate_end": _iso(row.mandate_end),
            "classified_by": row.classified_by,
            "included_in_score": row.specificity is not PledgeSpecificity.VAGUE,
        }

    @staticmethod
    def _status_draft_dict(draft: PledgeAssessmentDraft, member: str) -> dict:
        approvals = [approval.reviewer for approval in draft.approvals]
        author = draft.created_by if draft.origin is PledgeAssessmentOrigin.EDITOR else "Abbinamento automatico"
        return {
            "id": draft.id,
            "verdict": draft.proposed_verdict.value,
            "verdict_label": VERDICT_LABELS[draft.proposed_verdict.value],
            "rationale": draft.rationale,
            "quoted_excerpt": draft.quoted_excerpt,
            "source_url": draft.source_url,
            "effective_at": _iso(draft.effective_at),
            "author": author,
            "approvals": approvals,
            "approvals_required": approvals_required(draft.proposed_verdict),
            "status": draft.status.value,
            "can_approve": member != author and member not in approvals,
        }

    def _outlet_source(self, session: Session, name: str, url: str) -> Source:
        parsed = urlsplit(url)
        host = parsed.netloc.casefold().removeprefix("www.")
        key = f"redazione-{_slug(host)}"[:100]
        source = session.scalar(select(Source).where(Source.key == key))
        if source is None:
            source = Source(key=key, name=name or host, base_url=f"{parsed.scheme}://{parsed.netloc}")
            session.add(source)
            session.flush()
        return source

    def _snapshot(self, session: Session, *, source: Source, url: str, text: str, label: str, member: str) -> RawDocument:
        """Store the passage the editor copied from the source, with its URL.

        The verifier checks the passage against the page before approving; the
        excerpt the scorecard shows is then verbatim in a stored document.
        """

        digest = hashlib.sha256(f"{url}\n{text}".encode("utf-8")).hexdigest()
        existing = session.scalar(
            select(RawDocument).where(RawDocument.source_id == source.id, RawDocument.raw_sha256 == digest)
        )
        if existing is not None:
            return existing
        document = RawDocument(
            source_id=source.id,
            retrieved_at=self.clock(),
            source_url=url,
            content_type="text/plain",
            storage_key=f"redazione/{label}/{digest[:16]}.txt",
            raw_sha256=digest,
            normalized_sha256=digest,
            structured_records=[{"copied_by": member}],
            normalized_text=text,
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version=COLLECTOR,
            parser_version=COLLECTOR,
        )
        session.add(document)
        session.flush()
        return document

    def create_promise(self, politician_id: int, payload: dict, *, member: str) -> dict:
        title = _clean(payload.get("title"))
        statement = _clean(payload.get("exact_statement"))
        where = _clean(payload.get("where"))
        source = {"name": _clean((payload.get("source") or {}).get("name")), "url": _clean((payload.get("source") or {}).get("url"))}
        introduced = _parse_date(payload.get("introduced_at"), "data della dichiarazione")
        classification = self._classification_payload(payload.get("classification") or {})
        data = {"title": title, "exact_statement": statement, "introduced_at": introduced, "source": source}
        findings = style.promise_findings(data)
        if not title or not statement:
            raise RedazioneValidation("Servono la promessa e la dichiarazione esatta.")
        if style.has_errors(findings):
            raise RedazioneValidation("La promessa non rispetta i modelli.", [item.as_dict() for item in findings])
        with self.session_factory.begin() as session:
            politician = self._require_politician(session, politician_id)
            identifier = session.scalar(
                select(PoliticianSourceIdentifier).where(PoliticianSourceIdentifier.politician_id == politician_id)
            )
            if identifier is None:
                raise RedazioneConflict("Il politico non ha un identificativo ufficiale: importalo prima da Camera, Senato o Governo.")
            authority = session.get(Source, identifier.source_id)
            outlet = self._outlet_source(session, source["name"], source["url"])
            document = self._snapshot(
                session, source=outlet, url=source["url"], text=f"{title}\n{statement}", label="promesse", member=member
            )
            source_key, document_id = outlet.key, document.id
            display = f"{politician.canonical_given_name} {politician.canonical_family_name}"
            authority_key, source_identifier = authority.key, identifier.value
        proposal_identifier = f"redazione:promessa:{politician_id}:{_slug(title)}:{introduced.isoformat()}"
        evidence = [
            ("title", "redazione:promessa", title),
            ("proposal_type", "redazione:tipo", "explicit_promise"),
            ("current_status", "redazione:stato", "announced"),
            ("introduced_at", "redazione:data", introduced.isoformat()),
            ("exact_statement", "redazione:dichiarazione", statement),
        ]
        observation = ProposalObservation.model_validate(
            {
                "source_key": source_key,
                "raw_document_id": document_id,
                "proposal_identifier": proposal_identifier,
                "title": title,
                "exact_statement": statement,
                "proposal_type": "explicit_promise",
                "introduced_at": introduced,
                "source_status_label": where or "Dichiarazione pubblica",
                "normalized_status": "announced",
                "official_url": source["url"],
                "source_field": "redazione:promessa",
                "observed_at": self.clock(),
                "actors": [
                    {
                        "actor_type": "politician",
                        "role": "commitment_owner",
                        "display_name": display,
                        "authority_key": authority_key,
                        "source_identifier": source_identifier,
                        "source_field": "redazione:politico",
                    }
                ],
                "evidence": [
                    {"field_path": path, "source_url": source["url"], "source_field": field, "source_value": value}
                    for path, field, value in evidence
                ],
                "metadata": {
                    "redazione": {
                        "author": member,
                        "where": where,
                        "source": source,
                        "classification": classification,
                    }
                },
            }
        )
        try:
            result = self.proposals.sync((observation,))
        except ProposalServiceError as error:
            raise RedazioneValidation(str(error)) from error
        detail = result.details[0]
        if detail.draft_id is None:
            raise RedazioneConflict("Questa promessa è già registrata con la stessa data.")
        with self.session_factory.begin() as session:
            self._log(
                session,
                actor=member,
                action="scrittura",
                object_kind="promise",
                object_id=detail.draft_id,
                politician_id=politician_id,
                summary=f"Nuova promessa «{title}» ({_long_date(introduced)}) in attesa di verifica.",
                details={"proposal_id": detail.proposal_id, "source": source, "classification": classification},
            )
        return {"proposal_id": detail.proposal_id, "draft_id": detail.draft_id, "findings": [item.as_dict() for item in findings]}

    @staticmethod
    def _classification_payload(payload: dict) -> dict | None:
        if not payload:
            return None
        try:
            request = PledgeClassificationRequest(
                specificity=PledgeSpecificity(payload.get("specificity") or "high"),
                commitment_type=CommitmentType(payload.get("commitment_type") or "action"),
                holder_role=HolderRole(payload.get("holder_role") or "unknown"),
                cap_topic_code=_clean(payload.get("cap_topic_code")) or None,
                mandate_start=_parse_date(payload.get("mandate_start"), "inizio mandato"),
                mandate_end=_parse_date(payload.get("mandate_end"), "fine mandato"),
                note=_clean(payload.get("note")) or None,
            )
        except ValueError as error:
            if isinstance(error, RedazioneError):
                raise
            raise RedazioneValidation(f"Classificazione non valida: {error}") from error
        if request.mandate_start and request.mandate_end and request.mandate_end < request.mandate_start:
            raise RedazioneValidation("La fine del mandato precede l'inizio.")
        return _jsonable(request.model_dump())

    def request_reclassification(self, proposal_id: int, payload: dict, *, member: str) -> dict:
        classification = self._classification_payload(payload)
        if classification is None:
            raise RedazioneValidation("Classificazione mancante.")
        with self.session_factory.begin() as session:
            proposal = session.get(Proposal, proposal_id)
            if proposal is None or proposal.published_at is None:
                raise RedazioneNotFound("promessa pubblicata non trovata")
            owner = session.scalar(
                select(ProposalActor.politician_id).where(
                    ProposalActor.proposal_id == proposal_id,
                    ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
                )
            )
            current = session.scalar(select(PledgeClassification).where(PledgeClassification.proposal_id == proposal_id))
            request = EditorialChangeRequest(
                kind="classificazione",
                target_kind="promise",
                target_id=proposal_id,
                politician_id=owner,
                summary=f"Classificazione di «{proposal.canonical_title}» (incide sul punteggio).",
                payload={"classification": classification, "before": self._classification_dict(current)},
                status=ChangeRequestStatus.PENDING,
                created_by=member,
                created_at=self.clock(),
            )
            session.add(request)
            session.flush()
            self._log(
                session,
                actor=member,
                action="richiesta_classificazione",
                object_kind="change",
                object_id=request.id,
                politician_id=owner,
                summary=request.summary,
                details=request.payload,
            )
            return self._change_response(session, request, member)

    def propose_status(self, proposal_id: int, payload: dict, *, member: str) -> dict:
        try:
            verdict = FulfillmentVerdict(payload.get("verdict"))
        except ValueError as error:
            raise RedazioneValidation("Stato non valido.") from error
        if verdict is FulfillmentVerdict.NOT_YET_RATED:
            raise RedazioneValidation("«Da valutare» è lo stato di partenza: non si assegna.")
        rationale = _clean(payload.get("rationale"))
        excerpt = _clean(payload.get("quoted_excerpt"))
        source = {"name": _clean((payload.get("source") or {}).get("name")), "url": _clean((payload.get("source") or {}).get("url"))}
        effective = _parse_date(payload.get("effective_at"), "data del fatto")
        if effective is None:
            raise RedazioneValidation("Indica la data del fatto che giustifica lo stato.")
        if len(excerpt) < 12:
            raise RedazioneValidation("Copia dalla fonte il passaggio che giustifica lo stato (almeno una frase).")
        findings = style.verdict_findings({"rationale": rationale, "source": source})
        if verdict is FulfillmentVerdict.BROKEN:
            reason = payload.get("broken_reason")
            if reason not in BROKEN_REASONS:
                raise RedazioneValidation(
                    "«Non mantenuta» solo se la scadenza è passata senza risultato, il mandato è finito o c'è una rinuncia esplicita: scegli quale."
                )
            if reason == "scadenza_passata":
                deadline = _parse_date(payload.get("deadline"), "scadenza dichiarata")
                if deadline is None or deadline >= effective:
                    raise RedazioneValidation("La scadenza dichiarata deve essere precedente alla data del fatto.")
                rationale = f"{BROKEN_REASONS[reason]} ({_long_date(deadline)}). {rationale}"
            else:
                rationale = f"{BROKEN_REASONS[reason]}. {rationale}"
        if not rationale:
            raise RedazioneValidation("Scrivi l'aggiornamento: il fatto, con la data.")
        if style.has_errors(findings):
            raise RedazioneValidation("Lo stato non rispetta i modelli.", [item.as_dict() for item in findings])
        with self.session_factory.begin() as session:
            proposal = session.get(Proposal, proposal_id)
            if proposal is None or proposal.published_at is None:
                raise RedazioneNotFound("Promessa pubblicata non trovata: va prima verificata e pubblicata.")
            if proposal.proposal_type is not ProposalType.EXPLICIT_PROMISE:
                raise RedazioneConflict("Lo stato si assegna solo alle promesse.")
            if session.scalar(select(PledgeClassification).where(PledgeClassification.proposal_id == proposal_id)) is None:
                raise RedazioneConflict("Classifica la promessa prima di assegnarle uno stato: senza classificazione non entra nel punteggio.")
            outlet = self._outlet_source(session, source["name"], source["url"])
            document = self._snapshot(session, source=outlet, url=source["url"], text=excerpt, label="stati", member=member)
            document_id = document.id
            owner = session.scalar(
                select(ProposalActor.politician_id).where(
                    ProposalActor.proposal_id == proposal_id,
                    ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
                )
            )
            title = proposal.canonical_title
        try:
            draft, created = self.pledges.propose(
                NewAssessmentDraft(
                    proposal_id=proposal_id,
                    proposal=PledgeAssessmentProposal(
                        verdict=verdict,
                        evidence_label=VERDICT_EVIDENCE[verdict],
                        rationale=rationale,
                        quoted_excerpt=excerpt,
                        raw_document_id=document_id,
                        effective_at=effective,
                    ),
                    origin=PledgeAssessmentOrigin.EDITOR,
                    created_by=member,
                    retrieval={"retrieval_reason": "redazione", "source_name": source["name"]},
                )
            )
        except PledgeServiceError as error:
            raise RedazioneValidation(str(error)) from error
        if not created:
            raise RedazioneConflict("Lo stesso stato con la stessa fonte è già stato proposto.")
        with self.session_factory.begin() as session:
            self._log(
                session,
                actor=member,
                action="assegna_stato",
                object_kind="status",
                object_id=draft.id,
                politician_id=owner,
                summary=f"Proposto lo stato «{VERDICT_LABELS[verdict.value]}» per «{title}».",
                details={"rationale": rationale, "source": source, "effective_at": effective.isoformat()},
            )
        return {"draft_id": draft.id, "approvals_required": draft.approvals_required}

    # ------------------------------------------------------------------ news
    def save_news(self, payload: dict, *, member: str, post_id: int | None = None) -> dict:
        title = _clean(payload.get("title"))
        blocks = {key: _clean(value) for key, value in (payload.get("blocks") or {}).items() if isinstance(value, str)}
        sources = [
            {
                "name": _clean(item.get("name")),
                "url": _clean(item.get("url")),
                "date": _clean(item.get("date")) or None,
                "area": _clean(item.get("area")) or "altro",
            }
            for item in payload.get("sources") or []
            if _clean(item.get("url"))
        ]
        politician_ids = sorted({int(item) for item in payload.get("politician_ids") or [] if str(item).isdigit()})
        if len(title) < 5:
            raise RedazioneValidation("Il titolo è troppo corto.")
        body = self._news_body(blocks)
        stored_blocks = {**blocks, "fonti": sources, "politician_ids": politician_ids}
        scope = FeedScope(payload.get("scope") or "national")
        try:
            request = EditorialPostRequest(
                title=title,
                body=body[:12000] if len(body) >= 20 else (body + " " * 20)[:20],
                scope=scope,
                region_id=payload.get("region_id") or None,
                province_abbreviation=payload.get("province_abbreviation") or None,
                municipality_id=payload.get("municipality_id") or None,
                citations=tuple(
                    Citation(title=item["name"] or urlsplit(item["url"]).netloc, url=item["url"]) for item in sources[:10]
                ) or (Citation(title="Fonte da indicare", url="https://www.example.org/fonte-da-indicare"),),
                corrects_id=payload.get("corrects_id") or None,
            )
        except ValueError as error:
            raise RedazioneValidation(f"Notizia non valida: {error}") from error
        if post_id is None:
            try:
                created = self.editorial.create(request, author=member)
            except EditorialValidationError as error:
                raise RedazioneValidation(str(error)) from error
            post_id = created.id
            action, summary = "scrittura", f"Nuova notizia «{title}» in attesa di verifica."
            before = None
        else:
            action, summary = "modifica", f"Modificata la notizia «{title}»."
        with self.session_factory.begin() as session:
            post = session.get(EditorialPost, post_id)
            if post is None:
                raise RedazioneNotFound("notizia non trovata")
            if action == "modifica":
                if post.status is not EditorialPostStatus.PENDING:
                    raise RedazioneConflict("Una notizia pubblicata non si modifica: si pubblica una rettifica.")
                before = {"title": post.title, "blocks": post.blocks}
                post.title = request.title
                post.body = request.body
                post.scope = request.scope
                post.region_id = request.region_id
                post.province_abbreviation = request.province_abbreviation
                post.municipality_id = request.municipality_id
                post.citations = [{"title": item.title, "url": str(item.url)} for item in request.citations]
                post.created_by = member
            composed = card_module.sanitize(payload.get("card"), session)
            if composed:
                linked = {person["politician_id"] for person in composed["people"] if person.get("politician_id")}
                stored_blocks["politician_ids"] = sorted(set(stored_blocks["politician_ids"]) | linked)
            stored_blocks["card"] = composed
            post.blocks = stored_blocks
            post.updated_at = self.clock()
            session.flush()
            self._log(
                session,
                actor=member,
                action=action,
                object_kind="news",
                object_id=post.id,
                summary=summary,
                details={"before": _jsonable(before), "after": {"title": title, "blocks": stored_blocks}},
            )
            return self._news_dict(session, post, member)

    @staticmethod
    def _news_body(blocks: dict) -> str:
        parts = [blocks.get("sommario") or ""]
        for key, label, *_ in style.NEWS_BLOCKS:
            text = blocks.get(key)
            if key == "fatto" and blocks.get("perche_deciso"):
                text = f"{text or ''}\nPerché è stato deciso: {blocks['perche_deciso']}"
            if text:
                parts.append(f"{label}\n{text}")
        return "\n\n".join(part for part in parts if part).strip()

    def list_news(self, *, member: str) -> list[dict]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(EditorialPost).order_by(EditorialPost.created_at.desc(), EditorialPost.id.desc()).limit(100)
            ).all()
            return [self._news_dict(session, row, member) for row in rows]

    def news(self, post_id: int, *, member: str) -> dict:
        with self.session_factory() as session:
            post = session.get(EditorialPost, post_id)
            if post is None:
                raise RedazioneNotFound("notizia non trovata")
            return self._news_dict(session, post, member)

    def _news_dict(self, session: Session, post: EditorialPost, member: str) -> dict:
        blocks = dict(post.blocks or {})
        sources = blocks.pop("fonti", None) or [
            {"name": item.get("title"), "url": item.get("url"), "area": "altro", "date": None} for item in post.citations
        ]
        politician_ids = blocks.pop("politician_ids", []) or []
        composed = blocks.pop("card", None)
        if not post.blocks:
            blocks = {"sommario": post.body}
        findings = [
            item.as_dict() for item in style.news_findings({"title": post.title, "blocks": blocks, "sources": sources})
        ]
        if not composed:
            findings.append(
                {"level": "warning", "code": "card_mancante", "message": "La card del feed non è stata composta: comparirà come notizia semplice.", "field": "card"}
            )
        names = self._politician_names(session, set(politician_ids))
        return {
            "id": post.id,
            "title": post.title,
            "status": post.status.value,
            "scope": post.scope.value,
            "region_id": post.region_id,
            "province_abbreviation": post.province_abbreviation,
            "municipality_id": post.municipality_id,
            "blocks": blocks,
            "sources": sources,
            "politicians": [{"id": key, "name": names.get(key)} for key in politician_ids],
            "card": composed,
            "card_public": card_module.public(composed, session),
            "created_by": post.created_by,
            "reviewed_by": post.reviewed_by,
            "created_at": _iso(post.created_at),
            "published_at": _iso(post.published_at),
            "public_url": f"/app/?post={post.id}" if post.status is EditorialPostStatus.PUBLISHED else None,
            "words": style.words(post.body),
            "findings": findings,
            "can_approve": post.status is EditorialPostStatus.PENDING and post.created_by != member,
        }

    def _related_news(self, session: Session, politician_id: int) -> list[dict]:
        result = []
        for post in session.scalars(
            select(EditorialPost)
            .where(EditorialPost.blocks.is_not(None))
            .order_by(EditorialPost.created_at.desc())
            .limit(300)
        ):
            if politician_id in ((post.blocks or {}).get("politician_ids") or []):
                result.append(
                    {"id": post.id, "title": post.title, "status": post.status.value, "published_at": _iso(post.published_at)}
                )
        return result

    def list_parties(self) -> list[dict]:
        with self.session_factory() as session:
            return [
                card_module.party_dict(row)
                for row in session.scalars(select(PoliticalParty).order_by(PoliticalParty.canonical_name))
            ]

    # ---------------------------------------------------------------- images
    IMAGE_TYPES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg", b"RIFF": "image/webp"}
    MAX_IMAGE_BYTES = 400_000

    def upload_image(self, payload: dict, *, member: str) -> dict:
        """A square image for a feed card, cropped and resized by the console."""

        raw = str(payload.get("data") or "")
        if "," in raw and raw.startswith("data:"):
            raw = raw.split(",", 1)[1]
        try:
            data = base64.b64decode(raw, validate=True)
        except (ValueError, binascii.Error) as error:
            raise RedazioneValidation("Immagine non leggibile.") from error
        if not data or len(data) > self.MAX_IMAGE_BYTES:
            raise RedazioneValidation("L'immagine deve pesare meno di 400 KB.")
        content_type = next((kind for magic, kind in self.IMAGE_TYPES.items() if data.startswith(magic)), None)
        if content_type == "image/webp" and data[8:12] != b"WEBP":
            content_type = None
        if content_type is None:
            raise RedazioneValidation("Formato non supportato: usa JPEG, PNG o WebP.")
        digest = hashlib.sha256(data).hexdigest()
        with self.session_factory.begin() as session:
            existing = session.scalar(select(EditorialImage).where(EditorialImage.sha256 == digest))
            if existing is not None:
                return {"id": existing.id, "url": f"/media/{existing.id}"}
            image = EditorialImage(
                content_type=content_type,
                data=data,
                sha256=digest,
                width=int(payload["width"]) if str(payload.get("width") or "").isdigit() else None,
                height=int(payload["height"]) if str(payload.get("height") or "").isdigit() else None,
                alt=_clean(payload.get("alt"))[:300] or None,
                credit=_clean(payload.get("credit"))[:300] or None,
                uploaded_by=member,
                created_at=self.clock(),
            )
            session.add(image)
            session.flush()
            self._log(
                session,
                actor=member,
                action="immagine",
                object_kind="image",
                object_id=image.id,
                summary=f"Caricata un'immagine per le card del feed ({len(data) // 1024} KB).",
                details={"credit": image.credit, "alt": image.alt},
            )
            return {"id": image.id, "url": f"/media/{image.id}"}

    # ------------------------------------------------------- change requests
    def _change_requests(self, session: Session, *, politician_id: int | None = None, member: str) -> list[dict]:
        query = select(EditorialChangeRequest).where(EditorialChangeRequest.status == ChangeRequestStatus.PENDING)
        if politician_id is not None:
            query = query.where(EditorialChangeRequest.politician_id == politician_id)
        return [self._change_response(session, row, member) for row in session.scalars(query.order_by(EditorialChangeRequest.id))]

    @staticmethod
    def _change_response(session: Session, row: EditorialChangeRequest, member: str) -> dict:
        return {
            "id": row.id,
            "kind": row.kind,
            "target_kind": row.target_kind,
            "target_id": row.target_id,
            "politician_id": row.politician_id,
            "summary": row.summary,
            "payload": row.payload,
            "status": row.status.value,
            "created_by": row.created_by,
            "created_at": _iso(row.created_at),
            "can_approve": row.status is ChangeRequestStatus.PENDING and row.created_by != member,
        }

    # ------------------------------------------------------------------ queue
    def queue(self, *, member: str) -> list[dict]:
        items: list[dict] = []
        with self.session_factory() as session:
            names = self._politician_names(session, set(self._all_ids(session)))
            for kind, model in PROFILE_MODELS.items():
                for row in session.scalars(
                    select(model).where(model.status == ProfileContentStatus.PENDING).order_by(model.created_at, model.id)
                ):
                    item = self._profile_item(session, kind, row, member)
                    items.append(
                        self._queue_item(
                            kind=kind,
                            item_id=row.id,
                            title=KIND_LABELS[kind] + self._profile_title_suffix(kind, item["data"]),
                            politician_id=row.politician_id,
                            politician_name=names.get(row.politician_id),
                            author=row.created_by,
                            created_at=row.created_at,
                            preview=item["data"],
                            findings=item["findings"],
                            member=member,
                        )
                    )
            for draft, politician_id in self._pending_proposal_drafts(session):
                data = draft.proposed_data or {}
                redazione = (data.get("metadata") or {}).get("redazione") or {}
                is_promise = data.get("proposal_type") == ProposalType.EXPLICIT_PROMISE.value
                author = redazione.get("author") or SYSTEM_AUTHOR
                findings = (
                    [
                        item.as_dict()
                        for item in style.promise_findings(
                            {
                                "title": data.get("title"),
                                "exact_statement": data.get("exact_statement"),
                                "introduced_at": data.get("introduced_at"),
                                "source": redazione.get("source") or {"url": data.get("official_url")},
                            }
                        )
                    ]
                    if is_promise
                    else [item.as_dict() for item in style.source_findings([{"url": data.get("official_url")}])]
                )
                if is_promise and not redazione.get("classification"):
                    findings.append(
                        {
                            "level": "warning",
                            "code": "da_classificare",
                            "message": "Senza classificazione la promessa non entra nel punteggio: compilala prima di approvare.",
                            "field": "classificazione",
                        }
                    )
                items.append(
                    self._queue_item(
                        kind="promise" if is_promise else "proposal",
                        item_id=draft.id,
                        title=data.get("title") or "",
                        politician_id=politician_id,
                        politician_name=names.get(politician_id),
                        author=author,
                        created_at=draft.created_at,
                        preview={
                            "exact_statement": data.get("exact_statement"),
                            "summary": data.get("summary"),
                            "introduced_at": data.get("introduced_at"),
                            "where": redazione.get("where") or data.get("source_status_label"),
                            "source": redazione.get("source") or {"name": None, "url": data.get("official_url")},
                            "classification": redazione.get("classification"),
                            "suggested_verdict": (data.get("metadata") or {}).get("suggested_verdict"),
                            "proposal_type": data.get("proposal_type"),
                            "status_label": data.get("source_status_label"),
                        },
                        findings=findings,
                        member=member,
                    )
                )
            for draft in session.scalars(
                select(PledgeAssessmentDraft)
                .where(
                    PledgeAssessmentDraft.status.in_(
                        (PledgeAssessmentDraftStatus.PENDING, PledgeAssessmentDraftStatus.AWAITING_SECOND_APPROVAL)
                    )
                )
                .order_by(PledgeAssessmentDraft.created_at, PledgeAssessmentDraft.id)
            ):
                status = self._status_draft_dict(draft, member)
                owner = session.scalar(
                    select(ProposalActor.politician_id).where(
                        ProposalActor.proposal_id == draft.proposal_id,
                        ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
                    )
                )
                findings = [
                    item.as_dict()
                    for item in style.verdict_findings({"rationale": draft.rationale, "source": {"url": draft.source_url}})
                ]
                item = self._queue_item(
                    kind="status",
                    item_id=draft.id,
                    title=f"{status['verdict_label']} — {draft.proposal.canonical_title}",
                    politician_id=owner,
                    politician_name=names.get(owner),
                    author=status["author"],
                    created_at=draft.created_at,
                    preview=status,
                    findings=findings,
                    member=member,
                )
                item["approvals"] = status["approvals"]
                item["approvals_required"] = status["approvals_required"]
                item["can_approve"] = item["can_approve"] and member not in status["approvals"]
                items.append(item)
            for post in session.scalars(
                select(EditorialPost).where(EditorialPost.status == EditorialPostStatus.PENDING).order_by(EditorialPost.created_at)
            ):
                news = self._news_dict(session, post, member)
                items.append(
                    self._queue_item(
                        kind="news",
                        item_id=post.id,
                        title=post.title,
                        politician_id=None,
                        politician_name=None,
                        author=post.created_by,
                        created_at=post.created_at,
                        preview={
                            "blocks": news["blocks"],
                            "sources": news["sources"],
                            "words": news["words"],
                            "card": news["card_public"],
                            "title": post.title,
                            "scope": news["scope"],
                        },
                        findings=news["findings"],
                        member=member,
                    )
                )
            for change in self._change_requests(session, member=member):
                items.append(
                    self._queue_item(
                        kind="change",
                        item_id=change["id"],
                        title=change["summary"],
                        politician_id=change["politician_id"],
                        politician_name=names.get(change["politician_id"]),
                        author=change["created_by"],
                        created_at=datetime.fromisoformat(change["created_at"]),
                        preview=change,
                        findings=[],
                        member=member,
                    )
                )
        return items

    @staticmethod
    def _all_ids(session: Session) -> list[int]:
        return list(session.scalars(select(Politician.id)))

    @staticmethod
    def _profile_title_suffix(kind: str, data: dict) -> str:
        label = data.get("topic") or data.get("role") or data.get("title")
        return f": {label}" if label else ""

    @staticmethod
    def _queue_item(
        *,
        kind: str,
        item_id: int,
        title: str,
        politician_id: int | None,
        politician_name: str | None,
        author: str,
        created_at: datetime | None,
        preview: dict,
        findings: list[dict],
        member: str,
    ) -> dict:
        blocked = style.has_errors(findings)
        return {
            "kind": kind,
            "kind_label": KIND_LABELS[kind],
            "id": item_id,
            "title": title,
            "politician_id": politician_id,
            "politician_name": politician_name,
            "author": author,
            "created_at": _iso(created_at),
            "preview": _jsonable(preview),
            "findings": findings,
            "blocked": blocked,
            "own": author == member,
            "can_approve": author != member and not blocked,
            "approvals": [],
            "approvals_required": 1,
        }

    # ------------------------------------------------------------- decisions
    def _queue_entry(self, kind: str, item_id: int, member: str) -> dict:
        for item in self.queue(member=member):
            if item["kind"] == kind and item["id"] == item_id:
                return item
        raise RedazioneNotFound("Elemento non più in attesa di verifica.")

    def approve(self, kind: str, item_id: int, *, member: str, note: str | None = None, extra: dict | None = None) -> dict:
        item = self._queue_entry(kind, item_id, member)
        if item["own"]:
            raise RedazioneConflict("Chi scrive non è chi verifica: questo contenuto lo deve approvare un'altra persona.")
        if member in item.get("approvals", []):
            raise RedazioneConflict("Hai già approvato questo stato: serve una seconda persona.")
        if item["blocked"]:
            raise RedazioneValidation("Il contenuto ha errori da correggere prima della pubblicazione.", item["findings"])
        note = _clean(note) or None
        extra = extra or {}
        politician_id = item["politician_id"]
        summary = f"Approvato: {item['kind_label']} — {item['title']}"
        details: dict[str, Any] = {"note": note, "author": item["author"]}
        try:
            if kind in PROFILE_MODELS:
                self.profiles.approve(PROFILE_KINDS[kind], item_id, reviewer=member, note=note)
                summary = f"Pubblicato «{item['title']}»."
            elif kind in {"promise", "proposal"}:
                classification = None
                if kind == "promise":
                    classification = self._classification_payload(extra.get("classification") or {}) or item["preview"].get("classification")
                with self.session_factory() as session:
                    draft = session.get(ProposalDraft, item_id)
                    pending = draft.status is ProposalDraftStatus.PENDING
                if pending:
                    self.proposal_review.start_review(item_id)
                result = self.proposal_review.approve(item_id, reviewer=member, note=note)
                details["proposal_id"] = result.proposal_id
                if classification:
                    self.pledges.classify(
                        result.proposal_id,
                        PledgeClassificationRequest.model_validate(classification),
                        classified_by=item["author"] if item["author"] != SYSTEM_AUTHOR else member,
                    )
                    details["classification"] = classification
                summary = f"Pubblicata {'la promessa' if kind == 'promise' else 'la proposta'} «{item['title']}»."
            elif kind == "status":
                draft, assessment = self.pledges.approve(item_id, reviewer=member, note=note)
                if assessment is None:
                    summary = f"Prima approvazione ({len(draft.approvals)} di {draft.approvals_required}): {item['title']}."
                else:
                    summary = f"Pubblicato lo stato: {item['title']}. Il punteggio è aggiornato."
                    details["assessment_id"] = assessment.id
            elif kind == "news":
                self.editorial.publish(item_id, reviewer=member, note=note)
                summary = f"Pubblicata la notizia «{item['title']}»."
            elif kind == "change":
                summary = self._apply_change(item_id, member=member, note=note)
            else:
                raise RedazioneNotFound("tipo sconosciuto")
        except (
            PoliticianProfileServiceError,
            ProposalReviewServiceError,
            PledgeConflictError,
            PledgeServiceError,
            EditorialConflictError,
            EditorialValidationError,
        ) as error:
            raise RedazioneConflict(str(error)) from error
        self.log(
            actor=member,
            action="approvazione",
            object_kind=kind,
            object_id=item_id,
            politician_id=politician_id,
            summary=summary,
            details=details,
        )
        return {"ok": True, "summary": summary}

    def reject(self, kind: str, item_id: int, *, member: str, note: str) -> dict:
        note = _clean(note)
        if not note:
            raise RedazioneValidation("Scrivi cosa va corretto: chi ha scritto lo leggerà.")
        item = self._queue_entry(kind, item_id, member)
        try:
            if kind in PROFILE_MODELS:
                self.profiles.reject(PROFILE_KINDS[kind], item_id, reviewer=member, note=note)
            elif kind in {"promise", "proposal"}:
                with self.session_factory() as session:
                    pending = session.get(ProposalDraft, item_id).status is ProposalDraftStatus.PENDING
                if pending:
                    self.proposal_review.start_review(item_id)
                self.proposal_review.reject(item_id, reviewer=member, note=note)
            elif kind == "status":
                self.pledges.reject(item_id, reviewer=member, note=note)
            elif kind == "news":
                self.editorial.reject(item_id, reviewer=member, note=note)
            elif kind == "change":
                with self.session_factory.begin() as session:
                    row = session.get(EditorialChangeRequest, item_id)
                    row.status = ChangeRequestStatus.REJECTED
                    row.reviewed_by = member
                    row.reviewed_at = self.clock()
                    row.review_note = note
            else:
                raise RedazioneNotFound("tipo sconosciuto")
        except (
            PoliticianProfileServiceError,
            ProposalReviewServiceError,
            PledgeServiceError,
            EditorialConflictError,
        ) as error:
            raise RedazioneConflict(str(error)) from error
        summary = f"Respinto: {item['kind_label']} — {item['title']}. Motivo: {note}"
        self.log(
            actor=member,
            action="rifiuto",
            object_kind=kind,
            object_id=item_id,
            politician_id=item["politician_id"],
            summary=summary,
            details={"note": note, "author": item["author"]},
        )
        return {"ok": True, "summary": summary}

    def _apply_change(self, request_id: int, *, member: str, note: str | None) -> str:
        with self.session_factory.begin() as session:
            row = session.get(EditorialChangeRequest, request_id)
            if row is None or row.status is not ChangeRequestStatus.PENDING:
                raise RedazioneConflict("Richiesta non più in attesa.")
            if row.kind == "ritiro":
                target = session.get(PROFILE_MODELS[row.target_kind], row.target_id)
                if target is None or target.status is not ProfileContentStatus.PUBLISHED:
                    raise RedazioneConflict("Il contenuto non è più pubblicato.")
                target.status = ProfileContentStatus.SUPERSEDED
                target.review_note = f"Ritirato da {member}: {row.payload.get('reason')}"
                summary = f"Ritirato dal profilo pubblico: {row.summary}"
            elif row.kind == "classificazione":
                classification = row.payload["classification"]
                summary = f"Applicata la classificazione: {row.summary}"
            else:
                raise RedazioneConflict("Tipo di richiesta sconosciuto.")
            row.status = ChangeRequestStatus.APPROVED
            row.reviewed_by = member
            row.reviewed_at = self.clock()
            row.review_note = note
            kind, target_id, author = row.kind, row.target_id, row.created_by
        if kind == "classificazione":
            self.pledges.classify(
                target_id, PledgeClassificationRequest.model_validate(classification), classified_by=author
            )
        return summary

    # -------------------------------------------------------------- overview
    def overview(self, *, member: str) -> dict:
        queue = self.queue(member=member)
        counts: dict[str, int] = {}
        for item in queue:
            counts[item["kind"]] = counts.get(item["kind"], 0) + 1
        return {
            "member": member,
            "to_verify": sum(1 for item in queue if item["can_approve"]),
            "mine_pending": sum(1 for item in queue if item["own"]),
            "blocked": sum(1 for item in queue if item["blocked"]),
            "by_kind": [{"kind": kind, "label": KIND_LABELS[kind], "count": count} for kind, count in sorted(counts.items())],
            "recent": self.log_entries(limit=8)["items"],
        }


def _place(value: Any) -> str | None:
    if isinstance(value, dict):
        parts = [value.get("city"), value.get("subdivision")]
        return ", ".join(part for part in parts if part) or None
    return value or None


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "value") and not isinstance(value, (str, int, float, bool)):
        return value.value
    return value
