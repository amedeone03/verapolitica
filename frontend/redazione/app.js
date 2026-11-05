// VeraPolitica — Redazione console.
// One ES module, no build. Every write goes to /redazione/api and is logged;
// nothing reaches the citizen until another member approves it.

import { bindFeedCards, partyLogo, renderFeedCard, sourceCoverage } from "/app/feed-card.js";

const API = "/redazione/api";
const TOKEN_KEY = "vp-redazione-token";
const view = document.getElementById("view");
const toastBox = document.getElementById("toast");

const state = { token: null, me: null, rules: null };

// ------------------------------------------------------------------ helpers
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const words = (text) => (String(text || "").match(/[\p{L}\p{N}]+/gu) || []).length;
const MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
function longDate(value) {
  if (!value) return "";
  const [y, m, d] = String(value).slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return esc(value);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}
function dateTime(value) {
  if (!value) return "";
  const when = new Date(value);
  if (Number.isNaN(when.getTime())) return esc(value);
  return `${longDate(value)}, ${String(when.getHours()).padStart(2, "0")}:${String(when.getMinutes()).padStart(2, "0")}`;
}
function safeUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch { return null; }
}
function sourceLink(source) {
  const url = safeUrl(source?.url);
  const name = esc(source?.name || source?.title || (url ? new URL(url).hostname : "Fonte"));
  return url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${name}</a>` : name;
}

function toast(message, error = false) {
  toastBox.textContent = message;
  toastBox.classList.toggle("is-error", error);
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { toastBox.textContent = ""; }, error ? 7000 : 4000);
}

function readToken() {
  try { return sessionStorage.getItem(TOKEN_KEY); } catch { return state.token; }
}
function writeToken(value) {
  state.token = value;
  try { value ? sessionStorage.setItem(TOKEN_KEY, value) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* memory only */ }
}

// Each navigation gets a ticket: a slow GET from a previous view must not
// overwrite the view the editor has since opened.
let routeTicket = 0;
class StaleRoute extends Error {}

async function api(path, { method = "GET", body } = {}) {
  const ticket = routeTicket;
  const headers = { Accept: "application/json" };
  const token = state.token || readToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`${API}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (method === "GET" && ticket !== routeTicket && !path.startsWith("/me") && !path.startsWith("/regole") && !path.startsWith("/panoramica")) throw new StaleRoute();
  if (!response.ok) {
    const error = new Error(typeof data?.detail === "string" ? data.detail : "Operazione non riuscita.");
    error.status = response.status;
    error.findings = data?.findings || [];
    throw error;
  }
  return data;
}

function findingsList(findings) {
  if (!findings?.length) return `<ul class="findings"><li class="ok">Nessun problema rilevato dai controlli automatici.</li></ul>`;
  return `<ul class="findings">${findings.map((f) => `<li class="${f.level === "error" ? "error" : "warning"}">${esc(f.message)}</li>`).join("")}</ul>`;
}

function verdictChip(verdict, label) {
  return `<span class="verdict verdict-${esc(verdict)}">${esc(label)}</span>`;
}
const VERDICTS = [
  ["in_progress", "In corso"],
  ["kept", "Mantenuta"],
  ["partially_kept", "Parzialmente mantenuta"],
  ["stalled", "Iter bloccato"],
  ["broken", "Non mantenuta"],
];
const ROLES = [
  ["government_coalition", "Governo di coalizione"],
  ["government_single_party", "Governo monocolore"],
  ["opposition", "Opposizione"],
  ["unknown", "Non definito"],
];
const SOURCE_AREAS = [
  ["istituzionale", "Istituzionale"],
  ["agenzia", "Agenzia"],
  ["centrodestra", "Stampa centrodestra"],
  ["centrosinistra", "Stampa centrosinistra"],
  ["tecnica", "Tecnica (ISTAT, Banca d'Italia…)"],
  ["altro", "Altro"],
];
const PROCEEDING_TYPES = [
  ["judicial_proceeding", "Procedimento giudiziario"],
  ["investigation", "Indagine"],
  ["political_controversy", "Controversia politica"],
  ["legal_controversy", "Controversia legale"],
  ["media_controversy", "Controversia mediatica"],
];
const OUTCOMES = [["", "—"], ["ongoing", "In corso"], ["archived", "Archiviato"], ["dismissed", "Prosciolto / assolto"], ["unknown", "Non noto"]];
const options = (pairs, selected) => pairs.map(([value, label]) => `<option value="${esc(value)}"${value === selected ? " selected" : ""}>${esc(label)}</option>`).join("");

// Final checklist of the "Modelli di scrittura" (page 13).
const CHECKLIST = [
  "Fonti: ogni fatto e ogni cifra ha una fonte con data; i dati elettorali vengono da Eligendo.",
  "Varietà: almeno una fonte istituzionale o di agenzia, una di centrodestra e una di centrosinistra (per le notizie).",
  "Attribuzione: ogni opinione ha nome, ruolo e partito; nessun «si dice».",
  "Equilibrio: destra e sinistra hanno lo stesso numero di punti, la stessa lunghezza e lo stesso tono; chi non si è espresso è indicato come tale.",
  "Linguaggio: frasi corte, termini tecnici spiegati, nessun aggettivo di parte, titolo neutro.",
  "Parentesi quadre: nessuna rimasta aperta nel testo.",
  "Verifica: ho controllato fatti, fonti ed equilibrio sulla fonte originale.",
];

// ------------------------------------------------------------- sources editor
function sourcesEditor(name, sources = [], { area = true } = {}) {
  const rows = (sources.length ? sources : [{}]).map((source) => sourceRow(source, area)).join("");
  return `<div class="field"><span class="label">Fonti <span class="hint">Il link alla pagina precisa che riporta il fatto (non la home del sito). Fonti del diretto interessato: solo come fonte da citare.</span></span>
    <div class="sources-editor" data-sources="${esc(name)}">${rows}</div>
    <button type="button" class="button-link" data-add-source="${esc(name)}" data-area="${area ? 1 : 0}">+ Aggiungi fonte</button></div>`;
}
function sourceRow(source = {}, area = true) {
  return `<div class="source-row">
    <input type="text" aria-label="Nome della fonte" placeholder="Nome (es. ANSA, camera.it)" data-src="name" value="${esc(source.name || "")}" />
    <input type="url" aria-label="Link alla fonte" placeholder="https://…" data-src="url" value="${esc(source.url || "")}" />
    ${area ? `<select aria-label="Tipo di fonte" data-src="area">${options(SOURCE_AREAS, source.area || areaFromKind(source.kind))}</select>` : `<input type="date" aria-label="Data" data-src="date" value="${esc(source.date || "")}" />`}
    <button type="button" class="button-link" data-remove-source>Rimuovi</button>
  </div>`;
}
function areaFromKind(kind) {
  return { official: "istituzionale", institutional: "istituzionale", news: "agenzia", party_politician: "altro", other: "altro" }[kind] || "istituzionale";
}
function readSources(form, name) {
  const box = form.querySelector(`[data-sources="${name}"]`);
  if (!box) return [];
  return [...box.querySelectorAll(".source-row")].map((row) => {
    const get = (key) => row.querySelector(`[data-src="${key}"]`)?.value.trim() || "";
    return { name: get("name"), url: get("url"), area: get("area") || undefined, date: get("date") || undefined };
  }).filter((item) => item.name || item.url);
}
document.addEventListener("click", (event) => {
  const add = event.target.closest("[data-add-source]");
  if (add) {
    const box = add.parentElement.querySelector(`[data-sources="${add.dataset.addSource}"]`);
    box.insertAdjacentHTML("beforeend", sourceRow({}, add.dataset.area === "1"));
    box.lastElementChild.querySelector("input").focus();
  }
  const remove = event.target.closest("[data-remove-source]");
  if (remove) {
    const box = remove.closest(".sources-editor");
    if (box.children.length > 1) remove.closest(".source-row").remove();
    else remove.closest(".source-row").querySelectorAll("input").forEach((input) => { input.value = ""; });
  }
});

// Live word counters: <textarea data-count="50-80">
document.addEventListener("input", (event) => {
  const field = event.target.closest("[data-count]");
  if (!field) return;
  updateCounter(field);
});
function updateCounter(field) {
  const [min, max] = field.dataset.count.split("-").map(Number);
  const counter = field.parentElement.querySelector(".counter");
  if (!counter) return;
  const count = words(field.value);
  counter.textContent = `${count} parole · indicazione ${min}–${max}`;
  counter.className = `counter ${count === 0 ? "" : count >= min && count <= max ? "in-range" : "out-range"}`;
}
const counted = (min, max) => `data-count="${min}-${max}"`;

