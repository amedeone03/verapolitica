const DEMO = Object.freeze({
  publishedPoliticianId: 1,
  pendingDraftId: 2,
  pendingPoliticianId: 2,
  adminToken: "verapolitica-demo-admin",
});

const state = {
  apiBase: "http://127.0.0.1:8000",
  published: null,
  draft: null,
  newlyPublished: null,
  busy: false,
};

const byId = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "—")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function displayValue(value) {
  if (value === null || value === undefined || value === "") return "Not provided";
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? "" : "s"}`;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function titleCase(value) {
  return String(value ?? "").replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function mandateLabel(profile) {
  const mandate = profile?.mandates?.[0];
  if (!mandate) return "No current mandate";
  const area = mandate.election_area ? ` · ${mandate.election_area}` : "";
  return `${titleCase(mandate.office)} · Legislature ${mandate.legislature}${area}`;
}

function profileFacts(profile, versionNumber, versionLabel = "Published version") {
  return `
    <div class="profile-grid">
      <div class="data-point"><small>Birth date</small><strong>${escapeHtml(profile.birth_date)}</strong></div>
      <div class="data-point"><small>Profession</small><strong>${escapeHtml(profile.profession || "Not provided")}</strong></div>
      <div class="data-point"><small>Mandate</small><strong>${escapeHtml(mandateLabel(profile))}</strong></div>
      <div class="data-point"><small>${escapeHtml(versionLabel)}</small><strong>${escapeHtml(versionNumber ?? "Pending")}</strong></div>
    </div>`;
}

export function renderPublishedProfile(person, { citationLimit = null } = {}) {
  const citations = citationLimit === null
    ? person.citations
    : person.citations.slice(0, citationLimit);
  const remaining = person.citations.length - citations.length;
  return `
    <h3 class="profile-name">${escapeHtml(person.given_name)} ${escapeHtml(person.family_name)}</h3>
    <p class="profile-subtitle">${escapeHtml(mandateLabel(person.profile))}</p>
    ${profileFacts(person.profile, person.current_version_number)}
    <div class="section-rule"></div>
    <div class="subheading"><h3>Public citations</h3><span>${person.citation_count} verified sources</span></div>
    <div class="citation-list">
      ${citations.map((citation) => `
        <div class="citation">
          <strong>${escapeHtml(citation.field_path)}</strong>
          <small>${escapeHtml(citation.source_name)} · ${escapeHtml(citation.source_field)}</small><br />
          <a href="${escapeHtml(citation.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(citation.source_url)}</a>
        </div>`).join("")}
      ${remaining > 0 ? `<small>+ ${remaining} more citations in the complete public record</small>` : ""}
    </div>
    <details><summary>Technical details / JSON</summary><pre>${escapeHtml(JSON.stringify(person, null, 2))}</pre></details>`;
}

export function renderDraft(draft) {
  const profile = draft.proposed_profile;
  const sourceName = draft.source_document.source_name;
  return `
    <h3 class="profile-name">${escapeHtml(profile.given_name)} ${escapeHtml(profile.family_name)}</h3>
    <p class="profile-subtitle">${escapeHtml(mandateLabel(profile))}</p>
    ${profileFacts(profile, titleCase(draft.kind), "Proposal kind")}
    <div class="section-rule"></div>
    <div class="subheading"><h3>Proposed changes</h3><span>${draft.diff.changes.length} changes</span></div>
    <div class="change-list">
      ${draft.diff.changes.map((change) => `
        <div class="change">
          <strong>${escapeHtml(change.field_path)} · ${escapeHtml(titleCase(change.change_type))}</strong>
          <div class="change-values">
            <code>${escapeHtml(displayValue(change.old_value))}</code><span>→</span><code>${escapeHtml(displayValue(change.new_value))}</code>
          </div>
        </div>`).join("")}
    </div>
    <div class="section-rule"></div>
    <div class="subheading"><h3>Supporting evidence</h3><span>${draft.evidence.length} source-backed fields</span></div>
    <div class="evidence-list">
      ${draft.evidence.map((evidence) => `
        <div class="evidence">
          <strong>${escapeHtml(evidence.field_path)}</strong>
          <small>${escapeHtml(sourceName)} · source field ${escapeHtml(evidence.source_field_name)}</small><br />
          <a href="${escapeHtml(evidence.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(evidence.source_url)}</a>
          <div class="evidence-value">${escapeHtml(evidence.source_value)}</div>
        </div>`).join("")}
    </div>
    <details><summary>Technical details / JSON</summary><pre>${escapeHtml(JSON.stringify(draft, null, 2))}</pre></details>`;
}

export function createApiClient(baseUrl, token, fetchImpl = fetch) {
  const base = baseUrl.replace(/\/$/, "");
  async function request(path, { method = "GET", admin = false, body } = {}) {
    const headers = { Accept: "application/json" };
    if (admin) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let response;
    try {
      response = await fetchImpl(`${base}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (error) {
      throw new Error(`API unavailable at ${base}`);
    }
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const message = payload?.error?.message || `Request failed with HTTP ${response.status}`;
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return payload;
  }
  return {
    health: () => request("/health"),
    publicPolitician: (id) => request(`/politicians/${id}`),
    draft: (id) => request(`/admin/drafts/${id}`, { admin: true }),
    startReview: (id) => request(`/admin/drafts/${id}/start-review`, { method: "POST", admin: true }),
    approve: (id) => request(`/admin/drafts/${id}/approve`, {
      method: "POST",
      admin: true,
      body: { note: "Official evidence verified during demo" },
    }),
    reject: (id) => request(`/admin/drafts/${id}/reject`, {
      method: "POST",
      admin: true,
      body: { note: "Evidence rejected during demo" },
    }),
  };
}

