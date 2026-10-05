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

function romanLegislature(value) {
  const number = Number(value);
  if (!Number.isInteger(number) || number < 1 || number > 30) return String(value);
  const numerals = [[10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]];
  let remaining = number;
  let result = "";
  for (const [unit, symbol] of numerals) {
    while (remaining >= unit) {
      result += symbol;
      remaining -= unit;
    }
  }
  return result;
}

function renderGroupMembership(membership) {
  const sourceUrl = safeExternalUrl(membership.source?.url);
  const dates = membership.start_date
    ? (membership.end_date
      ? `${formatDate(membership.start_date)} – ${formatDate(membership.end_date)}`
      : `Since ${formatDate(membership.start_date)}`)
    : (membership.end_date ? `Until ${formatDate(membership.end_date)}` : "Dates not provided");
  const role = membership.role && membership.role.toLocaleLowerCase() !== "membro"
    ? `<span class="group-role">${escapeHtml(membership.role)}</span>`
    : "";
  return `<article class="group-membership">
    <div>
      <strong>${escapeHtml(membership.name)}</strong>${role}
      <p>${escapeHtml(membership.institution)} · ${escapeHtml(romanLegislature(membership.legislature))} legislature</p>
      <small>${escapeHtml(dates)}</small>
    </div>
    ${sourceUrl ? `<a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Official source ↗</a>` : ""}
  </article>`;
}

export function renderParliamentaryGroups(memberships = []) {
  if (!memberships.length) {
    return `<p class="empty-note">No parliamentary-group membership is currently available from the supported official sources.</p>`;
  }
  const current = memberships.filter((membership) => !membership.end_date);
  const historical = memberships.filter((membership) => membership.end_date);
  return `${current.length ? `<div class="group-list">${current.map(renderGroupMembership).join("")}</div>` : ""}
    ${historical.length ? `<h3 class="previous-groups-title">Previous groups</h3><div class="group-list">${historical.map(renderGroupMembership).join("")}</div>` : ""}`;
}