// --------------------------------------------------------------------- shell
function setSection(section) {
  document.querySelectorAll("[data-section]").forEach((link) => {
    if (link.dataset.section === section) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

async function refreshCount() {
  try {
    const overview = await api("/panoramica");
    const badge = document.getElementById("queue-count");
    badge.textContent = overview.to_verify;
    badge.hidden = !overview.to_verify;
    const identities = document.getElementById("identity-count");
    if (identities) {
      identities.textContent = overview.pending_identities || "";
      identities.hidden = !overview.pending_identities;
    }
  } catch { /* ignore */ }
}

async function route() {
  if (!state.me) return;
  routeTicket += 1;
  const [, section = "coda", id, extra] = location.hash.replace(/^#/, "").split("/");
  setSection(section);
  view.innerHTML = `<p class="muted">Caricamento…</p>`;
  try {
    if (section === "politici" && id) await showScheda(Number(id), extra);
    else if (section === "politici") await showPoliticians();
    else if (section === "notizie" && id) await showNewsEditor(id === "nuova" ? null : Number(id));
    else if (section === "notizie") await showNews();
    else if (section === "registro") await showLog();
    else if (section === "simboli") await showSymbols(id || "party");
    else if (section === "regole") showRules();
    else if (section === "identita" && id) await showIdentity(Number(id));
    else if (section === "identita") await showIdentities();
    else await showQueue();
  } catch (error) {
    if (error instanceof StaleRoute) return;
    if (error.status === 401) return signOut();
    view.innerHTML = `<div class="empty">${esc(error.message)}</div>`;
  }
  refreshCount();
}

// --------------------------------------------------------------------- login
async function showLogin(message) {
  document.getElementById("console-nav").hidden = true;
  document.getElementById("console-user").hidden = true;
  let access = { configured: true, demo_members: [] };
  try { access = await api("/accesso"); } catch { /* keep defaults */ }
  view.innerHTML = `<section class="login"><div class="card">
    <p class="eyebrow">Area riservata</p>
    <h1>Accesso redazione</h1>
    <p class="muted">Ogni persona della redazione entra con il proprio codice: il registro sa chi ha scritto e chi ha verificato.</p>
    ${message ? `<ul class="findings"><li class="error">${esc(message)}</li></ul>` : ""}
    ${access.configured ? `<form id="login-form" class="stack" style="margin-top:16px">
      <div class="field"><label for="token">Codice di accesso</label><input id="token" type="password" autocomplete="current-password" required /></div>
      <button class="button button-primary" type="submit">Entra</button>
    </form>` : `<p>La redazione non è configurata su questo server (VERAPOLITICA_REDAZIONE_MEMBERS).</p>`}
    ${access.demo_members.length ? `<div class="demo-members"><p class="small muted" style="margin-top:16px">Demo locale: entra come</p>
      ${access.demo_members.map((m) => `<button type="button" class="button button-secondary" data-demo-token="${esc(m.token)}">${esc(m.name)}</button>`).join("")}</div>` : ""}
  </div></section>`;
  view.querySelector("#login-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    signIn(view.querySelector("#token").value.trim());
  });
  view.querySelectorAll("[data-demo-token]").forEach((button) => button.addEventListener("click", () => signIn(button.dataset.demoToken)));
}

async function signIn(token) {
  writeToken(token);
  try {
    state.me = await api("/me");
    state.rules = await api("/regole");
  } catch (error) {
    writeToken(null);
    state.me = null;
    return showLogin(error.status === 401 ? "Codice non valido." : error.message);
  }
  document.getElementById("member-name").textContent = state.me.name;
  document.getElementById("console-nav").hidden = false;
  document.getElementById("console-user").hidden = false;
  if (!location.hash) location.hash = "#/coda";
  route();
}

function signOut() {
  writeToken(null);
  state.me = null;
  showLogin();
}
document.getElementById("sign-out").addEventListener("click", signOut);
window.addEventListener("hashchange", route);

// --------------------------------------------------------------------- queue
let queueFilter = "all";
async function showQueue() {
  const items = await api("/coda");
  const toVerify = items.filter((item) => item.can_approve);
  const mine = items.filter((item) => item.own);
  const blocked = items.filter((item) => item.blocked);
  const kinds = [...new Map(items.map((item) => [item.kind, item.kind_label])).entries()];
  const shown = items.filter((item) => queueFilter === "all" || (queueFilter === "verify" ? item.can_approve : queueFilter === "mine" ? item.own : item.kind === queueFilter));
  view.innerHTML = `<div class="page-head"><div><p class="eyebrow">Ciclo di lavoro</p><h1>Da verificare</h1>
    <p>Scrive il redattore, verifica un'altra persona, poi si pubblica. Nulla di quello che vedi qui è visibile al cittadino finché non viene approvato. Se manca una fonte, il contenuto resta in attesa. Una notizia in bozza si può eliminare: non è ancora pubblica. Una notizia già pubblicata non si cancella.</p></div></div>
    <div class="summary-strip">
      <div class="tile"><strong>${toVerify.length}</strong><span>da verificare da te</span></div>
      <div class="tile"><strong>${mine.length}</strong><span>scritti da te, in attesa di un'altra persona</span></div>
      <div class="tile"><strong>${blocked.length}</strong><span>bloccati da errori da correggere</span></div>
      <div class="tile"><strong>${items.length}</strong><span>in attesa in totale</span></div>
    </div>
    <div class="filters" role="group" aria-label="Filtra">
      ${[["all", "Tutti"], ["verify", "Da verificare da me"], ["mine", "Scritti da me"], ...kinds].map(([key, label]) => `<button type="button" data-filter="${esc(key)}" aria-pressed="${queueFilter === key}">${esc(label)}</button>`).join("")}
    </div>
    <div id="queue-list">${shown.length ? shown.map(queueCard).join("") : `<div class="empty">Niente in attesa${queueFilter === "all" ? "" : " con questo filtro"}.</div>`}</div>`;
  view.querySelectorAll("[data-filter]").forEach((button) => button.addEventListener("click", () => { queueFilter = button.dataset.filter; showQueue(); }));
  bindQueueActions(view, showQueue);
}

function queueCard(item) {
  const approvals = item.approvals_required > 1 ? `<span class="chip chip-pending">${item.approvals.length} di ${item.approvals_required} approvazioni</span>` : "";
  const politician = item.politician_id ? `<a href="#/politici/${item.politician_id}">${esc(item.politician_name || "Politico")}</a>` : "";
  const needsClassification = item.kind === "promise" && !item.preview?.classification;
  return `<article class="card queue-card" data-kind="${esc(item.kind)}" data-id="${item.id}">
    <div class="card-head"><div>
      <div class="item-meta"><span class="chip chip-kind">${esc(item.kind_label)}</span>${politician}<span>Scritto da <strong>${esc(item.author)}</strong></span><span>${dateTime(item.created_at)}</span>${approvals}</div>
      <h3>${esc(item.title)}</h3></div></div>
    ${previewFor(item)}
    ${findingsList(item.findings)}
    ${item.own ? `<p class="own-note">Scritto da te: lo verifica un'altra persona della redazione.</p>` : item.can_approve ? `
      <form class="decision" data-kind="${esc(item.kind)}" data-id="${item.id}">
        ${needsClassification ? classificationFields("approve", {}) : ""}
        <ul class="checklist">${CHECKLIST.map((text, index) => `<li><label class="check"><input type="checkbox" data-check="${index}" />${esc(text)}</label></li>`).join("")}</ul>
        <div class="field" style="margin-top:12px"><label for="note-${item.kind}-${item.id}">Nota per chi ha scritto</label><textarea id="note-${item.kind}-${item.id}" name="note" rows="2" placeholder="Obbligatoria se respingi: cosa va corretto."></textarea></div>
        <div class="actions">
          <button type="submit" class="button button-approve" data-action="approva" disabled>Approva e pubblica</button>
          <button type="button" class="button button-danger" data-action="rifiuta">Respingi</button>
          <span class="small muted" data-checklist-hint>Spunta la checklist per approvare.</span>
        </div>
      </form>` : item.blocked ? `<p class="own-note">Bloccato: va corretto da chi scrive prima della verifica.</p>` : `<p class="own-note">Hai già dato la tua approvazione: serve un'altra persona.</p>`}
    ${item.can_discard ? `<div class="actions"><button type="button" class="button button-danger" data-discard="${item.id}" data-title="${esc(item.title)}">Elimina la notizia</button><span class="small muted">Toglie la bozza dalla coda. Non arriva al cittadino.</span></div>` : ""}
  </article>`;
}

function previewFor(item) {
  const p = item.preview || {};
  if (item.kind === "biography") return `<div class="preview"><p class="item-body">${esc(p.body)}</p>${sourcesList(p.sources)}</div>`;
  if (item.kind === "career_entry") return `<div class="preview"><dl><dt>Incarico</dt><dd>${esc(p.role)} — ${esc(p.institution)}</dd><dt>Periodo</dt><dd>${longDate(p.start_date)} – ${p.is_current ? "in corso" : longDate(p.end_date) || "—"}</dd>${p.party_or_group ? `<dt>Partito o gruppo</dt><dd>${esc(p.party_or_group)}</dd>` : ""}</dl>${sourcesList(p.sources)}</div>`;
  if (item.kind === "position") return `<div class="preview"><dl><dt>Tema</dt><dd>${esc(p.topic)}</dd><dt>Posizione</dt><dd>${esc(p.position_statement)}</dd><dt>Dichiarazione o voto</dt><dd>${esc(p.verifiable_statement)}</dd><dt>Data</dt><dd>${longDate(p.statement_date) || "—"}</dd></dl>${sourcesList(p.sources)}</div>`;
  if (item.kind === "proceeding") return `<div class="preview"><dl><dt>Vicenda</dt><dd>${esc(p.title)}</dd><dt>Data</dt><dd>${longDate(p.event_date) || "—"}</dd><dt>Sintesi</dt><dd>${esc(p.summary)}</dd>${p.outcome_summary ? `<dt>Esito</dt><dd>${esc(p.outcome_summary)}</dd>` : ""}</dl>${sourcesList(p.sources)}</div>`;
  if (item.kind === "promise" || item.kind === "proposal") {
    const classification = p.classification ? `<dt>Classificazione</dt><dd>${esc(classificationText(p.classification))}</dd>` : "";
    const suggestion = p.suggested_verdict ? `<dt>Stato indicato nella scheda</dt><dd>${esc(p.suggested_verdict)} (si assegna dopo, con fonte)</dd>` : "";
    return `<div class="preview"><dl>${item.kind === "promise" ? `<dt>Dichiarazione</dt><dd>«${esc(p.exact_statement)}»</dd>` : p.summary ? `<dt>Sintesi</dt><dd>${esc(p.summary)}</dd>` : ""}<dt>Quando e dove</dt><dd>${longDate(p.introduced_at)}${p.where ? ` · ${esc(p.where)}` : ""}</dd><dt>Fonte</dt><dd>${sourceLink(p.source)}</dd>${classification}${suggestion}</dl></div>`;
  }
  if (item.kind === "status") return `<div class="preview"><dl><dt>Stato proposto</dt><dd>${verdictChip(p.verdict, p.verdict_label)}</dd><dt>Aggiornamento</dt><dd>${esc(p.rationale)}</dd><dt>Data del fatto</dt><dd>${longDate(p.effective_at) || "—"}</dd><dt>Passaggio della fonte</dt><dd>«${esc(p.quoted_excerpt)}»</dd><dt>Fonte</dt><dd>${sourceLink({ url: p.source_url })}</dd>${p.approvals?.length ? `<dt>Già approvato da</dt><dd>${esc(p.approvals.join(", "))}</dd>` : ""}</dl></div>`;
  if (item.kind === "news") return `${p.card ? `<div class="queue-card-preview"><p class="small muted">Come appare nel feed</p>${renderFeedCard({ key: `q-${item.id}`, url: "#", title: p.title || item.title, summary: p.blocks?.sommario, occurred_on: new Date().toISOString().slice(0, 10), sources: (p.sources || []).map((src) => ({ title: src.name, url: src.url })), card: { ...p.card, composed: true } }, { preview: true, resolvePortrait: (id) => state.portraits?.[String(id)]?.url || null })}</div>` : ""}<div class="preview news-preview">${newsPreview(p.blocks)}<p class="small muted" style="margin-top:8px">${p.words} parole · indicazione 450–700</p>${sourcesList(p.sources, true)}</div>`;
  if (item.kind === "change" && p.kind === "simbolo") return `<div class="preview symbol-preview"><img src="${esc(p.payload.image_url)}" alt="" width="96" height="96" /><div><p><strong>${esc(p.payload.name)}</strong></p><p class="small">${esc(p.payload.credit)} · ${esc(p.payload.license_label)}<br />Fonte: ${sourceLink({ url: p.payload.source_url })}</p></div></div>`;
  if (item.kind === "change" && p.kind === "partito_modifica") return `<div class="preview"><dl>${["name", "abbreviation", "website"].filter((k) => p.payload.before[k] !== p.payload.after[k]).map((k) => `<dt>${{ name: "Nome", abbreviation: "Sigla", website: "Sito" }[k]}</dt><dd><s>${esc(p.payload.before[k] || "—")}</s> → <strong>${esc(p.payload.after[k] || "—")}</strong></dd>`).join("")}${p.payload.remove_logo ? "<dt>Logo</dt><dd>rimosso</dd>" : ""}<dt>Motivo</dt><dd>${esc(p.payload.reason)}</dd></dl></div>`;
  if (item.kind === "change" && p.kind === "partito") return `<div class="preview"><p><strong>${esc(p.payload.name)}</strong>${p.payload.abbreviation ? ` (${esc(p.payload.abbreviation)})` : ""}</p><p class="small">${p.payload.website ? `Sito: ${sourceLink({ url: p.payload.website })}<br />` : ""}Fonte: ${sourceLink({ url: p.payload.source_url })}</p></div>`;
  if (item.kind === "change" && p.kind === "politico") return `<div class="preview"><dl><dt>Persona</dt><dd>${esc(p.payload.given_name)} ${esc(p.payload.family_name)}</dd>${p.payload.birth_date ? `<dt>Nascita</dt><dd>${longDate(p.payload.birth_date)}</dd>` : ""}${p.payload.office_label ? `<dt>Incarico</dt><dd>${esc(p.payload.office_label)}${p.payload.start_date ? ` dal ${longDate(p.payload.start_date)}` : ""}</dd>` : ""}<dt>Fonte</dt><dd>${sourceLink({ url: p.payload.source_url })}</dd></dl></div>`;
  if (item.kind === "change") return `<div class="preview"><p>${esc(p.summary)}</p>${p.payload?.classification ? `<p class="small"><strong>Nuova classificazione:</strong> ${esc(classificationText(p.payload.classification))}${p.payload.before ? `<br /><strong>Prima:</strong> ${esc(classificationText(p.payload.before))}` : ""}</p>` : ""}</div>`;
  return "";
}

function sourcesList(sources, withArea = false) {
  if (!sources?.length) return `<p class="small muted" style="margin-top:6px">Nessuna fonte.</p>`;
  const areas = Object.fromEntries(SOURCE_AREAS);
  return `<ul class="item-sources">${sources.map((s) => `<li>Fonte: ${sourceLink(s)}${withArea && s.area ? ` <span class="chip chip-muted">${esc(areas[s.area] || s.area)}</span>` : ""}${s.date ? ` · ${longDate(s.date)}` : ""}</li>`).join("")}</ul>`;
}

function newsPreview(blocks = {}) {
  const sections = [["sommario", "Sommario"], ...((state.rules?.news_blocks || []).map((b) => [b.key, b.label]))];
  return sections.filter(([key]) => blocks[key]).map(([key, label]) => `<section><h4>${esc(label)}</h4><p class="item-body">${esc(blocks[key])}${key === "fatto" && blocks.perche_deciso ? `\n\nPerché è stato deciso: ${esc(blocks.perche_deciso)}` : ""}</p></section>`).join("");
}

function bindQueueActions(root, reload) {
  root.querySelectorAll("form.decision").forEach((form) => {
    const approve = form.querySelector('[data-action="approva"]');
    const hint = form.querySelector("[data-checklist-hint]");
    const sync = () => {
      const all = [...form.querySelectorAll("[data-check]")].every((box) => box.checked);
      approve.disabled = !all;
      hint.hidden = all;
    };
    form.addEventListener("change", sync);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      approve.disabled = true;
      const body = { note: form.note.value };
      if (form.querySelector("[data-classification]")) body.classification = readClassification(form, "approve");
      try {
        const result = await api(`/coda/${form.dataset.kind}/${form.dataset.id}/approva`, { method: "POST", body });
        toast(result.summary);
        reload();
        refreshCount();
      } catch (error) { toast(error.message, true); sync(); }
    });
    form.querySelector('[data-action="rifiuta"]').addEventListener("click", async () => {
      if (!form.note.value.trim()) { form.note.focus(); return toast("Scrivi nella nota cosa va corretto.", true); }
      try {
        const result = await api(`/coda/${form.dataset.kind}/${form.dataset.id}/rifiuta`, { method: "POST", body: { note: form.note.value } });
        toast(result.summary);
        reload();
        refreshCount();
      } catch (error) { toast(error.message, true); }
    });
  });
  bindDiscardButtons(root, reload);
}

async function discardNews(id, title) {
  if (!confirm(`Eliminare definitivamente «${title}»? Scompare dalla coda e non sarà visibile a nessuno.`)) return false;
  try {
    const result = await api(`/notizie/${id}`, { method: "DELETE" });
    toast(result.summary);
    refreshCount();
    return true;
  } catch (error) {
    toast(error.message, true);
    return false;
  }
}

function bindDiscardButtons(root, onDone) {
  root.querySelectorAll("[data-discard]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!await discardNews(button.dataset.discard, button.dataset.title)) return;
      onDone();
    });
  });
}

// ---------------------------------------------------------- identities
function identityStatusLabel(status) {
  return {
    pending: "In attesa",
    resolved_existing: "Collegata a una persona già in archivio",
    resolved_new: "Nuova identità",
    ignored: "Ignorata",
  }[status] || status;
}

async function showIdentities() {
  const payload = await api("/identita?status=pending&limit=100");
  const items = payload.items || [];
  view.innerHTML = `<div class="page-head"><div><p class="eyebrow">Coda quotidiana</p><h1>Identità da risolvere</h1>
    <p>governo.it e l'elenco DAIT dei sindaci spesso non hanno la data di nascita. Il bootstrap automatico non crea quelle persone. Qui una persona della redazione collega il nome all'archivio, crea una nuova identità o lascia il caso in attesa. Il nome di chi decide finisce nel registro.</p></div></div>
    <div class="summary-strip">
      <div class="tile"><strong>${payload.total || 0}</strong><span>casi in attesa</span></div>
    </div>
    ${items.length ? items.map((item) => `<article class="card">
      <div class="card-head"><div>
        <div class="item-meta"><span class="chip chip-kind">${esc(item.source?.name || item.source?.key || "Fonte")}</span>
          ${item.current_role ? `<span>${esc(item.current_role)}</span>` : ""}
          ${item.birth_date ? `<span>Nato il ${esc(item.birth_date)}</span>` : `<span>Data di nascita assente</span>`}
        </div>
        <h3><a href="#/identita/${item.id}">${esc(item.candidate_display_name)}</a></h3>
        ${item.official_source_url ? `<p class="small">Fonte: ${sourceLink({ url: item.official_source_url, name: item.source_identifier || item.official_source_url })}</p>` : ""}
      </div></div>
    </article>`).join("") : `<div class="empty">Nessun caso in attesa. Dopo un ingest Governo o DAIT i nomi senza data di nascita arrivano qui.</div>`}`;
}

async function showIdentity(caseId) {
  const item = await api(`/identita/${caseId}`);
  const matches = item.possible_matches || [];
  const pending = item.status === "pending";
  view.innerHTML = `<p class="small"><a href="#/identita">← Tutte le identità</a></p>
    <div class="page-head"><div>
      <p class="eyebrow">${esc(item.source?.name || "Fonte ufficiale")}</p>
      <h1>${esc(item.candidate_display_name)}</h1>
      <p class="muted">${esc(identityStatusLabel(item.status))}${item.birth_date ? ` · nato il ${esc(item.birth_date)}` : " · data di nascita assente sulla pagina ufficiale"}</p>
      ${item.official_source_url ? `<p>Pagina ufficiale: ${sourceLink({ url: item.official_source_url })}</p>` : ""}
    </div></div>
    <article class="card"><h2>Persone già in archivio con lo stesso nome</h2>
      ${matches.length ? `<ul class="plain-list">${matches.map((match) => `<li>
        <strong>${esc(match.politician.given_name)} ${esc(match.politician.family_name)}</strong>
        ${match.politician.birth_date ? ` · ${esc(match.politician.birth_date)}` : ""}
        ${match.signals?.length ? ` · ${esc(match.signals.join(", "))}` : ""}
        ${pending ? `<form class="stack identity-form" data-action="collega" data-id="${item.id}">
          <input type="hidden" name="politician_id" value="${match.politician.id}" />
          <div class="field"><label>Nota</label><textarea name="note" rows="2" placeholder="Perché è la stessa persona."></textarea></div>
          <button class="button button-approve" type="submit">Collega a questa scheda</button>
        </form>` : ""}
      </li>`).join("")}</ul>` : `<p class="muted">Nessun omonimo in archivio. Se il nome è unico sulla fonte, puoi creare una nuova identità.</p>`}
    </article>
    ${pending ? `<article class="card"><h2>Altre decisioni</h2>
      <form class="stack identity-form" data-action="nuova" data-id="${item.id}">
        <p class="small muted">Crea una persona nuova solo se non c'è già in archivio con un nome ufficiale diverso.</p>
        <div class="field"><label>Nota</label><textarea name="note" rows="2" required placeholder="Perché è una persona distinta."></textarea></div>
        <button class="button button-primary" type="submit">Crea una nuova identità</button>
      </form>
      <form class="stack identity-form" data-action="ignora" data-id="${item.id}" style="margin-top:16px">
        <div class="field"><label>Nota</label><textarea name="note" rows="2" required placeholder="Perché il caso resta chiuso senza identità."></textarea></div>
        <button class="button button-danger" type="submit">Ignora il caso</button>
      </form>
    </article>` : item.reviewer_identity ? `<p class="muted">Deciso da ${esc(item.reviewer_identity)}${item.resolution_note ? `: ${esc(item.resolution_note)}` : ""}.</p>` : ""}`;
  view.querySelectorAll("form.identity-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const action = form.dataset.action;
      const body = { note: form.note?.value || "" };
      if (form.politician_id) body.politician_id = Number(form.politician_id.value);
      try {
        const result = await api(`/identita/${form.dataset.id}/${action}`, { method: "POST", body });
        toast(`Identità: ${identityStatusLabel(result.status)}`);
        location.hash = "#/identita";
        refreshCount();
      } catch (error) { toast(error.message, true); }
    });
  });
}

// ---------------------------------------------------------- classification
function classificationText(c) {
  const roles = Object.fromEntries(ROLES);
  const spec = { high: "precisa", medium: "abbastanza precisa", vague: "generica (esclusa dal punteggio)" }[c.specificity] || c.specificity;
  const type = { action: "azione", outcome: "risultato" }[c.commitment_type] || c.commitment_type;
  const topic = c.cap_topic_code ? state.rules?.topics?.[c.cap_topic_code] || c.cap_topic_code : "tema non indicato";
  const mandate = c.mandate_start ? ` · mandato ${longDate(c.mandate_start)} – ${longDate(c.mandate_end) || "…"}` : "";
  return `${spec} · ${type} · ${roles[c.holder_role] || c.holder_role} · ${topic}${mandate}`;
}
function classificationFields(prefix, c = {}) {
  const topics = Object.entries(state.rules?.topics || {});
  return `<fieldset data-classification="${prefix}"><legend>Classificazione (decide se e come la promessa entra nel punteggio)</legend>
    <div class="field-row">
      <div class="field"><label for="${prefix}-spec">Precisione</label><select id="${prefix}-spec" data-c="specificity">${options([["high", "Precisa: si può dire se è mantenuta"], ["medium", "Abbastanza precisa"], ["vague", "Generica: non entra nel punteggio"]], c.specificity || "high")}</select></div>
      <div class="field"><label for="${prefix}-type">Tipo</label><select id="${prefix}-type" data-c="commitment_type">${options([["action", "Azione (legge, decreto, atto)"], ["outcome", "Risultato (dato misurabile)"]], c.commitment_type || "action")}</select></div>
      <div class="field"><label for="${prefix}-role">Ruolo quando l'ha promessa</label><select id="${prefix}-role" data-c="holder_role">${options(ROLES, c.holder_role || "unknown")}</select><span class="hint">Il punteggio si calcola separatamente per ruolo.</span></div>
    </div>
    <div class="field-row">
      <div class="field"><label for="${prefix}-topic">Tema</label><select id="${prefix}-topic" data-c="cap_topic_code"><option value="">—</option>${topics.map(([code, label]) => `<option value="${esc(code)}"${code === c.cap_topic_code ? " selected" : ""}>${esc(label)}</option>`).join("")}</select></div>
      <div class="field"><label for="${prefix}-ms">Inizio mandato</label><input id="${prefix}-ms" type="date" data-c="mandate_start" value="${esc(c.mandate_start || "")}" /></div>
      <div class="field"><label for="${prefix}-me">Fine mandato</label><input id="${prefix}-me" type="date" data-c="mandate_end" value="${esc(c.mandate_end || "")}" /></div>
    </div></fieldset>`;
}
function readClassification(form, prefix) {
  const box = form.querySelector(`[data-classification="${prefix}"]`);
  const result = {};
  box.querySelectorAll("[data-c]").forEach((input) => { if (input.value) result[input.dataset.c] = input.value; });
  return result;
}

// ---------------------------------------------------------------- politicians
async function showPoliticians(query = "") {
  const [list, queue] = await Promise.all([
    api(`/politici?q=${encodeURIComponent(query)}&limit=60`),
    api("/coda"),
  ]);
  const pending = queue.filter((item) => item.kind === "change" && item.preview?.kind === "politico");
  view.innerHTML = `<div class="page-head"><div><p class="eyebrow">Modello Politico</p><h1>Politici</h1>
    <p>La scheda di una persona con un ruolo pubblico. Si scrive solo da fonti pubbliche: il politico non scrive mai la propria scheda.</p></div></div>
    ${newPoliticianForm(pending)}
    <form id="politician-search" class="card" role="search" style="margin-bottom:16px"><label for="pq">Cerca per nome o cognome</label>
      <div class="actions" style="margin-top:4px"><input id="pq" type="search" value="${esc(query)}" style="flex:1 1 260px" /><button class="button button-primary" type="submit">Cerca</button></div></form>
    ${list.length ? `<div class="table-wrap card" style="padding:0"><table class="data-table"><thead><tr><th>Nome</th><th>Nascita</th><th>Profilo pubblico</th><th>In attesa</th></tr></thead><tbody>
      ${list.map((p) => `<tr><td><a href="#/politici/${p.id}"><strong>${esc(p.name)}</strong></a></td><td>${longDate(p.birth_date) || "—"}</td><td>${p.public ? `<span class="chip chip-published">Pubblico</span>` : `<span class="chip chip-muted">Non pubblicato</span>`}</td><td>${p.pending ? `<span class="chip chip-pending">${p.pending} in attesa</span>` : "—"}</td></tr>`).join("")}
    </tbody></table></div>` : `<div class="empty">Nessun politico in elenco. Aggiungine uno qui sopra, oppure carica l'archivio ufficiale (Camera, Senato, Governo) sul server.</div>`}`;
  view.querySelector("#politician-search").addEventListener("submit", (event) => {
    event.preventDefault();
    showPoliticians(view.querySelector("#pq").value);
  });
  view.querySelector("#politician-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      await api("/politici", { method: "POST", body: Object.fromEntries(new FormData(form)) });
      toast("Politico proposto: entra nell'elenco dopo l'approvazione di un'altra persona.");
      showPoliticians(query);
      refreshCount();
    } catch (error) {
      toast(error.findings?.map((f) => f.message).join(" ") || error.message, true);
    }
  });
  view.querySelectorAll("[data-review]").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const action = event.submitter?.value;
    const id = form.dataset.review;
    try {
      if (action === "approva") await api(`/coda/change/${id}/approva`, { method: "POST", body: {} });
      else await api(`/coda/change/${id}/rifiuta`, { method: "POST", body: { note: form.reason.value } });
      toast(action === "approva" ? "Approvato e pubblicato." : "Respinto.");
      showPoliticians(query);
      refreshCount();
    } catch (error) { toast(error.message, true); }
  }));
}

const GOVERNMENT_OFFICES = [
  ["", "Nessun incarico di Governo (solo scheda)"],
  ["presidente del consiglio", "Presidente del Consiglio"],
  ["vice presidente del consiglio", "Vicepresidente del Consiglio"],
  ["ministro", "Ministro"],
  ["ministro senza portafoglio", "Ministro senza portafoglio"],
  ["sottosegretario", "Sottosegretario"],
];

function newPoliticianForm(pending) {
  return `<details class="card new-party"><summary><strong>Aggiungi un politico</strong> <span class="muted small">— nome, fonte ufficiale, eventuale incarico di Governo</span></summary>
    <form id="politician-form" class="stack" style="margin-top:12px">
      <div class="grid-2">
        <div class="field"><label for="pol-given">Nome</label><input id="pol-given" name="given_name" type="text" required minlength="2" maxlength="200" /></div>
        <div class="field"><label for="pol-family">Cognome</label><input id="pol-family" name="family_name" type="text" required minlength="2" maxlength="200" /></div>
        <div class="field"><label for="pol-birth">Data di nascita <span class="hint">facoltativa, aiuta a non duplicare</span></label><input id="pol-birth" name="birth_date" type="date" /></div>
        <div class="field"><label for="pol-source">Fonte <span class="hint">scheda Camera, Senato, Governo o pagina ufficiale</span></label><input id="pol-source" name="source_url" type="url" required placeholder="https://" /></div>
        <div class="field"><label for="pol-office">Incarico di Governo</label><select id="pol-office" name="office">${GOVERNMENT_OFFICES.map(([value, label]) => `<option value="${esc(value)}">${esc(label)}</option>`).join("")}</select></div>
        <div class="field"><label for="pol-start">Inizio incarico</label><input id="pol-start" name="start_date" type="date" /><span class="hint">Obbligatorio solo se scegli un incarico di Governo.</span></div>
      </div>
      <div class="actions"><button class="button button-primary" type="submit">Proponi il politico</button></div>
    </form>
  </details>
  ${pending.length ? `<section class="card pending-parties"><h2>Politici proposti <span class="count">${pending.length}</span></h2>
    <p class="small muted">Il cittadino li vede solo dopo l'approvazione di un'altra persona.</p>
    <ul class="symbol-list">${pending.map((item) => `<li>
      <span class="symbol-thumb is-empty" aria-hidden="true">${esc(`${item.preview.payload.given_name} ${item.preview.payload.family_name}`.replace(/[^\p{L}\p{N}]/gu, "").slice(0, 2).toUpperCase())}</span>
      <div class="symbol-text"><strong>${esc(item.preview.payload.given_name)} ${esc(item.preview.payload.family_name)}</strong>
        <p class="small muted">Proposto da ${esc(item.author)} · fonte ${sourceLink({ url: item.preview.payload.source_url })}${item.preview.payload.office_label ? ` · ${esc(item.preview.payload.office_label)}` : ""}</p></div>
      ${reviewControls({ id: item.id, created_by: item.author })}
    </li>`).join("")}</ul></section>` : ""}`;
}

const BLOCK_GUIDE = {
  biography: { n: 1, title: "Chi è", what: "Formazione e percorso: 3–5 righe di fatti.", length: "50–80 parole", avoid: "Giudizi («brillante», «controverso»)." },
  career_entry: { n: 2, title: "Cosa ha fatto", what: "Elenco cronologico di incarichi e mandati, ognuno con data.", length: "Elenco", avoid: "Date mancanti o approssimate." },
  position: { n: 3, title: "Posizioni su temi chiave", what: "3–5 temi. Ogni posizione si basa su una dichiarazione o un voto verificabile, con data e fonte.", length: "3–5 righe", avoid: "Riassumere «l'ideologia» della persona." },
  promise: { n: 4, title: "Le promesse", what: "Tabella: promessa, quando e dove è stata fatta, stato, aggiornamento, fonte.", length: "Tabella", avoid: "Promesse senza data o senza fonte." },
  proceeding: { n: 5, title: "Procedimenti e controversie", what: "Solo se documentati. Linguaggio giudiziario preciso. Se non ce ne sono, si omette il blocco.", length: "Solo se serve", avoid: "Presentare un'indagine come colpa." },
  news: { n: 6, title: "Notizie collegate e fonti", what: "Link alle Notizie che riguardano la persona e fonti usate per la scheda.", length: "Elenco", avoid: "Fonti scritte dal diretto interessato come unica fonte." },
};
function guide(key) {
  const g = BLOCK_GUIDE[key];
  return `<div class="block-guide"><div><b>Cosa scrivere</b>${esc(g.what)}</div><div><b>Lunghezza</b>${esc(g.length)}</div><div class="avoid"><b>Da evitare</b>${esc(g.avoid)}</div></div>`;
}
function blockHead(key, extra = "") {
  const g = BLOCK_GUIDE[key];
  return `<div class="card-head"><h2><span class="block-number">${g.n}</span>${esc(g.title)}</h2>${extra}</div>${guide(key)}`;
}

async function showScheda(politicianId, focus) {
  const s = await api(`/politici/${politicianId}`);
  const q = s.scheda_rapida;
  view.innerHTML = `<div class="page-head"><div><p class="eyebrow"><a href="#/politici">Politici</a> · Modello Politico</p><h1>${esc(s.name)}</h1></div>
      <div class="actions">${s.public_url ? `<a class="button button-secondary" href="${esc(s.public_url)}" target="_blank" rel="noopener">Vedi come lo vede il cittadino</a>` : `<span class="chip chip-muted">Profilo non ancora pubblico</span>`}
      <a class="button button-secondary" href="#/registro" data-log-politician="${s.id}">Registro di questa scheda</a></div></div>
    <div class="layout-side"><div>
      <section class="card"><div class="card-head"><h2><span class="block-number">0</span>Scheda rapida</h2></div>
        <div class="block-guide"><div><b>Cosa scrivere</b>Nome, data e luogo di nascita, partito, incarico attuale e da quando, «Aggiornato al».</div><div><b>Lunghezza</b>Riquadro</div><div class="avoid"><b>Da evitare</b>Titoli onorifici o aggettivi.</div></div>
        <div class="preview" style="max-height:none"><dl><dt>Nascita</dt><dd>${q.birth_date ? `${longDate(q.birth_date)}${q.birth_place ? `, ${esc(q.birth_place)}` : ""}` : "Non indicata"}</dd><dt>Incarico attuale</dt><dd>${q.office ? `${esc(q.office)}${q.office_since ? ` dal ${longDate(q.office_since)}` : ""}` : "Non indicato"}</dd><dt>Partito</dt><dd>${esc(q.party || "Non indicato")}</dd></dl></div>
        <p class="small muted">Aggiornato al ${q.updated_at ? longDate(q.updated_at) : "—"} · Redattore ${esc(q.writers.join(", ") || "—")} · Verificatore ${esc(q.verifiers.join(", ") || "—")}</p>
        <p class="small muted">Questi dati arrivano dall'importazione ufficiale (Camera, Senato, Governo): non si scrivono a mano.</p>
      </section>
      ${profileBlock(s, "biography")}
      ${profileBlock(s, "career_entry")}
      ${profileBlock(s, "position")}
      ${promisesBlock(s)}
      ${profileBlock(s, "proceeding")}
      ${newsBlock(s)}
    </div>
    <aside class="card side-panel"><h3>Prima di pubblicare la scheda</h3>
      <ul class="findings">${s.checklist.map((c) => `<li class="${c.ok ? "ok" : "warning"}">${esc(c.label)}</li>`).join("")}</ul>
      ${s.changes.length ? `<h3 style="margin-top:16px">Modifiche in attesa</h3><ul class="item-sources">${s.changes.map((c) => `<li>${esc(c.summary)} — ${esc(c.created_by)}</li>`).join("")}</ul>` : ""}
      <p class="small muted" style="margin-top:12px">Ogni salvataggio crea una bozza: il cittadino la vede solo dopo l'approvazione di un'altra persona. Tutte le modifiche finiscono nel registro.</p>
    </aside></div>`;
  bindScheda(s);
  if (focus) document.getElementById(focus)?.scrollIntoView();
}

function profileBlock(s, kind) {
  const items = s.blocks[kind];
  const published = items.filter((i) => i.status === "published");
  const pending = items.filter((i) => i.status === "pending");
  const extra = kind === "position" ? `<span class="chip ${published.length >= 3 && published.length <= 5 ? "chip-published" : "chip-pending"}">${published.length} pubblicate · indicazione 3–5</span>` : "";
  const single = kind === "biography";
  const writerLabel = single ? (published.length || pending.length ? "Modifica «Chi è»" : "Scrivi «Chi è»") : `Aggiungi ${kind === "career_entry" ? "un incarico" : kind === "position" ? "una posizione" : "un procedimento"}`;
  const starting = single ? (pending[0] || published[0]) : null;
  return `<section class="card" id="blocco-${kind}">${blockHead(kind, extra)}
    ${items.length ? items.map((item) => contentItem(kind, item)).join("") : `<p class="muted">${kind === "proceeding" ? "Non risultano procedimenti giudiziari documentati: il blocco non compare al cittadino." : "Ancora vuoto."}</p>`}
    ${kind === "proceeding" ? judicialFormulas() : ""}
    <details class="writer"><summary>${esc(writerLabel)}</summary>${blockForm(kind, starting ? { ...starting.data, identity_key: starting.identity_key, sources: starting.data.sources } : {})}</details>
  </section>`;
}

function contentItem(kind, item) {
  const d = item.data;
  const status = item.status === "published"
    ? `<span class="chip chip-published">Pubblicato</span><span>verificato da ${esc(item.reviewed_by || "—")} il ${longDate(item.published_at)}</span>`
    : `<span class="chip chip-pending">In attesa di verifica</span>`;
  let body = "";
  if (kind === "biography") body = `<p class="item-body">${esc(d.body)}</p>`;
  if (kind === "career_entry") body = `<p><strong>${esc(d.role)}</strong> — ${esc(d.institution)}${d.party_or_group ? ` · ${esc(d.party_or_group)}` : ""}<br /><span class="small muted">${longDate(d.start_date)} – ${d.is_current ? "in corso" : longDate(d.end_date) || "—"}</span></p>`;
  if (kind === "position") body = `<p><strong>${esc(d.topic)}</strong>: ${esc(d.position_statement)}</p><p class="small muted">${esc(d.verifiable_statement)} · ${longDate(d.statement_date) || "data mancante"}</p>`;
  if (kind === "proceeding") body = `<p><strong>${esc(d.title)}</strong> · ${longDate(d.event_date) || "data non indicata"}</p><p class="small">${esc(d.summary)}</p>${d.outcome_summary ? `<p class="small"><strong>Esito:</strong> ${esc(d.outcome_summary)}</p>` : ""}`;
  const edit = kind === "biography" ? "" : `<details class="writer"><summary>Modifica</summary>${blockForm(kind, { ...d, identity_key: item.identity_key })}</details>`;
  return `<div class="item ${item.status === "published" ? "is-published" : "is-pending"}">
    <div class="item-meta">${status}<span>scritto da ${esc(item.created_by)}</span></div>
    ${body}${sourcesList(d.sources)}
    ${item.status === "pending" ? findingsList(item.findings) : `<div class="actions"><button type="button" class="button-link" data-withdraw="${kind}:${item.id}">Ritira dal profilo pubblico</button></div>`}
    ${edit}
  </div>`;
}

function blockForm(kind, d = {}) {
  const id = `${kind}-${d.identity_key || "new"}`.replace(/[^a-z0-9-]/gi, "-");
  const key = `<input type="hidden" name="identity_key" value="${esc(d.identity_key || "")}" />`;
  let fields = "";
  if (kind === "biography") fields = `<div class="field"><label for="${id}-body">Testo <span class="counter"></span></label><textarea id="${id}-body" name="body" class="tall" ${counted(50, 80)} required>${esc(d.body || "")}</textarea><span class="hint">Formazione e percorso, solo fatti. Le parti da compilare vanno tra [parentesi quadre]: con parentesi aperte non si pubblica.</span></div>`;
  if (kind === "career_entry") fields = `<div class="field-row"><div class="field"><label for="${id}-role">Incarico</label><input id="${id}-role" type="text" name="role" value="${esc(d.role || "")}" required /></div><div class="field"><label for="${id}-inst">Istituzione</label><input id="${id}-inst" type="text" name="institution" value="${esc(d.institution || "")}" required /></div><div class="field"><label for="${id}-party">Partito o gruppo</label><input id="${id}-party" type="text" name="party_or_group" value="${esc(d.party_or_group || "")}" /></div></div>
    <div class="field-row"><div class="field"><label for="${id}-start">Inizio</label><input id="${id}-start" type="date" name="start_date" value="${esc(d.start_date || "")}" required /></div><div class="field"><label for="${id}-end">Fine</label><input id="${id}-end" type="date" name="end_date" value="${esc(d.end_date || "")}" /></div><div class="field"><span class="label">&nbsp;</span><label class="check"><input type="checkbox" name="is_current"${d.is_current ? " checked" : ""} />In corso</label></div></div>`;
  if (kind === "position") fields = `<div class="field-row"><div class="field"><label for="${id}-topic">Tema</label><input id="${id}-topic" type="text" name="topic" value="${esc(d.topic || "")}" required /></div><div class="field"><label for="${id}-date">Data della dichiarazione o del voto</label><input id="${id}-date" type="date" name="statement_date" value="${esc(d.statement_date || "")}" required /></div></div>
    <div class="field"><label for="${id}-pos">Posizione <span class="hint">Come l'ha espressa la persona, attribuita: «ha dichiarato…», «ha votato…».</span></label><textarea id="${id}-pos" name="position_statement" required>${esc(d.position_statement || "")}</textarea></div>
    <div class="field"><label for="${id}-ver">Dichiarazione o voto verificabile</label><textarea id="${id}-ver" name="verifiable_statement" rows="2" required>${esc(d.verifiable_statement || "")}</textarea></div>`;
  if (kind === "proceeding") fields = `<div class="field"><label for="${id}-title">Vicenda</label><input id="${id}-title" type="text" name="title" value="${esc(d.title || "")}" required /></div>
    <div class="field-row"><div class="field"><label for="${id}-type">Tipo</label><select id="${id}-type" name="proceeding_types">${options(PROCEEDING_TYPES, (d.proceeding_types || [])[0])}</select></div><div class="field"><label for="${id}-date">Data</label><input id="${id}-date" type="date" name="event_date" value="${esc(d.event_date || "")}" /></div><div class="field"><label for="${id}-out">Stato</label><select id="${id}-out" name="outcome">${options(OUTCOMES, d.outcome || "")}</select></div><div class="field"><label for="${id}-outd">Data dell'esito</label><input id="${id}-outd" type="date" name="outcome_date" value="${esc(d.outcome_date || "")}" /></div></div>
    <div class="field"><label for="${id}-sum">Sintesi <span class="hint">[corte], [data], [grado di giudizio], [reato]. Un'indagine non è una colpa.</span></label><textarea id="${id}-sum" name="summary" required>${esc(d.summary || "")}</textarea></div>
    <div class="field"><label for="${id}-outs">Esito, con la formula esatta della sentenza</label><textarea id="${id}-outs" name="outcome_summary" rows="2">${esc(d.outcome_summary || "")}</textarea></div>`;
  return `<form class="block-form" data-kind="${kind}">${key}${fields}${sourcesEditor(`${id}-src`, d.sources || [])}
    <div class="actions"><button class="button button-primary" type="submit">Salva e invia alla verifica</button><span class="small muted">Il cittadino non lo vede finché un'altra persona non approva.</span></div></form>`;
}

function readBlockForm(form) {
  const kind = form.dataset.kind;
  const get = (name) => form.elements[name]?.value?.trim() ?? "";
  const payload = { identity_key: get("identity_key") || undefined, sources: readSources(form, form.querySelector("[data-sources]")?.dataset.sources) };
  if (kind === "biography") payload.body = get("body");
  if (kind === "career_entry") Object.assign(payload, { role: get("role"), institution: get("institution"), party_or_group: get("party_or_group"), start_date: get("start_date"), end_date: get("end_date") || null, is_current: form.elements.is_current.checked });
  if (kind === "position") Object.assign(payload, { topic: get("topic"), statement_date: get("statement_date"), position_statement: get("position_statement"), verifiable_statement: get("verifiable_statement") });
  if (kind === "proceeding") Object.assign(payload, { title: get("title"), proceeding_types: [get("proceeding_types")], event_date: get("event_date") || null, outcome: get("outcome") || null, outcome_date: get("outcome_date") || null, summary: get("summary"), outcome_summary: get("outcome_summary") });
  return payload;
}

function judicialFormulas() {
  return `<details class="writer"><summary>Il linguaggio giudiziario: le formule corrette</summary>
    <div class="table-wrap" style="margin-top:8px"><table class="data-table"><thead><tr><th>Formula</th><th>Cosa significa e come si scrive</th></tr></thead><tbody>
    <tr><td>Indagato</td><td>È in corso un'indagine. Non è una colpa. Si scrive «è stato indagato per…», con la data.</td></tr>
    <tr><td>Rinviato a giudizio</td><td>Il giudice ha deciso che si faccia il processo. Non è una condanna.</td></tr>
    <tr><td>Condannato in primo grado / in appello</td><td>La sentenza non è definitiva: si scrive il grado e, se c'è stato, il successivo esito.</td></tr>
    <tr><td>Condannato in via definitiva</td><td>La Cassazione ha confermato la condanna. Si scrive: tribunale o corte, data, pena, reato.</td></tr>
    <tr><td>Assolto</td><td>Si scrive la formula esatta della sentenza (il fatto non sussiste, non costituisce reato, non l'ha commesso…).</td></tr>
    <tr><td>Prescrizione</td><td>Il reato è estinto per il tempo trascorso: non è né una condanna né un'assoluzione.</td></tr>
    </tbody></table></div></details>`;
}

function promisesBlock(s) {
  const rows = s.promises.map((p) => `<tr>
      <td><strong>${esc(p.title)}</strong>${p.exact_statement && p.exact_statement !== p.title ? `<br /><span class="small muted">«${esc(p.exact_statement)}»</span>` : ""}${p.classification ? `<br /><span class="small muted">${esc(classificationText(p.classification))}</span>` : p.published ? `<br /><span class="chip chip-pending">Da classificare: fuori dal punteggio</span>` : ""}</td>
      <td>${longDate(p.introduced_at)}${p.where ? `<br /><span class="small">${esc(p.where)}</span>` : ""}</td>
      <td>${p.published ? verdictChip(p.verdict, p.verdict_label) : `<span class="chip chip-pending">Promessa da verificare</span>`}${(p.pending_statuses || []).map((st) => `<br /><span class="small">Proposto: ${verdictChip(st.verdict, st.verdict_label)} (${st.approvals.length}/${st.approvals_required})</span>`).join("")}</td>
      <td class="small">${p.verdict_rationale ? esc(p.verdict_rationale) : "—"}${p.verdict_effective_at ? `<br /><span class="muted">al ${longDate(p.verdict_effective_at)}</span>` : ""}</td>
      <td class="small">${sourceLink(p.source)}${p.verdict_source_url ? `<br />Stato: ${sourceLink({ url: p.verdict_source_url })}` : ""}</td>
    </tr>
    ${p.published ? `<tr><td colspan="5" style="background:var(--color-background)"><details class="writer" style="margin:0;border:0;padding:0"><summary>Assegna lo stato a «${esc(p.title)}»</summary>${statusForm(p)}</details>
      <details class="writer" style="margin:4px 0 0;border:0;padding:0"><summary>${p.classified ? "Cambia la classificazione" : "Classifica (necessario per il punteggio)"}</summary>
      <form class="classify-form" data-proposal="${p.proposal_id}">${classificationFields(`cl-${p.proposal_id}`, p.classification || {})}<div class="actions"><button class="button button-primary" type="submit">Invia alla verifica</button><span class="small muted">Cambia il punteggio: la approva un'altra persona.</span></div></form></details></td></tr>` : ""}`).join("");
  return `<section class="card" id="blocco-promise">${blockHead("promise")}
    <div class="block-guide" style="grid-template-columns:1fr"><div><b>Come si assegna lo stato a una promessa</b>
      Si traccia solo se c'è una dichiarazione pubblica verificabile (data e fonte), abbastanza precisa da dire se è stata mantenuta.
      <strong>Mantenuta:</strong> realizzata (norma in vigore o impegno concluso). <strong>In corso:</strong> in attuazione o in parte, scadenza non ancora passata.
      <strong>Non mantenuta:</strong> solo se la scadenza dichiarata è passata senza risultato, o il mandato è finito, o c'è una rinuncia esplicita. Mai come giudizio: si dichiara con fatti e data. Serve l'approvazione di due persone.</div></div>
    ${s.promises.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Promessa</th><th>Quando e dove</th><th>Stato</th><th>Aggiornamento</th><th>Fonte</th></tr></thead><tbody>${rows}</tbody></table></div>` : `<p class="muted">Nessuna promessa registrata.</p>`}
    <details class="writer"><summary>Aggiungi una promessa</summary>
      <form class="promise-form">
        <div class="field"><label for="pr-title">Promessa <span class="hint">In forma neutra: cosa ha promesso, non un giudizio.</span></label><input id="pr-title" type="text" name="title" required /></div>
        <div class="field"><label for="pr-stmt">Dichiarazione esatta <span class="hint">Le parole usate, copiate dalla fonte.</span></label><textarea id="pr-stmt" name="exact_statement" rows="2" required></textarea></div>
        <div class="field-row"><div class="field"><label for="pr-date">Data della dichiarazione</label><input id="pr-date" type="date" name="introduced_at" required /></div><div class="field"><label for="pr-where">Dove <span class="hint">Es. «Discorso alla Camera per la fiducia»</span></label><input id="pr-where" type="text" name="where" /></div></div>
        <div class="field-row"><div class="field"><label for="pr-sname">Fonte</label><input id="pr-sname" type="text" name="source_name" placeholder="Es. Adnkronos" required /></div><div class="field"><label for="pr-surl">Link</label><input id="pr-surl" type="url" name="source_url" placeholder="https://…" required /></div></div>
        ${classificationFields("new-promise")}
        <div class="actions"><button class="button button-primary" type="submit">Salva e invia alla verifica</button></div>
      </form></details>
  </section>`;
}

function statusForm(p) {
  return `<form class="status-form" data-proposal="${p.proposal_id}">
    <div class="field-row"><div class="field"><label for="st-v-${p.proposal_id}">Stato</label><select id="st-v-${p.proposal_id}" name="verdict">${options(VERDICTS, "in_progress")}</select></div>
      <div class="field"><label for="st-d-${p.proposal_id}">Data del fatto</label><input id="st-d-${p.proposal_id}" type="date" name="effective_at" required /></div></div>
    <div class="broken-only" hidden><div class="field-row"><div class="field"><label for="st-r-${p.proposal_id}">Perché è non mantenuta</label><select id="st-r-${p.proposal_id}" name="broken_reason"><option value="">Scegli…</option><option value="scadenza_passata">La scadenza dichiarata è passata senza risultato</option><option value="mandato_concluso">Il mandato è finito</option><option value="rinuncia_esplicita">Rinuncia esplicita</option></select></div>
      <div class="field"><label for="st-dl-${p.proposal_id}">Scadenza dichiarata</label><input id="st-dl-${p.proposal_id}" type="date" name="deadline" /></div></div></div>
    <div class="field"><label for="st-a-${p.proposal_id}">Aggiornamento <span class="hint">Il fatto, con la data. Es. «Esenzione approvata per il 2027 (decreto-legge del 17 settembre)».</span></label><textarea id="st-a-${p.proposal_id}" name="rationale" rows="2" required></textarea></div>
    <div class="field"><label for="st-q-${p.proposal_id}">Passaggio copiato dalla fonte <span class="hint">La frase che lo dimostra, parola per parola: chi verifica la confronta con la pagina.</span></label><textarea id="st-q-${p.proposal_id}" name="quoted_excerpt" rows="2" required></textarea></div>
    <div class="field-row"><div class="field"><label for="st-sn-${p.proposal_id}">Fonte</label><input id="st-sn-${p.proposal_id}" type="text" name="source_name" required /></div><div class="field"><label for="st-su-${p.proposal_id}">Link</label><input id="st-su-${p.proposal_id}" type="url" name="source_url" required /></div></div>
    <div class="actions"><button class="button button-primary" type="submit">Proponi lo stato</button><span class="small muted">Entra nel punteggio solo dopo la verifica.</span></div>
  </form>`;
}

function newsBlock(s) {
  const sources = [];
  Object.values(s.blocks).flat().forEach((item) => (item.data.sources || []).forEach((src) => { if (src.url && !sources.some((x) => x.url === src.url)) sources.push(src); }));
  return `<section class="card" id="blocco-news">${blockHead("news")}
    <h3 style="margin-bottom:6px">Notizie collegate</h3>
    ${s.news.length ? `<ul class="item-sources">${s.news.map((n) => `<li><a href="#/notizie/${n.id}">${esc(n.title)}</a> <span class="chip ${n.status === "published" ? "chip-published" : "chip-pending"}">${n.status === "published" ? "Pubblicata" : "In attesa"}</span></li>`).join("")}</ul>` : `<p class="muted small">Nessuna notizia collega questa persona. Nella notizia, aggiungila tra i «Politici citati».</p>`}
    <h3 style="margin:14px 0 6px">Fonti usate nella scheda</h3>${sourcesList(sources)}
  </section>`;
}

function bindScheda(s) {
  const reload = (focus) => showScheda(s.id, focus);
  view.querySelectorAll("form.block-form").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const item = await api(`/politici/${s.id}/blocchi/${form.dataset.kind}`, { method: "POST", body: readBlockForm(form) });
      const errors = item.findings.filter((f) => f.level === "error").length;
      toast(errors ? `Bozza salvata con ${errors} errori da correggere prima della verifica.` : "Bozza salvata e inviata alla verifica.", Boolean(errors));
      reload(`blocco-${form.dataset.kind}`);
    } catch (error) { toast(error.message, true); }
  }));
  view.querySelectorAll("[data-withdraw]").forEach((button) => button.addEventListener("click", async () => {
    const reason = prompt("Motivo del ritiro (comparirà nel registro):");
    if (!reason) return;
    const [kind, id] = button.dataset.withdraw.split(":");
    try {
      await api(`/contenuti/${kind}/${id}/ritira`, { method: "POST", body: { reason } });
      toast("Richiesta di ritiro inviata: la approva un'altra persona.");
      reload(`blocco-${kind}`);
    } catch (error) { toast(error.message, true); }
  }));
  view.querySelector(".promise-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const body = {
      title: form.elements.title.value.trim(),
      exact_statement: form.exact_statement.value.trim(),
      introduced_at: form.introduced_at.value,
      where: form.where.value.trim(),
      source: { name: form.source_name.value.trim(), url: form.source_url.value.trim() },
      classification: readClassification(form, "new-promise"),
    };
    try {
      await api(`/politici/${s.id}/promesse`, { method: "POST", body });
      toast("Promessa salvata e inviata alla verifica.");
      reload("blocco-promise");
    } catch (error) { toast(error.findings?.length ? error.findings.map((f) => f.message).join(" ") : error.message, true); }
  });
  view.querySelectorAll(".status-form").forEach((form) => {
    const broken = form.querySelector(".broken-only");
    form.verdict.addEventListener("change", () => { broken.hidden = form.verdict.value !== "broken"; });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const body = {
        verdict: form.verdict.value,
        effective_at: form.effective_at.value,
        rationale: form.rationale.value.trim(),
        quoted_excerpt: form.quoted_excerpt.value.trim(),
        source: { name: form.source_name.value.trim(), url: form.source_url.value.trim() },
        broken_reason: form.broken_reason.value || undefined,
        deadline: form.deadline.value || undefined,
      };
      try {
        const result = await api(`/promesse/${form.dataset.proposal}/stato`, { method: "POST", body });
        toast(result.approvals_required > 1 ? "Stato proposto: servono due approvazioni." : "Stato proposto e inviato alla verifica.");
        reload("blocco-promise");
      } catch (error) { toast(error.findings?.length ? error.findings.map((f) => f.message).join(" ") : error.message, true); }
    });
  });
  view.querySelectorAll(".classify-form").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api(`/promesse/${form.dataset.proposal}/classificazione`, { method: "POST", body: readClassification(form, `cl-${form.dataset.proposal}`) });
      toast("Classificazione inviata alla verifica.");
      reload("blocco-promise");
    } catch (error) { toast(error.message, true); }
  }));
  view.querySelector("[data-log-politician]")?.addEventListener("click", (event) => {
    event.preventDefault();
    logFilter.politico = s.id;
    location.hash = "#/registro";
  });
  view.querySelectorAll("[data-count]").forEach(updateCounter);
}

// ---------------------------------------------------------------------- news
async function showNews() {
  const list = await api("/notizie");
  view.innerHTML = `<div class="page-head"><div><p class="eyebrow">Modello Notizia</p><h1>Notizie</h1>
    <p>Una sintesi imparziale di un fatto politico che incide sulla vita delle persone. Nove blocchi, sempre nello stesso ordine. Obiettivo: 2–4 sintesi a settimana.</p></div>
    <a class="button button-primary" href="#/notizie/nuova">Nuova notizia</a></div>
    ${list.length ? `<div class="table-wrap card" style="padding:0"><table class="data-table"><thead><tr><th>Titolo</th><th>Stato</th><th>Redattore</th><th>Verificatore</th><th>Data</th><th></th></tr></thead><tbody>
    ${list.map((n) => `<tr><td><a href="#/notizie/${n.id}"><strong>${esc(n.title)}</strong></a>${n.findings.some((f) => f.level === "error") && n.status === "pending" ? ` <span class="chip chip-rejected">Da correggere</span>` : ""}</td><td><span class="chip ${n.status === "published" ? "chip-published" : n.status === "rejected" ? "chip-rejected" : "chip-pending"}">${{ published: "Pubblicata", rejected: "Respinta", pending: "In attesa" }[n.status]}</span></td><td>${esc(n.created_by)}</td><td>${esc(n.reviewed_by || "—")}</td><td>${longDate(n.published_at || n.created_at)}</td><td>${n.can_discard ? `<button type="button" class="button button-danger" data-discard="${n.id}" data-title="${esc(n.title)}">Elimina</button>` : ""}</td></tr>`).join("")}
    </tbody></table></div>` : `<div class="empty">Nessuna notizia. <a href="#/notizie/nuova">Scrivi la prima</a>.</div>`}`;
  bindDiscardButtons(view, showNews);
}

const NEWS_HINTS = {
  perche: ["Quante persone riguarda, quale scadenza, perché proprio ora.", "Scrivere «importante» senza dire per chi."],
  fatto: ["Cosa è successo, chi ha deciso, quando, dove.", "Opinioni. Motivazioni presentate come verità."],
  cosa_cambia: ["Per chi cambia e per chi no, 2–3 esempi concreti con numeri, e cosa NON cambia. Il blocco più utile.", "Gergo tecnico. Risparmi promessi senza averli calcolati."],
  destra: ["Maggioranza di governo e centrodestra: 3–4 punti, ognuno con persona, ruolo e partito.", "Citare solo i più duri o solo i più morbidi."],
  sinistra: ["Opposizioni di centrosinistra: stesso numero di punti, stessa lunghezza, stesso tono del blocco 4.", "Un tono diverso dal blocco 4. Punti senza nome."],
  altri: ["Centro, Regioni, associazioni, imprese, sindacati, esperti.", "Ometterli perché «non fanno notizia»."],
  numeri: ["Costo, platea, copertura, effetti attesi. Ogni cifra con fonte e data; se due fonti divergono, affiancarle.", "Cifre senza fonte. Stime presentate come certezze."],
  cosa_succede: ["Prossimi passi con date: iter in Parlamento, scadenze, voti. Se non ci sono date, dirlo.", "Prevedere come andrà a finire."],
};

async function showNewsEditor(postId) {
  const post = postId ? await api(`/notizie/${postId}`) : { title: "", blocks: {}, sources: [], politicians: [], status: "pending", findings: [] };
  state.cardOptions = state.cardOptions || await api("/card");
  if (!state.portraits) {
    try { state.portraits = await fetch("/portraits").then((r) => (r.ok ? r.json() : {})); } catch { state.portraits = {}; }
  }
  state.parties = state.parties || await api("/partiti");
  const composer = createCardComposer(post.card, post.card_public);
  const editable = post.status === "pending" || !postId;
  const b = post.blocks || {};
  const blocks = state.rules.news_blocks;
  view.innerHTML = `<div class="page-head"><div><p class="eyebrow"><a href="#/notizie">Notizie</a> · Modello Notizia</p><h1>${postId ? esc(post.title) : "Nuova notizia"}</h1>
      ${postId ? `<p>Scritta da ${esc(post.created_by)}${post.reviewed_by ? ` · verificata da ${esc(post.reviewed_by)}` : ""} · <span class="chip ${post.status === "published" ? "chip-published" : "chip-pending"}">${{ published: "Pubblicata", rejected: "Respinta", pending: "In attesa di verifica" }[post.status]}</span></p>` : ""}</div>
      ${post.public_url || post.can_discard ? `<div class="actions" style="margin-top:0">${post.public_url ? `<a class="button button-secondary" href="${esc(post.public_url)}" target="_blank" rel="noopener">Vedi come la vede il cittadino</a>` : ""}${post.can_discard ? `<button type="button" class="button button-danger" id="n-discard">Elimina la notizia</button>` : ""}</div>` : ""}</div>
    ${!editable ? `<p class="own-note" style="margin-bottom:16px">Una notizia pubblicata non si modifica: un errore si corregge in modo visibile con una rettifica («Corretto il [data]: …»).</p>` : ""}
    <div class="layout-side"><form id="news-form" class="stack">
      <section class="card"><div class="card-head"><h2><span class="block-number">0</span>Titolo e sommario</h2></div>
        <div class="block-guide"><div><b>Cosa scrivere</b>Titolo: il fatto in forma neutra, soggetto + azione + quando. Sommario: 2 righe con chi, cosa, quando.</div><div><b>Lunghezza</b>Titolo ~90 caratteri</div><div class="avoid"><b>Da evitare</b>Verbi emotivi (attacca, boccia, trionfa); promesse nel titolo.</div></div>
        <div class="field"><label for="n-title">Titolo</label><input id="n-title" type="text" name="title" maxlength="300" value="${esc(post.title)}" required /></div>
        <div class="field"><label for="n-sommario">Sommario <span class="hint">È il testo della card nel feed.</span></label><textarea id="n-sommario" name="sommario" rows="2">${esc(b.sommario || "")}</textarea></div>
      </section>
      ${composer.html()}
      ${blocks.map((block, index) => `<section class="card"><div class="card-head"><h2><span class="block-number">${index + 1}</span>${esc(block.label)}</h2></div>
        <div class="block-guide"><div><b>Cosa scrivere</b>${esc(NEWS_HINTS[block.key][0])}</div><div><b>Lunghezza</b>${block.min}–${block.max} parole</div><div class="avoid"><b>Da evitare</b>${esc(NEWS_HINTS[block.key][1])}</div></div>
        <div class="field"><label for="n-${block.key}">Testo <span class="counter"></span></label><textarea id="n-${block.key}" name="${block.key}" class="tall" ${counted(block.min, block.max)}>${esc(b[block.key] || "")}</textarea>${["destra", "sinistra", "cosa_cambia"].includes(block.key) ? `<span class="hint">Un punto per riga, con «- ». Destra e sinistra: stesso numero di punti.</span>` : ""}</div>
        ${block.key === "fatto" ? `<div class="field"><label for="n-perche_deciso">Perché è stato deciso, secondo chi ha deciso</label><textarea id="n-perche_deciso" name="perche_deciso" rows="2">${esc(b.perche_deciso || "")}</textarea></div>` : ""}
        ${block.key === "sinistra" ? `<div class="label">Equilibrio destra / sinistra</div><div class="balance" id="balance"><span></span><span></span></div><p class="small muted" id="balance-text"></p>` : ""}
      </section>`).join("")}
      <section class="card"><div class="card-head"><h2><span class="block-number">9</span>Fonti</h2></div>
        <div class="block-guide"><div><b>Cosa scrivere</b>Elenco con data. Almeno 3 fonti: una di centrodestra, una di centrosinistra, una istituzionale o di agenzia.</div><div><b>Lunghezza</b>—</div><div class="avoid"><b>Da evitare</b>Elencare fonti non lette.</div></div>
        ${newsSourcesEditor(post.sources)}
        <div class="field-row"><div class="field"><label for="n-scope">Ambito</label><select id="n-scope" name="scope">${options([["national", "Nazionale"], ["region", "Regionale"], ["province", "Provinciale"], ["municipality", "Comunale"]], post.scope || "national")}</select></div>
          <div class="field"><label for="n-region">Codice regione / comune</label><input id="n-region" type="number" name="territory" min="1" value="${esc(post.region_id || post.municipality_id || "")}" /><span class="hint">Solo per notizie locali (id del territorio).</span></div>
          <div class="field"><label for="n-prov">Sigla provincia</label><input id="n-prov" type="text" name="province" maxlength="2" value="${esc(post.province_abbreviation || "")}" /></div></div>
        <div class="field"><label for="n-pol">Politici citati <span class="hint">La notizia compare in «Notizie collegate» nel loro profilo.</span></label>
          <div class="actions" style="margin-top:0"><input id="n-pol" type="search" placeholder="Cerca un politico" style="flex:1 1 220px" /><button type="button" class="button button-secondary" id="n-pol-add">Aggiungi</button></div>
          <ul class="item-sources" id="n-pol-list">${(post.politicians || []).map(politicianChip).join("")}</ul></div>
      </section>
      ${editable ? `<div class="actions"><button class="button button-primary" type="submit">${postId ? "Salva le modifiche" : "Salva e invia alla verifica"}</button><span class="small muted">Fonti: Redattore e Verificatore compaiono in fondo alla notizia pubblicata.</span></div>` : ""}
    </form>
    <aside class="card side-panel"><h3>Anteprima nel feed</h3>
      <div id="card-preview" class="card-preview"></div>
      <h3 style="margin-top:20px">Quando una notizia merita una sintesi</h3>
      <p class="small muted">Ne bastano 3 su 5. Con meno di 3 criteri non si scrive: resta tra le segnalazioni.</p>
      <ul class="criteria" id="criteria">${["Cambia qualcosa di concreto nella vita di molte persone", "È una decisione formale (legge, decreto, sentenza, voto)", "Gli schieramenti hanno posizioni diverse e verificabili", "C'è una scadenza", "Ha effetti economici misurabili"].map((text, i) => `<li><label class="check"><input type="checkbox" data-criterion="${i}" />${esc(text)}</label></li>`).join("")}</ul>
      <p class="small" id="criteria-text"></p>
      <h3 style="margin-top:16px">Controlli</h3><div id="news-findings">${findingsList(post.findings)}</div>
      <p class="small muted" style="margin-top:12px">Gli errori bloccano la pubblicazione; gli avvisi li valuta chi verifica.</p>
    </aside></div>`;
  const form = view.querySelector("#news-form");
  if (!editable) form.querySelectorAll("input, textarea, select, button").forEach((el) => { el.disabled = true; });
  const criteria = view.querySelector("#criteria");
  criteria.addEventListener("change", () => {
    const n = criteria.querySelectorAll("input:checked").length;
    view.querySelector("#criteria-text").textContent = n >= 3 ? `${n} criteri su 5: si scrive.` : `${n} criteri su 5: con meno di 3 resta tra le segnalazioni.`;
  });
  const collect = () => {
    const blocksData = { sommario: form.sommario.value.trim(), perche_deciso: form.perche_deciso.value.trim() };
    blocks.forEach((block) => { blocksData[block.key] = form[block.key].value.trim(); });
    const scope = form.scope.value;
    const territory = Number(form.territory.value) || null;
    return {
      title: form.elements.title.value.trim(),
      blocks: blocksData,
      sources: readNewsSources(form),
      scope,
      region_id: scope === "region" ? territory : null,
      municipality_id: scope === "municipality" ? territory : null,
      province_abbreviation: scope === "province" ? form.province.value.trim().toUpperCase() : null,
      politician_ids: [...view.querySelectorAll("#n-pol-list [data-politician]")].map((el) => Number(el.dataset.politician)),
      card: composer.value(),
    };
  };
  const preview = () => {
    const data = collect();
    view.querySelector("#card-preview").innerHTML = renderFeedCard({
      key: "anteprima",
      url: "#",
      title: data.title || "Titolo della notizia",
      summary: data.blocks.sommario || "Il sommario compare qui.",
      occurred_on: new Date().toISOString().slice(0, 10),
      place: { national: "Nazionale", region: "Regionale", province: "Provinciale", municipality: "Comunale" }[data.scope],
      sources: data.sources.map((src) => ({ title: src.name, url: src.url })),
      coverage: sourceCoverage(data.sources),
      card: composer.publicCard(),
    }, { preview: true, resolvePortrait: (id) => state.portraits?.[String(id)]?.url || null });
  };
  composer.bind(form, preview);
  bindFeedCards(view.querySelector("#card-preview"));
  const balance = () => {
    const right = words(form.destra.value), left = words(form.sinistra.value);
    const total = right + left || 1;
    const bar = view.querySelector("#balance");
    bar.children[0].style.width = `${(right / total) * 100}%`;
    bar.children[1].style.width = `${(left / total) * 100}%`;
    view.querySelector("#balance-text").textContent = `Destra ${right} parole · Sinistra ${left} parole`;
  };
  let timer;
  const check = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const result = await api("/controlla/notizia", { method: "POST", body: collect() });
        view.querySelector("#news-findings").innerHTML = findingsList(result.findings);
      } catch { /* ignore */ }
    }, 500);
  };
  form.addEventListener("input", () => { balance(); check(); preview(); });
  form.addEventListener("change", () => { check(); preview(); });
  view.querySelectorAll("[data-count]").forEach(updateCounter);
  balance();
  preview();
  bindPoliticianPicker();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const saved = await api(postId ? `/notizie/${postId}` : "/notizie", { method: postId ? "PUT" : "POST", body: collect() });
      const errors = saved.findings.filter((f) => f.level === "error").length;
      toast(errors ? `Salvata con ${errors} errori: va corretta prima della verifica.` : "Notizia salvata e inviata alla verifica.", Boolean(errors));
      location.hash = `#/notizie/${saved.id}`;
      if (postId) showNewsEditor(saved.id);
    } catch (error) { toast(error.message, true); }
  });
  view.querySelector("#n-discard")?.addEventListener("click", async () => {
    if (!await discardNews(post.id, post.title)) return;
    location.hash = "#/notizie";
  });
}

