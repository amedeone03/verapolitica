"""The redazione console's single entry point.

Everything an editor does goes through here, so three rules hold everywhere:

1. **Nothing reaches the citizen without a second person.** Every block of a
   profile, every promise, every promise status, every news item and every
   withdrawal or re-classification is first a draft or a change request; a
   member other than its author approves it (rule 8 of the "Modelli di
   scrittura": chi scrive non è chi verifica). "Non mantenuta" needs two
   approvers, neither of them the author.
2. **Every change is logged.** One append-only ``EditorialLogEntry`` per write,
   edit, approval, rejection, withdrawal, status assignment and discard of a
   news draft that never reached the citizen.
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
from datetime import date, datetime, timedelta, timezone
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
    EditorialSymbol,
    ImmutableEditorialPostError,
    FeedScope,
    Municipality,
    Region,
    SYMBOL_KINDS,
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
    PROCEEDING_CATEGORY_TYPES,
    ProceedingCategory,
    ProceedingType,
    proceeding_category_for,
    ProfileContentKind,
    ProfileContentStatus,
    ProfileSourceKind,
)
from backend.app.core.text import normalize_search_text
from backend.app.services.matching_service import normalize_person_name
from backend.app.schemas import ProposalObservation
from backend.app.services import symbols as symbols_module
from backend.app.schemas.feed import Citation, EditorialPostRequest
from backend.app.schemas.politician import PoliticianVersionProfile
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
    "proceeding": "Procedimento giudiziario",
    "promise": "Promessa",
    "proposal": "Proposta",
    "status": "Stato di una promessa",
    "news": "Notizia",
    "change": "Modifica a contenuto pubblico",
    "symbol": "Logo o stemma",
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
GOVERNMENT_OFFICES = {
    "presidente del consiglio": "Presidente del Consiglio dei ministri",
    "vice presidente del consiglio": "Vicepresidente del Consiglio dei ministri",
    "ministro": "Ministro",
    "ministro senza portafoglio": "Ministro senza portafoglio",
    "sottosegretario": "Sottosegretario",
}


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
        leads: frozenset[str] | set[str] = frozenset(),
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        # Admins write and publish at once, and publish what others write.
        # With no admin named, any second member verifies (four-eyes).
        self.leads = frozenset(leads)
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
            logos = symbols_module.logo_urls(session, "party")
            return [
                {
                    "id": row.id,
                    "name": f"{row.canonical_given_name} {row.canonical_family_name}",
                    "party": card_module.party_dict(parties[row.id], logos) if row.id in parties else None,
                    "birth_date": _iso(row.birth_date),
                    "public": row.current_version_id is not None,
                    "pending": pending.get(row.id, 0),
                }
                for row in rows
            ]

    def propose_politician(self, payload: dict, *, member: str) -> dict:
        """A new public identity. Another member must approve it before the citizen sees it."""

        given = _clean(payload.get("given_name"))[:200]
        family = _clean(payload.get("family_name"))[:200]
        birth = _parse_date(payload.get("birth_date"), "Data di nascita")
        source_url = _clean(payload.get("source_url"))
        office = _clean(payload.get("office"))
        institution = _clean(payload.get("institution")) or "Governo della Repubblica"
        start = _parse_date(payload.get("start_date"), "Inizio incarico")
        errors: dict[str, str] = {}
        if len(given) < 2:
            errors["given_name"] = "Scrivi il nome."
        if len(family) < 2:
            errors["family_name"] = "Scrivi il cognome."
        if not source_url.startswith("https://") or not urlsplit(source_url).netloc:
            errors["source_url"] = "Indica una fonte https (scheda Camera, Senato, Governo o pagina ufficiale)."
        if office:
            if office not in GOVERNMENT_OFFICES:
                errors["office"] = "Scegli un incarico di Governo, o lascialo vuoto."
            if start is None:
                errors["start_date"] = "Indica da quando ricopre l'incarico."
        if errors:
            raise RedazioneValidation(
                "Controlla i campi del politico.",
                [{"level": "error", "field": field, "message": message} for field, message in errors.items()],
            )
        folded = normalize_person_name(given, family)
        with self.session_factory.begin() as session:
            for row in session.scalars(select(Politician)):
                if row.normalized_name != folded:
                    continue
                if birth and row.birth_date and row.birth_date != birth:
                    continue
                raise RedazioneConflict(f"«{row.canonical_given_name} {row.canonical_family_name}» è già nell'elenco.")
            request = EditorialChangeRequest(
                kind="politico",
                target_kind="politician",
                target_id=0,
                politician_id=None,
                summary=f"Nuovo politico: {given} {family}",
                payload={
                    "given_name": given,
                    "family_name": family,
                    "birth_date": birth.isoformat() if birth else None,
                    "source_url": source_url,
                    "office": office or None,
                    "institution": institution if office else None,
                    "start_date": start.isoformat() if office and start else None,
                    "office_label": GOVERNMENT_OFFICES.get(office) if office else None,
                    **({"image": image} if (image := self._image_payload(session, payload)) else {}),
                },
                created_by=member,
                created_at=self.clock(),
            )
            session.add(request)
            session.flush()
            self._log(
                session,
                actor=member,
                action="proposta",
                object_kind="change",
                object_id=request.id,
                summary=f"Proposto: {request.summary}.",
                details=request.payload,
            )
            return {"id": request.id, "summary": request.summary}

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
            "can_self_verify": row.status is ProfileContentStatus.PENDING
            and row.created_by == member
            and self.can_self_verify(kind, member),
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
            "category": row.category or "proceeding",
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
                types = tuple(ProceedingType(item) for item in (payload.get("proceeding_types") or []) if item)
                category = ProceedingCategory(payload.get("category") or proceeding_category_for(types).value)
                if not types:
                    raise RedazioneValidation("Scegli il tipo di vicenda.")
                if any(item not in PROCEEDING_CATEGORY_TYPES[category] for item in types):
                    raise RedazioneValidation(
                        "Le controversie stanno nel box «Controversie»; nei procedimenti giudiziari vanno solo indagini e processi a carico del politico."
                        if category is ProceedingCategory.PROCEEDING
                        else "Un'indagine o un processo a carico del politico va nel box «Procedimenti giudiziari», non tra le controversie."
                    )
                fields = {
                    "title": _clean(payload.get("title")),
                    "category": category,
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
                    if name == "category":
                        value = value.value
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
            item.as_dict()
            for item in style.news_findings(
                {"title": post.title, "blocks": blocks, "sources": sources, "card": composed}
            )
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
            "can_discard": post.status is not EditorialPostStatus.PUBLISHED,
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
            logos = symbols_module.logo_urls(session, "party")
            return [
                card_module.party_dict(row, logos)
                for row in session.scalars(select(PoliticalParty).order_by(PoliticalParty.canonical_name))
            ]

    # --------------------------------------------------- parties and symbols
    SYMBOL_LABELS = {
        "party": "Logo del partito",
        "region": "Stemma della regione",
        "province": "Stemma della provincia",
        "politician": "Foto del politico",
    }

    @staticmethod
    def _provinces(session: Session) -> dict[str, dict]:
        rows = session.execute(
            select(Municipality.province_abbreviation, func.min(Municipality.province_name), func.min(Municipality.region_id))
            .group_by(Municipality.province_abbreviation)
        )
        return {
            abbreviation: {"key": abbreviation, "name": name, "region_id": region_id}
            for abbreviation, name, region_id in rows
            if abbreviation
        }

    def _symbol_targets(self, session: Session, kind: str) -> dict[str, dict]:
        if kind == "party":
            return {
                str(row.id): {"key": str(row.id), "name": row.canonical_name, "abbreviation": row.abbreviation, "website": row.official_website_url}
                for row in session.scalars(select(PoliticalParty).order_by(PoliticalParty.canonical_name))
            }
        if kind == "region":
            return {
                str(row.id): {"key": str(row.id), "name": row.canonical_name, "istat_code": row.istat_code}
                for row in session.scalars(select(Region).order_by(Region.canonical_name))
            }
        if kind == "province":
            return dict(sorted(self._provinces(session).items(), key=lambda item: item[1]["name"] or ""))
        if kind == "politician":
            # Only published schede: a photo appears on the public site, so the person must too.
            rows = session.execute(
                select(Politician.id, Politician.canonical_given_name, Politician.canonical_family_name)
                .join(PoliticianVersion, PoliticianVersion.id == Politician.current_version_id)
                .where(PoliticianVersion.published_at.is_not(None))
                .order_by(Politician.canonical_family_name, Politician.canonical_given_name, Politician.id)
            )
            return {
                str(pid): {"key": str(pid), "name": f"{given} {family}".strip()}
                for pid, given, family in rows
            }
        raise RedazioneValidation("Tipo di simbolo sconosciuto.")

    def symbols(self) -> dict:
        """Parties, regions, provinces and politicians with their approved image and pending proposals."""

        with self.session_factory() as session:
            pending: dict[tuple[str, str], list[dict]] = {}
            for row in session.scalars(
                select(EditorialChangeRequest).where(
                    EditorialChangeRequest.status == ChangeRequestStatus.PENDING,
                    EditorialChangeRequest.kind.in_(("simbolo", "partito", "partito_modifica")),
                )
            ):
                key = (
                    (row.target_kind, str(row.payload.get("key"))) if row.kind == "simbolo"
                    else ("party-edit", str(row.target_id)) if row.kind == "partito_modifica"
                    else ("party", "nuovo")
                )
                pending.setdefault(key, []).append(
                    {"id": row.id, "created_by": row.created_by, "summary": row.summary, "payload": row.payload}
                )
            result: dict[str, Any] = {
                "licenses": [{"key": k, "label": v} for k, v in symbols_module.LICENSES.items()],
                "portrait_licenses": [{"key": k, "label": v} for k, v in symbols_module.licenses_for("politician").items()],
            }
            for kind in SYMBOL_KINDS:
                approved = symbols_module.symbol_rows(session, kind)
                result[kind] = [
                    {
                        **target,
                        "symbol": symbols_module.symbol_dict(approved.get(key)),
                        "pending": pending.get((kind, key), []),
                        "pending_edit": pending.get(("party-edit", key), []) if kind == "party" else [],
                    }
                    for key, target in self._symbol_targets(session, kind).items()
                ]
            result["new_parties"] = pending.get(("party", "nuovo"), [])
        return result

    def propose_symbol(self, payload: dict, *, member: str) -> dict:
        kind = str(payload.get("kind") or "")
        key = str(payload.get("key") or "")
        credit = _clean(payload.get("credit"))[:300]
        license_key = str(payload.get("license") or "")
        source_url = _clean(payload.get("source_url"))
        errors = {}
        photo = kind == "politician"
        what = "la foto" if photo else "il logo"
        if kind not in SYMBOL_KINDS:
            errors["kind"] = "Scegli partito, regione, provincia o politico."
        if not credit:
            errors["credit"] = f"Indica il titolare o l'autore del{'la foto' if photo else ' logo'}."
        if photo and not license_key:
            license_key = "nel-credito"
        if license_key not in symbols_module.licenses_for(kind):
            errors["license"] = f"Scegli la licenza con cui {what} può essere pubblicat{'a' if photo else 'o'}."
        if (source_url or not photo) and (not source_url.startswith("https://") or not urlsplit(source_url).netloc):
            errors["source_url"] = f"Indica la pagina https da cui proviene {what}."
        if errors:
            raise RedazioneValidation("Controlla i campi del logo.", [{"level": "error", "field": f, "message": m} for f, m in errors.items()])
        with self.session_factory.begin() as session:
            targets = self._symbol_targets(session, kind)
            if key not in targets:
                raise RedazioneNotFound("Partito, regione o provincia non trovato.")
            image = session.get(EditorialImage, int(payload.get("image_id") or 0))
            if image is None:
                raise RedazioneValidation(f"Carica prima l'immagine del{'la foto' if photo else ' logo'}.")
            name = targets[key]["name"]
            request = EditorialChangeRequest(
                kind="simbolo",
                target_kind=kind,
                target_id=int(key) if key.isdigit() else 0,
                politician_id=None,
                summary=f"{self.SYMBOL_LABELS[kind]}: {name}",
                payload={
                    "key": key, "name": name, "image_id": image.id, "image_url": symbols_module.media_url(image.id),
                    "credit": credit, "license": license_key, "license_label": symbols_module.LICENSES[license_key],
                    "source_url": source_url,
                },
                created_by=member,
                created_at=self.clock(),
            )
            session.add(request)
            session.flush()
            self._log(
                session, actor=member, action="proposta", object_kind="change", object_id=request.id,
                summary=f"Proposto: {request.summary} (fonte {urlsplit(source_url).netloc}, {symbols_module.LICENSES[license_key]}).",
                details=request.payload,
            )
            return {"id": request.id, "summary": request.summary}

    def propose_party_edit(self, party_id: int, payload: dict, *, member: str) -> dict:
        """Change a party's name, abbreviation or website, or remove its logo. Waits for a second member."""

        name = _clean(payload.get("name"))[:300]
        abbreviation = _clean(payload.get("abbreviation"))[:40] or None
        website = _clean(payload.get("website")) or None
        remove_logo = bool(payload.get("remove_logo"))
        reason = _clean(payload.get("reason"))[:500]
        errors = {}
        if len(name) < 2:
            errors["name"] = "Scrivi il nome ufficiale del partito."
        if website and (not website.startswith("https://") or not urlsplit(website).netloc):
            errors["website"] = "Il sito ufficiale deve iniziare con https://."
        if not reason:
            errors["reason"] = "Spiega perché cambia (es. «nuovo nome dal congresso del …»)."
        if errors:
            raise RedazioneValidation("Controlla i campi del partito.", [{"level": "error", "field": f, "message": m} for f, m in errors.items()])
        with self.session_factory.begin() as session:
            party = session.get(PoliticalParty, party_id)
            if party is None:
                raise RedazioneNotFound("Partito non trovato.")
            before = {"name": party.canonical_name, "abbreviation": party.abbreviation, "website": party.official_website_url}
            after = {"name": name, "abbreviation": abbreviation, "website": website}
            has_logo = session.scalar(
                select(EditorialSymbol.id).where(EditorialSymbol.kind == "party", EditorialSymbol.key == str(party_id))
            ) is not None
            if before == after and not (remove_logo and has_logo):
                raise RedazioneValidation("Non c'è nessuna modifica da proporre.")
            folded = normalize_search_text(name)
            if any(normalize_search_text(row.canonical_name) == folded and row.id != party_id for row in session.scalars(select(PoliticalParty))):
                raise RedazioneConflict("Esiste già un altro partito con questo nome.")
            changes = [label for key, label in (("name", "nome"), ("abbreviation", "sigla"), ("website", "sito")) if before[key] != after[key]]
            if remove_logo and has_logo:
                changes.append("logo rimosso")
            request = EditorialChangeRequest(
                kind="partito_modifica",
                target_kind="party",
                target_id=party_id,
                politician_id=None,
                summary=f"Modifica del partito {party.canonical_name}: {', '.join(changes)}",
                payload={"before": before, "after": after, "remove_logo": remove_logo and has_logo, "reason": reason},
                created_by=member,
                created_at=self.clock(),
            )
            session.add(request)
            session.flush()
            self._log(
                session, actor=member, action="proposta", object_kind="change", object_id=request.id,
                summary=f"Proposto: {request.summary}. Motivo: {reason}", details=request.payload,
            )
            return {"id": request.id, "summary": request.summary}

    def _image_payload(self, session: Session, payload: dict) -> dict | None:
        """The photo or logo sent with a new politician or party: image, credit, optional source."""

        image_id = int(payload.get("image_id") or 0)
        if not image_id:
            return None
        if session.get(EditorialImage, image_id) is None:
            raise RedazioneValidation("Immagine non trovata: caricala di nuovo.")
        credit = _clean(payload.get("image_credit"))[:300]
        if not credit:
            raise RedazioneValidation("Scrivi da dove viene l'immagine (es. «Camera dei deputati», «Wikimedia Commons, CC BY-SA»).")
        source = _clean(payload.get("image_source_url"))
        if source and (not source.startswith("https://") or not urlsplit(source).netloc):
            raise RedazioneValidation("Il link dell'immagine deve iniziare con https://.")
        return {"image_id": image_id, "credit": credit, "source_url": source}

    def _attach_image(self, session: Session, kind: str, key: str, image: dict | None, *, proposed_by: str, approved_by: str) -> None:
        if not image:
            return
        current = session.scalar(select(EditorialSymbol).where(EditorialSymbol.kind == kind, EditorialSymbol.key == key))
        if current is None:
            current = EditorialSymbol(kind=kind, key=key)
            session.add(current)
        current.image_id = image["image_id"]
        current.credit = image["credit"]
        current.license = image.get("license") or "nel-credito"
        current.source_url = image.get("source_url") or ""
        current.proposed_by = proposed_by
        current.approved_by = approved_by
        current.approved_at = self.clock()

    def propose_party(self, payload: dict, *, member: str) -> dict:
        name = _clean(payload.get("name"))[:300]
        abbreviation = _clean(payload.get("abbreviation"))[:40] or None
        website = _clean(payload.get("website")) or None
        source_url = _clean(payload.get("source_url"))
        errors = {}
        if len(name) < 2:
            errors["name"] = "Scrivi il nome ufficiale del partito."
        if website and (not website.startswith("https://") or not urlsplit(website).netloc):
            errors["website"] = "Il sito ufficiale deve iniziare con https://."
        if not source_url.startswith("https://") or not urlsplit(source_url).netloc:
            errors["source_url"] = "Indica una fonte https che attesti il partito (statuto, registro, sito)."
        if errors:
            raise RedazioneValidation("Controlla i campi del partito.", [{"level": "error", "field": f, "message": m} for f, m in errors.items()])
        with self.session_factory.begin() as session:
            folded = normalize_search_text(name)
            for row in session.scalars(select(PoliticalParty)):
                if normalize_search_text(row.canonical_name) == folded:
                    raise RedazioneConflict(f"«{row.canonical_name}» è già nell'elenco dei partiti.")
            request = EditorialChangeRequest(
                kind="partito",
                target_kind="party",
                target_id=0,
                politician_id=None,
                summary=f"Nuovo partito: {name}" + (f" ({abbreviation})" if abbreviation else ""),
                payload={
                    "name": name, "abbreviation": abbreviation, "website": website, "source_url": source_url,
                    **({"image": image} if (image := self._image_payload(session, payload)) else {}),
                },
                created_by=member,
                created_at=self.clock(),
            )
            session.add(request)
            session.flush()
            self._log(
                session, actor=member, action="proposta", object_kind="change", object_id=request.id,
                summary=f"Proposto: {request.summary}.", details=request.payload,
            )
            return {"id": request.id, "summary": request.summary}

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

    def _change_response(self, session: Session, row: EditorialChangeRequest, member: str) -> dict:
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
            "can_self_verify": row.status is ChangeRequestStatus.PENDING
            and row.created_by == member
            and self.can_self_verify("change", member),
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
                            title=("Controversia" if item["data"].get("category") == "controversy" else KIND_LABELS[kind])
                            + self._profile_title_suffix(kind, item["data"]),
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

    def _queue_item(
        self,
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
            "kind_label": "Controversia" if kind == "proceeding" and (preview or {}).get("category") == "controversy" else KIND_LABELS[kind],
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
            "can_approve": author != member and not blocked and self.can_publish(member),
            "can_self_verify": author == member and not blocked and self.can_self_verify(kind, member),
            "can_discard": kind == "news",
            "approvals": [],
            "approvals_required": 1,
        }

    # ------------------------------------------------------------- decisions
    def _queue_entry(self, kind: str, item_id: int, member: str) -> dict:
        for item in self.queue(member=member):
            if item["kind"] == kind and item["id"] == item_id:
                return item
        raise RedazioneNotFound("Elemento non più in attesa di verifica.")

    # Pledge verdicts move the public score and keep their own two-person rule.
    SELF_VERIFY_EXCLUDED = frozenset({"status"})

    def is_lead(self, member: str) -> bool:
        return member in self.leads

    def can_self_verify(self, kind: str, member: str) -> bool:
        return self.is_lead(member) and kind not in self.SELF_VERIFY_EXCLUDED

    def can_publish(self, member: str) -> bool:
        """With admins named, only they publish; otherwise any member (four-eyes)."""

        return not self.leads or self.is_lead(member)

    def publish_own(self, kind: str, item_id: int, *, member: str, note: str | None = None) -> dict:
        """A capo squadra publishes what they just wrote, without a second person."""

        if not self.can_self_verify(kind, member):
            raise RedazioneConflict("Solo un admin pubblica direttamente ciò che scrive.")
        return self.approve(kind, item_id, member=member, note=note or "Pubblicato da un admin.")

    def approve(self, kind: str, item_id: int, *, member: str, note: str | None = None, extra: dict | None = None) -> dict:
        item = self._queue_entry(kind, item_id, member)
        if not self.can_publish(member):
            raise RedazioneConflict("Pubblica un admin della redazione.")
        self_verified = bool(item["own"])
        if self_verified and not self.can_self_verify(kind, member):
            if kind in self.SELF_VERIFY_EXCLUDED and self.is_lead(member):
                raise RedazioneConflict("Lo stato di una promessa cambia il punteggio: lo approva una seconda persona, anche se sei admin.")
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
        if self_verified:
            details["self_verified"] = True
            details["role"] = "admin"
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
                self.editorial.publish(item_id, reviewer=member, note=note, allow_author=self_verified)
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
        if self_verified:
            summary = f"{summary} Pubblicato direttamente da un admin."
        self.log(
            actor=member,
            action="approvazione",
            object_kind=kind,
            object_id=item_id,
            politician_id=politician_id,
            summary=summary,
            details=details,
        )
        return {"ok": True, "summary": summary, "self_verified": self_verified}

    def reject(self, kind: str, item_id: int, *, member: str, note: str) -> dict:
        note = _clean(note)
        if not note:
            raise RedazioneValidation("Scrivi cosa va corretto: chi ha scritto lo leggerà.")
        item = self._queue_entry(kind, item_id, member)
        if not self.can_publish(member):
            raise RedazioneConflict("Respinge un admin della redazione.")
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

    def discard_news(self, post_id: int, *, member: str) -> dict:
        """Remove a pending or rejected news draft. Published posts stay immutable."""

        with self.session_factory.begin() as session:
            post = session.get(EditorialPost, post_id)
            if post is None:
                raise RedazioneNotFound("notizia non trovata")
            if post.status is EditorialPostStatus.PUBLISHED:
                raise RedazioneConflict(
                    "Una notizia pubblicata non si elimina: si pubblica una rettifica visibile."
                )
            title = post.title
            status = post.status.value
            author = post.created_by
            politician_ids = (post.blocks or {}).get("politician_ids") or []
            politician_id = politician_ids[0] if politician_ids else None
            details = {
                "title": title,
                "status": status,
                "author": author,
                "blocks": _jsonable(post.blocks),
            }
            try:
                session.delete(post)
                session.flush()
            except ImmutableEditorialPostError as error:
                raise RedazioneConflict(
                    "Una notizia pubblicata non si elimina: si pubblica una rettifica visibile."
                ) from error
            summary = f"Eliminata la notizia «{title}»."
            self._log(
                session,
                actor=member,
                action="eliminazione",
                object_kind="news",
                object_id=post_id,
                politician_id=politician_id,
                summary=summary,
                details=details,
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
            elif row.kind == "simbolo":
                payload = row.payload
                if session.get(EditorialImage, payload["image_id"]) is None:
                    raise RedazioneConflict("L'immagine del logo non esiste più.")
                current = session.scalar(
                    select(EditorialSymbol).where(EditorialSymbol.kind == row.target_kind, EditorialSymbol.key == payload["key"])
                )
                if current is None:
                    current = EditorialSymbol(kind=row.target_kind, key=payload["key"])
                    session.add(current)
                current.image_id = payload["image_id"]
                current.credit = payload["credit"]
                current.license = payload["license"]
                current.source_url = payload["source_url"]
                current.proposed_by = row.created_by
                current.approved_by = member
                current.approved_at = self.clock()
                summary = f"Pubblicato: {row.summary}"
            elif row.kind == "partito_modifica":
                payload = row.payload
                party = session.get(PoliticalParty, row.target_id)
                if party is None:
                    raise RedazioneConflict("Il partito non esiste più.")
                current = {"name": party.canonical_name, "abbreviation": party.abbreviation, "website": party.official_website_url}
                if current != payload["before"]:
                    raise RedazioneConflict("Il partito è cambiato dopo la proposta: proponi di nuovo la modifica.")
                party.canonical_name = payload["after"]["name"]
                party.abbreviation = payload["after"]["abbreviation"]
                party.official_website_url = payload["after"]["website"]
                if payload.get("remove_logo"):
                    symbol = session.scalar(
                        select(EditorialSymbol).where(EditorialSymbol.kind == "party", EditorialSymbol.key == str(party.id))
                    )
                    if symbol is not None:
                        session.delete(symbol)
                summary = f"Applicata: {row.summary}"
            elif row.kind == "partito":
                payload = row.payload
                folded = normalize_search_text(payload["name"])
                if any(normalize_search_text(item.canonical_name) == folded for item in session.scalars(select(PoliticalParty))):
                    raise RedazioneConflict("Il partito è già nell'elenco.")
                party = PoliticalParty(
                    canonical_name=payload["name"],
                    abbreviation=payload.get("abbreviation"),
                    official_website_url=payload.get("website"),
                    search_primary=folded,
                    search_document=normalize_search_text(" ".join(filter(None, [payload["name"], payload.get("abbreviation")]))),
                )
                session.add(party)
                session.flush()
                row.target_id = party.id
                self._attach_image(session, "party", str(party.id), payload.get("image"), proposed_by=row.created_by, approved_by=member)
                summary = f"Aggiunto all'elenco: {row.summary.removeprefix('Nuovo partito: ')}"
            elif row.kind == "politico":
                payload = row.payload
                folded = normalize_person_name(payload["given_name"], payload["family_name"])
                birth = date.fromisoformat(payload["birth_date"]) if payload.get("birth_date") else None
                for existing in session.scalars(select(Politician)):
                    if existing.normalized_name != folded:
                        continue
                    if birth and existing.birth_date and existing.birth_date != birth:
                        continue
                    raise RedazioneConflict("Il politico è già nell'elenco.")
                politician = Politician(
                    canonical_given_name=payload["given_name"],
                    canonical_family_name=payload["family_name"],
                    normalized_name=folded,
                    birth_date=birth,
                )
                session.add(politician)
                session.flush()
                mandates = []
                if payload.get("office") and payload.get("start_date"):
                    mandates.append(
                        {
                            "institution": payload.get("institution") or "Governo della Repubblica",
                            "office": payload["office"],
                            "legislature": "Governo",
                            "mandate_type": "government",
                            "start_date": payload["start_date"],
                            "end_date": None,
                        }
                    )
                profile = PoliticianVersionProfile.model_validate(
                    {
                        "given_name": payload["given_name"],
                        "family_name": payload["family_name"],
                        "birth_date": payload.get("birth_date"),
                        "official_homepage_url": payload["source_url"],
                        "mandates": mandates,
                    }
                )
                version = PoliticianVersion(
                    politician_id=politician.id,
                    version_number=1,
                    profile_schema_version=1,
                    profile_data=profile.model_dump(mode="json"),
                    published_at=self.clock(),
                    created_at=self.clock(),
                )
                session.add(version)
                session.flush()
                politician.current_version_id = version.id
                self._attach_image(session, "politician", str(politician.id), payload.get("image"), proposed_by=row.created_by, approved_by=member)
                row.target_id = politician.id
                row.politician_id = politician.id
                summary = f"Aggiunto all'elenco: {payload['given_name']} {payload['family_name']}"
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
            **self._week_and_coverage(member),
        }

    def _week_and_coverage(self, member: str) -> dict:
        """What the desk published in the last 7 days, and how many public schede have a «Chi è»."""

        since = self.clock() - timedelta(days=7)
        with self.session_factory() as session:
            approved = select(func.count()).select_from(EditorialLogEntry).where(
                EditorialLogEntry.action == "approvazione", EditorialLogEntry.created_at >= since
            )
            public_ids = select(Politician.id).join(
                PoliticianVersion, PoliticianVersion.id == Politician.current_version_id
            ).where(PoliticianVersion.published_at.is_not(None))
            with_bio = select(func.count(func.distinct(PoliticianBiography.politician_id))).where(
                PoliticianBiography.status == ProfileContentStatus.PUBLISHED,
                PoliticianBiography.politician_id.in_(public_ids),
            )
            rejected = [
                {
                    "at": _iso(row.created_at),
                    "by": row.actor,
                    "object_kind": row.object_kind,
                    "object_id": row.object_id,
                    "politician_id": row.politician_id,
                    "summary": row.summary,
                    "note": (row.details or {}).get("note"),
                    "_created": row.created_at,
                }
                for row in session.scalars(
                    select(EditorialLogEntry)
                    .where(EditorialLogEntry.action == "rifiuto", EditorialLogEntry.created_at >= self.clock() - timedelta(days=14))
                    .order_by(EditorialLogEntry.created_at.desc())
                    .limit(50)
                )
                if (row.details or {}).get("author") == member
            ]
            # Gone from the list once the author saved that content again.
            rejected = [
                item for item in rejected
                if not session.scalar(
                    select(func.count()).select_from(EditorialLogEntry).where(
                        EditorialLogEntry.actor == member,
                        EditorialLogEntry.action != "rifiuto",
                        EditorialLogEntry.created_at > item["_created"],
                        EditorialLogEntry.object_kind == item["object_kind"],
                        (EditorialLogEntry.politician_id == item["politician_id"])
                        if item["politician_id"] is not None
                        else (EditorialLogEntry.object_id == item["object_id"]),
                    )
                )
            ][:10]
            for item in rejected:
                item.pop("_created", None)
            return {
                "my_rejected": rejected,
                "published_week": session.scalar(approved) or 0,
                "my_published_week": session.scalar(approved.where(EditorialLogEntry.actor == member)) or 0,
                "public_schede": session.scalar(select(func.count()).select_from(public_ids.subquery())) or 0,
                "schede_with_bio": session.scalar(with_bio) or 0,
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
