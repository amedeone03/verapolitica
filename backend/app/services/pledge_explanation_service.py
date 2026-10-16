"""Read-only citizen explanation of a published pledge assessment.

Never writes assessments, drafts, or reviews. Never changes a verdict.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from backend.app.ai.base import ExtractionProviderError
from backend.app.ai.text_completion import TextCompleter, completer_from_settings
from backend.app.core.config import Settings
from backend.app.models import PledgeAssessment, RawDocument
from backend.app.pipeline.prompts import (
    PLEDGE_EXPLANATION_PROMPT_VERSION,
    load_pledge_explanation_prompt,
)
from backend.app.schemas.pledge import PledgeExplanationResponse, PledgeExplanationSource
from backend.app.scoring.public_presentation import (
    PUBLIC_VERDICT_STYLES,
    public_verdict_label,
    scrub_public_ai_text,
)
from backend.app.scoring.types import FulfillmentVerdict, OPEN_VERDICTS
from backend.app.services.pledge_service import PledgeService


logger = logging.getLogger("verapolitica.pledge_explanation")
UNRATED_MESSAGE = (
    "VeraPolitica non ha ancora pubblicato una valutazione per questa promessa."
)
_CACHE_LIMIT = 256
_CACHE: OrderedDict[str, PledgeExplanationResponse] = OrderedDict()
_WORD = re.compile(r"\b\w+\b", re.UNICODE)
_HTTP_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _PublishedContext:
    pledge_id: int
    title: str
    statement: str | None
    verdict: FulfillmentVerdict
    assessment_id: int | None
    rationale: str
    excerpt: str
    source_url: str
    source_title: str
    effective_at: date | None
    commitment_type: str | None
    specificity: str | None
    holder_role: str | None


def clear_explanation_cache() -> None:
    _CACHE.clear()


def explanation_contradicts_verdict(verdict: FulfillmentVerdict, text: str) -> bool:
    """Reject copy that names a different public status than the published one."""

    lowered = text.casefold()
    published_label = public_verdict_label(verdict).casefold()
    other_labels = sorted(
        (
            style.label.casefold()
            for other, style in PUBLIC_VERDICT_STYLES.items()
            if other is not verdict
        ),
        key=len,
        reverse=True,
    )
    remainder = lowered
    for label in other_labels:
        if label not in remainder:
            continue
        if (
            verdict is FulfillmentVerdict.PARTIALLY_KEPT
            and label == "mantenuta"
            and "mantenuta parzialmente" in remainder
        ):
            remainder = remainder.replace("mantenuta parzialmente", " ")
            continue
        if published_label and published_label in remainder:
            remainder = remainder.replace(published_label, " ")
            if label not in remainder:
                continue
        return True
    for other in FulfillmentVerdict:
        if other is verdict:
            continue
        if re.search(rf"\b{re.escape(other.value)}\b", lowered):
            return True
    return False


def _word_count(text: str) -> int:
    return len(_WORD.findall(text))


def _contains_unapproved_url(text: str, allowed_url: str) -> bool:
    allowed = allowed_url.rstrip("/")
    for match in _HTTP_URL.findall(text):
        found = match.rstrip(".,);")
        if found.rstrip("/") != allowed and allowed not in found:
            return True
    return False


def _cache_get(key: str) -> PledgeExplanationResponse | None:
    cached = _CACHE.get(key)
    if cached is None:
        return None
    _CACHE.move_to_end(key)
    return cached


def _cache_put(key: str, value: PledgeExplanationResponse) -> None:
    _CACHE[key] = value
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_LIMIT:
        _CACHE.popitem(last=False)


def _source_title(assessment: PledgeAssessment) -> str:
    document = getattr(assessment, "raw_document", None)
    source = getattr(document, "source", None) if document is not None else None
    if source is not None and source.name:
        return source.name
    host = urlsplit(assessment.source_url).hostname or ""
    return host or "Fonte ufficiale"


def _public_sources(context: _PublishedContext) -> tuple[PledgeExplanationSource, ...]:
    if not context.source_url or context.assessment_id is None:
        return ()
    return (
        PledgeExplanationSource(
            title=context.source_title,
            url=context.source_url,
            excerpt=context.excerpt,
            effective_at=context.effective_at,
        ),
    )


def _fingerprint(context: _PublishedContext, *, model: str) -> str:
    payload = "|".join(
        [
            str(context.pledge_id),
            str(context.assessment_id or 0),
            context.verdict.value,
            context.rationale,
            context.excerpt,
            context.source_url,
            model,
            PLEDGE_EXPLANATION_PROMPT_VERSION,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fallback_text(context: _PublishedContext) -> str:
    if context.assessment_id is None:
        return UNRATED_MESSAGE
    label = public_verdict_label(context.verdict)
    promise = (context.statement or context.title).strip()
    parts = [
        f"Questa promessa riguarda {promise}." if promise else "Questa è una promessa pubblicata.",
        f"VeraPolitica la classifica come '{label}'.",
    ]
    if context.rationale:
        parts.append(f"La valutazione pubblicata spiega: {context.rationale.rstrip('.')}." )
    if context.source_title or context.source_url:
        parts.append(
            f"La valutazione si basa su {context.source_title or context.source_url}."
        )
    if context.excerpt:
        excerpt = context.excerpt.strip()
        if len(excerpt) > 280:
            excerpt = excerpt[:277].rstrip() + "…"
        parts.append(f"Estratto citato: «{excerpt}».")
    if context.verdict in OPEN_VERDICTS:
        parts.append(
            "Al momento non ci sono elementi sufficienti per considerarla conclusa."
        )
    elif not context.excerpt and not context.rationale:
        parts.append(
            "La valutazione è pubblicata, ma l'evidenza associata è insufficiente "
            "per una spiegazione più dettagliata."
        )
    return " ".join(parts)


def _user_payload(context: _PublishedContext) -> str:
    lines = [
        f"PUBLISHED_VERDICT: {context.verdict.value}",
        f"PUBLIC_LABEL: {public_verdict_label(context.verdict)}",
        f"PROMISE_TITLE: {context.title}",
        f"PROMISE_TEXT: {context.statement or ''}",
    ]
    if context.commitment_type:
        lines.append(f"COMMITMENT_TYPE: {context.commitment_type}")
    if context.specificity:
        lines.append(f"SPECIFICITY: {context.specificity}")
    if context.holder_role:
        lines.append(f"HOLDER_ROLE: {context.holder_role}")
    lines.extend(
        [
            f"ASSESSMENT_RATIONALE: {context.rationale}",
            f"EVIDENCE_EXCERPT: {context.excerpt}",
            f"SOURCE_TITLE: {context.source_title}",
            f"SOURCE_URL: {context.source_url}",
            f"SOURCE_DATE: {context.effective_at.isoformat() if context.effective_at else ''}",
        ]
    )
    return "\n".join(lines)


class PledgeExplanationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        completer: TextCompleter | None | object = ...,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        if completer is ...:
            self.completer = completer_from_settings(settings)
        else:
            self.completer = completer  # type: ignore[assignment]

    def explain(self, pledge_id: int) -> PledgeExplanationResponse:
        context = self._load_context(pledge_id)
        model_key = (
            f"{self.completer.provider_name}:{self.completer.model_name}"
            if self.completer is not None
            else "fallback"
        )
        cache_key = _fingerprint(context, model=model_key)
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        if context.assessment_id is None:
            payload = self._response(context, UNRATED_MESSAGE, generated_by_ai=False)
            _cache_put(cache_key, payload)
            return payload
        result = self._try_ai(context)
        if result is None:
            result = self._response(
                context, _fallback_text(context), generated_by_ai=False, fallback=True
            )
        _cache_put(cache_key, result)
        return result

    def _load_context(self, pledge_id: int) -> _PublishedContext:
        with self.session_factory() as session:
            proposal = PledgeService._load_pledge(session, pledge_id)
            classification = PledgeService._classification(session, pledge_id)
            latest = PledgeService._latest_assessments(session, [pledge_id]).get(pledge_id)
            assessment = None
            if latest is not None:
                assessment = session.scalar(
                    select(PledgeAssessment)
                    .where(PledgeAssessment.id == latest.id)
                    .options(selectinload(PledgeAssessment.raw_document).selectinload(RawDocument.source))
                )
            verdict = (
                assessment.verdict if assessment is not None else FulfillmentVerdict.NOT_YET_RATED
            )
            return _PublishedContext(
                pledge_id=proposal.id,
                title=proposal.canonical_title,
                statement=proposal.exact_statement,
                verdict=verdict,
                assessment_id=assessment.id if assessment is not None else None,
                rationale=(assessment.rationale if assessment is not None else "").strip(),
                excerpt=(assessment.quoted_excerpt if assessment is not None else "").strip(),
                source_url=(assessment.source_url if assessment is not None else "").strip(),
                source_title=_source_title(assessment) if assessment is not None else "",
                effective_at=assessment.effective_at if assessment is not None else None,
                commitment_type=(
                    classification.commitment_type.value if classification is not None else None
                ),
                specificity=(
                    classification.specificity.value if classification is not None else None
                ),
                holder_role=(
                    classification.holder_role.value if classification is not None else None
                ),
            )

    def _try_ai(self, context: _PublishedContext) -> PledgeExplanationResponse | None:
        if self.completer is None:
            return None
        try:
            text = self.completer.complete(
                system=load_pledge_explanation_prompt(),
                user=_user_payload(context),
            )
        except ExtractionProviderError:
            logger.info("pledge explanation model failed; using fallback")
            return None
        except Exception:
            logger.info("pledge explanation model failed unexpectedly; using fallback")
            return None
        text = scrub_public_ai_text(text)
        if (
            _word_count(text) < 20
            or explanation_contradicts_verdict(context.verdict, text)
            or _contains_unapproved_url(text, context.source_url)
        ):
            return None
        return self._response(context, text, generated_by_ai=True, fallback=False)

    def _response(
        self,
        context: _PublishedContext,
        explanation: str,
        *,
        generated_by_ai: bool,
        fallback: bool = False,
    ) -> PledgeExplanationResponse:
        model = None
        if generated_by_ai and self.completer is not None:
            model = self.completer.model_name
        return PledgeExplanationResponse(
            pledge_id=context.pledge_id,
            verdict=context.verdict,
            public_verdict_label=public_verdict_label(context.verdict),
            explanation=explanation,
            sources=_public_sources(context),
            generated_by_ai=generated_by_ai,
            model=model,
            fallback=fallback,
            prompt_version=PLEDGE_EXPLANATION_PROMPT_VERSION,
        )