// ------------------------------------------------------------- card composer
// The feed card: category band, badge, people with a round photo, institution,
// optional iter strip and link. Photos are cropped to a circle here and
// uploaded as small square JPEGs.
const BADGE_TONE_LABELS = { plain: "Solo testo", navy: "Blu", green: "Verde", red: "Rosso" };
const ITER_STATE_LABELS = { in_corso: "In corso", fermo: "Fermo", concluso: "Concluso" };

function createCardComposer(initial, initialPublic) {
  const opts = state.cardOptions;
  const today = new Date().toISOString().slice(0, 10);
  const publicPeople = new Map((initialPublic?.people || []).map((p) => [p.politician_id, p]));
  const c = {
    category: initial?.category || "notizia",
    badge: { label: initial?.badge?.label || "Nuova pubblicazione", tone: initial?.badge?.tone || "navy", date: initial?.badge?.date || today },
    aside: initial?.aside || "",
    institution: initial?.institution || "",
    // Only politicians with a profile: name and party come from the profile.
    people: (initial?.people || []).filter((p) => p.politician_id && publicPeople.has(p.politician_id)).map((p) => {
      const known = publicPeople.get(p.politician_id);
      const party = (state.parties || []).find((x) => x.id === known.party_id) || (known.role ? { id: known.party_id, name: known.role } : null);
      return { politician_id: p.politician_id, name: known.name, party, image_id: p.image_id || null, image_url: p.image_id ? `/media/${p.image_id}` : null, use_portrait: Boolean(p.use_portrait) };
    }),
    parties: [...(initial?.parties || [])],
    iter: initial?.iter ? { ...initial.iter, enabled: true } : { enabled: false, first: "camera", current: 1, state: "in_corso", status: "", since_label: "Presentato il", since: "" },
    link: initial?.link || { label: "", url: "" },
  };
  let root;
  let onChange = () => {};

  const personRow = (p, index) => `<div class="person-row" data-person="${index}">
      <button type="button" class="avatar-pick" data-pick-photo="${index}" aria-label="Carica la foto di ${esc(p.name)}">
        <span class="avatar-circle">${p.image_url ? `<img src="${esc(p.image_url)}" alt="" />` : p.use_portrait && portraitFor(p.politician_id) ? `<img src="${esc(portraitFor(p.politician_id))}" alt="" />` : `<span>${esc(initialsOf(p.name))}</span>`}</span>
        <span class="avatar-label">${p.image_url || (p.use_portrait && portraitFor(p.politician_id)) ? "Cambia foto" : "Carica foto"}</span>
      </button>
      <input type="file" accept="image/jpeg,image/png,image/webp" data-photo-input="${index}" hidden />
      <div class="person-fields">
        <p class="person-name"><strong>${esc(p.name)}</strong> <a class="small" href="#/politici/${p.politician_id}">scheda</a></p>
        <p class="person-party">${p.party ? `${esc(p.party.name)}${p.party.abbreviation ? ` (${esc(p.party.abbreviation)})` : ""}` : `<span class="muted">Partito non indicato nel profilo</span>`}</p>
        <div class="actions" style="margin-top:4px">
          ${portraitFor(p.politician_id) && !p.image_url ? `<label class="check small"><input type="checkbox" data-p="use_portrait"${p.use_portrait ? " checked" : ""} />Usa la foto del profilo</label>` : ""}
          ${p.image_url ? `<button type="button" class="button-link" data-remove-photo="${index}">Togli foto</button>` : ""}
          <button type="button" class="button-link" data-remove-person="${index}">Rimuovi</button>
        </div>
      </div>
    </div>`;

  const peopleParties = () => new Set(c.people.map((p) => p.party?.id).filter(Boolean));
  const partyChips = () => {
    const auto = peopleParties();
    const list = state.parties || [];
    if (!list.length) return `<p class="muted small">Nessun partito nell'archivio.</p>`;
    return list.map((party) => {
      const fromPerson = auto.has(party.id);
      const checked = fromPerson || c.parties.includes(party.id);
      return `<label class="party-chip${checked ? " is-on" : ""}${fromPerson ? " is-auto" : ""}"><input type="checkbox" value="${party.id}" data-party${checked ? " checked" : ""}${fromPerson ? " disabled" : ""} />${partyLogo(party)}${esc(party.abbreviation || party.name)}${party.abbreviation ? `<span class="party-full">${esc(party.name)}</span>` : ""}</label>`;
    }).join("");
  };

  const stepOptions = () => opts.iter_steps[c.iter.first].map((label, i) => [String(i + 1), `${i + 1}. ${label}`]);

  const html = () => `<section class="card" id="card-composer"><div class="card-head"><h2><span class="block-number">F</span>La card nel feed</h2><span class="chip chip-kind">Così appare nella timeline</span></div>
      <div class="block-guide"><div><b>Cosa scrivere</b>Il tipo di contenuto, l'etichetta con la data, chi è coinvolto (con foto rotonda), l'ente. Titolo e sommario sono quelli del blocco 0.</div><div><b>Persone</b>Fino a 3</div><div class="avoid"><b>Da evitare</b>Foto senza diritti d'uso: indica sempre il credito.</div></div>
      <div class="field-row">
        <div class="field"><label for="c-category">Tipo</label><select id="c-category" data-c="category">${options(opts.categories.map((x) => [x.key, x.label]), c.category)}</select></div>
        <div class="field"><label for="c-badge">Etichetta</label><input id="c-badge" type="text" list="c-badge-presets" data-c="badge.label" value="${esc(c.badge.label)}" /><datalist id="c-badge-presets">${opts.badge_presets.map((x) => `<option value="${esc(x)}"></option>`).join("")}</datalist></div>
        <div class="field"><label for="c-tone">Colore etichetta</label><select id="c-tone" data-c="badge.tone">${options(opts.badge_tones.map((x) => [x, BADGE_TONE_LABELS[x] || x]), c.badge.tone)}</select></div>
        <div class="field"><label for="c-date">Data</label><input id="c-date" type="date" data-c="badge.date" value="${esc(c.badge.date || "")}" /></div>
      </div>
      <div class="field-row">
        <div class="field"><label for="c-aside">Testo a destra <span class="hint">Facoltativo. Es. «Aperto il 1 aprile 2026».</span></label><input id="c-aside" type="text" data-c="aside" value="${esc(c.aside)}" /></div>
        <div class="field"><label for="c-inst">Ente o istituzione <span class="hint">Es. «Ministero delle Infrastrutture e dei Trasporti»</span></label><input id="c-inst" type="text" data-c="institution" value="${esc(c.institution)}" /></div>
      </div>
      <fieldset><legend>Politici coinvolti · foto rotonda accanto al nome</legend>
        <div id="people-rows">${c.people.map(personRow).join("")}</div>
        <div class="politician-picker">
          <label for="pp-q">Aggiungi un politico <span class="hint">Solo profili presenti in archivio: nome e partito arrivano dalla scheda. Fino a ${opts.max_people}.</span></label>
          <input id="pp-q" type="search" placeholder="Cerca per nome o cognome" autocomplete="off" aria-controls="pp-results"${c.people.length >= opts.max_people ? " disabled" : ""} />
          <ul id="pp-results" class="pp-results" role="listbox" aria-label="Politici trovati" hidden></ul>
        </div>
        <p class="hint" style="margin-top:6px">Tocca il cerchio per caricare una foto: la ritagli in tondo qui, poi viene salvata piccola (320×320). Oppure usa la foto del profilo, se c'è.</p>
      </fieldset>
      <fieldset><legend>Partiti coinvolti</legend>
        <div class="party-chips" id="party-chips">${partyChips()}</div>
        <p class="hint" style="margin-top:6px">I partiti dei politici scelti sono inclusi in automatico. Aggiungi gli altri partiti che c'entrano con la notizia.</p>
      </fieldset>
      <fieldset><legend><label class="check"><input type="checkbox" data-c="iter.enabled"${c.iter.enabled ? " checked" : ""} />Mostra l'iter (per leggi e decreti)</label></legend>
        <div class="iter-fields"${c.iter.enabled ? "" : " hidden"}>
          <div class="field-row">
            <div class="field"><label for="c-first">Prima lettura</label><select id="c-first" data-c="iter.first">${options([["camera", "Camera"], ["senato", "Senato"]], c.iter.first)}</select></div>
            <div class="field"><label for="c-current">Fase attuale</label><select id="c-current" data-c="iter.current">${options(stepOptions(), String(c.iter.current))}</select></div>
            <div class="field"><label for="c-state">Stato</label><select id="c-state" data-c="iter.state">${options(opts.iter_states.map((x) => [x, ITER_STATE_LABELS[x]]), c.iter.state)}</select></div>
          </div>
          <div class="field-row">
            <div class="field"><label for="c-status">Testo della fase <span class="hint">Es. «Esame in commissione · Senato»</span></label><input id="c-status" type="text" data-c="iter.status" value="${esc(c.iter.status || "")}" /></div>
            <div class="field"><label for="c-since-label">Etichetta data</label><input id="c-since-label" type="text" data-c="iter.since_label" value="${esc(c.iter.since_label || "Presentato il")}" /></div>
            <div class="field"><label for="c-since">Data</label><input id="c-since" type="date" data-c="iter.since" value="${esc(c.iter.since || "")}" /></div>
          </div>
        </div>
      </fieldset>
      <div class="field-row">
        <div class="field"><label for="c-link-label">Pulsante esterno <span class="hint">Facoltativo. Es. «Leggi su camera.it»</span></label><input id="c-link-label" type="text" data-c="link.label" value="${esc(c.link.label || "")}" /></div>
        <div class="field"><label for="c-link-url">Link</label><input id="c-link-url" type="url" data-c="link.url" value="${esc(c.link.url || "")}" placeholder="https://…" /></div>
      </div>
    </section>`;

  const setPath = (path, value) => {
    const [head, tail] = path.split(".");
    if (tail) c[head][tail] = value;
    else c[head] = value;
  };
  const redrawPeople = () => {
    root.querySelector("#people-rows").innerHTML = c.people.map(personRow).join("");
    root.querySelector("#pp-q").disabled = c.people.length >= opts.max_people;
    root.querySelector("#party-chips").innerHTML = partyChips();
    onChange();
  };
  let searchTimer;
  const searchPoliticians = () => {
    clearTimeout(searchTimer);
    const input = root.querySelector("#pp-q");
    const list = root.querySelector("#pp-results");
    const query = input.value.trim();
    if (query.length < 2) { list.hidden = true; return; }
    searchTimer = setTimeout(async () => {
      const found = await api(`/politici?q=${encodeURIComponent(query)}&limit=8`);
      const taken = new Set(c.people.map((p) => p.politician_id));
      list.innerHTML = found.length
        ? found.map((p) => `<li><button type="button" role="option" data-pick-politician="${p.id}"${taken.has(p.id) ? " disabled" : ""}><span class="avatar-mini">${portraitFor(p.id) ? `<img src="${esc(portraitFor(p.id))}" alt="" />` : esc(initialsOf(p.name))}</span><span><strong>${esc(p.name)}</strong><small>${esc(p.party ? p.party.name : "Partito non indicato")}</small></span></button></li>`).join("")
        : `<li class="muted small" style="padding:8px 12px">Nessun profilo trovato.</li>`;
      list.hidden = false;
      list._found = found;
    }, 250);
  };

  const bind = (form, changed) => {
    root = form.querySelector("#card-composer");
    onChange = changed;
    root.addEventListener("input", (event) => {
      const el = event.target;
      if (el.dataset.c) {
        setPath(el.dataset.c, el.type === "checkbox" ? el.checked : el.value);
        if (el.dataset.c === "iter.enabled") root.querySelector(".iter-fields").hidden = !el.checked;
        if (el.dataset.c === "iter.first") root.querySelector("#c-current").innerHTML = options(stepOptions(), String(c.iter.current));
      }
      const row = el.closest("[data-person]");
      if (row && el.dataset.p) {
        c.people[Number(row.dataset.person)][el.dataset.p] = el.type === "checkbox" ? el.checked : el.value;
        if (el.dataset.p === "use_portrait") redrawPeople();
      }
      if (el.id === "pp-q") searchPoliticians();
      if (el.matches("[data-party]")) {
        const id = Number(el.value);
        c.parties = el.checked ? [...new Set([...c.parties, id])] : c.parties.filter((x) => x !== id);
        el.closest(".party-chip").classList.toggle("is-on", el.checked);
      }
    });
    root.addEventListener("click", async (event) => {
      const el = event.target instanceof Element ? event.target : null;
      if (!el) return;
      const pickPolitician = el.closest("[data-pick-politician]");
      if (pickPolitician) {
        const list = root.querySelector("#pp-results");
        const found = (list._found || []).find((p) => p.id === Number(pickPolitician.dataset.pickPolitician));
        if (found && c.people.length < opts.max_people && !c.people.some((p) => p.politician_id === found.id)) {
          c.people.push({ politician_id: found.id, name: found.name, party: found.party, image_id: null, image_url: null, use_portrait: Boolean(portraitFor(found.id)) });
        }
        list.hidden = true;
        root.querySelector("#pp-q").value = "";
        redrawPeople();
        return;
      }
      const remove = el.closest("[data-remove-person]");
      if (remove) { c.people.splice(Number(remove.dataset.removePerson), 1); redrawPeople(); }
      const removePhoto = el.closest("[data-remove-photo]");
      if (removePhoto) { Object.assign(c.people[Number(removePhoto.dataset.removePhoto)], { image_id: null, image_url: null }); redrawPeople(); }
      const pick = el.closest("[data-pick-photo]");
      if (pick) root.querySelector(`[data-photo-input="${pick.dataset.pickPhoto}"]`).click();
    });
    root.addEventListener("change", async (event) => {
      const input = event.target.closest?.("[data-photo-input]");
      if (!input || !input.files?.[0]) return;
      const index = Number(input.dataset.photoInput);
      const result = await cropToCircle(input.files[0], c.people[index].name);
      input.value = "";
      if (!result) return;
      try {
        const uploaded = await api("/immagini", { method: "POST", body: { data: result.dataUrl, width: 320, height: 320, credit: result.credit, alt: c.people[index].name } });
        Object.assign(c.people[index], { image_id: uploaded.id, image_url: uploaded.url, use_portrait: false });
        redrawPeople();
        toast("Foto caricata.");
      } catch (error) { toast(error.message, true); }
    });
  };

  const value = () => ({
    category: c.category,
    badge: { ...c.badge },
    aside: c.aside,
    institution: c.institution,
    people: c.people.map((p) => ({ politician_id: p.politician_id, image_id: p.image_id, use_portrait: p.use_portrait })),
    parties: c.parties.filter((id) => !peopleParties().has(id)),
    iter: c.iter.enabled ? { ...c.iter, current: Number(c.iter.current) } : null,
    link: c.link.url ? { ...c.link } : null,
  });

  const publicCard = () => {
    const category = opts.categories.find((x) => x.key === c.category) || opts.categories[0];
    let iter = null;
    if (c.iter.enabled) {
      const current = Number(c.iter.current);
      iter = {
        ...c.iter,
        steps: opts.iter_steps[c.iter.first].map((label, i) => {
          const n = i + 1;
          const stateOf = n < current || (c.iter.state === "concluso" && n <= current) ? "done" : n === current ? (c.iter.state === "fermo" ? "stopped" : "current") : "todo";
          return { label, state: stateOf };
        }),
      };
    }
    return {
      category: c.category,
      category_label: category.label,
      tone: category.tone,
      composed: true,
      badge: { ...c.badge },
      aside: c.aside || null,
      institution: c.institution || null,
      people: c.people.map((p) => ({ name: p.name, role: p.party?.name || null, party_id: p.party?.id || null, politician_id: p.politician_id, image_url: p.image_url || (p.use_portrait ? `politician:${p.politician_id}` : null) })),
      parties: (() => {
        const ids = [...c.parties, ...[...peopleParties()].filter((id) => !c.parties.includes(id))];
        return ids.map((id) => (state.parties || []).find((x) => x.id === id)).filter(Boolean);
      })(),
      iter,
      link: c.link.url ? { label: c.link.label || "Leggi la fonte", url: c.link.url } : null,
    };
  };

  return { html, bind, value, publicCard };
}

