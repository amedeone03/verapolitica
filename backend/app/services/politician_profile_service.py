"""Editorial workflow for politician biography, career, positions and proceedings.

Pending records are reviewable. Public callers only see published rows.
Approved content is not rewritten: a later draft with the same identity key
supersedes the previous published row.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import Politician, PoliticianVersion
from backend.app.models.politician_profile import (
    PoliticianBiography,
    PoliticianCareerEntry,
    PoliticianPosition,
    PoliticianProceeding,
    PoliticianProfileSource,
    ProceedingType,
    ProfileContentKind,
    ProfileContentStatus,
)
from backend.app.schemas.politician_profile import (
    AdminProfileContentDetail,
    AdminProfileContentItem,
    AdminProfileContentList,
    BiographyDraftInput,
    CareerEntryDraftInput,
    PositionDraftInput,
    ProceedingDraftInput,
    ProfileSourceInput,
    PublicBiography,
    PublicCareerEntry,
    PublicPosition,
    PublicProceeding,
    PublicProfileSource,
)


CONTENT_MODELS = {
    ProfileContentKind.BIOGRAPHY: PoliticianBiography,
    ProfileContentKind.CAREER_ENTRY: PoliticianCareerEntry,
    ProfileContentKind.POSITION: PoliticianPosition,
    ProfileContentKind.PROCEEDING: PoliticianProceeding,
}

_ACTIVE = (ProfileContentStatus.PENDING, ProfileContentStatus.PUBLISHED)


class PoliticianProfileServiceError(RuntimeError):
    pass


class PoliticianProfileNotFoundError(PoliticianProfileServiceError):
    pass


class PoliticianProfileValidationError(PoliticianProfileServiceError):
    pass


class PoliticianProfileConflictError(PoliticianProfileServiceError):
    pass


class PoliticianProfileService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_biography(
        self, politician_id: int, payload: BiographyDraftInput
    ) -> tuple[int, str]:
        return self._upsert(
            politician_id,
            ProfileContentKind.BIOGRAPHY,
            payload.identity_key,
            payload.created_by,
            payload.sources,
            body=payload.body,
        )

    def upsert_career_entry(
        self, politician_id: int, payload: CareerEntryDraftInput
    ) -> tuple[int, str]:
        if payload.end_date and payload.end_date < payload.start_date:
            raise PoliticianProfileValidationError("end_date precedes start_date")
        return self._upsert(
            politician_id,
            ProfileContentKind.CAREER_ENTRY,
            payload.identity_key,
            payload.created_by,
            payload.sources,
            start_date=payload.start_date,
            end_date=payload.end_date,
            start_precision=payload.start_precision,
            end_precision=payload.end_precision,
            is_current=payload.is_current,
            role=payload.role.strip(),
            institution=payload.institution.strip(),
            organization=_blank_to_none(payload.organization),
            party_or_group=_blank_to_none(payload.party_or_group),
        )

    def upsert_position(
        self, politician_id: int, payload: PositionDraftInput
    ) -> tuple[int, str]:
        return self._upsert(
            politician_id,
            ProfileContentKind.POSITION,
            payload.identity_key,
            payload.created_by,
            payload.sources,
            topic=payload.topic.strip(),
            position_statement=payload.position_statement.strip(),
            verifiable_statement=payload.verifiable_statement.strip(),
            statement_date=payload.statement_date,
            statement_precision=payload.statement_precision,
        )

    def upsert_proceeding(
        self, politician_id: int, payload: ProceedingDraftInput
    ) -> tuple[int, str]:
        types = tuple(dict.fromkeys(payload.proceeding_types))
        if not types:
            raise PoliticianProfileValidationError("proceeding_types is required")
        if (
            payload.outcome_date
            and payload.event_date
            and payload.outcome_date < payload.event_date
        ):
            raise PoliticianProfileValidationError("outcome_date precedes event_date")
        return self._upsert(
            politician_id,
            ProfileContentKind.PROCEEDING,
            payload.identity_key,
            payload.created_by,
            payload.sources,
            title=payload.title.strip(),
            proceeding_types=[item.value for item in types],
            event_date=payload.event_date,
            event_precision=payload.event_precision,
            outcome=payload.outcome,
            outcome_date=payload.outcome_date,
            summary=payload.summary.strip(),
            outcome_summary=_blank_to_none(payload.outcome_summary),
        )

    def approve(
        self,
        kind: ProfileContentKind,
        content_id: int,
        *,
        reviewer: str,
        note: str | None = None,
    ) -> AdminProfileContentDetail:
        reviewer = reviewer.strip()
        if not reviewer:
            raise PoliticianProfileValidationError("reviewer is required")
        with self.session_factory.begin() as session:
            row = self._load(session, kind, content_id)
            if row.status is not ProfileContentStatus.PENDING:
                raise PoliticianProfileConflictError("only pending records can be approved")
            now = datetime.now(timezone.utc)
            version_id = session.scalar(
                select(Politician.current_version_id).where(Politician.id == row.politician_id)
            )
            if version_id is not None:
                published = session.scalar(
                    select(PoliticianVersion.published_at).where(
                        PoliticianVersion.id == version_id
                    )
                )
                row.politician_version_id = version_id if published is not None else None
            previous = session.scalar(
                select(CONTENT_MODELS[kind]).where(
                    CONTENT_MODELS[kind].politician_id == row.politician_id,
                    CONTENT_MODELS[kind].identity_key == row.identity_key,
                    CONTENT_MODELS[kind].status == ProfileContentStatus.PUBLISHED,
                    CONTENT_MODELS[kind].id != row.id,
                )
            )
            if previous is not None:
                previous.status = ProfileContentStatus.SUPERSEDED
            row.status = ProfileContentStatus.PUBLISHED
            row.reviewed_by = reviewer
            row.reviewed_at = now
            row.published_at = now
            row.review_note = _blank_to_none(note)
            session.flush()
            return PoliticianProfileService._admin_detail(session, kind, row)

    def reject(
        self,
        kind: ProfileContentKind,
        content_id: int,
        *,
        reviewer: str,
        note: str | None = None,
    ) -> AdminProfileContentDetail:
        reviewer = reviewer.strip()
        if not reviewer:
            raise PoliticianProfileValidationError("reviewer is required")
        with self.session_factory.begin() as session:
            row = self._load(session, kind, content_id)
            if row.status is not ProfileContentStatus.PENDING:
                raise PoliticianProfileConflictError("only pending records can be rejected")
            row.status = ProfileContentStatus.REJECTED
            row.reviewed_by = reviewer
            row.reviewed_at = datetime.now(timezone.utc)
            row.review_note = _blank_to_none(note)
            session.flush()
            return PoliticianProfileService._admin_detail(session, kind, row)

    def list_admin(
        self,
        *,
        kind: ProfileContentKind | None = None,
        status: ProfileContentStatus | None = None,
        politician_id: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> AdminProfileContentList:
        kinds = (kind,) if kind is not None else tuple(CONTENT_MODELS)
        items: list[AdminProfileContentItem] = []
        with self.session_factory() as session:
            for content_kind in kinds:
                model = CONTENT_MODELS[content_kind]
                query = select(model)
                if status is not None:
                    query = query.where(model.status == status)
                if politician_id is not None:
                    query = query.where(model.politician_id == politician_id)
                for row in session.scalars(query.order_by(model.created_at.desc(), model.id.desc())):
                    sources = PoliticianProfileService._sources(
                        session, content_kind, row.id
                    )
                    items.append(
                        AdminProfileContentItem(
                            id=row.id,
                            politician_id=row.politician_id,
                            kind=content_kind,
                            identity_key=row.identity_key,
                            status=row.status,
                            title=_admin_title(content_kind, row),
                            sources_incomplete=any(item.incomplete for item in sources),
                            created_by=row.created_by,
                            reviewed_by=row.reviewed_by,
                            published_at=row.published_at,
                            created_at=row.created_at,
                        )
                    )
        items.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        total = len(items)
        sliced = items[offset : offset + limit]
        return AdminProfileContentList(
            items=tuple(sliced), total=total, offset=offset, limit=limit
        )

    def get_admin(
        self, kind: ProfileContentKind, content_id: int
    ) -> AdminProfileContentDetail:
        with self.session_factory() as session:
            row = self._load(session, kind, content_id)
            return PoliticianProfileService._admin_detail(session, kind, row)

    @staticmethod
    def published_biography(session: Session, politician_id: int) -> PublicBiography | None:
        row = session.scalar(
            select(PoliticianBiography)
            .where(
                PoliticianBiography.politician_id == politician_id,
                PoliticianBiography.status == ProfileContentStatus.PUBLISHED,
            )
            .order_by(PoliticianBiography.published_at.desc(), PoliticianBiography.id.desc())
        )
        if row is None or row.published_at is None:
            return None
        return PublicBiography(
            body=row.body,
            sources=PoliticianProfileService._public_sources(
                session, ProfileContentKind.BIOGRAPHY, row.id
            ),
            published_at=row.published_at,
        )

    @staticmethod
    def published_career_entries(
        session: Session, politician_id: int
    ) -> tuple[PublicCareerEntry, ...]:
        rows = session.scalars(
            select(PoliticianCareerEntry)
            .where(
                PoliticianCareerEntry.politician_id == politician_id,
                PoliticianCareerEntry.status == ProfileContentStatus.PUBLISHED,
            )
            .order_by(PoliticianCareerEntry.start_date, PoliticianCareerEntry.id)
        )
        return tuple(
            PublicCareerEntry(
                start_date=row.start_date,
                end_date=row.end_date,
                start_precision=row.start_precision,
                end_precision=row.end_precision,
                is_current=row.is_current,
                role=row.role,
                institution=row.institution,
                organization=row.organization,
                party_or_group=row.party_or_group,
                sources=PoliticianProfileService._public_sources(
                    session, ProfileContentKind.CAREER_ENTRY, row.id
                ),
            )
            for row in rows
        )

    @staticmethod
    def published_positions(
        session: Session, politician_id: int
    ) -> tuple[PublicPosition, ...]:
        rows = session.scalars(
            select(PoliticianPosition)
            .where(
                PoliticianPosition.politician_id == politician_id,
                PoliticianPosition.status == ProfileContentStatus.PUBLISHED,
            )
            .order_by(PoliticianPosition.statement_date, PoliticianPosition.id)
        )
        return tuple(
            PublicPosition(
                topic=row.topic,
                position_statement=row.position_statement,
                verifiable_statement=row.verifiable_statement,
                statement_date=row.statement_date,
                statement_precision=row.statement_precision,
                sources=PoliticianProfileService._public_sources(
                    session, ProfileContentKind.POSITION, row.id
                ),
            )
            for row in rows
        )

    @staticmethod
    def published_proceedings(
        session: Session, politician_id: int
    ) -> tuple[PublicProceeding, ...]:
        rows = session.scalars(
            select(PoliticianProceeding)
            .where(
                PoliticianProceeding.politician_id == politician_id,
                PoliticianProceeding.status == ProfileContentStatus.PUBLISHED,
            )
            .order_by(PoliticianProceeding.event_date, PoliticianProceeding.id)
        )
        return tuple(
            PublicProceeding(
                title=row.title,
                proceeding_types=tuple(ProceedingType(item) for item in row.proceeding_types),
                event_date=row.event_date,
                event_precision=row.event_precision,
                outcome=row.outcome,
                outcome_date=row.outcome_date,
                summary=row.summary,
                outcome_summary=row.outcome_summary,
                sources=PoliticianProfileService._public_sources(
                    session, ProfileContentKind.PROCEEDING, row.id
                ),
            )
            for row in rows
        )

    def _upsert(
        self,
        politician_id: int,
        kind: ProfileContentKind,
        identity_key: str,
        created_by: str,
        sources: tuple[ProfileSourceInput, ...],
        **fields,
    ):
        model = CONTENT_MODELS[kind]
        with self.session_factory.begin() as session:
            politician = session.get(Politician, politician_id)
            if politician is None:
                raise PoliticianProfileNotFoundError("politician not found")
            existing = session.scalar(
                select(model).where(
                    model.politician_id == politician_id,
                    model.identity_key == identity_key,
                    model.status.in_(_ACTIVE),
                )
            )
            if existing is not None:
                return existing.id, "skipped"
            row = model(
                politician_id=politician_id,
                identity_key=identity_key,
                status=ProfileContentStatus.PENDING,
                created_by=created_by.strip(),
                **fields,
            )
            session.add(row)
            session.flush()
            self._store_sources(session, kind, row.id, sources)
            return row.id, "created"

    def _load(self, session: Session, kind: ProfileContentKind, content_id: int):
        row = session.get(CONTENT_MODELS[kind], content_id)
        if row is None:
            raise PoliticianProfileNotFoundError("profile content not found")
        return row

    def _store_sources(
        self,
        session: Session,
        kind: ProfileContentKind,
        content_id: int,
        sources: tuple[ProfileSourceInput, ...],
    ) -> None:
        for index, source in enumerate(sources):
            url = str(source.url) if source.url else None
            session.add(
                PoliticianProfileSource(
                    content_kind=kind,
                    content_id=content_id,
                    sort_index=index,
                    title=source.title,
                    name=source.name,
                    url=url,
                    kind=source.kind,
                    excerpt=source.excerpt,
                    incomplete=url is None,
                )
            )

    @staticmethod
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

    @staticmethod
    def _public_sources(
        session: Session, kind: ProfileContentKind, content_id: int
    ) -> tuple[PublicProfileSource, ...]:
        return tuple(
            PublicProfileSource(
                title=row.title,
                name=row.name,
                url=row.url,
                kind=row.kind,
                excerpt=row.excerpt,
            )
            for row in PoliticianProfileService._sources(session, kind, content_id)
        )

    @staticmethod
    def _admin_detail(
        session: Session, kind: ProfileContentKind, row
    ) -> AdminProfileContentDetail:
        sources = PoliticianProfileService._sources(session, kind, row.id)
        return AdminProfileContentDetail(
            id=row.id,
            politician_id=row.politician_id,
            kind=kind,
            identity_key=row.identity_key,
            status=row.status,
            created_by=row.created_by,
            reviewed_by=row.reviewed_by,
            reviewed_at=row.reviewed_at,
            published_at=row.published_at,
            review_note=row.review_note,
            sources=tuple(
                PublicProfileSource(
                    title=item.title,
                    name=item.name,
                    url=item.url,
                    kind=item.kind,
                    excerpt=item.excerpt,
                )
                for item in sources
            ),
            sources_incomplete=any(item.incomplete for item in sources),
            body=getattr(row, "body", None),
            topic=getattr(row, "topic", None),
            title=getattr(row, "title", None) or getattr(row, "role", None),
            summary=getattr(row, "summary", None) or getattr(row, "position_statement", None),
            role=getattr(row, "role", None),
            institution=getattr(row, "institution", None),
            proceeding_types=(
                tuple(ProceedingType(item) for item in row.proceeding_types)
                if getattr(row, "proceeding_types", None)
                else None
            ),
            outcome=getattr(row, "outcome", None),
        )


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _admin_title(kind: ProfileContentKind, row) -> str:
    if kind is ProfileContentKind.BIOGRAPHY:
        return "Biografia"
    if kind is ProfileContentKind.CAREER_ENTRY:
        return row.role
    if kind is ProfileContentKind.POSITION:
        return row.topic
    return row.title
