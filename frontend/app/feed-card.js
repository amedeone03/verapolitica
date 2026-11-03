// VeraPolitica — feed card, shared by the public feed (/app) and the
// redazione console preview (/redazione). One function, same markup.
//
//   [category band]
//   [badge · date]                [aside]
//   (o) Name     (o) Name        round image + party or role
//   Institution
//   Title
//   Summary                       ("Mostra altro" when long)
//   Info · Fonti · Chiedi
//   [iter: 4 steps]  status · since
//   [external link]        [save] [share]

const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const PATHS = {
  doc: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 13h4"/><path d="M10 17h4"/>',
  vote: '<path d="m9 12 2 2 4-4"/><path d="M5 7c0-1.1.9-2 2-2h10a2 2 0 0 1 2 2v12H5V7Z"/><path d="M22 19H2"/>',
  ballot: '<path d="M4 4h16v16H4z"/><path d="m8 12 3 3 5-6"/>',
  promise: '<path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/>',
  news: '<path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8"/><path d="M15 18h-5"/><path d="M10 6h8v4h-8V6Z"/>',
  question: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
  building: '<path d="M3 22h18"/><path d="M6 18v-7"/><path d="M10 18v-7"/><path d="M14 18v-7"/><path d="M18 18v-7"/><path d="M12 2 2 7h20Z"/>',
  swap: '<path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/>',
  stamp: '<path d="M5 22h14"/><path d="M19.27 13.73A2.5 2.5 0 0 0 17.5 13h-11A2.5 2.5 0 0 0 4 15.5V17a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-1.5c0-.66-.26-1.3-.73-1.77Z"/><path d="M14 13V8.5C14 7 15 7 15 5a3 3 0 0 0-6 0c0 2 1 2 1 3.5V13"/>',
  info: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M8 13h8"/><path d="M8 17h8"/><path d="M8 9h2"/>',
  sources: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  bookmark: '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/>',
  share: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
  external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
};
export function cardIcon(name, size = 16, filled = false) {
  return `<svg class="vp-icon" aria-hidden="true" focusable="false" viewBox="0 0 24 24" width="${size}" height="${size}" fill="${filled ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${PATHS[name] || ""}</svg>`;
}

const CATEGORY_ICON = {
  notizia: "news", pubblicazione: "doc", disegno_di_legge: "doc", proposta_di_legge: "doc", decreto: "doc",
  votazione: "vote", interrogazione: "question", referendum: "ballot", promessa: "promise", elezioni: "ballot",
};
const STEP_ICON = ["building", "building", "swap", "stamp"];
const SHORT_MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];