function portraitFor(politicianId) {
  if (!politicianId) return null;
  const url = state.portraits?.[String(politicianId)]?.url;
  return url || null;
}
function initialsOf(name) {
  return String(name || "").split(/\s+/).filter(Boolean).slice(0, 2).map((x) => x[0]).join("").toUpperCase();
}

// Round crop: drag to move, slider to zoom. Output: 320×320 JPEG.
function cropToCircle(file, name) {
  return new Promise((resolve) => {
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) { toast("Usa una foto JPEG, PNG o WebP.", true); return resolve(null); }
    // Read as a data: URL: the site's Content-Security-Policy does not allow blob: images.
    const reader = new FileReader();
    const img = new Image();
    img.onload = () => {
      const dialog = document.createElement("dialog");
      dialog.className = "crop-dialog";
      dialog.innerHTML = `<form method="dialog" class="stack">
        <h2>Ritaglia la foto${name ? ` di ${esc(name)}` : ""}</h2>
        <p class="small muted">Trascina per spostare, usa il cursore per ingrandire. Nel feed si vede solo il cerchio.</p>
        <div class="crop-stage"><canvas width="280" height="280" aria-label="Anteprima del ritaglio"></canvas></div>
        <div class="field"><label for="crop-zoom">Zoom</label><input id="crop-zoom" type="range" min="1" max="4" step="0.01" value="1" /></div>
        <div class="field"><label for="crop-credit">Credito della foto <span class="hint">Es. «Camera dei deputati» o «Foto: nome, licenza CC BY»</span></label><input id="crop-credit" type="text" required /></div>
        <div class="actions"><button class="button button-primary" value="ok">Usa questa foto</button><button class="button button-secondary" value="cancel" formnovalidate>Annulla</button></div>
      </form>`;
      document.body.append(dialog);
      const canvas = dialog.querySelector("canvas");
      const ctx = canvas.getContext("2d");
      const zoomInput = dialog.querySelector("#crop-zoom");
      const base = Math.max(280 / img.width, 280 / img.height);
      let zoom = 1, x = 0, y = 0, drag = null;
      const clamp = () => {
        const w = img.width * base * zoom, h = img.height * base * zoom;
        x = Math.min(0, Math.max(280 - w, x));
        y = Math.min(0, Math.max(280 - h, y));
      };
      const draw = (target = ctx, size = 280) => {
        const k = size / 280;
        target.fillStyle = "#fff";
        target.fillRect(0, 0, size, size);
        target.drawImage(img, x * k, y * k, img.width * base * zoom * k, img.height * base * zoom * k);
      };
      x = (280 - img.width * base) / 2; y = (280 - img.height * base) / 2; clamp(); draw();
      zoomInput.addEventListener("input", () => {
        const prev = zoom; zoom = Number(zoomInput.value);
        x = 140 - (140 - x) * (zoom / prev); y = 140 - (140 - y) * (zoom / prev); clamp(); draw();
      });
      canvas.addEventListener("pointerdown", (e) => { drag = { sx: e.clientX, sy: e.clientY, x, y }; canvas.setPointerCapture(e.pointerId); });
      canvas.addEventListener("pointermove", (e) => { if (!drag) return; x = drag.x + e.clientX - drag.sx; y = drag.y + e.clientY - drag.sy; clamp(); draw(); });
      canvas.addEventListener("pointerup", () => { drag = null; });
      dialog.addEventListener("close", () => {
        if (dialog.returnValue !== "ok") { dialog.remove(); return resolve(null); }
        const out = document.createElement("canvas");
        out.width = 320; out.height = 320;
        draw(out.getContext("2d"), 320);
        const credit = dialog.querySelector("#crop-credit").value.trim();
        dialog.remove();
        resolve({ dataUrl: out.toDataURL("image/jpeg", 0.86), credit });
      });
      dialog.showModal();
    };
    img.onerror = () => { toast("Non riesco a leggere questa immagine.", true); resolve(null); };
    reader.onload = () => { img.src = reader.result; };
    reader.onerror = img.onerror;
    if (file.size > 15_000_000) { toast("La foto è troppo grande (massimo 15 MB).", true); return resolve(null); }
    reader.readAsDataURL(file);
  });
}

