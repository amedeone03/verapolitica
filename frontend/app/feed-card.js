// VeraPolitica — feed card, shared by the public feed (/app) and the
// redazione console preview (/redazione). One function, same markup.
//
//   [CATEGORY BAND in the tone colour]
//   [badge · date]                [aside]
//   (o) Name     (o) Name        round image + party or role
//   Institution
//   Title
//   Summary                       ("Mostra altro" when long)
//   Info · Fonti · Chiedi
//   [coverage]  [iter: 4 steps]  status · since
//   ♡ 12  ⟲  [external link]               [save] [share]
//
// Reactions: tap the heart; press and hold (or ArrowUp on the keyboard) for
// ❤️ 😡 🎉 😢. Drawn with the system emoji, so on iPhone and Mac they are Apple's.

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
  heart: '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>',
  repost: '<path d="m2 9 3-3 3 3"/><path d="M13 18H7a2 2 0 0 1-2-2V6"/><path d="m22 15-3 3-3-3"/><path d="M11 6h6a2 2 0 0 1 2 2v10"/>',
};
export function cardIcon(name, size = 16, filled = false) {
  return `<svg class="vp-icon" aria-hidden="true" focusable="false" viewBox="0 0 24 24" width="${size}" height="${size}" fill="${filled ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${PATHS[name] || ""}</svg>`;
}

// The four reactions, in picker order. Codes match the API.
export const REACTIONS = [
  { code: "heart", emoji: "❤️", label: "Cuore" },
  { code: "angry", emoji: "😡", label: "Arrabbiato" },
  { code: "party", emoji: "🎉", label: "Festa" },
  { code: "tears", emoji: "😢", label: "Lacrime" },
];
const REACTION = Object.fromEntries(REACTIONS.map((item) => [item.code, item]));

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
// "Oggi", "Ieri", else the short date: how timelines read.
export function feedDate(value, now = new Date()) {
  const [y, m, d] = String(value || "").slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return "";
  const day = Date.UTC(y, m - 1, d);
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const diff = Math.round((today - day) / 86400000);
  if (diff === 0) return "Oggi";
  if (diff === 1) return "Ieri";
  return shortDate(value);
}
const NAME_PARTICLES = new Set(["di", "de", "del", "della", "delle", "dei", "degli", "da", "dal", "lo", "la", "le", "e", "y", "van", "von"]);

