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
    EditorialPreviewBiography,
    EditorialPreviewCareerEntry,
    EditorialPreviewPosition,
    EditorialPreviewProceeding,
    EditorialPreviewResponse,
    PositionDraftInput,
    ProceedingDraftInput,
    ProfileSourceInput,
    PublicBiography,
    PublicCareerEntry,
    PublicPosition,
    PublicProceeding,
    PublicProfileSource,
    SourceCompleteness,
)
from backend.app.services.reference_profile_audit import (
    DEFAULT_FIXTURE,
    EDITORIAL_PREVIEW_BANNER,
    SourceAuditRow,
    audit_politician,
    ceo_warning_for,
    classify_profile_item,
    is_complete_source_url,
    proceeding_nature,
    published_pdc_start,
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
        source_completeness: SourceCompleteness | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> AdminProfileContentList:
        kinds = (kind,) if kind is not None else tuple(CONTENT_MODELS)
        items: list[AdminProfileContentItem] = []
        with self.session_factory() as session:
            names, pdc_starts = PoliticianProfileService._politician_context(session)
            for content_kind in kinds:
                model = CONTENT_MODELS[content_kind]
                query = select(model)
                if status is not None:
                    query = query.where(model.status == status)
                if politician_id is not None:
                    query = query.where(model.politician_id == politician_id)
                for row in session.scalars(query.order_by(model.created_at.desc(), model.id.desc())):
                    item = PoliticianProfileService._admin_item(
                        session,
                        content_kind,
                        row,
                        politician_name=names.get(row.politician_id, ""),
                        pdc_mandate_start=pdc_starts.get(row.politician_id),
                    )
                    if (
                        source_completeness is not None
                        and item.source_completeness is not source_completeness
                    ):
                        continue
                    items.append(item)
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

    def editorial_preview(self, politician_id: int) -> EditorialPreviewResponse:
        with self.session_factory() as session:
            politician = session.get(Politician, politician_id)
            if politician is None:
                raise PoliticianProfileNotFoundError("politician not found")
            pdc_start = published_pdc_start(session, politician)
            name = f"{politician.canonical_given_name} {politician.canonical_family_name}"
            biography = PoliticianProfileService._preview_biography(
                session, politician_id, pdc_start
            )
            career = PoliticianProfileService._preview_career(
                session, politician_id, pdc_start
            )
            positions = PoliticianProfileService._preview_positions(
                session, politician_id, pdc_start
            )
            proceedings = PoliticianProfileService._preview_proceedings(
                session, politician_id, pdc_start
            )
            return EditorialPreviewResponse(
                editorial_preview=True,
                banner=EDITORIAL_PREVIEW_BANNER,
                publication_unchanged=True,
                politician_id=politician_id,
                politician_name=name,
                biography=biography,
                career_entries=career,
                positions=positions,
                proceedings=proceedings,
                pending_counts={
                    "biography": int(
                        biography is not None
                        and biography.status is ProfileContentStatus.PENDING
                    ),
                    "career_entries": sum(
                        1
                        for item in career
                        if item.status is ProfileContentStatus.PENDING
                    ),
                    "positions": sum(
                        1
                        for item in positions
                        if item.status is ProfileContentStatus.PENDING
                    ),
                    "proceedings": sum(
                        1
                        for item in proceedings
                        if item.status is ProfileContentStatus.PENDING
                    ),
                },
            )

    def reference_readiness(self, politician_id: int) -> dict:
        with self.session_factory() as session:
            politician = session.get(Politician, politician_id)
            if politician is None:
                raise PoliticianProfileNotFoundError("politician not found")
            return audit_politician(
                session, politician, fixture_path=DEFAULT_FIXTURE
            ).to_dict()

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
    def _politician_context(
        session: Session,
    ) -> tuple[dict[int, str], dict[int, object]]:
        names: dict[int, str] = {}
        starts: dict[int, object] = {}
        for person in session.scalars(select(Politician)):
            names[person.id] = f"{person.canonical_given_name} {person.canonical_family_name}"
            starts[person.id] = published_pdc_start(session, person)
        return names, starts

    @staticmethod
    def _admin_item(
        session: Session,
        kind: ProfileContentKind,
        row,
        *,
        politician_name: str,
        pdc_mandate_start,
    ) -> AdminProfileContentItem:
        return PoliticianProfileService._admin_payload(
            session,
            kind,
            row,
            politician_name=politician_name,
            pdc_mandate_start=pdc_mandate_start,
            detail=False,
        )

    @staticmethod
    def _admin_detail(
        session: Session, kind: ProfileContentKind, row
    ) -> AdminProfileContentDetail:
        person = session.get(Politician, row.politician_id)
        name = (
            f"{person.canonical_given_name} {person.canonical_family_name}"
            if person is not None
            else ""
        )
        return PoliticianProfileService._admin_payload(
            session,
            kind,
            row,
            politician_name=name,
            pdc_mandate_start=published_pdc_start(session, person) if person else None,
            detail=True,
        )

    @staticmethod
    def _admin_payload(
        session: Session,
        kind: ProfileContentKind,
        row,
        *,
        politician_name: str,
        pdc_mandate_start,
        detail: bool,
    ):
        source_rows = PoliticianProfileService._sources(session, kind, row.id)
        public_sources = tuple(
            PublicProfileSource(
                title=item.title,
                name=item.name,
                url=item.url,
                kind=item.kind,
                excerpt=item.excerpt,
            )
            for item in source_rows
        )
        audit_sources = [
            SourceAuditRow(
                name=item.name,
                url=item.url,
                kind=item.kind.value,
                complete=is_complete_source_url(item.url),
            )
            for item in source_rows
        ]
        title = _admin_title(kind, row)
        classified = classify_profile_item(
            kind=kind,
            identity_key=row.identity_key,
            title=title,
            sources=audit_sources,
            body=getattr(row, "body", None),
            role=getattr(row, "role", None),
            institution=getattr(row, "institution", None),
            start_date=getattr(row, "start_date", None),
            position_statement=getattr(row, "position_statement", None),
            verifiable_statement=getattr(row, "verifiable_statement", None),
            statement_date=getattr(row, "statement_date", None),
            summary=getattr(row, "summary", None),
            proceeding_types=getattr(row, "proceeding_types", None),
            pdc_mandate_start=pdc_mandate_start,
            publication_status=row.status.value,
            content_id=row.id,
        )
        types = (
            tuple(ProceedingType(item) for item in row.proceeding_types)
            if getattr(row, "proceeding_types", None)
            else None
        )
        proposed = (
            getattr(row, "body", None)
            or getattr(row, "position_statement", None)
            or getattr(row, "summary", None)
            or title
        )
        payload = dict(
            id=row.id,
            politician_id=row.politician_id,
            politician_name=politician_name,
            kind=kind,
            identity_key=row.identity_key,
            status=row.status,
            title=title,
            proposed_text=proposed,
            sources=public_sources,
            source_names=tuple(item.name for item in source_rows),
            source_urls=tuple(item.url for item in source_rows if item.url),
            source_kinds=tuple(item.kind for item in source_rows),
            sources_incomplete=any(item.incomplete for item in source_rows),
            source_completeness=SourceCompleteness(classified.source_completeness),
            completeness_blockers=tuple(
                item for item in classified.flags
            )
            + (
                ()
                if classified.blocker == "none"
                else (classified.blocker,)
            ),
            incomplete_secondary_sources=tuple(
                flag.removeprefix("incomplete secondary source: ")
                for flag in classified.flags
                if flag.startswith("incomplete secondary source: ")
            ),
            created_by=row.created_by,
            reference_origin=ceo_warning_for(row.created_by) is not None,
            ceo_reference_warning=ceo_warning_for(row.created_by),
            reviewed_by=row.reviewed_by,
            published_at=row.published_at,
            created_at=row.created_at,
            start_date=getattr(row, "start_date", None),
            end_date=getattr(row, "end_date", None),
            is_current=getattr(row, "is_current", None),
            role=getattr(row, "role", None),
            institution=getattr(row, "institution", None),
            organization=getattr(row, "organization", None),
            party_or_group=getattr(row, "party_or_group", None),
            topic=getattr(row, "topic", None),
            position_statement=getattr(row, "position_statement", None),
            verifiable_statement=getattr(row, "verifiable_statement", None),
            statement_date=getattr(row, "statement_date", None),
            proceeding_types=types,
            proceeding_nature=proceeding_nature(types),
            outcome=getattr(row, "outcome", None),
            outcome_summary=getattr(row, "outcome_summary", None),
            event_date=getattr(row, "event_date", None),
        )
        if detail:
            return AdminProfileContentDetail(
                **payload,
                reviewed_at=row.reviewed_at,
                review_note=row.review_note,
                body=getattr(row, "body", None),
                summary=getattr(row, "summary", None),
            )
        return AdminProfileContentItem(**payload)

    @staticmethod
    def _preview_rows(session: Session, model, politician_id: int, published_only: bool):
        query = select(model).where(model.politician_id == politician_id)
        if published_only:
            query = query.where(model.status == ProfileContentStatus.PUBLISHED)
        else:
            query = query.where(
                model.status.in_(
                    (ProfileContentStatus.PENDING, ProfileContentStatus.PUBLISHED)
                )
            )
        return list(session.scalars(query.order_by(model.id)))

    @staticmethod
    def _preview_biography(session: Session, politician_id: int, pdc_start):
        rows = PoliticianProfileService._preview_rows(
            session, PoliticianBiography, politician_id, published_only=False
        )
        if not rows:
            return None
        published = [row for row in rows if row.status is ProfileContentStatus.PUBLISHED]
        chosen = published[0] if published else rows[0]
        sources = PoliticianProfileService._public_sources(
            session, ProfileContentKind.BIOGRAPHY, chosen.id
        )
        classified = classify_profile_item(
            kind=ProfileContentKind.BIOGRAPHY,
            identity_key=chosen.identity_key,
            title="Biografia",
            sources=[
                SourceAuditRow(
                    name=item.name,
                    url=str(item.url) if item.url else None,
                    kind=item.kind.value,
                    complete=is_complete_source_url(str(item.url) if item.url else None),
                )
                for item in sources
            ],
            body=chosen.body,
            pdc_mandate_start=pdc_start,
            publication_status=chosen.status.value,
            content_id=chosen.id,
        )
        return EditorialPreviewBiography(
            body=chosen.body,
            sources=sources,
            status=chosen.status,
            identity_key=chosen.identity_key,
            source_completeness=SourceCompleteness(classified.source_completeness),
            ceo_reference_warning=ceo_warning_for(chosen.created_by),
        )

    @staticmethod
    def _preview_career(session: Session, politician_id: int, pdc_start):
        rows = PoliticianProfileService._preview_rows(
            session, PoliticianCareerEntry, politician_id, published_only=False
        )
        items = []
        for row in rows:
            sources = PoliticianProfileService._public_sources(
                session, ProfileContentKind.CAREER_ENTRY, row.id
            )
            classified = classify_profile_item(
                kind=ProfileContentKind.CAREER_ENTRY,
                identity_key=row.identity_key,
                title=row.role,
                sources=[
                    SourceAuditRow(
                        name=item.name,
                        url=str(item.url) if item.url else None,
                        kind=item.kind.value,
                        complete=is_complete_source_url(
                            str(item.url) if item.url else None
                        ),
                    )
                    for item in sources
                ],
                role=row.role,
                institution=row.institution,
                start_date=row.start_date,
                pdc_mandate_start=pdc_start,
                publication_status=row.status.value,
                content_id=row.id,
            )
            items.append(
                EditorialPreviewCareerEntry(
                    start_date=row.start_date,
                    end_date=row.end_date,
                    start_precision=row.start_precision,
                    end_precision=row.end_precision,
                    is_current=row.is_current,
                    role=row.role,
                    institution=row.institution,
                    organization=row.organization,
                    party_or_group=row.party_or_group,
                    sources=sources,
                    status=row.status,
                    identity_key=row.identity_key,
                    source_completeness=SourceCompleteness(classified.source_completeness),
                    ceo_reference_warning=ceo_warning_for(row.created_by),
                )
            )
        return tuple(items)

    @staticmethod
    def _preview_positions(session: Session, politician_id: int, pdc_start):
        rows = PoliticianProfileService._preview_rows(
            session, PoliticianPosition, politician_id, published_only=False
        )
        items = []
        for row in rows:
            sources = PoliticianProfileService._public_sources(
                session, ProfileContentKind.POSITION, row.id
            )
            classified = classify_profile_item(
                kind=ProfileContentKind.POSITION,
                identity_key=row.identity_key,
                title=row.topic,
                sources=[
                    SourceAuditRow(
                        name=item.name,
                        url=str(item.url) if item.url else None,
                        kind=item.kind.value,
                        complete=is_complete_source_url(
                            str(item.url) if item.url else None
                        ),
                    )
                    for item in sources
                ],
                position_statement=row.position_statement,
                verifiable_statement=row.verifiable_statement,
                statement_date=row.statement_date,
                pdc_mandate_start=pdc_start,
                publication_status=row.status.value,
                content_id=row.id,
            )
            items.append(
                EditorialPreviewPosition(
                    topic=row.topic,
                    position_statement=row.position_statement,
                    verifiable_statement=row.verifiable_statement,
                    statement_date=row.statement_date,
                    statement_precision=row.statement_precision,
                    sources=sources,
                    status=row.status,
                    identity_key=row.identity_key,
                    source_completeness=SourceCompleteness(classified.source_completeness),
                    ceo_reference_warning=ceo_warning_for(row.created_by),
                )
            )
        return tuple(items)

    @staticmethod
    def _preview_proceedings(session: Session, politician_id: int, pdc_start):
        rows = PoliticianProfileService._preview_rows(
            session, PoliticianProceeding, politician_id, published_only=False
        )
        items = []
        for row in rows:
            sources = PoliticianProfileService._public_sources(
                session, ProfileContentKind.PROCEEDING, row.id
            )
            types = tuple(ProceedingType(item) for item in row.proceeding_types)
            classified = classify_profile_item(
                kind=ProfileContentKind.PROCEEDING,
                identity_key=row.identity_key,
                title=row.title,
                sources=[
                    SourceAuditRow(
                        name=item.name,
                        url=str(item.url) if item.url else None,
                        kind=item.kind.value,
                        complete=is_complete_source_url(
                            str(item.url) if item.url else None
                        ),
                    )
                    for item in sources
                ],
                summary=row.summary,
                proceeding_types=types,
                pdc_mandate_start=pdc_start,
                publication_status=row.status.value,
                content_id=row.id,
            )
            items.append(
                EditorialPreviewProceeding(
                    title=row.title,
                    proceeding_types=types,
                    event_date=row.event_date,
                    event_precision=row.event_precision,
                    outcome=row.outcome,
                    outcome_date=row.outcome_date,
                    summary=row.summary,
                    outcome_summary=row.outcome_summary,
                    sources=sources,
                    status=row.status,
                    identity_key=row.identity_key,
                    source_completeness=SourceCompleteness(classified.source_completeness),
                    proceeding_nature=proceeding_nature(types),
                    ceo_reference_warning=ceo_warning_for(row.created_by),
                )
            )
        return tuple(items)


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