function newsSourcesEditor(sources = []) {
  const rows = (sources.length ? sources : [{}, {}, {}]).map(newsSourceRow).join("");
  return `<div class="sources-editor" id="news-sources">${rows}</div><button type="button" class="button-link" id="add-news-source">+ Aggiungi fonte</button>`;
}
function newsSourceRow(s = {}) {
  return `<div class="source-row" style="grid-template-columns:1fr 2fr 1fr 1fr auto">
    <input type="text" aria-label="Testata" placeholder="Testata o ente" data-src="name" value="${esc(s.name || "")}" />
    <input type="url" aria-label="Link" placeholder="https://…" data-src="url" value="${esc(s.url || "")}" />
    <input type="date" aria-label="Data" data-src="date" value="${esc(s.date || "")}" />
    <select aria-label="Tipo di fonte" data-src="area">${options(SOURCE_AREAS, s.area || "agenzia")}</select>
    <button type="button" class="button-link" data-remove-source>Rimuovi</button></div>`;
}
function readNewsSources(form) {
  return [...form.querySelectorAll("#news-sources .source-row")].map((row) => {
    const get = (key) => row.querySelector(`[data-src="${key}"]`).value.trim();
    return { name: get("name"), url: get("url"), date: get("date") || null, area: get("area") };
  }).filter((s) => s.url);
}
document.addEventListener("click", (event) => {
  if (event.target.id === "add-news-source") document.getElementById("news-sources").insertAdjacentHTML("beforeend", newsSourceRow());
});
function politicianChip(p) {
  return `<li data-politician="${p.id}">${esc(p.name || `Politico ${p.id}`)} <button type="button" class="button-link" data-remove-politician>rimuovi</button></li>`;
}
function bindPoliticianPicker() {
  const input = view.querySelector("#n-pol");
  const list = view.querySelector("#n-pol-list");
  list.addEventListener("click", (event) => { if (event.target.matches("[data-remove-politician]")) { event.target.closest("li").remove(); list.dispatchEvent(new Event("input", { bubbles: true })); } });
  view.querySelector("#n-pol-add").addEventListener("click", async () => {
    const found = await api(`/politici?q=${encodeURIComponent(input.value)}&limit=1`);
    if (!found.length) return toast("Nessun politico con questo nome.", true);
    if (!list.querySelector(`[data-politician="${found[0].id}"]`)) list.insertAdjacentHTML("beforeend", politicianChip(found[0]));
    input.value = "";
    view.querySelector("#news-form").dispatchEvent(new Event("change"));
  });
}

