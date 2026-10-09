"""Local editorial page: commitment vs official evidence. Never public."""

from html import escape
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Path, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.demo_editorial import _page
from backend.app.api.deps import get_api_settings, get_session_factory
from backend.app.core.config import Settings
from backend.app.models import PledgeAssessmentDraftStatus
from backend.app.services.pledge_service import (
    PledgeConflictError,
    PledgeNotFoundError,
    PledgeService,
    PledgeValidationError,
)


router = APIRouter(prefix="/demo", tags=["demo-pledge-review"])


def _service(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> PledgeService:
    return PledgeService(session_factory)


def _reviewer(settings: Annotated[Settings, Depends(get_api_settings)]) -> str:
    return settings.admin_reviewer_identity or "editor-reviewer"


def _quote(value: str | None) -> str:
    if not value:
        return "<p class=\"empty-note\">Not recorded.</p>"
    return f"<blockquote class=\"pledge-quote\">{escape(value)}</blockquote>"


def _draft_card(draft) -> str:
    status_label, badge = {
        "pending": ("Pending", "badge-pending"),
        "approved": ("Approved", "badge-approved"),
        "rejected": ("Rejected", "badge-rejected"),
        "awaiting_second_approval": ("Awaiting second approval", "badge-review"),
    }.get(draft.status, (draft.status, "badge-muted"))
    date = draft.effective_at.isoformat() if draft.effective_at else "date not recorded"
    source = draft.source_title or "Official source title not stored"
    actions = ""
    if draft.status == "pending":
        actions = f"""
          <div class="review-actions">
            <form method="post" action="/demo/pledge-review/{draft.id}/approve">
              <button class="button" type="submit">Approve</button>
            </form>
            <form method="post" action="/demo/pledge-review/{draft.id}/reject">
              <label class="sr-only" for="reject-note-{draft.id}">Rejection note</label>
              <input id="reject-note-{draft.id}" name="note" required maxlength="500"
                     value="Retrieved official evidence does not support this commitment." />
              <button class="button button-secondary" type="submit">Reject</button>
            </form>
          </div>
        """
    return f"""
      <article class="pledge-review-card" data-status="{escape(draft.status)}">
        <header class="pledge-review-head">
          <span class="badge {badge}">{escape(status_label)}</span>
          <span>Draft {draft.id} · proposal {draft.proposal_id}</span>
        </header>
        <div class="compare-grid">
          <section>
            <h3>Commitment</h3>
            <p><strong>{escape(draft.commitment_title or "Untitled commitment")}</strong></p>
            {_quote(draft.commitment_statement)}
          </section>
          <section>
            <h3>Official evidence</h3>
            <p><strong>{escape(source)}</strong></p>
            <p><a href="{escape(draft.source_url)}" rel="noopener noreferrer">{escape(draft.source_url)}</a></p>
            <p>Effective / publication date: {escape(date)}</p>
            <p class="evidence-label">Exact quote</p>
            {_quote(draft.quoted_excerpt)}
          </section>
        </div>
        <dl class="review-meta">
          <div><dt>Proposed FEVER label</dt><dd>{escape(draft.evidence_label.value)}</dd></div>
          <div><dt>Proposed verdict</dt><dd>{escape(draft.proposed_verdict.value)}</dd></div>
          <div><dt>Retrieval reason</dt><dd>{escape(draft.retrieval_reason or "not recorded")}</dd></div>
        </dl>
        <p class="rationale">{escape(draft.rationale)}</p>
        {actions}
      </article>
    """


@router.get("/pledge-review", response_class=HTMLResponse)
def pledge_review_list(
    request: Request,
    service: Annotated[PledgeService, Depends(_service)],
    notice: Annotated[str | None, Query()] = None,
    error: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    del request
    drafts = service.list_drafts()
    cards = "".join(_draft_card(draft) for draft in drafts) or (
        "<p class=\"empty-note\">No pledge-assessment drafts yet.</p>"
    )
    body = f"""
      <style>
        .compare-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:1.25rem; }}
        .pledge-review-card {{ border:1px solid rgba(255,255,255,.12); border-radius:16px; padding:1.25rem; margin:1rem 0; }}
        .pledge-review-head {{ display:flex; gap:.75rem; align-items:center; margin-bottom:1rem; }}
        .review-meta {{ display:grid; grid-template-columns:repeat(3,1fr); gap:1rem; }}
        .review-actions {{ display:flex; gap:.75rem; align-items:flex-end; margin-top:1rem; }}
        .review-actions input {{ min-width:22rem; }}
        @media (max-width: 840px) {{ .compare-grid, .review-meta {{ grid-template-columns:1fr; }} }}
      </style>
      <section class="hero">
        <p class="eyebrow">Editorial review · unpublished</p>
        <h1>Commitment vs official evidence</h1>
        <p class="hero-copy">Compare the exact promise with the later official act. Approving publishes an append-only assessment. Rejecting leaves the public scorecard unchanged.</p>
      </section>
      {cards}
    """
    return _page(
        body,
        title="Pledge evidence review",
        notice=notice,
        error=bool(error),
        mode_label="PLEDGE REVIEW",
    )


@router.post("/pledge-review/{draft_id}/approve")
def approve_pledge_draft(
    draft_id: Annotated[int, Path(gt=0)],
    service: Annotated[PledgeService, Depends(_service)],
    reviewer: Annotated[str, Depends(_reviewer)],
) -> RedirectResponse:
    try:
        service.approve(draft_id, reviewer=reviewer, note="Editorial review of official evidence.")
    except (PledgeNotFoundError, PledgeValidationError, PledgeConflictError) as exc:
        return RedirectResponse(
            url=f"/demo/pledge-review?notice={quote(str(exc))}&error=1",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/demo/pledge-review?notice={quote('Draft approved. Public scorecard updated only if a new assessment was published.')}",
        status_code=303,
    )


@router.post("/pledge-review/{draft_id}/reject")
def reject_pledge_draft(
    draft_id: Annotated[int, Path(gt=0)],
    service: Annotated[PledgeService, Depends(_service)],
    reviewer: Annotated[str, Depends(_reviewer)],
    note: Annotated[str, Form()] = (
        "Retrieved official evidence does not support this commitment."
    ),
) -> RedirectResponse:
    try:
        service.reject(draft_id, reviewer=reviewer, note=note)
    except (PledgeNotFoundError, PledgeValidationError, PledgeConflictError) as exc:
        return RedirectResponse(
            url=f"/demo/pledge-review?notice={quote(str(exc))}&error=1",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/demo/pledge-review?notice={quote('Draft rejected. No public assessment was created.')}",
        status_code=303,
    )