function renderPartyAffiliation(affiliation) {
  const sourceUrl = safeExternalUrl(affiliation.source?.url);
  const websiteUrl = safeExternalUrl(affiliation.official_website_url);
  const dates = affiliation.start_date
    ? (affiliation.end_date
      ? `${formatDate(affiliation.start_date)} – ${formatDate(affiliation.end_date)}`
      : `Since ${formatDate(affiliation.start_date)}`)
    : (affiliation.end_date ? `Until ${formatDate(affiliation.end_date)}` : "Dates not provided");
  const affiliationType = affiliation.affiliation_type
    ? `<span class="party-affiliation-type">${escapeHtml(titleCase(affiliation.affiliation_type))}</span>`
    : "";
  return `<article class="party-affiliation">
    <div>
      <strong>${websiteUrl ? `<a href="${escapeHtml(websiteUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(affiliation.name)}</a>` : escapeHtml(affiliation.name)}</strong>${affiliationType}
      <p>${escapeHtml(dates)}</p>
    </div>
    ${sourceUrl ? `<a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Official source ↗</a>` : ""}
  </article>`;
}

export function renderPoliticalParties(affiliations = []) {
  if (!affiliations.length) {
    return `<p class="empty-note">No explicit political-party affiliation is currently available from the supported official sources.</p>`;
  }
  const current = affiliations.filter((affiliation) => !affiliation.end_date);
  const historical = affiliations.filter((affiliation) => affiliation.end_date);
  return `${current.length ? `<div class="party-list">${current.map(renderPartyAffiliation).join("")}</div>` : ""}
    ${historical.length ? `<h3 class="previous-parties-title">Previous parties</h3><div class="party-list">${historical.map(renderPartyAffiliation).join("")}</div>` : ""}`;
}

function proposalTypeLabel(value) {
  return value === "explicit_promise" ? "Explicit promise" : titleCase(value);
}

function renderProposalActor(actor) {
  const name = actor.politician_id
    ? `<a href="./?politician=${encodeURIComponent(actor.politician_id)}">${escapeHtml(actor.display_name)}</a>`
    : escapeHtml(actor.display_name);
  return `<span class="proposal-actor">${name}<small>${escapeHtml(titleCase(actor.role))}</small></span>`;
}

export function renderProposalCard(proposal) {
  const sourceUrl = safeExternalUrl(proposal.source?.url);
  return `<article class="proposal-card">
    <div class="proposal-card-top"><span class="proposal-type">${escapeHtml(proposalTypeLabel(proposal.proposal_type))}</span><span class="status-chip">${escapeHtml(titleCase(proposal.current_status))}</span></div>
    <h3>${escapeHtml(proposal.title)}</h3>
    <div class="proposal-actors">${proposal.actors.length ? proposal.actors.map(renderProposalActor).join("") : "<span>Actor not published</span>"}</div>
    <p>${escapeHtml(formatDate(proposal.introduced_at))}</p>
    <div class="proposal-card-links"><a class="profile-link" href="./?proposal=${encodeURIComponent(proposal.id)}">View timeline <span aria-hidden="true">→</span></a>${sourceUrl ? `<a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Official source ↗</a>` : ""}</div>
  </article>`;
}

export function renderProposalTimeline(events = []) {
  return `<ol class="proposal-timeline">${events.map((event) => {
    const url = safeExternalUrl(event.source?.url);
    return `<li><time>${escapeHtml(formatDate(event.effective_at))}</time><div><strong>${escapeHtml(titleCase(event.status))}</strong><p>Official label: ${escapeHtml(event.source_status_label)}</p>${url ? `<a class="source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Supporting evidence ↗</a>` : ""}</div></li>`;
  }).join("")}</ol>`;
}

export function renderProposalDetail(proposal) {
  return `<section class="proposal-detail-hero">
      <span class="proposal-type">${escapeHtml(proposalTypeLabel(proposal.proposal_type))}</span>
      <h1 id="proposal-detail-title">${escapeHtml(proposal.title)}</h1>
      <div class="proposal-actors">${proposal.actors.length ? proposal.actors.map(renderProposalActor).join("") : "<span>Actor not published</span>"}</div>
      <p class="lead">Current institutional status: <strong>${escapeHtml(titleCase(proposal.current_status))}</strong></p>
      ${proposal.exact_statement ? `<blockquote>${escapeHtml(proposal.exact_statement)}</blockquote>` : proposal.summary ? `<p>${escapeHtml(proposal.summary)}</p>` : ""}
    </section>
    <section class="detail-card proposal-timeline-card"><p class="eyebrow">Reviewed history</p><h2>Status timeline</h2>${renderProposalTimeline(proposal.status_history)}</section>
    <section class="detail-card"><p class="eyebrow">Traceable information</p><h2>Official sources</h2><div class="source-list">${proposal.sources.map((source) => {
      const url = safeExternalUrl(source.url);
      return `<article class="source-block"><h3>${escapeHtml(source.name)}</h3>${url ? `<a class="source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Open official source ↗</a>` : ""}</article>`;
    }).join("")}</div></section>`;
}

export function renderPoliticianProposals(proposals = []) {
  if (!proposals.length) return `<p class="empty-note">No published proposal or explicit commitment is linked to this politician.</p>`;
  return `<div class="linked-proposals">${proposals.map((proposal) => `<article><span class="proposal-type">${escapeHtml(proposalTypeLabel(proposal.proposal_type))}</span><h3><a href="./?proposal=${encodeURIComponent(proposal.id)}">${escapeHtml(proposal.title)}</a></h3><p>${escapeHtml(titleCase(proposal.role))} · ${escapeHtml(titleCase(proposal.current_status))}</p></article>`).join("")}</div>`;
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
    <section class="detail-card groups-card">
      <p class="eyebrow">Institutional affiliation</p><h2>Parliamentary groups</h2>
      <p class="group-disclaimer">Parliamentary groups are chamber-specific institutional bodies and are not the same as political parties.</p>
      ${renderParliamentaryGroups(person.parliamentary_groups || [])}
    </section>
    <section class="detail-card parties-card">
      <p class="eyebrow">Political affiliation</p><h2>Political party</h2>
      <p class="party-disclaimer">Political parties and parliamentary groups are distinct institutional concepts.</p>
      ${renderPoliticalParties(person.political_parties || [])}
    </section>
    <section class="detail-card proposals-card">
      <p class="eyebrow">Public record</p><h2>Proposals / commitments</h2>
      <p class="proposal-disclaimer">The displayed role states whether this person is a proposer, co-sponsor, or commitment owner.</p>
      ${renderPoliticianProposals(person.proposals || [])}
    </section>
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
    listProposals: () => request("/proposals?offset=0&limit=50"),
    getProposal: (id) => request(`/proposals/${encodeURIComponent(id)}`),
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

async function showProposals(api) {
  byId("archive-view").hidden = true;
  byId("proposals-view").hidden = false;
  try {
    const payload = await api.listProposals();
    byId("proposal-count").textContent = `${payload.total} published record${payload.total === 1 ? "" : "s"}`;
    if (!payload.items.length) {
      showState(byId("proposals-status"), "No reviewed proposals are currently available.", "Published proposals will appear here after editorial verification.");
      return;
    }
    byId("proposals-status").hidden = true;
    byId("proposal-list").hidden = false;
    byId("proposal-list").innerHTML = payload.items.map(renderProposalCard).join("");
  } catch {
    showState(byId("proposals-status"), "We couldn't load the proposal tracker.", "The public API is currently unavailable.", true);
  }
}

async function showProposalDetail(api, proposalId) {
  byId("archive-view").hidden = true;
  byId("proposal-detail-view").hidden = false;
  try {
    const proposal = await api.getProposal(proposalId);
    byId("proposal-detail-status").hidden = true;
    byId("proposal-detail").hidden = false;
    byId("proposal-detail").innerHTML = renderProposalDetail(proposal);
    document.title = `${proposal.title} — VeraPolitica`;
  } catch (error) {
    const missing = error.status === 404;
    showState(byId("proposal-detail-status"), missing ? "This proposal is not publicly available." : "We couldn't load this proposal.", missing ? "It may still be under editorial review." : "The public API is currently unavailable.", true);
  }
}

const api = createPublicApiClient();
const params = new URLSearchParams(window.location.search);
const politicianId = params.get("politician");
const proposalId = params.get("proposal");
if (proposalId && /^\d+$/.test(proposalId)) {
  showProposalDetail(api, proposalId);
} else if (politicianId && /^\d+$/.test(politicianId)) {
  showDetail(api, politicianId);
} else if (params.get("view") === "proposals") {
  showProposals(api);
} else {
  showArchive(api);
}