// ----------------------------------------------------------------------- log
const logFilter = { politico: null, utente: "" };
const ACTIONS = { scrittura: "Scrittura", modifica: "Modifica", approvazione: "Approvazione", rifiuto: "Rifiuto", assegna_stato: "Stato proposto", richiesta_ritiro: "Richiesta di ritiro", richiesta_classificazione: "Richiesta di classificazione" };
async function showLog(offset = 0) {
  const params = new URLSearchParams({ limit: "50", offset: String(offset) });
  if (logFilter.politico) params.set("politico", logFilter.politico);
  if (logFilter.utente) params.set("utente", logFilter.utente);
  const log = await api(`/registro?${params}`);
  view.innerHTML = `<div class="page-head"><div><p class="eyebrow">Trasparenza interna</p><h1>Registro modifiche</h1>
    <p>Ogni scrittura, modifica, approvazione, rifiuto, ritiro, assegnazione di stato ed eliminazione di una bozza, con chi l'ha fatta e quando. Il registro non si può modificare né cancellare.</p></div></div>
    <form id="log-filter" class="card" style="margin-bottom:16px"><div class="field-row">
      <div class="field"><label for="lf-user">Persona</label><select id="lf-user"><option value="">Tutte</option>${state.me.members.map((m) => `<option${m === logFilter.utente ? " selected" : ""}>${esc(m)}</option>`).join("")}</select></div>
      <div class="field"><label for="lf-pol">Politico (id)</label><input id="lf-pol" type="number" min="1" value="${esc(logFilter.politico || "")}" /></div>
      <div class="field"><span class="label">&nbsp;</span><button class="button button-secondary" type="submit">Filtra</button></div></div></form>
    ${log.items.length ? `<div class="card table-wrap" style="padding:0"><table class="data-table log-table"><thead><tr><th>Quando</th><th>Persona</th><th>Azione</th><th>Cosa</th></tr></thead><tbody>
      ${log.items.map((e) => `<tr><td>${dateTime(e.at)}</td><td>${esc(e.actor)}</td><td><span class="chip ${e.action === "approvazione" ? "chip-published" : e.action === "rifiuto" ? "chip-rejected" : "chip-kind"}">${esc(ACTIONS[e.action] || e.action)}</span></td>
        <td>${e.politician_id ? `<a href="#/politici/${e.politician_id}">${esc(e.politician_name || `Politico ${e.politician_id}`)}</a> · ` : ""}<span class="muted">${esc(e.object_label)}</span><br />${esc(e.summary)}
        ${e.details ? `<details class="log-details"><summary>Dettagli</summary><pre>${esc(JSON.stringify(e.details, null, 2))}</pre></details>` : ""}</td></tr>`).join("")}
    </tbody></table></div>
    <div class="actions"><span class="small muted">${offset + 1}–${offset + log.items.length} di ${log.total}</span>${offset ? `<button class="button button-secondary" id="log-prev">Più recenti</button>` : ""}${offset + log.items.length < log.total ? `<button class="button button-secondary" id="log-next">Precedenti</button>` : ""}</div>` : `<div class="empty">Nessuna voce nel registro con questi filtri.</div>`}`;
  view.querySelector("#log-filter").addEventListener("submit", (event) => {
    event.preventDefault();
    logFilter.utente = view.querySelector("#lf-user").value;
    logFilter.politico = Number(view.querySelector("#lf-pol").value) || null;
    showLog();
  });
  view.querySelector("#log-prev")?.addEventListener("click", () => showLog(Math.max(0, offset - 50)));
  view.querySelector("#log-next")?.addEventListener("click", () => showLog(offset + 50));
}

