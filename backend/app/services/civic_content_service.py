from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import Source
from backend.app.models.civic import GlossaryTerm, VotingGuide
from backend.app.schemas.civic import GlossaryTermInput, VotingGuideInput


class CivicContentServiceError(RuntimeError):
    pass


class CivicContentValidationError(CivicContentServiceError):
    pass


class CivicContentService:
    """Manually curated voting guides and glossary terms. No AI generation."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_voting_guide(self, payload: VotingGuideInput) -> VotingGuide:
        with self.session_factory() as session:
            with session.begin():
                source = self._source(session, payload.source_key)
                guide = session.scalar(
                    select(VotingGuide).where(
                        VotingGuide.title == payload.title,
                        VotingGuide.source_id == source.id,
                    )
                )
                published_at = (
                    datetime.now(timezone.utc) if payload.publish else None
                )
                sections = [item.model_dump(mode="json") for item in payload.sections]
                if guide is None:
                    guide = VotingGuide(
                        title=payload.title,
                        scope=payload.scope,
                        sections=sections,
                        valid_from=payload.valid_from,
                        valid_until=payload.valid_until,
                        source_url=str(payload.source_url),
                        source_id=source.id,
                        is_synthetic=payload.is_synthetic,
                        published_at=published_at,
                    )
                    session.add(guide)
                else:
                    guide.scope = payload.scope
                    guide.sections = sections
                    guide.valid_from = payload.valid_from
                    guide.valid_until = payload.valid_until
                    guide.source_url = str(payload.source_url)
                    guide.is_synthetic = payload.is_synthetic
                    if payload.publish and guide.published_at is None:
                        guide.published_at = published_at
                    if not payload.publish:
                        guide.published_at = None
                session.flush()
                session.refresh(guide)
                session.expunge(guide)
                return guide

    def upsert_glossary_term(self, payload: GlossaryTermInput) -> GlossaryTerm:
        with self.session_factory() as session:
            with session.begin():
                source = self._source(session, payload.source_key)
                term = session.scalar(
                    select(GlossaryTerm).where(GlossaryTerm.slug == payload.slug)
                )
                published_at = (
                    datetime.now(timezone.utc) if payload.publish else None
                )
                if term is None:
                    term = GlossaryTerm(
                        slug=payload.slug,
                        term=payload.term,
                        short_definition=payload.short_definition,
                        extended_definition=payload.extended_definition,
                        source_url=str(payload.source_url),
                        source_id=source.id,
                        is_synthetic=payload.is_synthetic,
                        published_at=published_at,
                    )
                    session.add(term)
                else:
                    term.term = payload.term
                    term.short_definition = payload.short_definition
                    term.extended_definition = payload.extended_definition
                    term.source_url = str(payload.source_url)
                    term.source_id = source.id
                    term.is_synthetic = payload.is_synthetic
                    if payload.publish and term.published_at is None:
                        term.published_at = published_at
                    if not payload.publish:
                        term.published_at = None
                session.flush()
                session.refresh(term)
                session.expunge(term)
                return term

    @staticmethod
    def _source(session: Session, source_key: str) -> Source:
        source = session.scalar(select(Source).where(Source.key == source_key))
        if source is None:
            raise CivicContentValidationError(f"unknown civic source {source_key!r}")
        return source