export function shortDate(value) {
  const [y, m, d] = String(value || "").slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return "";
  return `${d} ${SHORT_MONTHS[m - 1]}${y !== new Date().getFullYear() ? ` ${y}` : ""}`;
}
export function longDate(value) {
  const [y, m, d] = String(value || "").slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return "";
  return `${d} ${MONTHS[m - 1]} ${y}`;
}
function safeUrl(value) {
  if (typeof value === "string" && /^\/(media|portraits)\//.test(value)) return value;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch { return null; }
}
function initials(name) {
  return String(name || "").split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function avatar(person, resolvePortrait) {
  let url = person.image_url;
  if (url && url.startsWith("politician:")) url = resolvePortrait ? resolvePortrait(Number(url.split(":")[1])) : null;
  const src = url ? safeUrl(url) : null;
  return `<span class="vp-avatar">${src ? `<img src="${esc(src)}" alt="" loading="lazy" decoding="async" width="44" height="44" />` : `<span aria-hidden="true">${esc(initials(person.name))}</span>`}</span>`;
}

// Where the sources come from, as counts: a fact, not a judgement on the news.
export function sourceCoverage(fonti = []) {
  const count = { centrosinistra: 0, centro: 0, centrodestra: 0 };
  for (const source of fonti) {
    if (source.area === "centrosinistra") count.centrosinistra += 1;
    else if (source.area === "centrodestra") count.centrodestra += 1;
    else count.centro += 1;
  }
  return count.centrosinistra + count.centro + count.centrodestra ? count : null;
}

function coverageBar(coverage) {
  if (!coverage) return "";
  const total = coverage.centrosinistra + coverage.centro + coverage.centrodestra;
  const parts = [
    ["centrosinistra", "Centrosinistra", coverage.centrosinistra],
    ["centro", "Istituzionali e agenzie", coverage.centro],
    ["centrodestra", "Centrodestra", coverage.centrodestra],
  ];
  const label = parts.map(([, name, n]) => `${n} ${name.toLowerCase()}`).join(", ");
  return `<div class="vp-coverage" role="img" aria-label="Fonti: ${esc(label)}">
      <div class="vp-coverage-bar">${parts.filter(([, , n]) => n).map(([key, , n]) => `<span class="cov-${key}" style="flex-grow:${n}"></span>`).join("")}</div>
      <p class="vp-coverage-legend">${parts.map(([key, name, n]) => `<span class="cov-${key}">${n} ${esc(name)}</span>`).join("")}<span class="vp-coverage-total">${total} fonti</span></p>
    </div>`;
}

/**
 * item: { key, url, title, summary, occurred_on, place, sources: [{title,url}], card }
 * options: { resolvePortrait(id) -> url, saved: bool, preview: bool }
 */
export function renderFeedCard(item, options = {}) {
  const card = item.card || {};
  const key = String(item.key || item.url || "card").replace(/[^a-z0-9_-]/gi, "-");
  const tone = card.tone || "navy";
  const badge = card.badge || { label: "Dalla redazione", tone: "plain" };
  const badgeDate = badge.date || item.occurred_on;
  const people = card.people || [];
  // Parties already shown under a person are not repeated.
  const shownParties = new Set(people.map((person) => person.party_id).filter(Boolean));
  const extraParties = (card.parties || []).filter((party) => !shownParties.has(party.id));
  const partyById = new Map((card.parties || []).map((party) => [party.id, party]));
  const sources = (item.sources || []).map((source) => {
    const url = safeUrl(source.url);
    return url ? `<li><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(source.title || source.name || new URL(url).hostname)} ${cardIcon("external", 13)}</a></li>` : "";
  }).filter(Boolean);
  const summary = item.summary || "";
  const long = summary.length > 260;
  const iterData = card.iter;
  const link = card.link && safeUrl(card.link.url);
  const href = options.preview ? "#" : item.url;
  const question = `Spiegami: ${item.title}`;
  return `<article class="vp-card tone-${esc(tone)}" data-card="${esc(key)}">
    <header class="vp-band">${cardIcon(CATEGORY_ICON[card.category] || "news", 16)}<span>${esc(card.category_label || "Notizia")}</span></header>
    <div class="vp-sub">
      <span class="vp-badge badge-${esc(badge.tone || "plain")}">${esc(badge.label)}${badgeDate ? ` · ${esc(shortDate(badgeDate))}` : ""}</span>
      ${card.aside ? `<span class="vp-aside">${esc(card.aside)}</span>` : item.place ? `<span class="vp-aside">${esc(item.place)}</span>` : ""}
    </div>
    <div class="vp-body">
      ${people.length ? `<ul class="vp-people">${people.map((person) => `<li>${avatar(person, options.resolvePortrait)}<span class="vp-person-text">${person.politician_id && !options.preview ? `<a href="./?politician=${encodeURIComponent(person.politician_id)}">${esc(person.name)}</a>` : `<strong>${esc(person.name)}</strong>`}${person.role ? `<small>${partyLogo(partyById.get(person.party_id))}${esc(person.role)}</small>` : ""}</span></li>`).join("")}</ul>` : ""}
      ${extraParties.length ? `<ul class="vp-parties" aria-label="Partiti coinvolti"><li class="vp-parties-label" aria-hidden="true">Anche</li>${extraParties.map((party) => `<li title="${esc(party.name)}">${partyLogo(party)}${esc(party.abbreviation || party.name)}</li>`).join("")}</ul>` : ""}
      ${card.institution ? `<p class="vp-institution">${esc(card.institution)}</p>` : ""}
      <h3 class="vp-title"><a href="${esc(href)}">${esc(item.title)}</a></h3>
      ${summary ? `<p class="vp-summary${long ? " is-clamped" : ""}" id="sum-${esc(key)}">${esc(summary)}</p>${long ? `<button type="button" class="vp-more" data-card-more="sum-${esc(key)}" aria-expanded="false">Mostra altro</button>` : ""}` : ""}
      <div class="vp-pills">
        <a class="vp-pill is-primary" href="${esc(href)}">${cardIcon("info", 15)}Info</a>
        ${sources.length ? `<button type="button" class="vp-pill" data-card-sources="src-${esc(key)}" aria-expanded="false">${cardIcon("sources", 15)}Fonti <span class="vp-count">${sources.length}</span></button>` : ""}
        <a class="vp-pill" href="${options.preview ? "#" : `./?view=ask&amp;prefill=${encodeURIComponent(question)}`}">${cardIcon("question", 15)}Chiedi</a>
      </div>
      ${sources.length ? `<ul class="vp-sources" id="src-${esc(key)}" hidden>${sources.join("")}</ul>` : ""}
      ${coverageBar(item.coverage)}
      ${iterData?.steps ? `<ol class="vp-iter" aria-label="Iter" style="--vp-progress:${Math.max(0, iterData.steps.findIndex((step) => step.state !== "done") === -1 ? 1 : iterData.steps.findIndex((step) => step.state !== "done") / (iterData.steps.length - 1))}">${iterData.steps.map((step, index) => `<li class="vp-step is-${esc(step.state)}"><span class="vp-step-dot">${cardIcon(STEP_ICON[index], 14)}</span><span class="vp-step-name">${esc(step.label)}</span><span class="vp-hidden"> (${esc({ done: "completato", current: "fase attuale", stopped: "fermo", todo: "da fare" }[step.state] || step.state)})</span></li>`).join("")}</ol>
        ${iterData.status ? `<p class="vp-stage">${esc(iterData.status)}</p>` : ""}
        ${iterData.since ? `<p class="vp-since">${esc(iterData.since_label || "Presentato il")} ${esc(longDate(iterData.since))}</p>` : ""}` : ""}
    </div>
    <footer class="vp-foot">
      ${link ? `<a class="vp-outline" href="${esc(link)}" target="_blank" rel="noopener noreferrer">${esc(card.link.label)} ${cardIcon("external", 14)}</a>` : ""}
      <span class="vp-foot-spacer"></span>
      <button type="button" class="vp-icon-button" data-card-save="${esc(item.url)}" data-card-title="${esc(item.title)}" aria-pressed="${options.saved ? "true" : "false"}" aria-label="${options.saved ? "Rimuovi dai salvati" : "Salva"}">${cardIcon("bookmark", 20, options.saved)}</button>
      <button type="button" class="vp-icon-button" data-card-share="${esc(item.url)}" data-card-title="${esc(item.title)}" aria-label="Condividi">${cardIcon("share", 20)}</button>
    </footer>
  </article>`;
}

/** One delegated listener per container: "Mostra altro", "Fonti", share. */
export function bindFeedCards(container, { onSave } = {}) {
  if (!container || container.dataset.cardsBound) return;
  container.dataset.cardsBound = "1";
  container.addEventListener("click", async (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const more = target.closest("[data-card-more]");
    if (more) {
      const text = document.getElementById(more.dataset.cardMore);
      const open = more.getAttribute("aria-expanded") !== "true";
      text?.classList.toggle("is-clamped", !open);
      more.setAttribute("aria-expanded", String(open));
      more.textContent = open ? "Mostra meno" : "Mostra altro";
      return;
    }
    const toggle = target.closest("[data-card-sources]");
    if (toggle) {
      const list = document.getElementById(toggle.dataset.cardSources);
      const open = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", String(open));
      if (list) list.hidden = !open;
      return;
    }
    const save = target.closest("[data-card-save]");
    if (save && onSave) {
      const saved = onSave(save.dataset.cardSave, save.dataset.cardTitle);
      save.setAttribute("aria-pressed", String(saved));
      save.setAttribute("aria-label", saved ? "Rimuovi dai salvati" : "Salva");
      save.innerHTML = cardIcon("bookmark", 20, saved);
      return;
    }
    const share = target.closest("[data-card-share]");
    if (share) {
      const url = new URL(share.dataset.cardShare, window.location.href).href;
      try {
        if (navigator.share) await navigator.share({ title: share.dataset.cardTitle, url });
        else {
          await navigator.clipboard.writeText(url);
          share.setAttribute("aria-label", "Link copiato");
          share.classList.add("is-done");
        }
      } catch { /* cancelled */ }
    }
  });
}

// Approved party logo (served by VeraPolitica at /media/{id}); nothing otherwise.
export function partyLogo(party, size = 16) {
  const url = party?.logo_url;
  if (typeof url !== "string" || !/^\/media\/\d+$/.test(url)) return "";
  return `<img class="vp-logo" src="${esc(url)}" alt="" width="${size}" height="${size}" loading="lazy" />`;
}