export function displayPersonName(given, family = "") {
  const parts = [given, family].map((part) => String(part ?? "").trim()).filter(Boolean);
  const words = parts.join(" ").split(/\s+/).filter(Boolean);
  return words.map((word, index) => {
    const bits = word.split(/(['’])/);
    return bits.map((bit) => {
      if (!bit || bit === "'" || bit === "’") return bit;
      const lower = bit.toLocaleLowerCase("it");
      if (index > 0 && NAME_PARTICLES.has(lower)) return lower;
      return lower.charAt(0).toLocaleUpperCase("it") + lower.slice(1);
    }).join("");
  }).join(" ");
}

// Photos are served by this site only: /media (uploaded and approved by the
// redazione) or /portraits (files already stored). No image is loaded from
// Camera, Senato, Governo or any other outside host.
export function hostedImageUrl(value) {
  return typeof value === "string" && /^\/(media\/\d+|portraits\/\d+\/image)$/.test(value) ? value : null;
}

function safeUrl(value) {
  if (typeof value === "string" && /^\/(media|portraits)\//.test(value)) return value;
  return hostedImageUrl(value);
}
function initials(name) {
  return String(name || "").split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function avatar(person, resolvePortrait) {
  let url = person.image_url;
  if (url && url.startsWith("politician:")) url = resolvePortrait ? resolvePortrait(Number(url.split(":")[1])) : null;
  const src = url ? safeUrl(url) : null;
  return `<span class="vp-avatar">${src ? `<img src="${esc(src)}" alt="" loading="lazy" decoding="async" width="56" height="56" referrerpolicy="no-referrer" />` : `<span aria-hidden="true">${esc(initials(displayPersonName(person.name)))}</span>`}</span>`;
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
      <p class="vp-coverage-legend">${parts.filter(([, , n]) => n).map(([key, name, n]) => `<span class="cov-${key}">${n} ${esc(name)}</span>`).join("")}<span class="vp-coverage-total">${total} ${total === 1 ? "fonte" : "fonti"}</span></p>
    </div>`;
}

/** The post id behind a card URL ("./?post=12" → 12), or null. */
export function postIdOf(url) {
  const match = /^\.\/\?post=(\d{1,9})$/.exec(String(url || ""));
  return match ? Number(match[1]) : null;
}

function reactionInner(mine, total) {
  const icon = mine && REACTION[mine]
    ? `<span class="vp-react-emoji" aria-hidden="true">${REACTION[mine].emoji}</span>`
    : `<span class="vp-react-heart">${cardIcon("heart", 20)}</span>`;
  return `${icon}<span class="vp-react-count"${total ? "" : " hidden"}>${total ? compactCount(total) : ""}</span>`;
}

// 9 · 999 · 1.284 → "1,3 mila": counts never push the action row off one line.
const COUNT = typeof Intl !== "undefined" ? new Intl.NumberFormat("it-IT", { notation: "compact", maximumFractionDigits: 1 }) : null;
export function compactCount(value) {
  const n = Number(value) || 0;
  return n < 1000 || !COUNT ? String(n) : COUNT.format(n).replace(/\s/g, "\u00a0");
}

function reactionLabel(mine, total) {
  const own = mine && REACTION[mine] ? `La tua reazione: ${REACTION[mine].label}` : "Reagisci con un cuore";
  return `${own}${total ? `, ${total} ${total === 1 ? "reazione" : "reazioni"}` : ""}. Tieni premuto per altre reazioni`;
}

/**
 * item: { key, url, title, summary, occurred_on, place, sources: [{title,url}], card }
 * options: { resolvePortrait(id) -> url, saved: bool, shared: bool, preview: bool, index: number }
 */
export function renderFeedCard(item, options = {}) {
  const card = item.card || {};
  const key = String(item.key || item.url || "card").replace(/[^a-z0-9_-]/gi, "-");
  const tone = card.tone || "navy";
  const badge = card.badge || { label: "Dalla redazione", tone: "plain" };
  const date = feedDate(badge.date || item.occurred_on);
  const people = card.people || [];
  const feature = people.length === 1;
  // Parties already shown under a person are not repeated.
  const shownParties = new Set(people.map((person) => person.party_id).filter(Boolean));
  const extraParties = (card.parties || []).filter((party) => !shownParties.has(party.id));
  const partyById = new Map((card.parties || []).map((party) => [party.id, party]));
  const sources = (item.sources || []).map((source) => {
    const url = safeUrl(source.url);
    return url ? `<li><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(source.title || source.name || new URL(url).hostname)} ${cardIcon("external", 13)}</a></li>` : "";
  }).filter(Boolean);
  const summary = item.summary || "";
  const long = summary.length > 220;
  const iterData = card.iter;
  const link = card.link && safeUrl(card.link.url);
  const href = options.preview ? "#" : item.url;
  const postId = options.preview ? null : postIdOf(item.url);
  const question = `Spiegami: ${item.title}`;
  const badgeDate = badge.date || item.occurred_on;
  const aside = card.aside || item.place;
  // Entrance (choreograph): only the first three cards, lead first, gaps shrinking (0, 60, 100ms).
  const ENTER = [[0, 10], [60, 6], [100, 6]];
  const enter = Number.isInteger(options.index) && options.index < ENTER.length ? ENTER[options.index] : null;
  const style = enter ? ` style="--vp-delay:${enter[0]}ms;--vp-rise:${enter[1]}px"` : "";
  return `<article class="vp-card tone-${esc(tone)}${feature ? " is-feature" : ""}${options.preview ? " is-preview" : ""}${enter ? " is-entering" : ""}" data-card="${esc(key)}"${style}>
    <header class="vp-band">${cardIcon(CATEGORY_ICON[card.category] || "news", 16)}<span>${esc(card.category_label || "Notizia")}</span></header>
    <div class="vp-sub">
      <span class="vp-badge badge-${esc(badge.tone || "plain")}">${esc(badge.label)}${badgeDate ? ` · ${esc(feedDate(badgeDate))}` : ""}</span>
      ${aside ? `<span class="vp-aside vp-place">${esc(aside)}</span>` : ""}
    </div>
    <div class="vp-body">
      ${people.length ? `<ul class="vp-people">${people.map((person) => {
        const name = displayPersonName(person.name);
        return `<li>${avatar({ ...person, name }, options.resolvePortrait)}<span class="vp-person-text">${person.politician_id && !options.preview ? `<a href="./?politician=${encodeURIComponent(person.politician_id)}">${esc(name)}</a>` : `<strong>${esc(name)}</strong>`}${person.role ? `<small>${partyLogo(partyById.get(person.party_id))}${esc(person.role)}</small>` : ""}</span></li>`;
      }).join("")}</ul>` : ""}
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
      <div class="vp-react-wrap">
        <button type="button" class="vp-action vp-react" ${postId ? `data-react-post="${postId}"` : "disabled"} data-mine="" aria-pressed="false" aria-haspopup="true" aria-label="${esc(reactionLabel(null, 0))}">${reactionInner(null, 0)}</button>
      </div>
      <button type="button" class="vp-action vp-repost" data-card-repost="${esc(item.url)}" data-card-title="${esc(item.title)}" aria-pressed="${options.shared ? "true" : "false"}" aria-label="${options.shared ? "Ricondivisa nel tuo profilo: togli" : "Ricondividi nel tuo profilo"}">${cardIcon("repost", 20)}</button>
      ${link ? `<a class="vp-outline" href="${esc(link)}" target="_blank" rel="noopener noreferrer">${esc(card.link.label)} ${cardIcon("external", 14)}</a>` : ""}
      <span class="vp-foot-spacer"></span>
      <button type="button" class="vp-action vp-save" data-card-save="${esc(item.url)}" data-card-title="${esc(item.title)}" aria-pressed="${options.saved ? "true" : "false"}" aria-label="${options.saved ? "Salvata nel profilo: togli" : "Salva nel profilo"}">${cardIcon("bookmark", 20, options.saved)}</button>
      <button type="button" class="vp-action" data-card-share="${esc(item.url)}" data-card-title="${esc(item.title)}" aria-label="Condividi">${cardIcon("share", 20)}</button>
    </footer>
  </article>`;
}

/** Fill reaction counts and the reader's own reaction into rendered cards. */
export function applyReactions(container, summaries = []) {
  if (!container) return;
  for (const summary of summaries) {
    for (const button of container.querySelectorAll(`[data-react-post="${Number(summary.post_id)}"]`)) {
      setReactionButton(button, summary, false);
    }
  }
}

function setReactionButton(button, summary, animate) {
  const mine = summary.mine && REACTION[summary.mine] ? summary.mine : null;
  const total = Number(summary.total) || 0;
  const changed = button.dataset.mine !== (mine || "");
  button.dataset.mine = mine || "";
  button.dataset.counts = JSON.stringify(summary.counts || {});
  button.setAttribute("aria-pressed", String(Boolean(mine)));
  button.setAttribute("aria-label", reactionLabel(mine, total));
  button.innerHTML = reactionInner(mine, total);
  if (animate && changed && mine) button.querySelector(".vp-react-emoji")?.classList.add("is-popping");
}

const LONG_PRESS_MS = 380;
const reduceMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * One delegated listener per container: "Altro", "Fonti", reactions, re-share, save, share.
 * handlers: {
 *   onSave(url, title) -> bool,
 *   onRepost(url, title) -> bool,
 *   onReact(postId, code|null) -> Promise<summary|null>   (null: not allowed, keep as it was)
 * }
 */
export function bindFeedCards(container, { onSave, onRepost, onReact } = {}) {
  if (!container || container.dataset.cardsBound) return;
  container.dataset.cardsBound = "1";
  let press = null;       // { button, timer, opened, pointerId }
  let picker = null;      // { root, button, keyboard }
  let swallowClick = false;

  const react = async (button, code) => {
    if (!onReact) return;
    const before = { mine: button.dataset.mine || null, counts: JSON.parse(button.dataset.counts || "{}") };
    const counts = { ...before.counts };
    if (before.mine) counts[before.mine] = Math.max(0, (counts[before.mine] || 0) - 1);
    if (code) counts[code] = (counts[code] || 0) + 1;
    const optimistic = { mine: code, counts, total: Object.values(counts).reduce((sum, n) => sum + (Number(n) || 0), 0) };
    setReactionButton(button, optimistic, !reduceMotion());
    try {
      const result = await onReact(Number(button.dataset.reactPost), code);
      if (result === null) setReactionButton(button, { ...before, total: Object.values(before.counts).reduce((s, n) => s + (Number(n) || 0), 0) }, false);
      else if (result) setReactionButton(button, result, false);
    } catch {
      setReactionButton(button, { ...before, total: Object.values(before.counts).reduce((s, n) => s + (Number(n) || 0), 0) }, false);
    }
  };

  const closePicker = (restoreFocus = false) => {
    if (!picker) return;
    const { root, button } = picker;
    picker = null;
    button.setAttribute("aria-expanded", "false");
    if (restoreFocus) button.focus();
    if (reduceMotion() || root.dataset.keyboard) { root.remove(); return; }
    root.classList.add("is-leaving");
    root.addEventListener("transitionend", () => root.remove(), { once: true });
    setTimeout(() => root.remove(), 200);
  };

  const openPicker = (button, { keyboard = false } = {}) => {
    closePicker();
    const counts = JSON.parse(button.dataset.counts || "{}");
    const mine = button.dataset.mine;
    const root = document.createElement("div");
    root.className = "vp-picker";
    root.setAttribute("role", "menu");
    root.setAttribute("aria-label", "Reazioni");
    if (keyboard) root.dataset.keyboard = "1";
    root.innerHTML = REACTIONS.map((item, index) => `<button type="button" role="menuitemradio" aria-checked="${mine === item.code}" class="vp-picker-item${mine === item.code ? " is-mine" : ""}" data-react-code="${item.code}" style="--vp-delay:${[0, 25, 45, 60][index]}ms" aria-label="${esc(item.label)}${counts[item.code] ? `, ${counts[item.code]}` : ""}"><span class="vp-picker-emoji" aria-hidden="true">${item.emoji}</span><span class="vp-picker-count" aria-hidden="true">${counts[item.code] ? compactCount(counts[item.code]) : ""}</span></button>`).join("");
    button.parentElement.appendChild(root);
    button.setAttribute("aria-expanded", "true");
    picker = { root, button };
    if (keyboard) root.querySelector(".vp-picker-item")?.focus();
    else requestAnimationFrame(() => root.classList.add("is-open"));
    if (keyboard) root.classList.add("is-open");
  };

  const choose = (code) => {
    if (!picker) return;
    const { button, root } = picker;
    const next = button.dataset.mine === code ? null : code;
    closePicker(Boolean(root.dataset.keyboard));
    react(button, next);
  };

  // Press and hold: the picker opens under the finger; slide onto an emoji and let go.
  container.addEventListener("pointerdown", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const button = target?.closest("[data-react-post]");
    if (!button || event.button > 0) return;
    swallowClick = false;
    press = {
      button,
      pointerId: event.pointerId,
      opened: false,
      timer: setTimeout(() => {
        if (!press) return;
        press.opened = true;
        swallowClick = true;
        try { navigator.vibrate?.(8); } catch { /* no haptics */ }
        openPicker(button);
      }, LONG_PRESS_MS),
    };
  });
  const hovered = (event) => {
    const under = document.elementFromPoint(event.clientX, event.clientY);
    return under instanceof Element ? under.closest("[data-react-code]") : null;
  };
  container.addEventListener("pointermove", (event) => {
    if (!press?.opened || !picker) return;
    const over = hovered(event);
    for (const item of picker.root.querySelectorAll("[data-react-code]")) item.classList.toggle("is-hover", item === over);
  });
  const endPress = (event) => {
    if (!press) return;
    clearTimeout(press.timer);
    const { opened } = press;
    press = null;
    if (opened && event?.type === "pointerup") {
      const over = hovered(event);
      if (over) choose(over.dataset.reactCode);
    }
  };
  container.addEventListener("pointerup", endPress);
  container.addEventListener("pointercancel", () => { if (press) { clearTimeout(press.timer); press = null; } });
  container.addEventListener("contextmenu", (event) => {
    const button = event.target instanceof Element ? event.target.closest("[data-react-post]") : null;
    if (!button) return;
    event.preventDefault();
    if (!picker) openPicker(button);
  });
  container.addEventListener("keydown", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    if (target.matches("[data-react-post]") && event.key === "ArrowUp") {
      event.preventDefault();
      openPicker(target, { keyboard: true });
      return;
    }
    if (!picker || !target.closest(".vp-picker")) return;
    const items = [...picker.root.querySelectorAll("[data-react-code]")];
    const index = items.indexOf(target.closest("[data-react-code]"));
    if (event.key === "Escape") { event.preventDefault(); closePicker(true); }
    else if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      items[(index + (event.key === "ArrowRight" ? 1 : -1) + items.length) % items.length].focus();
    } else if (event.key === "Tab") closePicker(false);
  });
  document.addEventListener("pointerdown", (event) => {
    if (!picker) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest(".vp-picker") || target === picker.button || picker.button.contains(target)) return;
    closePicker();
  });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && picker) closePicker(true); });

  container.addEventListener("click", async (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const pick = target.closest("[data-react-code]");
    if (pick) { choose(pick.dataset.reactCode); return; }
    const reactButton = target.closest("[data-react-post]");
    if (reactButton) {
      if (swallowClick) { swallowClick = false; return; }
      if (picker) { closePicker(); return; }
      // A tap is the heart; tapping again removes whatever reaction is set.
      react(reactButton, reactButton.dataset.mine ? null : "heart");
      return;
    }
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
    const repost = target.closest("[data-card-repost]");
    if (repost) {
      if (!onRepost) return;
      const shared = onRepost(repost.dataset.cardRepost, repost.dataset.cardTitle);
      repost.setAttribute("aria-pressed", String(shared));
      repost.setAttribute("aria-label", shared ? "Ricondivisa nel tuo profilo: togli" : "Ricondividi nel tuo profilo");
      if (shared && !reduceMotion()) {
        repost.classList.remove("is-turning");
        void repost.offsetWidth;
        repost.classList.add("is-turning");
      }
      return;
    }
    const save = target.closest("[data-card-save]");
    if (save) {
      if (!onSave) return;
      const saved = onSave(save.dataset.cardSave, save.dataset.cardTitle);
      save.setAttribute("aria-pressed", String(saved));
      save.setAttribute("aria-label", saved ? "Salvata nel profilo: togli" : "Salva nel profilo");
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