// --------------------------------------------------------------------- rules
function showRules() {
  const rules = [
    ["Il fatto non si tocca", "Solo elementi verificabili, con la fonte. Nessuna interpretazione, nessun aggettivo di parte."],
    ["Attribuire sempre", "Ogni opinione ha un nome e un ruolo: «secondo…», «ha dichiarato…». Mai «si dice», «molti pensano»."],
    ["Stesso spazio per tutti", "Destra e sinistra: stesso numero di punti, stessa lunghezza, stesso livello di dettaglio, stesso tono."],
    ["Chi tace, tace", "Se uno schieramento non si è espresso, lo si scrive. Non si inventa una posizione plausibile."],
    ["Numeri con fonte e data", "Cifra, unità, anno, fonte. Se due fonti divergono si riportano entrambe e si spiega la differenza."],
    ["Linguaggio semplice", "Frasi corte, termini tecnici spiegati subito. Si scrive per chi non ha studiato politica."],
    ["Titoli neutri", "Dicono cosa è successo, non cosa pensare. Niente «finalmente», «scandalo», «storico», «attacca», «affonda»."],
    ["Due persone per contenuto", "Chi scrive non è chi verifica. Ogni scheda riporta data di aggiornamento, redattore e verificatore."],
  ];
  view.innerHTML = `<div class="page-head"><div><p class="eyebrow">Modelli di scrittura</p><h1>Le otto regole che valgono sempre</h1>
    <p>Valgono per ogni contenuto, dal Presidente del Consiglio al consigliere di un piccolo comune. Se un modello e una regola sembrano in conflitto, vince la regola. La console controlla in automatico quelle verificabili.</p></div></div>
    <div class="rules-grid">${rules.map(([title, text], i) => `<div class="rule"><b>${i + 1}</b><h3>${esc(title)}</h3><p class="small">${esc(text)}</p></div>`).join("")}</div>
    <section class="card" style="margin-top:20px"><h2>Convenzioni di scrittura</h2><div class="table-wrap" style="margin-top:10px"><table class="data-table"><thead><tr><th>Cosa</th><th>Come si scrive</th></tr></thead><tbody>
      <tr><td>Date</td><td>Per esteso: «16 settembre 2026». Mai «16/9». Orari 24 ore.</td></tr>
      <tr><td>Numeri e soldi</td><td>Punto per le migliaia, virgola per i decimali: «13.250.709 voti», «53,24%», «2,29 miliardi di euro».</td></tr>
      <tr><td>Parti da compilare</td><td>Tra [parentesi quadre]. Una scheda con parentesi quadre aperte non può essere pubblicata: la console la blocca.</td></tr>
      <tr><td>Fonti nel testo</td><td>Alla fine di ogni blocco, tra parentesi: (Fonte: ANSA, 16 settembre 2026).</td></tr>
      <tr><td>Aggiornamento</td><td>«Aggiornato al [data]» in testa a ogni scheda, con redattore e verificatore: il sito lo mostra in automatico.</td></tr>
      <tr><td>Tipi di fonte</td><td>Istituzionali (Gazzetta Ufficiale, camera.it, senato.it, governo.it, Ministero dell'Interno) · Agenzie (ANSA, AGI, Adnkronos) · Stampa di aree diverse · Tecniche (ISTAT, Banca d'Italia, Ufficio parlamentare di bilancio).</td></tr>
      <tr><td>Il politico</td><td>Non scrive mai la propria scheda. I suoi comunicati sono una fonte da citare, non da copiare.</td></tr>
    </tbody></table></div></section>
    <section class="card"><h2>Checklist prima di pubblicare</h2><ul class="findings" style="margin-top:10px">${CHECKLIST.map((text) => `<li class="ok">${esc(text)}</li>`).join("")}</ul>
      <p class="small muted" style="margin-top:10px">Chi verifica la spunta voce per voce prima di approvare.</p></section>
    <section class="card"><h2>Cosa controlla la console</h2><ul class="item-sources" style="margin-top:8px">
      <li><strong>Blocca la pubblicazione:</strong> parentesi quadre aperte; fonti mancanti o che puntano a una home; notizia senza una fonte istituzionale o di agenzia e senza una testata per ciascuna area (una pubblicazione ufficiale, tipo elenco istituzionale, basta la pagina ufficiale); posizione o incarico senza data; chi ha scritto che prova ad approvare.</li>
      <li><strong>Avvisa:</strong> lunghezze fuori indicazione, squilibrio destra/sinistra, titoli con parole cariche, giudizi, opinioni senza nome, date abbreviate.</li>
      <li><strong>Punteggio:</strong> conta solo le promesse pubblicate, classificate e con uno stato approvato. «Non mantenuta» richiede due persone diverse da chi l'ha proposta e un motivo tra scadenza passata, mandato finito o rinuncia esplicita.</li>
    </ul></section>`;
}

// ---------------------------------------------------------------------- boot
const saved = readToken();
if (saved) signIn(saved);
else showLogin();


// ------------------------------------------------------------------ symbols
// Party logos and coats of arms of regions and provinces. Each upload is a
// proposal: it goes public only when another member approves it in the queue.
const SYMBOL_TABS = [["party", "Partiti"], ["region", "Regioni"], ["province", "Province"], ["politician", "Foto dei politici"]];
let symbolFilter = "";

function symbolThumb(item, stored = null, kind = "") {
  const photo = kind === "politician";
  if (item.symbol) return `<img class="symbol-thumb${photo ? " is-photo" : ""}" src="${esc(item.symbol.url)}" alt="" width="48" height="48" />`;
  if (stored) return `<img class="symbol-thumb is-photo" src="${esc(stored.url)}" alt="" width="48" height="48" />`;
  if (photo) {
    const words = item.name.split(/\s+/).filter(Boolean);
    return `<span class="symbol-thumb is-empty" aria-hidden="true">${esc(`${[...words[0]][0]}${[...words[words.length - 1]][0]}`.toUpperCase())}</span>`;
  }
  const source = item.abbreviation || (/^[A-Z]{2}$/.test(item.key) ? item.key : item.name);
  const letters = String(source).replace(/[^\p{L}\p{N}]/gu, "").slice(0, 3);
  return `<span class="symbol-thumb is-empty" aria-hidden="true">${esc(letters.toUpperCase())}</span>`;
}