async function publicOrNull(api, id) {
  try {
    return await api.publicPolitician(id);
  } catch (error) {
    if (error.status === 404) return null;
    throw error;
  }
}

function setConnection(connected, message) {
  const element = byId("api-status");
  element.className = `connection-pill ${connected ? "is-connected" : "is-error"}`;
  element.innerHTML = `<span class="status-dot"></span>${escapeHtml(message)}`;
}

function showNotice(message, isError = false) {
  const notice = byId("notice");
  notice.hidden = false;
  notice.className = `notice is-visible${isError ? " is-error" : ""}`;
  notice.textContent = message;
}

function setBusy(busy) {
  state.busy = busy;
  updateControls();
}

function badgeForDraft(status) {
  const definitions = {
    pending: ["Pending", "badge-pending"],
    in_review: ["In review", "badge-review"],
    approved: ["Approved", "badge-approved"],
    rejected: ["Rejected", "badge-rejected"],
    superseded: ["Superseded", "badge-muted"],
    failed: ["Failed", "badge-rejected"],
  };
  return definitions[status] || [titleCase(status), "badge-muted"];
}

function render() {
  if (state.published) {
    byId("published-profile").className = "card-body";
    byId("published-profile").innerHTML = renderPublishedProfile(state.published, { citationLimit: 4 });
  }
  if (state.draft) {
    const [label, style] = badgeForDraft(state.draft.status);
    const headings = {
      pending: "Pending proposal",
      in_review: "Proposal in review",
      approved: "Approved proposal",
      rejected: "Rejected proposal",
    };
    byId("draft-heading").textContent = headings[state.draft.status] || "Editorial proposal";
    byId("draft-status").className = `badge ${style}`;
    byId("draft-status").textContent = label;
    byId("draft-profile").className = "card-body";
    byId("draft-profile").innerHTML = renderDraft(state.draft);
  }
  if (state.newlyPublished) {
    byId("new-public-status").className = "badge badge-verified";
    byId("new-public-status").textContent = "Published successfully";
    byId("new-public-profile").className = "card-body published-reveal";
    byId("new-public-profile").innerHTML = renderPublishedProfile(state.newlyPublished);
  }
  updateWorkflow();
  updateControls();
}

function updateWorkflow() {
  const status = state.draft?.status;
  const completed = new Set(["source", "parsed", "matched", "draft"]);
  if (["in_review", "approved", "rejected"].includes(status)) completed.add("review");
  if (state.newlyPublished) completed.add("published");
  document.querySelectorAll("#workflow li").forEach((item) => {
    item.classList.toggle("is-complete", completed.has(item.dataset.stage));
    item.classList.remove("is-active");
  });
  const active = state.newlyPublished ? "published" : status === "in_review" ? "review" : "draft";
  document.querySelector(`[data-stage="${active}"]`)?.classList.add("is-active");
  const [label, style] = state.newlyPublished
    ? ["Published", "badge-approved"]
    : badgeForDraft(status || "pending");
  byId("workflow-summary").className = `badge ${style}`;
  byId("workflow-summary").textContent = label;
}

function updateControls() {
  const status = state.draft?.status;
  const final = ["approved", "rejected", "superseded", "failed"].includes(status);
  byId("start-review").disabled = state.busy || status !== "pending";
  byId("approve").disabled = state.busy || final || !["pending", "in_review"].includes(status);
  byId("reject").disabled = state.busy || final || !["pending", "in_review"].includes(status);
}

async function loadDemo() {
  state.apiBase = byId("api-base").value.trim().replace(/\/$/, "");
  localStorage.setItem("verapolitica-demo-api", state.apiBase);
  const api = createApiClient(state.apiBase, DEMO.adminToken);
  setBusy(true);
  try {
    await api.health();
    [state.published, state.draft, state.newlyPublished] = await Promise.all([
      api.publicPolitician(DEMO.publishedPoliticianId),
      api.draft(DEMO.pendingDraftId),
      publicOrNull(api, DEMO.pendingPoliticianId),
    ]);
    setConnection(true, "API connected");
    render();
  } catch (error) {
    setConnection(false, error.status === 401 ? "Admin unauthorized" : "API unavailable");
    showNotice(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function performAction(action, successMessage) {
  const api = createApiClient(state.apiBase, DEMO.adminToken);
  setBusy(true);
  try {
    await api[action](DEMO.pendingDraftId);
    state.draft = await api.draft(DEMO.pendingDraftId);
    state.newlyPublished = await publicOrNull(api, DEMO.pendingPoliticianId);
    render();
    showNotice(successMessage);
  } catch (error) {
    if (error.status === 409) {
      await loadDemo();
      showNotice(`The draft state changed: ${error.message}`, true);
    } else {
      showNotice(error.status === 401 ? "Demo admin credential was rejected." : error.message, true);
    }
  } finally {
    setBusy(false);
  }
}

function boot() {
  const configured = new URLSearchParams(window.location.search).get("api")
    || localStorage.getItem("verapolitica-demo-api")
    || "http://127.0.0.1:8000";
  byId("api-base").value = configured;
  byId("reconnect").addEventListener("click", loadDemo);
  byId("start-review").addEventListener("click", () => performAction("startReview", "Draft moved to in review."));
  byId("approve").addEventListener("click", () => {
    if (window.confirm("Approve Draft 2 and publish an immutable public version?")) {
      performAction("approve", "Published successfully. Demo reset is now required to restore the opening state.");
    }
  });
  byId("reject").addEventListener("click", () => {
    if (window.confirm("Reject Draft 2? This is a final editorial decision.")) {
      performAction("reject", "Draft rejected. Demo reset is required to try the approval path.");
    }
  });
  loadDemo();
}

boot();
