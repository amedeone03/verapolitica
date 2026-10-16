"""Read-only Ask VeraPolitica over published pledges, verdicts, topics, and sources.

Never writes assessments or drafts. Never infers a new fulfilment verdict.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.ai.base import ExtractionProviderError
from backend.app.ai.text_completion import TextCompleter, completer_from_settings
from backend.app.core.config import Settings
from backend.app.core.text import normalize_search_text, search_tokens
from backend.app.models import (
    PledgeAssessment,
    PledgeClassification,
    Politician,
    PoliticianVersion,
    Proposal,
    ProposalType,
)
from backend.app.pipeline.prompts import (
    ASK_VERAPOLITICA_PROMPT_VERSION,
    load_ask_verapolitica_prompt,
)
from backend.app.schemas.ask import AskResponse, AskResultItem, AskSource
from backend.app.schemas.search import SearchEntityType
from backend.app.scoring.public_presentation import (
    PUBLIC_VERDICT_LEGEND_ORDER,
    PUBLIC_VERDICT_STYLES,
    public_verdict_label,
    scrub_public_ai_text,
)
from backend.app.scoring.retrieval_profile import TOPIC_KEYWORDS
from backend.app.scoring.types import FulfillmentVerdict
from backend.app.services.ask_query_planner import (
    ASK_TOPIC_SYNONYMS,
    AskIntent,
    AskPlan,
    plan_ask_question,
)
from backend.app.services.pledge_explanation_service import (
    UNRATED_MESSAGE,
    explanation_contradicts_verdict,
)
from backend.app.services.pledge_service import PledgeService
from backend.app.services.search_service import MAX_QUERY_LENGTH, SearchService, SearchValidationError


logger = logging.getLogger("verapolitica.ask")
PROMPT_VERSION = ASK_VERAPOLITICA_PROMPT_VERSION
MAX_RESULTS = 12
_CACHE_LIMIT = 256
_CACHE: OrderedDict[str, AskResponse] = OrderedDict()
_WORD = re.compile(r"\b\w+\b", re.UNICODE)
_HTTP_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_FORBIDDEN_RHETORIC = (
    "ha mentito",
    "è corrotto",
    "e corrotto",
    "il migliore",
    "la migliore",
    "il peggiore",
    "la peggiore",
)
UNSUPPORTED_ANSWER = (
    "VeraPolitica può rispondere a domande su politici pubblicati, promesse "
    "esplicite, stati di valutazione, temi ed evidenze ufficiali già pubblicate. "
    "Formula una domanda su uno di questi argomenti."
)


@dataclass(frozen=True, slots=True)
class _PoliticianHit:
    politician_id: int
    name: str
    url: str


@dataclass(frozen=True, slots=True)
class _PledgeRow:
    pledge_id: int
    title: str
    statement: str | None
    verdict: FulfillmentVerdict
    topic_code: str | None
    assessment_id: int | None
    rationale: str
    excerpt: str
    source_url: str
    politician_id: int | None = None


def clear_ask_cache() -> None:
    _CACHE.clear()


def _word_count(text: str) -> int:
    return len(_WORD.findall(text))


def _contains_unapproved_url(text: str, allowed_urls: tuple[str, ...]) -> bool:
    allowed = {item.rstrip("/") for item in allowed_urls if item}
    for match in _HTTP_URL.findall(text):
        found = match.rstrip(".,);").rstrip("/")
        if found not in allowed and not any(item in found for item in allowed):
            return True
    return False


def _source_title(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host or "Fonte ufficiale"


def _short_excerpt(text: str, limit: int = 280) -> str:
    excerpt = text.strip()
    if len(excerpt) > limit:
        return excerpt[: limit - 1].rstrip() + "…"
    return excerpt


def _cache_get(key: str) -> AskResponse | None:
    cached = _CACHE.get(key)
    if cached is None:
        return None
    _CACHE.move_to_end(key)
    return cached


def _cache_put(key: str, value: AskResponse) -> None:
    _CACHE[key] = value
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_LIMIT:
        _CACHE.popitem(last=False)


def _fingerprint(
    *,
    question: str,
    intent: str,
    politician_id: int | None,
    pledge_ids: tuple[int, ...],
    assessment_ids: tuple[int, ...],
    model: str,
) -> str:
    payload = "|".join(
        [
            normalize_search_text(question),
            intent,
            str(politician_id or 0),
            ",".join(str(item) for item in pledge_ids),
            ",".join(str(item) for item in assessment_ids),
            model,
            PROMPT_VERSION,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _AmbiguousPolitician(Exception):
    def __init__(self, candidates: tuple[_PoliticianHit, ...]) -> None:
        super().__init__("ambiguous politician")
        self.candidates = candidates


class AskVeraPoliticaService:
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

    def ask(self, question: str) -> AskResponse:
        plan = plan_ask_question(question)
        with self.session_factory() as session:
            payload = self._answer(session, question, plan)
        return payload

    def _answer(self, session: Session, question: str, plan: AskPlan) -> AskResponse:
        try:
            politician, _candidates = self._resolve_politician(session, question, plan)
        except _AmbiguousPolitician as exc:
            return self._clarification(question, plan, exc.candidates)

        matched_pledge = self._match_specific_pledge(session, question, plan, politician)
        intent = self._effective_intent(plan, politician, matched_pledge)
        if (
            politician is None
            and matched_pledge is None
            and intent is AskIntent.POLITICIAN_PLEDGES
        ):
            if plan.topic_code is not None:
                intent = AskIntent.PLEDGES_BY_TOPIC
            elif plan.verdict is not None:
                intent = AskIntent.PLEDGES_BY_VERDICT
            else:
                tokens = (plan.entity_query or "").split()
                if 1 <= len(tokens) <= 3:
                    return self._response(
                        intent=intent,
                        answer=(
                            "VeraPolitica non ha un profilo pubblicato corrispondente a "
                            f"«{plan.entity_query}»."
                        ),
                        entities=self._entities(plan, None, None),
                        results=(),
                        sources=(),
                        generated_by_ai=False,
                    )
                intent = AskIntent.UNSUPPORTED
        if intent is AskIntent.UNSUPPORTED and matched_pledge is None:
            return self._response(
                intent=intent,
                answer=UNSUPPORTED_ANSWER,
                entities=self._entities(plan, politician, matched_pledge),
                results=(),
                sources=(),
                generated_by_ai=False,
            )

        if intent is AskIntent.PLEDGE_EXPLANATION or intent is AskIntent.PLEDGE_SOURCES:
            if matched_pledge is None:
                return self._response(
                    intent=intent,
                    answer=(
                        "VeraPolitica non ha identificato una promessa pubblicata "
                        "corrispondente. Indica il titolo della promessa o il politico."
                    ),
                    entities=self._entities(plan, politician, None),
                    results=(),
                    sources=(),
                    generated_by_ai=False,
                )
            return self._pledge_detail(session, question, plan, intent, politician, matched_pledge)

        rows = self._retrieve_pledges(session, plan, politician, intent)
        results = self._result_items(rows)
        sources = self._sources_from_rows(session, rows)
        answer = self._deterministic_list_answer(intent, plan, politician, rows)
        model_key = (
            f"{self.completer.provider_name}:{self.completer.model_name}"
            if self.completer is not None
            else "fallback"
        )
        cache_key = _fingerprint(
            question=question,
            intent=intent.value,
            politician_id=politician.politician_id if politician else None,
            pledge_ids=tuple(row.pledge_id for row in rows),
            assessment_ids=tuple(row.assessment_id or 0 for row in rows),
            model=model_key,
        )
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        generated = False
        fallback = False
        if self._should_synthesize(plan, intent, rows):
            synthesized = self._try_ai(
                question=question,
                intent=intent,
                plan=plan,
                politician=politician,
                rows=rows,
                sources=sources,
                session=session,
            )
            if synthesized is not None:
                answer = synthesized
                generated = True
            else:
                fallback = self.completer is not None
        payload = self._response(
            intent=intent,
            answer=answer,
            entities=self._entities(plan, politician, matched_pledge),
            results=results,
            sources=sources,
            generated_by_ai=generated,
            fallback=fallback,
        )
        _cache_put(cache_key, payload)
        return payload

    def _effective_intent(
        self,
        plan: AskPlan,
        politician: _PoliticianHit | None,
        matched_pledge: _PledgeRow | None,
    ) -> AskIntent:
        if matched_pledge is not None and (plan.wants_sources or plan.wants_explanation):
            return AskIntent.PLEDGE_SOURCES if plan.wants_sources and not plan.wants_explanation else AskIntent.PLEDGE_EXPLANATION
        if matched_pledge is not None and plan.asks_specific_status and plan.entity_query:
            title_norm = normalize_search_text(matched_pledge.title)
            query_norm = normalize_search_text(plan.entity_query)
            if title_norm in query_norm or query_norm in title_norm or self._tokens_fit_pledge(
                plan.entity_query, matched_pledge, politician
            ):
                return AskIntent.PLEDGE_EXPLANATION
        if plan.intent is AskIntent.PLEDGE_EXPLANATION:
            return AskIntent.PLEDGE_EXPLANATION
        if plan.intent is AskIntent.PLEDGE_SOURCES:
            return AskIntent.PLEDGE_SOURCES
        if politician is not None:
            return AskIntent.POLITICIAN_PLEDGES
        if plan.intent is AskIntent.POLITICIAN_PLEDGES and plan.entity_query:
            return AskIntent.POLITICIAN_PLEDGES
        if plan.topic_code is not None:
            return AskIntent.PLEDGES_BY_TOPIC
        if plan.verdict is not None:
            return AskIntent.PLEDGES_BY_VERDICT
        return AskIntent.UNSUPPORTED

    def _resolve_politician(
        self, session: Session, question: str, plan: AskPlan
    ) -> tuple[_PoliticianHit | None, tuple[_PoliticianHit, ...]]:
        query = (plan.entity_query or "").strip()
        if not query:
            return None, ()
        clipped = query[:MAX_QUERY_LENGTH]
        try:
            found = SearchService(session).search(
                clipped, entity_type=SearchEntityType.POLITICIAN, limit=20
            )
        except SearchValidationError:
            return None, ()
        question_norm = normalize_search_text(question)
        named: list[_PoliticianHit] = []
        for item in found.items:
            title_norm = normalize_search_text(item.title)
            parts = title_norm.split()
            family = parts[-1] if parts else ""
            given = parts[0] if parts else ""
            if family and family in question_norm:
                named.append(
                    _PoliticianHit(
                        politician_id=int(item.metadata["id"]),
                        name=item.title,
                        url=item.url,
                    )
                )
            elif given and given in question_norm and title_norm in question_norm:
                named.append(
                    _PoliticianHit(
                        politician_id=int(item.metadata["id"]),
                        name=item.title,
                        url=item.url,
                    )
                )
        if not named:
            return None, ()
        full = [
            hit
            for hit in named
            if normalize_search_text(hit.name) in question_norm
            or all(token in question_norm for token in normalize_search_text(hit.name).split())
        ]
        pool = full or named
        unique: dict[int, _PoliticianHit] = {}
        for hit in pool:
            unique[hit.politician_id] = hit
        candidates = tuple(unique.values())
        if len(candidates) == 1:
            return candidates[0], ()
        raise _AmbiguousPolitician(candidates)

    def _match_specific_pledge(
        self,
        session: Session,
        question: str,
        plan: AskPlan,
        politician: _PoliticianHit | None,
    ) -> _PledgeRow | None:
        query = (plan.entity_query or "").strip()
        question_norm = normalize_search_text(question)
        rows = self._classified_pledges(
            session, politician_id=politician.politician_id if politician else None
        )
        scored: list[tuple[int, _PledgeRow]] = []
        for row in rows:
            title_norm = normalize_search_text(row.title)
            statement_norm = normalize_search_text(row.statement or "")
            if title_norm and title_norm in question_norm:
                scored.append((0, row))
                continue
            if (
                query
                and len(query) >= 5
                and (query in title_norm or query in statement_norm)
            ):
                scored.append((1, row))
                continue
            if self._tokens_fit_pledge(query, row, politician):
                scored.append((2, row))
        if not scored:
            return self._unique_topic_or_verdict_pledge(rows, plan)
        scored.sort(key=lambda item: (item[0], item[1].pledge_id))
        best_tier = scored[0][0]
        best = [row for tier, row in scored if tier == best_tier]
        if len(best) == 1:
            return best[0]
        if plan.verdict is not None:
            matching = [row for row in best if row.verdict is plan.verdict]
            if len(matching) == 1:
                return matching[0]
        return None

    def _unique_topic_or_verdict_pledge(
        self, rows: list[_PledgeRow], plan: AskPlan
    ) -> _PledgeRow | None:
        if not (plan.wants_explanation or plan.wants_sources):
            return None
        filtered = list(rows)
        if plan.topic_code is not None:
            filtered = [
                row
                for row in filtered
                if row.topic_code == plan.topic_code
                or self._topic_text_match(row, plan.topic_code, plan.topic_label)
            ]
        if plan.verdict is not None:
            with_verdict = [row for row in filtered if row.verdict is plan.verdict]
            if with_verdict:
                filtered = with_verdict
        if plan.wants_sources:
            with_source = [row for row in filtered if row.assessment_id is not None]
            if with_source:
                filtered = with_source
        if len(filtered) == 1:
            return filtered[0]
        return None

    def _tokens_fit_pledge(
        self,
        query: str | None,
        row: _PledgeRow,
        politician: _PoliticianHit | None,
    ) -> bool:
        if not query:
            return False
        skip = set(_STOP_NAME_TOKENS)
        if politician is not None:
            skip.update(normalize_search_text(politician.name).split())
        tokens = [token for token in search_tokens(query) if token not in skip]
        if len(tokens) < 2:
            return False
        blob = normalize_search_text(f"{row.title} {row.statement or ''}")
        return all(token in blob for token in tokens)

    def _retrieve_pledges(
        self,
        session: Session,
        plan: AskPlan,
        politician: _PoliticianHit | None,
        intent: AskIntent,
    ) -> tuple[_PledgeRow, ...]:
        politician_id = politician.politician_id if politician else None
        rows = self._classified_pledges(session, politician_id=politician_id)
        if plan.verdict is not None and intent is not AskIntent.PLEDGE_EXPLANATION:
            rows = [row for row in rows if row.verdict is plan.verdict]
        if plan.topic_code is not None:
            topic_rows = [
                row
                for row in rows
                if row.topic_code == plan.topic_code
                or self._topic_text_match(row, plan.topic_code, plan.topic_label)
            ]
            if topic_rows or intent is AskIntent.PLEDGES_BY_TOPIC:
                rows = topic_rows
        return tuple(rows[:MAX_RESULTS])

    def _topic_text_match(self, row: _PledgeRow, topic_code: str, topic_label: str | None) -> bool:
        blob = normalize_search_text(f"{row.title} {row.statement or ''}")
        needles = [topic_code]
        if topic_label:
            needles.append(normalize_search_text(topic_label))
        needles.extend(TOPIC_KEYWORDS.get(topic_code, ()))
        needles.extend(ASK_TOPIC_SYNONYMS.get(topic_code, ()))
        return any(needle and needle in blob for needle in needles)

    def _classified_pledges(
        self, session: Session, *, politician_id: int | None
    ) -> list[_PledgeRow]:
        if politician_id is not None:
            pledges = PledgeService._politician_pledges(session, politician_id)
        else:
            pledges = list(
                session.scalars(
                    select(Proposal)
                    .where(
                        Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
                        Proposal.published_at.is_not(None),
                    )
                    .order_by(Proposal.id)
                )
            )
        ids = [pledge.id for pledge in pledges]
        classifications = {
            row.proposal_id: row
            for row in session.scalars(
                select(PledgeClassification).where(PledgeClassification.proposal_id.in_(ids))
            )
        } if ids else {}
        latest = PledgeService._latest_assessments(session, ids)
        rows: list[_PledgeRow] = []
        for pledge in pledges:
            classification = classifications.get(pledge.id)
            if classification is None:
                continue
            assessment = latest.get(pledge.id)
            rows.append(
                _PledgeRow(
                    pledge_id=pledge.id,
                    title=pledge.canonical_title,
                    statement=pledge.exact_statement,
                    verdict=(
                        assessment.verdict
                        if assessment is not None
                        else FulfillmentVerdict.NOT_YET_RATED
                    ),
                    topic_code=classification.cap_topic_code,
                    assessment_id=assessment.id if assessment is not None else None,
                    rationale=(assessment.rationale if assessment is not None else "").strip(),
                    excerpt=(assessment.quoted_excerpt if assessment is not None else "").strip(),
                    source_url=(assessment.source_url if assessment is not None else "").strip(),
                    politician_id=politician_id,
                )
            )
        return rows

    def _pledge_detail(
        self,
        session: Session,
        question: str,
        plan: AskPlan,
        intent: AskIntent,
        politician: _PoliticianHit | None,
        row: _PledgeRow,
    ) -> AskResponse:
        results = self._result_items((row,))
        sources = self._sources_from_rows(session, (row,))
        if row.assessment_id is None:
            answer = UNRATED_MESSAGE
            payload = self._response(
                intent=intent,
                answer=answer,
                entities=self._entities(plan, politician, row),
                results=results,
                sources=(),
                generated_by_ai=False,
            )
            return payload
        if intent is AskIntent.PLEDGE_SOURCES:
            answer = self._deterministic_sources_answer(row, sources)
            return self._response(
                intent=intent,
                answer=answer,
                entities=self._entities(plan, politician, row),
                results=results,
                sources=sources,
                generated_by_ai=False,
            )
        answer = self._deterministic_explanation_answer(row)
        generated = False
        fallback = False
        if self.completer is not None:
            synthesized = self._try_ai(
                question=question,
                intent=intent,
                plan=plan,
                politician=politician,
                rows=(row,),
                sources=sources,
                session=session,
            )
            if synthesized is not None:
                answer = synthesized
                generated = True
            else:
                fallback = True
        return self._response(
            intent=intent,
            answer=answer,
            entities=self._entities(plan, politician, row),
            results=results,
            sources=sources,
            generated_by_ai=generated,
            fallback=fallback,
        )

    def _clarification(
        self, question: str, plan: AskPlan, candidates: tuple[_PoliticianHit, ...]
    ) -> AskResponse:
        names = "; ".join(hit.name for hit in candidates)
        results = tuple(
            AskResultItem(
                type="politician",
                id=hit.politician_id,
                title=hit.name,
                url=hit.url,
            )
            for hit in candidates
        )
        return self._response(
            intent=AskIntent.POLITICIAN_PLEDGES,
            answer=(
                "Più profili pubblici corrispondono. Precisa quale intendi: "
                f"{names}."
            ),
            entities=self._entities(plan, None, None),
            results=results,
            sources=(),
            generated_by_ai=False,
        )

    def _should_synthesize(
        self, plan: AskPlan, intent: AskIntent, rows: tuple[_PledgeRow, ...]
    ) -> bool:
        if self.completer is None:
            return False
        if plan.wants_count or intent is AskIntent.UNSUPPORTED:
            return False
        if not rows:
            return False
        if intent is AskIntent.PLEDGE_SOURCES:
            return False
        return True

    def _try_ai(
        self,
        *,
        question: str,
        intent: AskIntent,
        plan: AskPlan,
        politician: _PoliticianHit | None,
        rows: tuple[_PledgeRow, ...],
        sources: tuple[AskSource, ...],
        session: Session,
    ) -> str | None:
        if self.completer is None:
            return None
        user = self._user_payload(question, intent, plan, politician, rows, sources)
        try:
            text = self.completer.complete(
                system=load_ask_verapolitica_prompt(),
                user=user,
            )
        except ExtractionProviderError:
            logger.info("ask model failed; using fallback")
            return None
        except Exception:
            logger.info("ask model failed unexpectedly; using fallback")
            return None
        text = scrub_public_ai_text(text)
        if self._reject_generation(text, intent, rows, sources, politician, session):
            return None
        return text

    def _reject_generation(
        self,
        text: str,
        intent: AskIntent,
        rows: tuple[_PledgeRow, ...],
        sources: tuple[AskSource, ...],
        politician: _PoliticianHit | None,
        session: Session,
    ) -> bool:
        if _word_count(text) < 12:
            return True
        lowered = text.casefold()
        if any(phrase in lowered for phrase in _FORBIDDEN_RHETORIC):
            return True
        allowed_urls = tuple(source.url for source in sources)
        if _contains_unapproved_url(text, allowed_urls):
            return True
        if intent in {AskIntent.PLEDGE_EXPLANATION, AskIntent.PLEDGE_SOURCES} and rows:
            row = rows[0]
            if row.assessment_id is None:
                return True
            if explanation_contradicts_verdict(row.verdict, text):
                return True
        elif rows:
            present = {row.verdict for row in rows}
            remainder = lowered
            for verdict, style in sorted(
                PUBLIC_VERDICT_STYLES.items(),
                key=lambda item: len(item[1].label),
                reverse=True,
            ):
                label = style.label.casefold()
                if verdict in present or label not in remainder:
                    continue
                if (
                    FulfillmentVerdict.PARTIALLY_KEPT in present
                    and verdict is FulfillmentVerdict.KEPT
                    and "mantenuta parzialmente" in remainder
                ):
                    remainder = remainder.replace("mantenuta parzialmente", " ")
                    continue
                return True
            tracked = len(rows)
            by_verdict = Counter(row.verdict for row in rows)
            allowed_counts = {tracked, *by_verdict.values(), 0}
            for match in re.finditer(r"(\d+)\s+promess", lowered):
                if int(match.group(1)) not in allowed_counts:
                    return True
        allowed_ids = {politician.politician_id} if politician is not None else set()
        for row in rows:
            if row.politician_id:
                allowed_ids.add(row.politician_id)
        if self._mentions_foreign_politician(session, text, allowed_ids):
            return True
        return False

    def _mentions_foreign_politician(
        self, session: Session, text: str, allowed_ids: set[int]
    ) -> bool:
        if not allowed_ids:
            return False
        lowered = text.casefold()
        rows = session.scalars(
            select(Politician)
            .join(
                PoliticianVersion,
                (PoliticianVersion.id == Politician.current_version_id)
                & (PoliticianVersion.politician_id == Politician.id),
            )
            .where(
                Politician.current_version_id.is_not(None),
                PoliticianVersion.published_at.is_not(None),
            )
        )
        for politician in rows:
            if politician.id in allowed_ids:
                continue
            name = f"{politician.canonical_given_name} {politician.canonical_family_name}".strip()
            if len(name) >= 5 and name.casefold() in lowered:
                return True
        return False

    def _user_payload(
        self,
        question: str,
        intent: AskIntent,
        plan: AskPlan,
        politician: _PoliticianHit | None,
        rows: tuple[_PledgeRow, ...],
        sources: tuple[AskSource, ...],
    ) -> str:
        lines = [
            "USER_QUESTION:",
            question.strip(),
            "",
            "VERIFIED_CONTEXT:",
            f"INTENT: {intent.value}",
        ]
        if politician is not None:
            lines.append(f"POLITICIAN: {politician.name}")
        if plan.verdict is not None:
            lines.append(
                f"ASKED_VERDICT: {plan.verdict.value} ({public_verdict_label(plan.verdict)})"
            )
        if plan.topic_label:
            lines.append(f"TOPIC: {plan.topic_label}")
        lines.append(f"TRACKED_COUNT: {len(rows)}")
        counts = Counter(row.verdict for row in rows)
        for verdict in PUBLIC_VERDICT_LEGEND_ORDER:
            if counts.get(verdict):
                lines.append(
                    f"COUNT_{verdict.value}: {counts[verdict]} ({public_verdict_label(verdict)})"
                )
        for row in rows:
            lines.append(
                "PLEDGE: "
                f"id={row.pledge_id}; title={row.title}; "
                f"verdict={row.verdict.value}; "
                f"label={public_verdict_label(row.verdict)}; "
                f"statement={row.statement or ''}"
            )
            if row.assessment_id is None:
                lines.append("ASSESSMENT: none published")
            else:
                lines.append(
                    "ASSESSMENT: "
                    f"id={row.assessment_id}; rationale={row.rationale}; "
                    f"excerpt={_short_excerpt(row.excerpt)}"
                )
        for source in sources:
            lines.append(f"SOURCE: title={source.title}; url={source.url}; excerpt={source.excerpt}")
        if not rows:
            lines.append("NO_PUBLISHED_MATCHES")
        return "\n".join(lines)

    def _deterministic_list_answer(
        self,
        intent: AskIntent,
        plan: AskPlan,
        politician: _PoliticianHit | None,
        rows: tuple[_PledgeRow, ...],
    ) -> str:
        if not rows:
            if politician is not None:
                return (
                    f"VeraPolitica non registra promesse pubblicate"
                    f"{' con questo filtro' if plan.verdict or plan.topic_code else ''} "
                    f"per {politician.name}."
                )
            if plan.verdict is not None:
                label = public_verdict_label(plan.verdict)
                return f"VeraPolitica non registra promesse pubblicate con stato '{label}'."
            if plan.topic_label:
                return (
                    "VeraPolitica non registra promesse pubblicate sul tema "
                    f"'{plan.topic_label}'."
                )
            return UNSUPPORTED_ANSWER
        counts = Counter(row.verdict for row in rows)
        breakdown = self._breakdown(counts)
        titles = "; ".join(
            f"{row.title} ({public_verdict_label(row.verdict)})" for row in rows
        )
        if intent is AskIntent.POLITICIAN_PLEDGES and politician is not None:
            total = len(rows)
            if plan.verdict is not None:
                label = public_verdict_label(plan.verdict)
                return (
                    f"VeraPolitica registra {total} "
                    f"{'promessa' if total == 1 else 'promesse'} "
                    f"con stato '{label}' per {politician.name}: {titles}."
                )
            if plan.topic_label:
                return (
                    f"VeraPolitica registra {total} "
                    f"{'promessa' if total == 1 else 'promesse'} "
                    f"di {politician.name} sul tema '{plan.topic_label}': {titles}."
                )
            return (
                f"VeraPolitica registra {total} "
                f"{'promessa pubblicata' if total == 1 else 'promesse pubblicate'} "
                f"per {politician.name}. {breakdown} {titles}."
            )
        if intent is AskIntent.PLEDGES_BY_VERDICT and plan.verdict is not None:
            label = public_verdict_label(plan.verdict)
            return (
                f"Risultano {len(rows)} "
                f"{'promessa' if len(rows) == 1 else 'promesse'} "
                f"con stato '{label}': {titles}."
            )
        if intent is AskIntent.PLEDGES_BY_TOPIC and plan.topic_label:
            return (
                f"VeraPolitica registra {len(rows)} "
                f"{'promessa pubblicata' if len(rows) == 1 else 'promesse pubblicate'} "
                f"sul tema '{plan.topic_label}': {titles}."
            )
        return f"{breakdown} {titles}."

    def _breakdown(self, counts: Counter[FulfillmentVerdict]) -> str:
        parts: list[str] = []
        for verdict in PUBLIC_VERDICT_LEGEND_ORDER:
            number = counts.get(verdict, 0)
            if not number:
                continue
            label = public_verdict_label(verdict)
            if number != 1:
                label = {
                    FulfillmentVerdict.KEPT: "Mantenute",
                    FulfillmentVerdict.PARTIALLY_KEPT: "Mantenute parzialmente",
                    FulfillmentVerdict.BROKEN: "Non mantenute",
                    FulfillmentVerdict.NOT_YET_RATED: "Non ancora valutate",
                    FulfillmentVerdict.STALLED: "Iter bloccato",
                }.get(verdict, label)
            verb = "è" if number == 1 else "sono"
            parts.append(f"{number} {verb} {label}")
        if not parts:
            return ""
        if len(parts) == 1:
            return f"{parts[0]}."
        return f"{', '.join(parts[:-1])} e {parts[-1]}."

    def _deterministic_explanation_answer(self, row: _PledgeRow) -> str:
        label = public_verdict_label(row.verdict)
        promise = (row.statement or row.title).strip()
        parts = [
            f"Questa promessa riguarda {promise}." if promise else "Questa è una promessa pubblicata.",
            f"VeraPolitica la classifica come '{label}'.",
        ]
        if row.rationale:
            parts.append(f"La valutazione pubblicata spiega: {row.rationale.rstrip('.')}.")
        if row.source_url:
            parts.append(
                f"La valutazione si basa su {_source_title(row.source_url)}."
            )
        if row.excerpt:
            parts.append(f"Estratto citato: «{_short_excerpt(row.excerpt)}».")
        return " ".join(parts)

    def _deterministic_sources_answer(
        self, row: _PledgeRow, sources: tuple[AskSource, ...]
    ) -> str:
        if not sources:
            return UNRATED_MESSAGE
        source = sources[0]
        parts = [
            "La valutazione pubblicata utilizza la seguente fonte ufficiale: "
            f"{source.title} ({source.url})."
        ]
        if source.excerpt:
            parts.append(f"Estratto: «{source.excerpt}».")
        parts.append(
            f"Lo stato pubblicato è '{public_verdict_label(row.verdict)}'."
        )
        return " ".join(parts)

    def _result_items(self, rows: tuple[_PledgeRow, ...]) -> tuple[AskResultItem, ...]:
        return tuple(
            AskResultItem(
                type="pledge",
                id=row.pledge_id,
                title=row.title,
                verdict=row.verdict,
                public_verdict_label=public_verdict_label(row.verdict),
                url=f"/app/?proposal={row.pledge_id}",
            )
            for row in rows
        )

    def _sources_from_rows(
        self, session: Session, rows: tuple[_PledgeRow, ...]
    ) -> tuple[AskSource, ...]:
        seen: set[str] = set()
        items: list[AskSource] = []
        for row in rows:
            if not row.source_url or row.assessment_id is None:
                continue
            url = row.source_url
            if url in seen:
                continue
            seen.add(url)
            title = _source_title(url)
            assessment = session.get(PledgeAssessment, row.assessment_id)
            document = getattr(assessment, "raw_document", None) if assessment is not None else None
            source = getattr(document, "source", None) if document is not None else None
            if source is not None and source.name:
                title = source.name
            items.append(
                AskSource(
                    title=title,
                    url=url,
                    excerpt=_short_excerpt(row.excerpt),
                )
            )
        return tuple(items)

    def _entities(
        self,
        plan: AskPlan,
        politician: _PoliticianHit | None,
        pledge: _PledgeRow | None,
    ) -> dict[str, str]:
        entities: dict[str, str] = {}
        if politician is not None:
            entities["politician"] = politician.name
        if plan.verdict is not None:
            entities["verdict"] = plan.verdict.value
        if plan.topic_label:
            entities["topic"] = plan.topic_label
        if pledge is not None:
            entities["pledge"] = pledge.title
        return entities

    def _response(
        self,
        *,
        intent: AskIntent,
        answer: str,
        entities: dict[str, str],
        results: tuple[AskResultItem, ...],
        sources: tuple[AskSource, ...],
        generated_by_ai: bool,
        fallback: bool = False,
    ) -> AskResponse:
        model = None
        if generated_by_ai and self.completer is not None:
            model = self.completer.model_name
        return AskResponse(
            answer=answer,
            intent=intent.value,
            entities=entities,
            results=results,
            sources=sources,
            generated_by_ai=generated_by_ai,
            fallback=fallback,
            prompt_version=PROMPT_VERSION,
            model=model,
        )


_STOP_NAME_TOKENS = frozenset({"di", "del", "della"})
