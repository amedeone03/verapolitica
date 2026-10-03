const byId = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "—")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeExternalUrl(value) {
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch {
    return null;
  }
}

function titleCase(value) {
  return String(value ?? "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value) {
  if (!value) return "Not provided";
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.valueOf())
    ? String(value)
    : new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(date);
}

function initials(person) {
  return `${person.given_name?.[0] ?? ""}${person.family_name?.[0] ?? ""}`.toUpperCase() || "VP";
}

function portrait(person) {
  const imageUrl = safeExternalUrl(person.profile?.image_url);
  if (imageUrl) {
    return `<div class="portrait"><span aria-hidden="true">${escapeHtml(initials(person))}</span><img src="${escapeHtml(imageUrl)}" alt="Portrait of ${escapeHtml(`${person.given_name} ${person.family_name}`)}" onerror="this.remove()" /></div>`;
  }
  return `<div class="portrait" aria-label="No portrait available">${escapeHtml(initials(person))}</div>`;
}

function primaryMandate(person) {
  return person.profile?.mandates?.[0] ?? null;
}

function mandateTitle(mandate) {
  if (!mandate) return "Mandate information not provided";
  return `${titleCase(mandate.office)} — Legislature ${mandate.legislature}`;
}

export function renderPoliticianCard(person) {
  const mandate = primaryMandate(person);
  return `<article class="politician-card">
    ${portrait(person)}
    <div class="card-content">
      <span class="verified-badge">Verified from official sources</span>
      <h3>${escapeHtml(person.given_name)} ${escapeHtml(person.family_name)}</h3>
      <p class="mandate">${escapeHtml(mandateTitle(mandate))}</p>
      <p class="area">${escapeHtml(mandate?.institution ?? "National institution")}${mandate?.election_area ? ` · ${escapeHtml(mandate.election_area)}` : ""}</p>
      <p class="source-count">${person.citation_count} verified data reference${person.citation_count === 1 ? "" : "s"}</p>
      <a class="profile-link" href="./?politician=${encodeURIComponent(person.id)}">View profile <span aria-hidden="true">→</span></a>
    </div>
  </article>`;
}

export function fieldLabel(fieldPath) {
  const exact = {
    given_name: "First name",
    family_name: "Family name",
    birth_date: "Date of birth",
    "birth_place.city": "City of birth",
    "birth_place.subdivision": "Province or region of birth",
    "birth_place.country": "Country of birth",
    gender: "Gender",
    profession: "Profession",
    image_url: "Official portrait",
    official_homepage_url: "Official website",
  };
  if (exact[fieldPath]) return exact[fieldPath];
  const mandateField = fieldPath.match(/^mandates\[\d+\]\.(.+)$/)?.[1];
  const mandateLabels = {
    institution: "Institution",
    office: "Office",
    legislature: "Legislature",
    mandate_type: "Mandate type",
    start_date: "Mandate start date",
    end_date: "Mandate end date",
    election_area: "Election area",
  };
  return mandateLabels[mandateField] ?? titleCase(fieldPath.split(".").at(-1));
}

export function groupCitations(citations) {
  const grouped = new Map();
  for (const citation of citations) {
    const key = `${citation.source_name}\u0000${citation.source_url}`;
    if (!grouped.has(key)) {
      grouped.set(key, {
        sourceName: citation.source_name,
        sourceUrl: citation.source_url,
        fields: new Set(),
        referenceCount: 0,
      });
    }
    const group = grouped.get(key);
    group.fields.add(fieldLabel(citation.field_path));
    group.referenceCount += 1;
  }
  return [...grouped.values()].map((group) => ({
    ...group,
    fields: [...group.fields].sort((left, right) => left.localeCompare(right)),
  }));
}

function renderMandate(mandate) {
  const dates = `${formatDate(mandate.start_date)}${mandate.end_date ? ` – ${formatDate(mandate.end_date)}` : " – present"}`;
  return `<div class="mandate-block">
    <strong>${escapeHtml(titleCase(mandate.office))}</strong>
    <p>${escapeHtml(mandate.institution)} · Legislature ${escapeHtml(mandate.legislature)}</p>
    <p>${escapeHtml(mandate.election_area || "Election area not provided")} · ${escapeHtml(dates)}</p>
  </div>`;
}

function fact(label, value, { href = null } = {}) {
  const content = href
    ? `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(value)}</a>`
    : escapeHtml(value);
  return `<div class="fact"><dt>${escapeHtml(label)}</dt><dd>${content}</dd></div>`;
}

function birthPlace(profile) {
  if (!profile.birth_place) return "Not provided";
  return [profile.birth_place.city, profile.birth_place.subdivision, profile.birth_place.country].filter(Boolean).join(", ") || "Not provided";
}