async function showSymbols(kind) {
  if (!SYMBOL_TABS.some(([key]) => key === kind)) kind = "party";
  const data = await api("/simboli");
  const items = data[kind];
  const withLogo = items.filter((item) => item.symbol).length;
  const q = symbolFilter.trim().toLocaleLowerCase("it");
  const shown = items.filter((item) => !q || `${item.name} ${item.abbreviation || ""} ${item.key}`.toLocaleLowerCase("it").includes(q));
  const photo = kind === "politician";
  const noun = photo ? "foto" : "logo";
  // Photos already stored on the site before the redazione flow: they stay until replaced.
  let stored = {};
  if (photo) {
    try { stored = await (await fetch("/portraits")).json(); } catch { stored = {}; }
  }
  const storedFor = (item) => (photo && !item.symbol && stored[item.key]?.url?.startsWith("/portraits/") ? stored[item.key] : null);
  view.innerHTML = `<div class="page-head"><div><p class="eyebrow">Elenchi</p><h1>${photo ? "Foto dei politici" : "Partiti e territori"}</h1>
    <p>${photo
      ? "La foto di ogni politico pubblicato la carica la redazione: il sito non prende immagini da Camera, Senato o Governo. Serve il credito, la licenza e la pagina di provenienza, e la deve approvare un'altra persona. Le foto già presenti restano finché non le sostituisci."
      : "Loghi dei partiti e stemmi di regioni e province: li vede il cittadino nella registrazione, nel feed e nelle schede. Ogni logo serve con credito, licenza e pagina di provenienza, e va approvato da un'altra persona."}</p></div></div>
    <nav class="filters" aria-label="Elenco">${SYMBOL_TABS.map(([key, label]) => `<a class="filter-link" href="#/simboli/${key}" aria-current="${key === kind ? "page" : "false"}">${label} <span class="count">${data[key].length}</span></a>`).join("")}</nav>
    <div class="summary-strip">
      <div class="tile"><strong>${items.length}</strong><span>${kind === "party" ? "partiti nell'elenco" : kind === "region" ? "regioni (ISTAT)" : kind === "province" ? "province (ISTAT)" : "schede pubblicate"}</span></div>
      <div class="tile"><strong>${withLogo}</strong><span>con ${noun} della redazione${photo ? ` (${items.filter((item) => storedFor(item)).length} con foto già presente)` : ""}</span></div>
      <div class="tile"><strong>${items.filter((item) => item.pending.length).length}</strong><span>${noun} in verifica</span></div>
    </div>
    ${kind === "party" ? newPartyForm(data.new_parties) : ""}
    ${(kind === "region" || kind === "province") && items.length < (kind === "region" ? 20 : 100) ? `<p class="notice">L'elenco ISTAT non è completo in questo database. Per caricare tutte le regioni, province e comuni esegui <code>scripts\\sync_reference_data.cmd</code> (serve internet).</p>` : ""}
    <div class="field symbol-search"><label for="symbol-q">Cerca</label><input id="symbol-q" type="search" value="${esc(symbolFilter)}" autocomplete="off" /></div>
    <ul class="symbol-list">${shown.map((item) => `<li>
      ${symbolThumb(item, storedFor(item), kind)}
      <div class="symbol-text"><strong>${esc(item.name)}</strong>${item.abbreviation ? ` <span class="muted">${esc(item.abbreviation)}</span>` : ""}${kind === "province" ? ` <span class="muted">${esc(item.key)}</span>` : ""}
        <p class="small muted">${item.symbol ? `Pubblicato · ${esc(item.symbol.credit)} · ${esc(item.symbol.license)} · approvato da ${esc(item.symbol.approved_by)}` : storedFor(item) ? `Foto già presente · ${esc(storedFor(item).credit)} · resta finché non la sostituisci` : photo ? "Nessuna foto" : "Nessun logo pubblicato"}</p>
        ${item.pending.length ? `<div class="pending-symbol"><img src="${esc(item.pending[0].payload.image_url)}" alt="${photo ? "Foto proposta" : "Logo proposto"}" width="40" height="40" /><p class="small"><strong>Proposto</strong> da ${esc(item.pending[0].created_by)} · ${esc(item.pending[0].payload.credit)} · ${esc(item.pending[0].payload.license_label)} · ${sourceLink({ url: item.pending[0].payload.source_url, name: "fonte" })}</p></div>` : ""}</div>
      <div class="symbol-actions">
        ${item.pending.length ? reviewControls(item.pending[0]) : `<button type="button" class="button button-secondary" data-symbol="${esc(item.key)}" data-symbol-name="${esc(item.name)}">${item.symbol || storedFor(item) ? `Sostituisci ${noun}` : `Carica ${noun}`}</button>`}
        ${kind === "party" && !item.pending_edit.length ? `<button type="button" class="button button-secondary" data-edit-party="${esc(item.key)}">Modifica</button>` : ""}
      </div>
      ${item.pending_edit.length ? `<div class="pending-edit"><p class="small"><strong>Modifica proposta</strong> da ${esc(item.pending_edit[0].created_by)}: ${esc(item.pending_edit[0].summary)}. Motivo: ${esc(item.pending_edit[0].payload.reason)}</p>${reviewControls(item.pending_edit[0])}</div>` : ""}
    </li>`).join("") || `<li class="empty">Nessun risultato.</li>`}</ul>`;
  const search = view.querySelector("#symbol-q");
  search.addEventListener("input", () => {
    symbolFilter = search.value;
    const position = search.selectionStart;
    showSymbols(kind).then(() => { const again = view.querySelector("#symbol-q"); again.focus(); again.setSelectionRange(position, position); }).catch(() => {});
  });
  view.querySelectorAll("[data-symbol]").forEach((button) => button.addEventListener("click", async () => {
    const proposal = await symbolDialog(kind, button.dataset.symbolName, photo ? data.portrait_licenses : data.licenses);
    if (!proposal) return;
    try {
      const image = await api("/immagini", { method: "POST", body: { data: proposal.data, credit: proposal.credit, alt: `${photo ? "Foto" : "Simbolo"}: ${button.dataset.symbolName}` } });
      await api("/simboli", { method: "POST", body: { kind, key: button.dataset.symbol, image_id: image.id, credit: proposal.credit, license: proposal.license, source_url: proposal.source_url } });
      toast(photo ? "Foto proposta: ora la deve approvare un'altra persona." : "Logo proposto: ora lo deve approvare un'altra persona.");
      showSymbols(kind);
    } catch (error) {
      toast(error.findings?.map((f) => f.message).join(" ") || error.message, true);
    }
  }));
  view.querySelectorAll("[data-edit-party]").forEach((button) => button.addEventListener("click", async () => {
    const party = items.find((item) => item.key === button.dataset.editParty);
    const edit = await partyEditDialog(party);
    if (!edit) return;
    try {
      await api(`/partiti/${party.key}`, { method: "PUT", body: edit });
      toast("Modifica proposta: la applica un'altra persona approvandola.");
      showSymbols("party");
    } catch (error) {
      toast(error.findings?.map((f) => f.message).join(" ") || error.message, true);
    }
  }));
  view.querySelectorAll("[data-review]").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const action = event.submitter?.value;
    const id = form.dataset.review;
    try {
      if (action === "approva") await api(`/coda/change/${id}/approva`, { method: "POST", body: {} });
      else await api(`/coda/change/${id}/rifiuta`, { method: "POST", body: { note: form.reason.value } });
      toast(action === "approva" ? "Approvato e pubblicato." : "Respinto.");
      showSymbols(kind);
      refreshCount();
    } catch (error) {
      toast(error.message, true);
    }
  }));
  view.querySelector("#party-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      await api("/partiti", { method: "POST", body: Object.fromEntries(new FormData(form)) });
      toast("Partito proposto: entra nell'elenco dopo l'approvazione di un'altra persona.");
      showSymbols("party");
    } catch (error) {
      toast(error.findings?.map((f) => f.message).join(" ") || error.message, true);
    }
  });
}

const REJECT_REASONS = ["Non più attivo", "Non è un partito", "Duplicato di una voce esistente", "Logo non corretto o non ufficiale", "Licenza non verificabile"];
function reviewControls(item) {
  if (item.created_by === state.me?.name) return `<p class="small muted">In attesa di un'altra persona</p>`;
  return `<form class="review-inline" data-review="${esc(item.id)}">
    <button class="button button-approve" type="submit" value="approva">Approva</button>
    <select name="reason" aria-label="Motivo">${REJECT_REASONS.map((reason) => `<option>${esc(reason)}</option>`).join("")}</select>
    <button class="button button-danger" type="submit" value="rifiuta">Respingi</button>
  </form>`;
}

function newPartyForm(pending) {
  return `<details class="card new-party"><summary><strong>Aggiungi un partito</strong> <span class="muted small">— nome ufficiale e una fonte che lo attesti</span></summary>
    <form id="party-form" class="stack" style="margin-top:12px">
      <div class="grid-2">
        <div class="field"><label for="party-name">Nome ufficiale</label><input id="party-name" name="name" type="text" required minlength="2" maxlength="300" /></div>
        <div class="field"><label for="party-abbr">Sigla <span class="hint">facoltativa</span></label><input id="party-abbr" name="abbreviation" type="text" maxlength="40" /></div>
        <div class="field"><label for="party-site">Sito ufficiale <span class="hint">https://…</span></label><input id="party-site" name="website" type="url" /></div>
        <div class="field"><label for="party-source">Fonte <span class="hint">statuto, registro dei partiti, sito</span></label><input id="party-source" name="source_url" type="url" required /></div>
      </div>
      <div class="actions"><button class="button button-primary" type="submit">Proponi il partito</button></div>
    </form>
  </details>
  ${pending.length ? `<section class="card pending-parties"><h2>Partiti proposti <span class="count">${pending.length}</span></h2>
    <p class="small muted">Approva solo i partiti attivi oggi; respingi quelli sciolti, i duplicati e le voci che non sono partiti.</p>
    <ul class="symbol-list">${pending.map((item) => `<li>
      <span class="symbol-thumb is-empty" aria-hidden="true">${esc(String(item.payload.abbreviation || item.payload.name).replace(/[^\p{L}\p{N}]/gu, "").slice(0, 3).toUpperCase())}</span>
      <div class="symbol-text"><strong>${esc(item.payload.name)}</strong>${item.payload.abbreviation ? ` <span class="muted">${esc(item.payload.abbreviation)}</span>` : ""}
        <p class="small muted">Proposto da ${esc(item.created_by)} · fonte ${sourceLink({ url: item.payload.source_url })}${item.payload.website ? ` · sito ${sourceLink({ url: item.payload.website })}` : ""}</p></div>
      ${reviewControls(item)}
    </li>`).join("")}</ul></section>` : ""}`;
}

function partyEditDialog(party) {
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "crop-dialog";
    dialog.innerHTML = `<form method="dialog" class="stack">
      <h2>Modifica: ${esc(party.name)}</h2>
      <div class="field"><label for="pe-name">Nome ufficiale</label><input id="pe-name" type="text" required minlength="2" maxlength="300" value="${esc(party.name)}" /></div>
      <div class="field"><label for="pe-abbr">Sigla</label><input id="pe-abbr" type="text" maxlength="40" value="${esc(party.abbreviation || "")}" /></div>
      <div class="field"><label for="pe-site">Sito ufficiale <span class="hint">https://…</span></label><input id="pe-site" type="url" value="${esc(party.website || "")}" /></div>
      ${party.symbol ? `<label class="check"><input id="pe-logo" type="checkbox" /> Rimuovi il logo pubblicato</label>` : ""}
      <div class="field"><label for="pe-reason">Perché cambia</label><input id="pe-reason" type="text" required maxlength="500" /></div>
      <div class="actions"><button class="button button-primary" value="ok">Proponi la modifica</button><button class="button button-secondary" value="cancel" formnovalidate>Annulla</button></div>
    </form>`;
    document.body.append(dialog);
    dialog.addEventListener("close", () => {
      const result = dialog.returnValue === "ok" ? {
        name: dialog.querySelector("#pe-name").value.trim(),
        abbreviation: dialog.querySelector("#pe-abbr").value.trim(),
        website: dialog.querySelector("#pe-site").value.trim(),
        remove_logo: Boolean(dialog.querySelector("#pe-logo")?.checked),
        reason: dialog.querySelector("#pe-reason").value.trim(),
      } : null;
      dialog.remove();
      resolve(result);
    });
    dialog.showModal();
  });
}

// Logos are not cropped: the whole image is fitted inside a transparent square.
function symbolDialog(kind, name, licenses) {
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "crop-dialog";
    dialog.innerHTML = `<form method="dialog" class="stack">
      <h2>${kind === "party" ? "Logo" : kind === "politician" ? "Foto" : "Stemma"}: ${esc(name)}</h2>
      <p class="small muted">${kind === "politician"
        ? "Carica una foto di cui conosci autore e licenza (per esempio da Wikimedia Commons o autorizzata dalla persona). Il volto al centro: verrà ritagliata in un quadrato."
        : "Usa il file ufficiale o quello di Wikimedia Commons. Niente ricostruzioni o versioni ridisegnate."}</p>
      <div class="field"><label for="sym-file">Immagine <span class="hint">PNG, JPEG o WebP</span></label><input id="sym-file" type="file" accept="image/png,image/jpeg,image/webp" required /></div>
      <div class="symbol-stage"><canvas width="256" height="256" aria-label="Anteprima"></canvas></div>
      <div class="field"><label for="sym-credit">Titolare o autore</label><input id="sym-credit" type="text" required maxlength="300" /></div>
      <div class="field"><label for="sym-license">Licenza</label><select id="sym-license" required><option value="">Scegli…</option>${licenses.map((item) => `<option value="${esc(item.key)}">${esc(item.label)}</option>`).join("")}</select></div>
      <div class="field"><label for="sym-source">Pagina di provenienza <span class="hint">https://…</span></label><input id="sym-source" type="url" required /></div>
      <div class="actions"><button class="button button-primary" value="ok">Proponi</button><button class="button button-secondary" value="cancel" formnovalidate>Annulla</button></div>
    </form>`;
    document.body.append(dialog);
    const canvas = dialog.querySelector("canvas");
    const ctx = canvas.getContext("2d");
    let ready = false;
    dialog.querySelector("#sym-file").addEventListener("change", (event) => {
      const file = event.target.files[0];
      ready = false;
      ctx.clearRect(0, 0, 256, 256);
      if (!file) return;
      if (!/^image\/(jpeg|png|webp)$/.test(file.type)) { toast("Usa un file PNG, JPEG o WebP.", true); return; }
      const reader = new FileReader();
      const img = new Image();
      img.onload = () => {
        ctx.clearRect(0, 0, 256, 256);
        if (kind === "politician") {
          // Fill the square: centre crop, slightly towards the top where the face usually is.
          const side = Math.min(img.width, img.height);
          const sx = (img.width - side) / 2;
          const sy = Math.max(0, Math.min(img.height - side, (img.height - side) * 0.25));
          ctx.drawImage(img, sx, sy, side, side, 0, 0, 256, 256);
        } else {
          const k = Math.min(232 / img.width, 232 / img.height);
          const w = img.width * k, h = img.height * k;
          ctx.drawImage(img, (256 - w) / 2, (256 - h) / 2, w, h);
        }
        ready = true;
      };
      reader.onload = () => { img.src = reader.result; };
      reader.readAsDataURL(file);
    });
    dialog.addEventListener("close", () => {
      const ok = dialog.returnValue === "ok" && ready;
      const result = ok ? {
        data: kind === "politician" ? canvas.toDataURL("image/jpeg", 0.9) : canvas.toDataURL("image/png"),
        credit: dialog.querySelector("#sym-credit").value.trim(),
        license: dialog.querySelector("#sym-license").value,
        source_url: dialog.querySelector("#sym-source").value.trim(),
      } : null;
      if (dialog.returnValue === "ok" && !ready) toast("Scegli prima l'immagine.", true);
      dialog.remove();
      resolve(result);
    });
    dialog.showModal();
  });
}
