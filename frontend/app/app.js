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

function officeLabel(office) {
  if (office === "mayor") return "Mayor";
  if (office === "regional_president") return "Regional president";
  return titleCase(office);
}

function holderLabel(holder) {
  if (!holder) return "Not currently linked";
  const name = `${holder.given_name} ${holder.family_name}`;
  return holder.politician_id
    ? `<a href="./?politician=${encodeURIComponent(holder.politician_id)}">${escapeHtml(name)}</a>`
    : escapeHtml(name);
}

export function renderTerritorialOffices(offices = []) {
  if (!offices.length) {
    return `<p class="empty-note">No territorial office mandate is currently linked to this politician.</p>`;
  }
  return `<div class="territorial-offices">${offices.map((office) => {
    const sourceUrl = safeExternalUrl(office.source?.url);
    const territory = office.municipality
      ? `<a href="./?municipality=${encodeURIComponent(office.municipality_id)}">${escapeHtml(office.municipality)}</a>`
      : office.region_id
        ? `<a href="./?region=${encodeURIComponent(office.region_id)}">${escapeHtml(office.region)}</a>`
        : escapeHtml(office.region || "Territory not provided");
    return `<article class="territorial-office">
      <div><span class="proposal-type">${escapeHtml(officeLabel(office.office))}</span><h3>${territory}</h3>
      <p>${office.municipality && office.region ? `Region: ${escapeHtml(office.region)} · ` : ""}${office.end_date ? `${formatDate(office.start_date)} – ${formatDate(office.end_date)}` : `Since ${formatDate(office.start_date)}`}</p></div>
      ${sourceUrl ? `<a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Official source ↗</a>` : ""}
    </article>`;
  }).join("")}</div>`;
}

export function renderRegionCard(region) {
  const president = region.current_president
    ? `${region.current_president.given_name} ${region.current_president.family_name}`
    : "President not currently linked";
  return `<article class="proposal-card">
    <span class="proposal-type">ISTAT ${escapeHtml(region.istat_code)}</span>
    <h3>${escapeHtml(region.name)}</h3>
    <p>President: ${escapeHtml(president)}</p>
    <a class="profile-link" href="./?region=${encodeURIComponent(region.id)}">View region <span aria-hidden="true">→</span></a>
  </article>`;
}

export function renderMunicipalityCard(municipality) {
  const mayor = municipality.current_mayor
    ? `${municipality.current_mayor.given_name} ${municipality.current_mayor.family_name}`
    : "Mayor not currently linked";
  return `<article class="proposal-card">
    <span class="proposal-type">ISTAT ${escapeHtml(municipality.istat_code)}</span>
    <h3>Comune di ${escapeHtml(municipality.name)}</h3>
    <p>Region: ${escapeHtml(municipality.region_name)} · Mayor: ${escapeHtml(mayor)}</p>
    <a class="profile-link" href="./?municipality=${encodeURIComponent(municipality.id)}">View municipality <span aria-hidden="true">→</span></a>
  </article>`;
}

export function renderRegionDetail(region, municipalities = []) {
  const sourceUrl = safeExternalUrl(region.source?.url);
  return `<section class="proposal-detail-hero">
      <p class="eyebrow">ISTAT region ${escapeHtml(region.istat_code)}</p>
      <h1 id="region-detail-title">${escapeHtml(region.name)}</h1>
      <p>President: ${holderLabel(region.current_president)}</p>
      <p>${region.municipality_count} municipalities in the official reference data.</p>
      ${sourceUrl ? `<p><a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Official ISTAT source ↗</a></p>` : ""}
    </section>
    <section class="detail-card">
      <p class="eyebrow">Municipalities</p><h2>Comuni in this region</h2>
      ${municipalities.length ? `<div class="proposal-grid">${municipalities.map(renderMunicipalityCard).join("")}</div>` : `<p class="empty-note">No municipalities are currently listed for this region.</p>`}
    </section>`;
}