export function renderSources(citations) {
  const groups = groupCitations(citations);
  if (!groups.length) {
    return `<div class="state-card"><div><strong>No official source references are available for this profile.</strong></div></div>`;
  }
  return groups.map((group) => {
    const sourceUrl = safeExternalUrl(group.sourceUrl);
    return `<article class="source-block">
      <div class="source-top">
        <div><h3>${escapeHtml(group.sourceName)}</h3><small>${group.referenceCount} verified data reference${group.referenceCount === 1 ? "" : "s"}</small></div>
        ${sourceUrl ? `<a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Open official source ↗</a>` : ""}
      </div>
      <p class="supports-label">Supports</p>
      <ul class="supports">${group.fields.map((label) => `<li>${escapeHtml(label)}</li>`).join("")}</ul>
    </article>`;
  }).join("");
}

export function renderPoliticianDetail(person) {
  const profile = person.profile;
  const homepage = safeExternalUrl(profile.official_homepage_url);
  const citationGroups = groupCitations(person.citations);
  const publishedDate = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric" }).format(new Date(person.published_at));
  return `<section class="profile-hero">
      ${portrait(person)}
      <div class="profile-intro">
        <span class="verified-badge">Verified from official sources</span>
        <h1 id="profile-name">${escapeHtml(person.given_name)} ${escapeHtml(person.family_name)}</h1>
        <p class="lead">${escapeHtml(mandateTitle(primaryMandate(person)))}</p>
        <p class="publication-meta">Current published profile · Version ${person.current_version_number} · Published ${escapeHtml(publishedDate)}</p>
      </div>
    </section>
    <div class="detail-grid">
      <section class="detail-card">
        <p class="eyebrow">Profile</p><h2>Personal information</h2>
        <dl class="facts">
          ${fact("Date of birth", formatDate(person.birth_date))}
          ${fact("Place of birth", birthPlace(profile))}
          ${fact("Profession", profile.profession || "Not provided")}
          ${homepage ? fact("Official website", "Visit official page ↗", { href: homepage }) : fact("Official website", "Not provided")}
        </dl>
      </section>
      <section class="detail-card">
        <p class="eyebrow">Public office</p><h2>Mandates</h2>
        ${profile.mandates.length ? profile.mandates.map(renderMandate).join("") : "<p>No mandate information is available.</p>"}
      </section>
    </div>
    <section class="detail-card sources-card">
      <div class="sources-heading">
        <div><p class="eyebrow">Traceable information</p><h2>Official sources</h2></div>
        <div class="sources-summary"><strong>${person.citation_count} verified data references</strong><br />${citationGroups.length} official source${citationGroups.length === 1 ? "" : "s"}</div>
      </div>
      <div class="source-list">${renderSources(person.citations)}</div>
    </section>`;
}

export function createPublicApiClient(fetchImpl = fetch) {
  async function request(path) {
    let response;
    try {
      response = await fetchImpl(path, { headers: { Accept: "application/json" } });
    } catch {
      throw new Error("api_unavailable");
    }
    if (!response.ok) {
      const error = new Error(response.status === 404 ? "not_found" : "api_error");
      error.status = response.status;
      throw error;
    }
    return response.json();
  }
  return {
    listPoliticians: () => request("/politicians?offset=0&limit=50"),
    getPolitician: (id) => request(`/politicians/${encodeURIComponent(id)}`),
  };
}

function showState(element, title, detail, isError = false) {
  element.hidden = false;
  element.className = `state-card${isError ? " is-error" : ""}`;
  element.innerHTML = `<div><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail)}</small></div>`;
}

async function showArchive(api) {
  try {
    const payload = await api.listPoliticians();
    byId("archive-count").textContent = `${payload.total} verified profile${payload.total === 1 ? "" : "s"}`;
    if (!payload.items.length) {
      showState(byId("archive-status"), "No verified profiles are currently available.", "Published profiles will appear here after editorial verification.");
      return;
    }
    byId("archive-status").hidden = true;
    byId("politician-list").hidden = false;
    byId("politician-list").innerHTML = payload.items.map(renderPoliticianCard).join("");
  } catch {
    byId("archive-count").textContent = "Unavailable";
    showState(byId("archive-status"), "We couldn't load the verified profiles. Please try again.", "The public API is currently unavailable.", true);
  }
}

async function showDetail(api, politicianId) {
  byId("archive-view").hidden = true;
  byId("detail-view").hidden = false;
  try {
    const person = await api.getPolitician(politicianId);
    byId("detail-status").hidden = true;
    byId("profile-detail").hidden = false;
    byId("profile-detail").innerHTML = renderPoliticianDetail(person);
    document.title = `${person.given_name} ${person.family_name} — VeraPolitica`;
  } catch (error) {
    const missing = error.status === 404;
    showState(
      byId("detail-status"),
      missing ? "This verified profile is not currently available." : "We couldn't load this verified profile. Please try again.",
      missing ? "It may not have been published yet." : "The public API is currently unavailable.",
      true,
    );
  }
}

const api = createPublicApiClient();
const politicianId = new URLSearchParams(window.location.search).get("politician");
if (politicianId && /^\d+$/.test(politicianId)) {
  showDetail(api, politicianId);
} else {
  showArchive(api);
}
