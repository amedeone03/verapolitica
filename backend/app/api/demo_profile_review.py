"""Local editorial desk for politician profile content. Never public."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from backend.app.api.demo_editorial import _page


router = APIRouter(prefix="/demo", tags=["demo-profile-review"])


@router.get("/profile-review", response_class=HTMLResponse)
def profile_review_desk(request: Request) -> HTMLResponse:
    del request
    body = """
      <style>
        .review-toolbar { display:flex; flex-wrap:wrap; gap:.75rem; align-items:end; margin:1rem 0 1.5rem; }
        .review-toolbar label { display:flex; flex-direction:column; gap:.35rem; font-size:.85rem; color:var(--muted); }
        .review-toolbar input, .review-toolbar select { min-width:16rem; }
        .profile-review-card { border:1px solid rgba(255,255,255,.12); border-radius:16px; padding:1.1rem; margin:1rem 0; }
        .profile-review-card.is-ready { border-color: rgba(61,220,151,.35); }
        .profile-review-card.is-blocked { border-color: rgba(255,107,107,.35); }
        .profile-review-head { display:flex; flex-wrap:wrap; gap:.75rem; align-items:center; margin-bottom:.75rem; }
        .review-grid { display:grid; grid-template-columns:1fr 1fr; gap:1rem; }
        .review-actions { display:flex; gap:.75rem; align-items:end; margin-top:1rem; }
        .ceo-warning { background: rgba(245,185,66,.14); border:1px solid rgba(245,185,66,.35); padding:.75rem 1rem; border-radius:12px; }
        .preview-banner { background: rgba(255,107,26,.16); border:1px solid rgba(255,107,26,.4); padding:.85rem 1rem; border-radius:12px; font-weight:600; }
        .source-line { font-size:.9rem; color:var(--muted); }
        @media (max-width: 840px) { .review-grid { grid-template-columns:1fr; } }
      </style>
      <section class="hero">
        <p class="eyebrow">Editorial review · unpublished</p>
        <h1>Profile content desk</h1>
        <p class="hero-copy">Review pending biography, career, positions and proceedings. Approving publishes that item only. Missing source URLs stay visible here and stay hidden from the public archive until an editor approves them.</p>
      </section>
      <div class="review-toolbar">
        <label>Admin token
          <input id="admin-token" type="password" autocomplete="off" placeholder="Bearer token" />
        </label>
        <label>Politician ID
          <input id="politician-id" type="number" min="1" placeholder="206" />
        </label>
        <label>Filter
          <select id="readiness-filter">
            <option value="">All pending</option>
            <option value="READY_FOR_EDITORIAL_REVIEW">READY TO APPROVE</option>
            <option value="MISSING_SOURCE_URL">NEEDS SOURCE URL</option>
            <option value="MISSING_SOURCE_METADATA">NEEDS SOURCE METADATA</option>
            <option value="NEEDS_FACT_CHECK">NEEDS EVIDENCE / FACT CHECK</option>
            <option value="OTHER_BLOCKER">OTHER BLOCKER</option>
          </select>
        </label>
        <button class="button" id="load-review" type="button">Load pending</button>
        <button class="button button-secondary" id="load-preview" type="button">Editorial preview</button>
      </div>
      <p id="review-status" class="empty-note">Enter the admin token. Pending content is not loaded until you authenticate.</p>
      <div id="preview-root"></div>
      <div id="review-root"></div>
      <section class="hero">
        <p class="eyebrow">Promises</p>
        <h2>Pledge reconciliation</h2>
        <p class="hero-copy">Declaration sources are not fulfilment evidence. Do not approve assessments from PDF commentary. Existing duplicates stay skipped.</p>
      </section>
      <div id="pledge-root"></div>
      <script src="/demo/profile-review.js"></script>
    """
    return _page(
        body,
        title="Profile content review",
        mode_label="PROFILE REVIEW",
    )