export function renderMunicipalityDetail(municipality) {
  const sourceUrl = safeExternalUrl(municipality.source?.url);
  return `<section class="proposal-detail-hero">
      <p class="eyebrow">ISTAT municipality ${escapeHtml(municipality.istat_code)}</p>
      <h1 id="municipality-detail-title">Comune di ${escapeHtml(municipality.name)}</h1>
      <p>Region: <a href="./?region=${encodeURIComponent(municipality.region_id)}">${escapeHtml(municipality.region_name)}</a></p>
      <p>Mayor: ${holderLabel(municipality.current_mayor)}</p>
      <p>Province/UTS: ${escapeHtml(municipality.province_name)} (${escapeHtml(municipality.province_abbreviation)})</p>
      ${sourceUrl ? `<p><a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Official ISTAT source ↗</a></p>` : ""}
    </section>`;
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
    <section class="detail-card territorial-card">
      <p class="eyebrow">Local office</p><h2>Territorial offices</h2>
      <p class="territorial-disclaimer">Regional and municipal offices are stored separately from national parliamentary mandates.</p>
      ${renderTerritorialOffices(person.territorial_offices || [])}
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
    listRegions: () => request("/regions?offset=0&limit=50"),
    getRegion: (id) => request(`/regions/${encodeURIComponent(id)}`),
    listMunicipalities: ({ offset = 0, regionId = null } = {}) => {
      const params = new URLSearchParams({ offset: String(offset), limit: "50" });
      if (regionId) params.set("region", String(regionId));
      return request(`/municipalities?${params}`);
    },
    getMunicipality: (id) => request(`/municipalities/${encodeURIComponent(id)}`),
    search: ({ q, type = "", offset = 0 } = {}) => {
      const params = new URLSearchParams({ q, offset: String(offset), limit: "20" });
      if (type) params.set("type", type);
      return request(`/search?${params}`);
    },
    getParliamentaryGroup: (id) => request(`/parliamentary-groups/${encodeURIComponent(id)}`),
    getPoliticalParty: (id) => request(`/political-parties/${encodeURIComponent(id)}`),
    listReferendums: () => request("/referendums?offset=0&limit=50"),
    getReferendum: (id) => request(`/referendums/${encodeURIComponent(id)}`),
    listVotingGuides: () => request("/voting-guides?offset=0&limit=50"),
    getVotingGuide: (id) => request(`/voting-guides/${encodeURIComponent(id)}`),
    listGlossary: () => request("/glossary?offset=0&limit=50"),
    getGlossaryTerm: (slug) => request(`/glossary/${encodeURIComponent(slug)}`),
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

async function showRegions(api) {
  byId("archive-view").hidden = true;
  byId("regions-view").hidden = false;
  try {
    const payload = await api.listRegions();
    byId("region-count").textContent = `${payload.total} region${payload.total === 1 ? "" : "s"}`;
    if (!payload.items.length) {
      showState(byId("regions-status"), "No regions are currently available.", "Official ISTAT territories will appear after territorial ingestion.");
      return;
    }
    byId("regions-status").hidden = true;
    byId("region-list").hidden = false;
    byId("region-list").innerHTML = payload.items.map(renderRegionCard).join("");
  } catch {
    showState(byId("regions-status"), "We couldn't load regions.", "The public API is currently unavailable.", true);
  }
}

async function showRegionDetail(api, regionId) {
  byId("archive-view").hidden = true;
  byId("region-detail-view").hidden = false;
  try {
    const region = await api.getRegion(regionId);
    const municipalities = await api.listMunicipalities({ regionId });
    byId("region-detail-status").hidden = true;
    byId("region-detail").hidden = false;
    byId("region-detail").innerHTML = renderRegionDetail(region, municipalities.items || []);
    document.title = `${region.name} — VeraPolitica`;
  } catch (error) {
    const missing = error.status === 404;
    showState(byId("region-detail-status"), missing ? "This region is not available." : "We couldn't load this region.", missing ? "It may not have been ingested yet." : "The public API is currently unavailable.", true);
  }
}

async function showMunicipalities(api, offset) {
  byId("archive-view").hidden = true;
  byId("municipalities-view").hidden = false;
  try {
    const payload = await api.listMunicipalities({ offset });
    byId("municipality-count").textContent = `${payload.total} ${payload.total === 1 ? "municipality" : "municipalities"}`;
    if (!payload.items.length) {
      showState(byId("municipalities-status"), "No municipalities are currently available.", "Official ISTAT comuni will appear after territorial ingestion.");
      return;
    }
    byId("municipalities-status").hidden = true;
    byId("municipality-list").hidden = false;
    byId("municipality-list").innerHTML = payload.items.map(renderMunicipalityCard).join("");
    const pagination = byId("municipality-pagination");
    const previous = offset > 0 ? Math.max(0, offset - payload.limit) : null;
    const next = offset + payload.items.length < payload.total ? offset + payload.limit : null;
    pagination.hidden = previous === null && next === null;
    pagination.innerHTML = `${previous !== null ? `<a href="./?view=municipalities&offset=${previous}">Previous</a>` : ""}<span>Showing ${offset + 1}–${offset + payload.items.length} of ${payload.total}</span>${next !== null ? `<a href="./?view=municipalities&offset=${next}">Next</a>` : ""}`;
  } catch {
    showState(byId("municipalities-status"), "We couldn't load municipalities.", "The public API is currently unavailable.", true);
  }
}

function highlight(text, query) {
  const source = String(text ?? "");
  const tokens = String(query ?? "")
    .trim()
    .split(/\s+/)
    .filter((token) => token.length >= 2);
  if (!tokens.length) return escapeHtml(source);
  const pattern = new RegExp(`(${tokens.map((token) => token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  let result = "";
  let cursor = 0;
  for (const match of source.matchAll(pattern)) {
    const start = match.index ?? 0;
    result += escapeHtml(source.slice(cursor, start));
    result += `<mark class="search-hit">${escapeHtml(match[0])}</mark>`;
    cursor = start + match[0].length;
  }
  result += escapeHtml(source.slice(cursor));
  return result;
}

function searchTypeLabel(value) {
  return {
    politician: "Politician",
    proposal: "Proposal",
    municipality: "Municipality",
    region: "Region",
    parliamentary_group: "Parliamentary group",
    political_party: "Political party",
    referendum: "Referendum",
    glossary_term: "Glossary",
  }[value] || titleCase(value);
}

export function renderSearchCard(item, query) {
  return `<article class="search-card">
    <span class="search-type">${escapeHtml(searchTypeLabel(item.entity_type))}</span>
    <h3><a href="${escapeHtml(item.url)}">${highlight(item.title, query)}</a></h3>
    <p>${highlight(item.subtitle, query)}</p>
    ${item.snippet ? `<p>${highlight(item.snippet, query)}</p>` : ""}
  </article>`;
}

async function showSearch(api, query, type) {
  byId("archive-view").hidden = true;
  byId("search-view").hidden = false;
  byId("search-page-q").value = query;
  byId("search-type").value = type;
  byId("site-search-q").value = query;
  if (!query.trim()) {
    byId("search-count").textContent = "Ready";
    byId("search-list").hidden = true;
    showState(byId("search-status"), "Enter a search term.", "Use the form above to search the public archive.");
    return;
  }
  byId("search-status").hidden = false;
  byId("search-status").className = "state-card loading-state";
  byId("search-status").innerHTML = `<span class="loading-mark" aria-hidden="true"></span><div><strong>Searching…</strong><small>Looking through published public records.</small></div>`;
  try {
    const payload = await api.search({ q: query, type });
    byId("search-count").textContent = `${payload.total} result${payload.total === 1 ? "" : "s"}`;
    if (!payload.items.length) {
      byId("search-list").hidden = true;
      showState(byId("search-status"), "No public records match this search.", "Try another spelling, or filter by a different entity type.");
      return;
    }
    byId("search-status").hidden = true;
    byId("search-list").hidden = false;
    byId("search-list").innerHTML = payload.items.map((item) => renderSearchCard(item, query)).join("");
    document.title = `${query} — Search — VeraPolitica`;
  } catch (error) {
    byId("search-count").textContent = "Unavailable";
    showState(
      byId("search-status"),
      error.status === 422 ? "That search cannot be run." : "We couldn't complete this search.",
      error.status === 422 ? "Check the query length or selected type." : "The public API is currently unavailable.",
      true,
    );
  }
}

async function showOrganization(api, kind, entityId) {
  byId("archive-view").hidden = true;
  byId("organization-detail-view").hidden = false;
  try {
    const record = kind === "party"
      ? await api.getPoliticalParty(entityId)
      : await api.getParliamentaryGroup(entityId);
    byId("organization-detail-status").hidden = true;
    byId("organization-detail").hidden = false;
    const subtitle = kind === "party"
      ? "Political party"
      : `Parliamentary group · ${record.institution} · ${record.legislature} legislature`;
    byId("organization-detail").innerHTML = `<article class="proposal-detail-hero">
      <p class="eyebrow">${escapeHtml(kind === "party" ? "Political party" : "Parliamentary group")}</p>
      <h1 id="organization-detail-title">${escapeHtml(record.name)}</h1>
      <p class="hero-copy">${escapeHtml(subtitle)}${record.abbreviation ? ` · ${escapeHtml(record.abbreviation)}` : ""}</p>
    </article>`;
    document.title = `${record.name} — VeraPolitica`;
  } catch (error) {
    const missing = error.status === 404;
    showState(byId("organization-detail-status"), missing ? "This record is not available." : "We couldn't load this record.", missing ? "It may not exist in the public archive." : "The public API is currently unavailable.", true);
  }
}

async function showMunicipalityDetail(api, municipalityId) {
  byId("archive-view").hidden = true;
  byId("municipality-detail-view").hidden = false;
  try {
    const municipality = await api.getMunicipality(municipalityId);
    byId("municipality-detail-status").hidden = true;
    byId("municipality-detail").hidden = false;
    byId("municipality-detail").innerHTML = renderMunicipalityDetail(municipality);
    document.title = `Comune di ${municipality.name} — VeraPolitica`;
  } catch (error) {
    const missing = error.status === 404;
    showState(byId("municipality-detail-status"), missing ? "This municipality is not available." : "We couldn't load this municipality.", missing ? "It may not have been ingested yet." : "The public API is currently unavailable.", true);
  }
}

export function renderReferendumCard(item) {
  const synthetic = item.is_synthetic
    ? `<span class="institutional-note">Synthetic demo record</span>`
    : `<span class="institutional-note">Official source</span>`;
  return `<article class="proposal-card">
    <p class="eyebrow">${escapeHtml(titleCase(item.referendum_type))} · ${escapeHtml(titleCase(item.status))}</p>
    <h3><a href="./?referendum=${encodeURIComponent(item.id)}">${escapeHtml(item.title)}</a></h3>
    <p>${escapeHtml(item.vote_date)} · ${escapeHtml(titleCase(item.scope_type))}${item.region_name ? ` · ${escapeHtml(item.region_name)}` : ""}</p>
    ${synthetic}
  </article>`;
}

export function renderReferendumDetail(item) {
  const synthetic = item.is_synthetic
    ? `<p class="hero-copy"><strong>Synthetic demo record.</strong> This is not a current official vote.</p>`
    : "";
  const quorum = item.quorum_description
    ? `<p><strong>Quorum.</strong> ${escapeHtml(item.quorum_description)}</p>`
    : "<p>No quorum description is published for this record.</p>";
  const sources = (item.sources || []).map((source) => `
    <p><a href="${escapeHtml(source.source_url)}" rel="noreferrer">${escapeHtml(source.source_name)}</a>
    · ${escapeHtml(source.official_identifier)}</p>`).join("");
  const guide = item.voting_guide_id
    ? `<p><a href="./?view=voting-guide">Related voting guide</a></p>`
    : "";
  return `<article class="proposal-detail-hero">
    <p class="eyebrow">${escapeHtml(titleCase(item.referendum_type))} · ${escapeHtml(titleCase(item.status))}</p>
    <h1 id="referendum-detail-title">${escapeHtml(item.title)}</h1>
    ${synthetic}
    <p class="hero-copy"><strong>Official question.</strong> ${escapeHtml(item.official_question)}</p>
    <p>${escapeHtml(item.vote_date)}${item.vote_end_date ? ` – ${escapeHtml(item.vote_end_date)}` : ""}${item.start_time ? ` · ${escapeHtml(item.start_time)}` : ""}${item.end_time ? `–${escapeHtml(item.end_time)}` : ""} · ${escapeHtml(titleCase(item.scope_type))}</p>
    ${item.voting_hours_description ? `<p>${escapeHtml(item.voting_hours_description)}</p>` : ""}
    ${quorum}
    ${guide}
    <div class="section-rule"></div>
    <p class="eyebrow">Official sources</p>
    ${sources || `<p><a href="${escapeHtml(item.official_source_url)}" rel="noreferrer">${escapeHtml(item.official_source_url)}</a></p>`}
  </article>`;
}

export function renderVotingGuide(guide) {
  const sections = (guide.sections || []).map((section) => `
    <section class="guide-section">
      <h2>${escapeHtml(section.title)}</h2>
      <p>${escapeHtml(section.body)}</p>
      ${section.source_url ? `<p><a href="${escapeHtml(section.source_url)}" rel="noreferrer">Official source</a></p>` : ""}
    </section>`).join("");
  return `<article>
    <p class="eyebrow">${escapeHtml(titleCase(guide.scope))}</p>
    <h2>${escapeHtml(guide.title)}</h2>
    <p class="hero-copy">Guidance compiled from ${escapeHtml(guide.source_name)}. It does not recommend a yes or no vote.</p>
    ${sections}
    <p><a href="${escapeHtml(guide.source_url)}" rel="noreferrer">Guide-level official source</a></p>
  </article>`;
}

export function renderGlossaryTerm(item) {
  return `<article class="glossary-card" id="${escapeHtml(item.slug)}">
    <h3><a href="./?glossary=${encodeURIComponent(item.slug)}">${escapeHtml(item.term)}</a></h3>
    <p>${escapeHtml(item.short_definition)}</p>
    ${item.extended_definition ? `<p>${escapeHtml(item.extended_definition)}</p>` : ""}
    <p><a href="${escapeHtml(item.source_url)}" rel="noreferrer">Official source</a></p>
  </article>`;
}

async function showReferendums(api) {
  byId("archive-view").hidden = true;
  byId("referendums-view").hidden = false;
  try {
    const payload = await api.listReferendums();
    byId("referendum-count").textContent = `${payload.total} published record${payload.total === 1 ? "" : "s"}`;
    if (!payload.items.length) {
      showState(byId("referendums-status"), "No published referendums are currently available.", "Published civic records will appear here after editorial review.");
      return;
    }
    byId("referendums-status").hidden = true;
    byId("referendum-list").hidden = false;
    byId("referendum-list").innerHTML = payload.items.map(renderReferendumCard).join("");
    document.title = "Referendums — VeraPolitica";
  } catch {
    byId("referendum-count").textContent = "Unavailable";
    showState(byId("referendums-status"), "We couldn't load referendums.", "The public API is currently unavailable.", true);
  }
}

async function showReferendumDetail(api, referendumId) {
  byId("archive-view").hidden = true;
  byId("referendum-detail-view").hidden = false;
  try {
    const record = await api.getReferendum(referendumId);
    byId("referendum-detail-status").hidden = true;
    byId("referendum-detail").hidden = false;
    byId("referendum-detail").innerHTML = renderReferendumDetail(record);
    document.title = `${record.title} — VeraPolitica`;
  } catch (error) {
    const missing = error.status === 404;
    showState(byId("referendum-detail-status"), missing ? "This referendum is not available." : "We couldn't load this referendum.", missing ? "It may not have been published yet." : "The public API is currently unavailable.", true);
  }
}

async function showVotingGuide(api) {
  byId("archive-view").hidden = true;
  byId("voting-guide-view").hidden = false;
  try {
    const payload = await api.listVotingGuides();
    if (!payload.items.length) {
      showState(byId("voting-guide-status"), "No published voting guide is currently available.", "Official civic guidance appears after editorial publication.");
      return;
    }
    byId("voting-guide-status").hidden = true;
    byId("voting-guide-detail").hidden = false;
    byId("voting-guide-detail").innerHTML = payload.items.map(renderVotingGuide).join("");
    document.title = "How to vote — VeraPolitica";
  } catch {
    showState(byId("voting-guide-status"), "We couldn't load the voting guide.", "The public API is currently unavailable.", true);
  }
}

async function showGlossary(api, slug) {
  byId("archive-view").hidden = true;
  byId("glossary-view").hidden = false;
  try {
    const payload = await api.listGlossary();
    byId("glossary-count").textContent = `${payload.total} term${payload.total === 1 ? "" : "s"}`;
    if (!payload.items.length) {
      showState(byId("glossary-status"), "No glossary terms are currently published.", "Editorially reviewed definitions will appear here.");
      return;
    }
    byId("glossary-status").hidden = true;
    byId("glossary-list").hidden = false;
    byId("glossary-list").innerHTML = payload.items.map(renderGlossaryTerm).join("");
    document.title = slug ? `${slug} — Glossary — VeraPolitica` : "Glossary — VeraPolitica";
    if (slug) {
      const target = document.getElementById(slug);
      if (target) target.scrollIntoView();
    }
  } catch {
    byId("glossary-count").textContent = "Unavailable";
    showState(byId("glossary-status"), "We couldn't load the glossary.", "The public API is currently unavailable.", true);
  }
}

const api = createPublicApiClient();
const params = new URLSearchParams(window.location.search);
const politicianId = params.get("politician");
const proposalId = params.get("proposal");
const referendumId = params.get("referendum");
const glossarySlug = params.get("glossary");
const regionId = params.get("region");
const municipalityId = params.get("municipality");
const groupId = params.get("parliamentary_group");
const partyId = params.get("political_party");
const municipalityOffset = Number.parseInt(params.get("offset") || "0", 10);
if (proposalId && /^\d+$/.test(proposalId)) {
  showProposalDetail(api, proposalId);
} else if (politicianId && /^\d+$/.test(politicianId)) {
  showDetail(api, politicianId);
} else if (referendumId && /^\d+$/.test(referendumId)) {
  showReferendumDetail(api, referendumId);
} else if (glossarySlug) {
  showGlossary(api, glossarySlug);
} else if (municipalityId && /^\d+$/.test(municipalityId)) {
  showMunicipalityDetail(api, municipalityId);
} else if (regionId && /^\d+$/.test(regionId)) {
  showRegionDetail(api, regionId);
} else if (groupId && /^\d+$/.test(groupId)) {
  showOrganization(api, "group", groupId);
} else if (partyId && /^\d+$/.test(partyId)) {
  showOrganization(api, "party", partyId);
} else if (params.get("view") === "proposals") {
  showProposals(api);
} else if (params.get("view") === "referendums") {
  showReferendums(api);
} else if (params.get("view") === "voting-guide") {
  showVotingGuide(api);
} else if (params.get("view") === "glossary") {
  showGlossary(api);
} else if (params.get("view") === "regions") {
  showRegions(api);
} else if (params.get("view") === "municipalities") {
  showMunicipalities(api, Number.isFinite(municipalityOffset) ? municipalityOffset : 0);
} else if (params.get("view") === "search") {
  showSearch(api, params.get("q") || "", params.get("type") || "");
} else {
  showArchive(api);
}
