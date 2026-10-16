const tokenInput = document.getElementById("admin-token");
const politicianInput = document.getElementById("politician-id");
const filterSelect = document.getElementById("readiness-filter");
const statusNode = document.getElementById("review-status");
const reviewRoot = document.getElementById("review-root");
const previewRoot = document.getElementById("preview-root");
const pledgeRoot = document.getElementById("pledge-root");

function headers() {
  const token = tokenInput.value.trim();
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setStatus(message, isError) {
  statusNode.textContent = message;
  statusNode.classList.toggle("is-error", Boolean(isError));
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, { ...options, headers: headers() });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function sourceLines(item) {
  const sources = item.sources || [];
  if (!sources.length) return "<p class=\"source-line\">No sources stored.</p>";
  return sources.map((source) => {
    const url = source.url || "";
    return `<p class="source-line"><strong>${escapeHtml(source.name)}</strong> · ${escapeHtml(source.kind || "")}${url ? ` · <a href="${escapeHtml(url)}" rel="noopener noreferrer">${escapeHtml(url)}</a>` : " · URL missing"}</p>`;
  }).join("");
}

function proceedingExtras(item) {
  if (item.kind !== "proceeding") return "";
  return `<dl class="review-meta">
    <div><dt>Proceeding type</dt><dd>${escapeHtml((item.proceeding_types || []).join(", "))}</dd></div>
    <div><dt>Outcome / status</dt><dd>${escapeHtml(item.outcome || "not recorded")}</dd></div>
    <div><dt>Nature</dt><dd>${escapeHtml(item.proceeding_nature || "unspecified")}</dd></div>
  </dl>`;
}

function card(item) {
  const ready = item.source_completeness === "READY_FOR_EDITORIAL_REVIEW";
  const warning = item.ceo_reference_warning
    ? `<p class="ceo-warning">${escapeHtml(item.ceo_reference_warning)}</p>`
    : "";
  const blockers = (item.completeness_blockers || []).filter((row) => row && row !== "none");
  return `<article class="profile-review-card ${ready ? "is-ready" : "is-blocked"}" data-kind="${escapeHtml(item.kind)}" data-id="${item.id}">
    <header class="profile-review-head">
      <span class="badge ${ready ? "badge-approved" : "badge-pending"}">${escapeHtml(item.source_completeness)}</span>
      <span>${escapeHtml(item.politician_name)} · ${escapeHtml(item.kind)} · ${escapeHtml(item.status)}</span>
    </header>
    ${warning}
    <p><strong>${escapeHtml(item.title)}</strong> <code>${escapeHtml(item.identity_key)}</code></p>
    <p>${escapeHtml(item.proposed_text)}</p>
    ${proceedingExtras(item)}
    <p class="source-line">Origin: ${escapeHtml(item.created_by)}${item.reference_origin ? " · CEO reference fixture" : ""} · created ${escapeHtml(item.created_at || "")}</p>
    ${sourceLines(item)}
    ${blockers.length ? `<p class="source-line">Blocker: ${escapeHtml(blockers.join("; "))}</p>` : ""}
    <div class="review-actions">
      <button class="button" type="button" data-action="approve">${ready ? "Approve" : "Approve anyway"}</button>
      <button class="button button-secondary" type="button" data-action="reject">Reject</button>
    </div>
  </article>`;
}

async function loadPending() {
  const politicianId = politicianInput.value.trim();
  const readiness = filterSelect.value;
  const params = new URLSearchParams({ status: "pending", limit: "100" });
  if (politicianId) params.set("politician_id", politicianId);
  if (readiness) params.set("source_completeness", readiness);
  const payload = await fetchJson(`/admin/profile-content?${params}`);
  if (!payload.items.length) {
    reviewRoot.innerHTML = "<p class=\"empty-note\">No pending profile content for this filter.</p>";
    setStatus("Loaded 0 pending items.");
    return;
  }
  if (!politicianInput.value) {
    politicianInput.value = String(payload.items[0].politician_id);
  }
  reviewRoot.innerHTML = payload.items.map(card).join("");
  setStatus(`Loaded ${payload.items.length} pending item(s). Public archive is unchanged.`);
}

async function loadPreview() {
  const politicianId = politicianInput.value.trim();
  if (!politicianId) throw new Error("Set politician ID for preview");
  const payload = await fetchJson(`/admin/politicians/${politicianId}/editorial-preview`);
  previewRoot.innerHTML = `<div class="preview-banner">${escapeHtml(payload.banner)}</div>
    <p class="empty-note">${escapeHtml(payload.politician_name)} · publication unchanged: ${payload.publication_unchanged}</p>
    <div class="review-grid">
      <section><h3>Biography</h3><p>${escapeHtml(payload.biography?.body || "No biography in preview.")}</p></section>
      <section><h3>Pending counts</h3><pre>${escapeHtml(JSON.stringify(payload.pending_counts, null, 2))}</pre></section>
    </div>`;
}

async function loadPledges() {
  const politicianId = politicianInput.value.trim();
  if (!politicianId) return;
  const payload = await fetchJson(`/admin/politicians/${politicianId}/reference-readiness`);
  const pledges = payload.pledges || [];
  if (!pledges.length) {
    pledgeRoot.innerHTML = "<p class=\"empty-note\">No reference pledge rows.</p>";
    return;
  }
  pledgeRoot.innerHTML = `<table class="facts"><thead><tr>
    <th>PDF</th><th>Title</th><th>Declaration</th><th>Match</th><th>Status</th><th>Evidence</th>
  </tr></thead><tbody>${pledges.map((row) => `<tr>
    <td>${row.pdf_number}</td>
    <td>${escapeHtml(row.title)}</td>
    <td>${escapeHtml(row.declaration_source)}<br />${row.declaration_url ? `<a href="${escapeHtml(row.declaration_url)}" rel="noopener noreferrer">source</a>` : "URL missing"}</td>
    <td>${escapeHtml(row.matched_existing_pledge || "new")} · ${row.duplicate_safe ? "duplicate-safe" : "skip duplicate"}</td>
    <td>${escapeHtml(row.publication_status)} / ${escapeHtml(row.assessment_status)}</td>
    <td>${escapeHtml((row.evidence_readiness || []).join(", "))}</td>
  </tr>`).join("")}</tbody></table>`;
}

async function act(kind, id, action) {
  await fetchJson(`/admin/profile-content/${kind}/${id}/${action}`, {
    method: "POST",
    body: JSON.stringify({ note: action === "reject" ? "Rejected from profile desk." : "Approved from profile desk." }),
  });
  await loadPending();
}

document.getElementById("load-review").addEventListener("click", async () => {
  try {
    await loadPending();
    await loadPledges();
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.getElementById("load-preview").addEventListener("click", async () => {
  try {
    await loadPreview();
  } catch (error) {
    setStatus(error.message, true);
  }
});

reviewRoot.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const cardNode = button.closest(".profile-review-card");
  try {
    await act(cardNode.dataset.kind, cardNode.dataset.id, button.dataset.action);
  } catch (error) {
    setStatus(error.message, true);
  }
});
