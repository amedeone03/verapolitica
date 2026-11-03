import { bindFeedCards, partyLogo, renderFeedCard, sourceCoverage } from "./feed-card.js";
import { renderAccountForm, renderWelcome, runOnboarding } from "./onboarding.js";
const byId = (id) => document.getElementById(id);

// Lucide icons (ISC licence, lucide-static 0.460.0), inlined: no runtime dependency.
const ICON_PATHS = {
  chevronRight: '<path d="m9 18 6-6-6-6"/>',
  proposal: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  scale: '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>',
  calculator: '<rect width="16" height="20" x="4" y="2" rx="2"/><path d="M8 6h8"/><path d="M16 14v4"/><path d="M16 10h.01"/><path d="M12 10h.01"/><path d="M8 10h.01"/><path d="M12 14h.01"/><path d="M8 14h.01"/><path d="M12 18h.01"/><path d="M8 18h.01"/>',
  arrowRight: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  arrowLeft: '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
  share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" x2="15.42" y1="13.51" y2="17.49"/><line x1="15.41" x2="8.59" y1="6.51" y2="10.49"/>',
  badgeCheck: '<path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z"/><path d="m9 12 2 2 4-4"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  ask: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  mapPin: '<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/>',
  map: '<path d="M14.106 5.553a2 2 0 0 0 1.788 0l3.659-1.83A1 1 0 0 1 21 4.619v12.764a1 1 0 0 1-.553.894l-4.553 2.277a2 2 0 0 1-1.788 0l-4.212-2.106a2 2 0 0 0-1.788 0l-3.659 1.83A1 1 0 0 1 3 19.381V6.618a1 1 0 0 1 .553-.894l4.553-2.277a2 2 0 0 1 1.788 0z"/><path d="M15 5.764v15"/><path d="M9 3.236v15"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  book: '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>',
  vote: '<path d="m9 12 2 2 4-4"/><path d="M5 7c0-1.1.9-2 2-2h10a2 2 0 0 1 2 2v12H5V7Z"/><path d="M22 19H2"/>',
  flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/>',
  star: '<path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"/>',
};

export function icon(name, { size = 16, filled = false } = {}) {
  return `<svg class="icon" aria-hidden="true" focusable="false" viewBox="0 0 24 24" width="${size}" height="${size}" fill="${filled ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">${ICON_PATHS[name]}</svg>`;
}


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

// Formatters are built once: constructing Intl objects per call is slow on phones.
const DATE_UTC = new Intl.DateTimeFormat("it-IT", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
const DATE_LOCAL = new Intl.DateTimeFormat("it-IT", { day: "numeric", month: "long", year: "numeric" });
const PERCENT = new Map();

function formatDate(value) {
  if (!value) return "Non indicata";
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.valueOf())
    ? String(value)
    : DATE_UTC.format(date);
}

function formatYear(value) {
  if (!value) return "";
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.valueOf()) ? "" : String(date.getUTCFullYear());
}

function formatYearRange(start, end) {
  const from = formatYear(start);
  if (!from) return "Date non indicate";
  if (!end) return `${from}–oggi`;
  const to = formatYear(end);
  return to && to !== from ? `${from}–${to}` : from;
}

function formatPublishedAt(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? ""
    : DATE_LOCAL.format(date);
}

const PROPOSAL_TYPE_LABELS = {
  proposal: "Proposta",
  legislative_proposal: "Proposta di legge",
  government_initiative: "Iniziativa governativa",
  explicit_promise: "Promessa esplicita",
};
const PROPOSAL_STATUS_LABELS = {
  announced: "Annunciata",
  introduced: "Presentata",
  assigned: "Assegnata",
  under_review: "In esame",
  approved: "Approvata",
  rejected: "Respinta",
  withdrawn: "Ritirata",
  enacted: "Promulgata",
  completed: "Conclusa",
  superseded: "Superata",
  lapsed: "Decaduta",
  returned: "Rinviata",
};
const ACTOR_ROLE_LABELS = {
  proposer: "Proponente",
  sponsor: "Firmatario",
  co_sponsor: "Cofirmatario",
  government: "Governo",
  commitment_owner: "Titolare della promessa",
};
const REFERENDUM_TYPE_LABELS = {
  national_abrogative: "Abrogativo nazionale",
  constitutional: "Costituzionale",
  regional: "Regionale",
  municipal: "Comunale",
  consultative: "Consultivo",
  other: "Altro",
};
const REFERENDUM_STATUS_LABELS = {
  scheduled: "In programma",
  open: "Aperto",
  closed: "Chiuso",
  cancelled: "Annullato",
  completed: "Concluso",
};
const SCOPE_TYPE_LABELS = {
  national: "Nazionale",
  region: "Regionale",
  municipality: "Comunale",
};
const AFFILIATION_TYPE_LABELS = {
  member: "Membro",
  founder: "Fondatore",
  supporter: "Sostenitore",
};
const PUBLIC_UNAVAILABLE = "L'archivio pubblico non è al momento disponibile.";

function mappedLabel(map, value, fallback = "") {
  if (value == null || value === "") return fallback;
  return map[value] || titleCase(value);
}

function countLabel(n, singular, plural) {
  return `${n} ${Number(n) === 1 ? singular : plural}`;
}

const graphemes = typeof Intl !== "undefined" && Intl.Segmenter
  ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
  : null;

function firstGrapheme(value) {
  const text = String(value ?? "").trim().replace(/^[^\p{L}\p{N}]+/u, "");
  if (!text) return "";
  if (!graphemes) return text[0];
  return graphemes.segment(text)[Symbol.iterator]().next().value?.segment ?? "";
}

// Initials from whole characters (accents, non-Latin scripts), first + last word.
function initials(person) {
  const family = String(person.family_name ?? "").trim().split(/\s+/);
  const value = `${firstGrapheme(person.given_name)}${firstGrapheme(family[family.length - 1])}`;
  return value.toLocaleUpperCase() || "VP";
}

// Credited portrait dataset (official source first, then Wikimedia Commons).
const portraits = new Map();

function safeImageUrl(value) {
  // Portraits stored by the demo are served by this API (same origin).
  if (typeof value === "string" && /^\/portraits\/\d+\/image$/.test(value)) return value;
  return safeExternalUrl(value);
}

function portraitFor(person) {
  const credited = portraits.get(String(person.id));
  if (credited) return credited;
  const official = safeExternalUrl(person.profile?.image_url);
  return official ? { url: official, credit: "Fonte ufficiale", license: "Ritratto istituzionale ufficiale", source_url: official, origin: "Fonte ufficiale" } : null;
}

function portrait(person, { size = "card" } = {}) {
  const photo = portraitFor(person);
  const imageUrl = photo ? safeImageUrl(photo.url) : null;
  const name = `${person.given_name} ${person.family_name}`;
  const monogram = `<span class="monogram" aria-hidden="true">${escapeHtml(initials(person))}</span>`;
  const image = imageUrl
    ? `<img src="${escapeHtml(imageUrl)}" alt="Ritratto di ${escapeHtml(name)}" loading="${size === "hero" ? "eager" : "lazy"}" decoding="async" referrerpolicy="no-referrer" />`
    : "";
  return `<div class="portrait glass-portrait is-${size}${imageUrl ? " has-photo" : ""}"${imageUrl ? "" : ` role="img" aria-label="Nessun ritratto disponibile"`}>${monogram}${image}</div>`;
}

export function renderPhotoCredit(person) {
  const photo = portraitFor(person);
  if (!photo || !safeImageUrl(photo.url)) return "";
  const link = safeExternalUrl(photo.source_url);
  const label = photo.origin === "Wikimedia Commons"
    ? `Foto: ${photo.credit} · ${photo.license} · Wikimedia Commons`
    : `Foto: ${photo.origin}`;
  return link
    ? `<a class="photo-credit" href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)} ${icon("external", { size: 14 })}</a>`
    : `<span class="photo-credit">${escapeHtml(label)}</span>`;
}

function officeDisplayLabel(office, gender) {
  const key = String(office ?? "").trim().toLocaleLowerCase("it");
  const feminine = gender === "female";
  const mapped = {
    senator: feminine ? "Senatrice" : "Senatore",
    senatore: feminine ? "Senatrice" : "Senatore",
    deputy: feminine ? "Deputata" : "Deputato",
    deputato: feminine ? "Deputata" : "Deputato",
    "presidente del consiglio": "Presidente del Consiglio dei ministri",
    "vice presidente del consiglio": "Vicepresidente del Consiglio dei ministri",
    ministro: "Ministro",
    "ministro senza portafoglio": "Ministro senza portafoglio",
    mayor: "Sindaco",
    regional_president: "Presidente di regione",
  };
  return mapped[key] || titleCase(office);
}

function latestOpenMandate(person) {
  const mandates = [...(person.profile?.mandates || [])];
  const open = mandates.filter((item) => !item.end_date);
  const pool = open.length ? open : mandates;
  pool.sort((left, right) => String(right.start_date || "").localeCompare(String(left.start_date || "")));
  return pool[0] ?? null;
}

export function cabinetMandate(person) {
  const mandates = [...(person.profile?.mandates || [])];
  const open = mandates.filter((item) => !item.end_date);
  const pool = open.length ? open : mandates;
  const ranked = pool
    .map((mandate) => ({ mandate, rank: governmentOfficeRank(mandate.office) }))
    .filter((item) => item.rank < GOVERNMENT_RANK.length)
    .sort((a, b) => a.rank - b.rank || String(b.mandate.start_date || "").localeCompare(String(a.mandate.start_date || "")));
  return ranked[0]?.mandate ?? null;
}

function currentMandate(person) {
  return cabinetMandate(person) || latestOpenMandate(person);
}

export function currentParty(person) {
  const affiliation = (person.political_parties || []).find((item) => !item.end_date) || null;
  if (affiliation) return affiliation;
  const career = (person.career_entries || []).find(
    (item) => explicitlyCurrent(item) && item.party_or_group,
  );
  if (!career) return null;
  return { name: career.party_or_group, end_date: null };
}

function primaryMandate(person) {
  return currentMandate(person);
}

function isLegislatureNumber(value) {
  return /^\d+$/.test(String(value ?? "").trim());
}

function explicitlyCurrent(item) {
  return item?.is_current === true;
}

function mandateRole(mandate, gender) {
  // Government roles carry their full title ("Ministro della Cultura dal 06/09/2024").
  const title = String(mandate.mandate_type ?? "").replace(/\s+dal\s+\d{1,2}\/\d{1,2}\/\d{4}\s*$/i, "").trim();
  return title && !isLegislatureNumber(mandate.legislature) ? title : officeDisplayLabel(mandate.office, gender);
}

function mandateTitle(mandate, gender) {
  if (!mandate) return "Incarico non indicato";
  return isLegislatureNumber(mandate.legislature)
    ? `${officeDisplayLabel(mandate.office, gender)} — Legislatura ${mandate.legislature}`
    : `${mandateRole(mandate, gender)} · ${mandate.legislature}`;
}

export function renderPoliticianCard(person) {
  const mandate = primaryMandate(person);
  const gender = person.profile?.gender;
  return `<article class="politician-card">
    ${portrait(person)}
    <div class="card-content">
      <div class="card-title-row"><h3>${escapeHtml(person.given_name)} ${escapeHtml(person.family_name)}</h3>${renderFavoriteToggle(person)}</div>
      <p class="mandate">${escapeHtml(mandateTitle(mandate, gender))}</p>
      <p class="area">${escapeHtml(mandate?.institution ?? "Istituzione nazionale")}${mandate?.election_area ? ` · ${escapeHtml(mandate.election_area)}` : ""}</p>
      <div class="card-record" data-record-for="${escapeHtml(person.id)}"><p class="card-record-empty">Caricamento delle promesse…</p></div>
      <a class="profile-link card-link" href="./?politician=${encodeURIComponent(person.id)}">Vedi profilo ${icon("arrowRight")}</a>
    </div>
  </article>`;
}

export function fieldLabel(fieldPath) {
  const exact = {
    given_name: "Nome",
    family_name: "Cognome",
    birth_date: "Data di nascita",
    "birth_place.city": "Città di nascita",
    "birth_place.subdivision": "Provincia o regione di nascita",
    "birth_place.country": "Paese di nascita",
    gender: "Genere",
    profession: "Professione",
    image_url: "Ritratto ufficiale",
    official_homepage_url: "Sito ufficiale",
  };
  if (exact[fieldPath]) return exact[fieldPath];
  const mandateField = fieldPath.match(/^mandates\[\d+\]\.(.+)$/)?.[1];
  const mandateLabels = {
    institution: "Istituzione",
    office: "Incarico",
    legislature: "Legislatura",
    mandate_type: "Tipo di mandato",
    start_date: "Inizio mandato",
    end_date: "Fine mandato",
    election_area: "Circoscrizione",
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

function renderMandate(mandate, gender) {
  const dates = `${formatDate(mandate.start_date)}${mandate.end_date ? ` – ${formatDate(mandate.end_date)}` : " – in carica"}`;
  const context = isLegislatureNumber(mandate.legislature)
    ? `${mandate.institution} · Legislatura ${mandate.legislature}`
    : `${mandate.institution} · ${mandate.legislature}`;
  return `<div class="mandate-block">
    <strong>${escapeHtml(mandateRole(mandate, gender))}</strong>
    <p>${escapeHtml(context)}</p>
    <p>${escapeHtml(mandate.election_area || (isLegislatureNumber(mandate.legislature) ? "Circoscrizione non indicata" : "Incarico di governo"))} · ${escapeHtml(dates)}</p>
  </div>`;
}

function sourceHostLabel(url) {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "").toLocaleLowerCase("it");
    if (host === "dati.senato.it" || host === "senato.it") return "Senato della Repubblica";
    if (host === "dati.camera.it" || host === "camera.it") return "Camera dei Deputati";
    if (host === "gazzettaufficiale.it") return "Gazzetta Ufficiale";
    if (host === "governo.it") return "Presidenza del Consiglio dei ministri";
    if (host === "interno.gov.it" || host === "dait.interno.gov.it") return "Ministero dell'Interno";
    if (host === "istat.it") return "ISTAT";
    return null;
  } catch {
    return null;
  }
}

const SOURCE_KIND_LABELS = {
  official: "Fonte ufficiale",
  institutional: "Fonte istituzionale",
  news: "Fonte giornalistica",
  party_politician: "Fonte del partito o della persona",
  fact_check: "Verifica",
  other: "Fonte",
};

function sourceKindFromUrl(url) {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "").toLocaleLowerCase("it");
    if (/(senato\.it|camera\.it|governo\.it|gazzettaufficiale\.it|interno\.gov\.it|inps\.it|riformeistituzionali\.gov\.it)$/.test(host)) {
      return "official";
    }
    if (/(europa\.eu|ecrparty\.eu)$/.test(host)) return "institutional";
    if (host.includes("pagellapolitica.it")) return "fact_check";
    if (host.includes("giorgiameloni.it") || host.includes("fratelli-italia.it")) return "party_politician";
    if (/(corriere\.it|rainews\.it|ansa\.it|sky\.it|fanpage\.it|youtube\.com)$/.test(host)) return "news";
    return "other";
  } catch {
    return "other";
  }
}

function sourceKindLabel(kind, url = "") {
  if (kind && SOURCE_KIND_LABELS[kind]) return SOURCE_KIND_LABELS[kind];
  return SOURCE_KIND_LABELS[sourceKindFromUrl(url)] || "Fonte";
}

export function renderSourceCard({
  name = "",
  url = "",
  title = "",
  date = "",
  kind = "",
  extra = "",
} = {}) {
  const href = safeExternalUrl(url);
  const displayName = name || (href ? sourceHostLabel(href) : "") || "";
  if (!displayName && !href && !title) return "";
  const kindLabel = kind && !SOURCE_KIND_LABELS[kind] ? kind : sourceKindLabel(kind, href);
  // One quiet line: the name is the link; kind and date follow in muted text.
  const label = displayName || title;
  const meta = [kindLabel, displayName && title ? title : "", date].filter(Boolean).join(" · ");
  return `<p class="source-card">
    ${href ? `<a class="source-name" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)} ${icon("external", { size: 14 })}</a>` : `<span class="source-name">${escapeHtml(label)}</span>`}
    ${meta ? `<span class="source-card-meta">${escapeHtml(meta)}</span>` : ""}
    ${extra}
  </p>`;
}

function careerDedupeKey(entry) {
  return `${String(entry.role || "").toLocaleLowerCase("it")}|${String(entry.start || "").slice(0, 4)}`;
}

export function careerEntries(person) {
  const gender = person.profile?.gender;
  const entries = [];
  for (const item of person.career_entries || []) {
    entries.push({
      start: item.start_date,
      end: item.is_current ? null : item.end_date,
      role: item.role,
      institution: item.institution,
      extra: [item.organization, item.party_or_group].filter(Boolean).join(" · "),
      source: (item.sources || [])[0] || null,
      editorial: true,
      current: explicitlyCurrent(item),
    });
  }
  (person.profile?.mandates || []).forEach((mandate, index) => {
    const citation = (person.citations || []).find((item) => item.field_path.startsWith(`mandates[${index}]`));
    entries.push({
      start: mandate.start_date,
      end: mandate.end_date,
      role: mandateRole(mandate, gender),
      institution: mandate.institution,
      extra: mandate.election_area || (isLegislatureNumber(mandate.legislature) ? `Legislatura ${mandate.legislature}` : mandate.legislature),
      source: citation
        ? { name: citation.source_name, url: citation.source_url }
        : null,
      current: explicitlyCurrent(mandate),
    });
  });
  for (const office of person.territorial_offices || []) {
    const territory = office.municipality
      ? `Comune di ${office.municipality}`
      : office.region || "Territorio non indicato";
    entries.push({
      start: office.start_date,
      end: office.end_date,
      role: officeLabel(office.office),
      institution: territory,
      extra: office.municipality && office.region ? office.region : "",
      source: office.source || null,
      current: explicitlyCurrent(office),
    });
  }
  const seen = new Set();
  const unique = [];
  for (const entry of entries) {
    const key = careerDedupeKey(entry);
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(entry);
  }
  unique.sort((left, right) => {
    const byStart = String(left.start || "").localeCompare(String(right.start || ""));
    if (byStart) return byStart;
    return String(left.role || "").localeCompare(String(right.role || ""), "it");
  });
  return unique;
}

export function renderCareerTimeline(person) {
  const entries = careerEntries(person);
  if (!entries.length) {
    return `<p class="empty-note">Nessun incarico istituzionale pubblicato è ancora disponibile per questo profilo.</p>`;
  }
  return `<ol class="career-timeline">${entries.map((entry) => `<li class="career-entry${entry.current ? " is-current" : ""}">
    <span class="career-marker" aria-hidden="true"></span>
    <time${entry.start ? ` datetime="${escapeHtml(String(entry.start).slice(0, 10))}"` : ""}>${escapeHtml(formatYearRange(entry.start, entry.end))}</time>
    <div class="career-body">
      ${entry.current ? `<span class="career-current">In carica</span>` : ""}
      <strong>${escapeHtml(entry.role)}</strong>
      <p>${escapeHtml(entry.institution)}${entry.extra ? ` · ${escapeHtml(entry.extra)}` : ""}</p>
      ${entry.source ? renderSourceCard({
        name: entry.source.name,
        url: entry.source.url,
        kind: entry.source.kind || "official",
      }) : ""}
    </div>
  </li>`).join("")}</ol>`;
}

export function renderWhoIs(person) {
  const profile = person.profile || {};
  const name = `${person.given_name} ${person.family_name}`;
  const mandate = currentMandate(person);
  const party = currentParty(person);
  const place = birthPlace(profile);
  const biography = person.biography?.body;
  if (biography) {
    const bioSources = (person.biography.sources || []).map((source) => renderSourceCard({
      name: source.name,
      url: source.url,
      title: source.title,
      kind: source.kind,
    })).filter(Boolean);
    return `<section class="detail-card profile-block profile-who" id="profilo">
    <h2>Chi è</h2>
    ${biography.split(/\n+/).map((paragraph) => `<p class="who-copy">${escapeHtml(paragraph)}</p>`).join("")}
    ${bioSources.length ? `<div class="source-card-list">${bioSources.join("")}</div>` : ""}
  </section>`;
  }
  const sentences = [];
  if (mandate) {
    sentences.push(`${name} è ${mandateRole(mandate, profile.gender)} presso ${mandate.institution}.`);
  }
  const bornVerb = profile.gender === "male" ? "Nato" : profile.gender === "female" ? "Nata" : "Nato/a";
  if (person.birth_date && place !== "Non indicato") {
    sentences.push(`${bornVerb} il ${formatDate(person.birth_date)} a ${place}.`);
  } else if (person.birth_date) {
    sentences.push(`${bornVerb} il ${formatDate(person.birth_date)}.`);
  } else if (place !== "Non indicato") {
    sentences.push(`Luogo di nascita: ${place}.`);
  }
  if (profile.profession) {
    sentences.push(`Professione dichiarata nelle fonti ufficiali: ${profile.profession}.`);
  }
  if (party) {
    sentences.push(`Affiliazione di partito pubblicata: ${party.name}.`);
  }
  if (!sentences.length) return "";
  const homepage = safeExternalUrl(profile.official_homepage_url);
  const partySource = party?.source;
  const sources = [
    homepage ? renderSourceCard({ kind: "Sito ufficiale", name: "Pagina istituzionale", url: homepage }) : "",
    partySource ? renderSourceCard({ kind: "Fonte ufficiale", name: partySource.name, url: partySource.url }) : "",
  ].filter(Boolean);
  return `<section class="detail-card profile-block profile-who" id="profilo">
    <h2>Chi è</h2>
    ${sentences.map((sentence) => `<p class="who-copy">${escapeHtml(sentence)}</p>`).join("")}
    ${sources.length ? `<div class="source-card-list">${sources.join("")}</div>` : ""}
  </section>`;
}

const PROCEEDING_TYPE_LABELS = {
  judicial_proceeding: "Procedimento giudiziario",
  investigation: "Inchiesta",
  political_controversy: "Controversia politica",
  legal_controversy: "Controversia giuridica",
  media_controversy: "Controversia mediatica",
};

const PROCEEDING_OUTCOME_LABELS = {
  archived: "Archiviato",
  ongoing: "In corso",
  dismissed: "Archiviato",
  unknown: "Non indicato",
};

function proceedingTypeLabel(types = []) {
  const labels = types.map((value) => PROCEEDING_TYPE_LABELS[value] || titleCase(value));
  if (labels.length === 2) return `${labels[0]} e ${labels[1].replace(/^Controversia /i, "").toLocaleLowerCase("it")}`;
  return labels.join(" · ");
}

export function renderKeyPositions(person = {}) {
  const items = person.positions || [];
  const body = items.length
    ? `<div class="position-list">${items.map((item) => `<article class="position-card">
        <h3>${escapeHtml(item.topic)}</h3>
        <dl class="facts">
          ${fact("Posizione", item.position_statement)}
          ${fact("Dichiarazione / atto verificabile", item.verifiable_statement)}
          ${item.statement_date ? fact("Data", formatDate(item.statement_date)) : ""}
        </dl>
        <div class="source-card-list">${(item.sources || []).map((source) => renderSourceCard({
          name: source.name,
          url: source.url,
          title: source.title,
          kind: source.kind,
        })).join("")}</div>
      </article>`).join("")}</div>`
    : `<p class="empty-note">Non sono ancora disponibili posizioni verificate per questo profilo.</p>`;
  return `<section class="detail-card profile-block profile-positions" id="posizioni">
    <h2>Posizioni su temi chiave</h2>
    ${body}
  </section>`;
}

export function renderProceedings(person = {}) {
  const items = person.proceedings || [];
  const body = items.length
    ? `<div class="proceeding-list">${items.map((item) => `<article class="proceeding-card">
        <h3>${escapeHtml(item.title)}</h3>
        <p class="proceeding-meta"><span class="proceeding-type">${escapeHtml(proceedingTypeLabel(item.proceeding_types || []))}</span>${item.outcome ? `<span class="proceeding-outcome">Stato/Esito: ${escapeHtml(PROCEEDING_OUTCOME_LABELS[item.outcome] || item.outcome)}</span>` : ""}</p>
        <p class="who-copy">${escapeHtml(item.summary)}</p>
        ${item.outcome_summary ? `<p class="empty-note">${escapeHtml(item.outcome_summary)}</p>` : ""}
        <div class="source-card-list">${(item.sources || []).map((source) => renderSourceCard({
          name: source.name,
          url: source.url,
          title: source.title,
          kind: source.kind,
        })).join("")}</div>
      </article>`).join("")}</div>`
    : `<p class="empty-note">Questa sezione non contiene ancora elementi pubblicati.</p>`;
  return `<section class="detail-card profile-block profile-proceedings" id="procedimenti">
    <h2>Procedimenti e controversie</h2>
    ${body}
  </section>`;
}

export function suggestedAskQuestions(person, scorecard = null) {
  const name = `${person.given_name} ${person.family_name}`.trim();
  if (!name) return [];
  const questions = [`Quali promesse di ${name} sono ancora in corso?`];
  const pledges = scorecard?.pledges || [];
  if (pledges.some((item) => item.verdict === "not_yet_rated") || !pledges.length) {
    questions.push(`Quali promesse di ${name} non sono ancora valutate?`);
  }
  if (pledges.some((item) => item.latest_assessment)) {
    questions.push(`Quali sono le fonti delle valutazioni pubblicate su ${name}?`);
  }
  const topic = (scorecard?.strata || []).flatMap((stratum) => stratum.topics || [])[0];
  const topicName = topic ? topicLabel(topic.cap_topic_code) : "";
  const askTopics = new Set(["Economia", "Sanità", "Lavoro", "Istruzione", "Immigrazione", "Giustizia e criminalità", "Welfare", "Governo e istituzioni"]);
  if (topicName && askTopics.has(topicName)) {
    const phrase = topicName === "Giustizia e criminalità" ? "la giustizia" : topicName === "Governo e istituzioni" ? "le istituzioni" : topicName.toLocaleLowerCase("it");
    questions.push(`Quali promesse di ${name} riguardano ${phrase}?`);
  }
  return questions.slice(0, 3);
}

export function renderAskSuggestions(person, scorecard = null) {
  const questions = suggestedAskQuestions(person, scorecard);
  if (!questions.length) return "";
  const name = `${person.given_name} ${person.family_name}`;
  return `<section class="profile-ask" aria-label="Chiedi a VeraPolitica">
    <a class="profile-ask-cta" href="./?view=ask&amp;prefill=${encodeURIComponent(questions[0])}">Chiedi a VeraPolitica su ${escapeHtml(name)}</a>
    <div class="ask-suggestions">${questions.map((question) => `<a class="ask-suggestion" href="./?view=ask&amp;question=${encodeURIComponent(question)}">${escapeHtml(question)}</a>`).join("")}</div>
  </section>`;
}

export function renderTrustBlock() {
  return `<section class="detail-card profile-block profile-trust" id="metodologia-profilo">
    <h2>Come vengono verificati questi dati?</h2>
    <p>VeraPolitica utilizza fonti pubbliche e documenti verificabili. Le valutazioni delle promesse vengono pubblicate solo dopo revisione.</p>
    <a class="profile-link" href="./?view=methodology">Metodologia ${icon("arrowRight")}</a>
  </section>`;
}

function renderProfileSectionNav(sections) {
  const links = sections.filter((item) => item.href && item.label);
  if (!links.length) return "";
  // Links work without JavaScript (anchors); bindProfileSectionNav upgrades them to ARIA tabs.
  return `<nav class="profile-section-nav" aria-label="Sezioni del profilo">${
    links.map((item, index) => `<a href="${escapeHtml(item.href)}"${index === 0 ? ' aria-current="location"' : ""}>${escapeHtml(item.label)}</a>`).join("")
  }</nav>`;
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
      : `Dal ${formatDate(membership.start_date)}`)
    : (membership.end_date ? `Fino al ${formatDate(membership.end_date)}` : "Date non indicate");
  const role = membership.role && membership.role.toLocaleLowerCase() !== "membro"
    ? `<span class="group-role">${escapeHtml(membership.role)}</span>`
    : "";
  return `<article class="group-membership">
    <div>
      <strong>${escapeHtml(membership.name)}</strong>${role}
      <p>${escapeHtml(membership.institution)} · legislatura ${escapeHtml(romanLegislature(membership.legislature))}</p>
      <small>${escapeHtml(dates)}</small>
    </div>
    ${sourceUrl ? renderSourceCard({ name: membership.source?.name, url: sourceUrl }) : ""}
  </article>`;
}

export function renderParliamentaryGroups(memberships = []) {
  if (!memberships.length) {
    return `<p class="empty-note">Nessuna appartenenza a un gruppo parlamentare è al momento disponibile dalle fonti ufficiali supportate.</p>`;
  }
  const current = memberships.filter((membership) => !membership.end_date);
  const historical = memberships.filter((membership) => membership.end_date);
  return `${current.length ? `<div class="group-list">${current.map(renderGroupMembership).join("")}</div>` : ""}
    ${historical.length ? `<h3 class="previous-groups-title">Gruppi precedenti</h3><div class="group-list">${historical.map(renderGroupMembership).join("")}</div>` : ""}`;
}

function renderPartyAffiliation(affiliation) {
  const sourceUrl = safeExternalUrl(affiliation.source?.url);
  const websiteUrl = safeExternalUrl(affiliation.official_website_url);
  const dates = affiliation.start_date
    ? (affiliation.end_date
      ? `${formatDate(affiliation.start_date)} – ${formatDate(affiliation.end_date)}`
      : `Dal ${formatDate(affiliation.start_date)}`)
    : (affiliation.end_date ? `Fino al ${formatDate(affiliation.end_date)}` : "Date non indicate");
  const affiliationType = affiliation.affiliation_type
    ? `<span class="party-affiliation-type">${escapeHtml(mappedLabel(AFFILIATION_TYPE_LABELS, affiliation.affiliation_type))}</span>`
    : "";
  return `<article class="party-affiliation">
    <div>
      <strong>${websiteUrl ? `<a href="${escapeHtml(websiteUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(affiliation.name)}</a>` : escapeHtml(affiliation.name)}</strong>${affiliationType}
      <p>${escapeHtml(dates)}</p>
    </div>
    ${sourceUrl ? renderSourceCard({ name: affiliation.source?.name, url: sourceUrl }) : ""}
  </article>`;
}

export function renderPoliticalParties(affiliations = []) {
  if (!affiliations.length) {
    return `<p class="empty-note">Nessuna affiliazione di partito esplicita è al momento disponibile dalle fonti ufficiali supportate.</p>`;
  }
  const current = affiliations.filter((affiliation) => !affiliation.end_date);
  const historical = affiliations.filter((affiliation) => affiliation.end_date);
  return `${current.length ? `<div class="party-list">${current.map(renderPartyAffiliation).join("")}</div>` : ""}
    ${historical.length ? `<h3 class="previous-parties-title">Partiti precedenti</h3><div class="party-list">${historical.map(renderPartyAffiliation).join("")}</div>` : ""}`;
}

function proposalTypeLabel(value) {
  return mappedLabel(PROPOSAL_TYPE_LABELS, value, "Proposta");
}

function proposalStatusLabel(value) {
  return mappedLabel(PROPOSAL_STATUS_LABELS, value, "Non indicato");
}

function actorRoleLabel(value) {
  return mappedLabel(ACTOR_ROLE_LABELS, value, titleCase(value));
}

function renderProposalActor(actor) {
  const name = actor.politician_id
    ? `<a href="./?politician=${encodeURIComponent(actor.politician_id)}">${escapeHtml(actor.display_name)}</a>`
    : escapeHtml(actor.display_name);
  return `<span class="proposal-actor">${name}<small>${escapeHtml(actorRoleLabel(actor.role))}</small></span>`;
}

export function renderProposalTags(tags = []) {
  if (!tags.length) return "";
  return `<div class="topic-chips is-inline">${tags.map((tag) => {
    const param = tag.kind === "dossier" ? "dossier" : "topic";
    return `<a class="topic-chip is-small${tag.kind === "dossier" ? " is-dossier" : ""}" href="./?view=proposals&amp;${param}=${encodeURIComponent(tag.value)}">${escapeHtml(tag.label)}</a>`;
  }).join("")}</div>`;
}

const isPromise = (proposal) => proposal.proposal_type === "explicit_promise";

// The one state a reader needs first: the verdict for a promise, the
// institutional status for a bill. Never both in the same place.
function proposalStateChip(proposal) {
  return isPromise(proposal)
    ? renderVerdictChip(proposal.verdict || "not_yet_rated")
    : `<span class="status-chip">${escapeHtml(proposalStatusLabel(proposal.current_status))}</span>`;
}

function proposalActorNames(proposal) {
  return proposal.actors.length ? proposal.actors.map((actor) => actor.display_name).join(", ") : "Attore non indicato";
}

// List row (Ground News list + iOS grouped row): state and topic on top, the
// title, then who and when. The whole row opens the record; the official
// source is one tap further, in the record itself.
export function renderProposalCard(proposal, { showType = true } = {}) {
  const topic = proposal.tags.find((tag) => tag.kind === "topic");
  // The verdict chip already says "promise"; the type is named only for bills.
  const kicker = [showType && !isPromise(proposal) ? proposalTypeLabel(proposal.proposal_type) : "", topic?.label || ""].filter(Boolean).join(" · ");
  const date = formatDate(proposal.introduced_at);
  return `<li><a class="row-link proposal-row" href="./?proposal=${encodeURIComponent(proposal.id)}">
    ${proposal.actors[0] ? actorAvatar(proposal.actors[0], " is-small") : `<span class="actor-avatar is-small" aria-hidden="true">${icon("proposal", { size: 18 })}</span>`}
    <span class="row-text">
      <span class="proposal-row-top">${proposalStateChip(proposal)}${kicker ? `<span class="proposal-kicker">${escapeHtml(kicker)}</span>` : ""}</span>
      <strong>${escapeHtml(proposal.title)}</strong>
      <small>${escapeHtml(proposalActorNames(proposal))}${date ? ` · ${escapeHtml(date)}` : ""}</small>
    </span>
    <span class="row-chevron" aria-hidden="true">${icon("chevronRight", { size: 18 })}</span>
  </a></li>`;
}

// Verdict mix of the promises on screen (same bar as the profile record).
export function renderPromiseSummary(items, total) {
  const promises = items.filter(isPromise);
  if (!promises.length) return "";
  const counts = new Map();
  for (const item of promises) counts.set(item.verdict || "not_yet_rated", (counts.get(item.verdict || "not_yet_rated") || 0) + 1);
  const entries = VERDICT_LEGEND_ORDER.map((verdict) => ({ verdict, count: counts.get(verdict) || 0 }));
  const unrated = counts.get("not_yet_rated") || 0;
  const scope = total > items.length ? ` (le prime ${promises.length} in elenco)` : "";
  const note = unrated === promises.length
    ? "Nessuna di queste promesse ha ancora una valutazione. Ogni valutazione cita un documento ufficiale ed è approvata da un secondo membro della redazione."
    : "Ogni valutazione cita un documento ufficiale ed è approvata da un secondo membro della redazione.";
  return `<div class="block-head"><h2 id="proposal-summary-title">Come stanno le promesse</h2><a class="block-link" href="./?view=methodology">Il metodo</a></div>
    <div class="proposal-summary-card">
      <p class="proposal-summary-count"><strong>${promises.length}</strong> ${promises.length === 1 ? "promessa" : "promesse"}${escapeHtml(scope)}</p>
      ${renderCompositionBar(entries)}
      <p class="proposal-summary-note">${note}</p>
    </div>`;
}

export function renderProposalTimeline(events = []) {
  return `<ol class="proposal-timeline">${events.map((event) => {
    const url = safeExternalUrl(event.source?.url);
    return `<li><time>${escapeHtml(formatDate(event.effective_at))}</time><div><strong>${escapeHtml(proposalStatusLabel(event.status))}</strong><p>Etichetta ufficiale: ${escapeHtml(event.source_status_label)}</p>${url ? `<a class="source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Elementi di verifica ${icon("external", { size: 14 })}</a>` : ""}</div></li>`;
  }).join("")}</ol>`;
}

function renderProposalState(proposal) {
  if (isPromise(proposal)) {
    const verdict = proposal.verdict || "not_yet_rated";
    const body = verdict === "not_yet_rated"
      ? "La redazione non ha ancora pubblicato una valutazione. Comparirà qui con il documento che la giustifica."
      : "Valutazione pubblicata dalla redazione, con il documento ufficiale che la giustifica.";
    return `<section class="state-panel tone-${verdictMeta(verdict).tone}" aria-label="Valutazione">
      <p class="state-panel-label">Valutazione VeraPolitica</p>
      <p class="state-panel-value">${renderVerdictChip(verdict)}</p>
      <p class="state-panel-note">${body}</p>
      ${verdict === "not_yet_rated" ? "" : `<button class="ghost-button explain-pledge" type="button" data-pledge-id="${escapeHtml(proposal.id)}">Perché questa valutazione</button><div class="pledge-explanation" hidden></div>`}
    </section>`;
  }
  return `<section class="state-panel" aria-label="Stato">
    <p class="state-panel-label">Stato istituzionale</p>
    <p class="state-panel-value"><span class="status-chip">${escapeHtml(proposalStatusLabel(proposal.current_status))}</span></p>
    <p class="state-panel-note">Come risulta dalla fonte ufficiale più recente.</p>
  </section>`;
}

function actorAvatar(actor, size = "") {
  const words = String(actor.display_name || "").trim().split(/\s+/);
  const photo = actor.politician_id ? resolvePortrait(actor.politician_id) : null;
  const mono = initials({ given_name: words[0] || "", family_name: words.length > 1 ? words[words.length - 1] : "" });
  return `<span class="actor-avatar${size}" aria-hidden="true">${photo ? `<img src="${escapeHtml(photo)}" alt="" loading="lazy" />` : escapeHtml(mono)}</span>`;
}

function renderProposalActorRow(actor) {
  const inner = `${actorAvatar(actor)}<span class="row-text"><strong>${escapeHtml(actor.display_name)}</strong><small>${escapeHtml(actorRoleLabel(actor.role))}</small></span>`;
  return actor.politician_id
    ? `<li><a class="row-link" href="./?politician=${encodeURIComponent(actor.politician_id)}">${inner}<span class="row-chevron" aria-hidden="true">${icon("chevronRight", { size: 18 })}</span></a></li>`
    : `<li><div class="row-link is-static">${inner}<span></span></div></li>`;
}

export function renderProposalDetail(proposal) {
  const date = formatDate(proposal.introduced_at);
  const first = proposal.sources[0];
  const text = proposal.exact_statement
    ? `<figure class="statement">
        <figcaption class="statement-label">${isPromise(proposal) ? "Le parole esatte" : "Testo"}</figcaption>
        <blockquote>${escapeHtml(proposal.exact_statement)}</blockquote>
        <figcaption class="statement-cite">${escapeHtml(proposalActorNames(proposal))}${first ? ` — ${escapeHtml(first.name)}` : ""}${date ? `, ${escapeHtml(date)}` : ""}</figcaption>
      </figure>`
    : proposal.summary ? `<p class="lead">${escapeHtml(proposal.summary)}</p>` : "";
  return `<header class="proposal-hero">
      <p class="proposal-kicker">${escapeHtml(proposalTypeLabel(proposal.proposal_type))}${date ? ` · ${escapeHtml(date)}` : ""}</p>
      <h1 id="proposal-detail-title">${escapeHtml(proposal.title)}</h1>
      ${renderProposalTags(proposal.tags)}
    </header>
    ${renderProposalState(proposal)}
    ${text}
    <section class="politics-block" aria-labelledby="proposal-actors-title">
      <div class="block-head"><h2 id="proposal-actors-title">${isPromise(proposal) ? "Chi l'ha promesso" : "Chi l'ha presentata"}</h2></div>
      <ul class="row-list">${proposal.actors.length ? proposal.actors.map(renderProposalActorRow).join("") : `<li class="row-empty">Nessun attore pubblicato.</li>`}</ul>
    </section>
    <section class="politics-block" aria-labelledby="proposal-history-title">
      <div class="block-head"><h2 id="proposal-history-title">Cronologia</h2></div>
      <div class="detail-card proposal-timeline-card">${renderProposalTimeline(proposal.status_history)}</div>
    </section>
    <section class="politics-block" aria-labelledby="proposal-sources-title">
      <div class="block-head"><h2 id="proposal-sources-title">Fonti ufficiali</h2></div>
      <ul class="row-list">${proposal.sources.map((source) => {
        const url = safeExternalUrl(source.url);
        const inner = `<span class="row-icon" aria-hidden="true">${icon("external", { size: 18 })}</span><span class="row-text"><strong>${escapeHtml(source.name)}</strong><small>${url ? escapeHtml(new URL(url).hostname.replace(/^www\./, "")) : "Indirizzo non disponibile"}</small></span>`;
        return url
          ? `<li><a class="row-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${inner}<span class="row-chevron" aria-hidden="true">${icon("chevronRight", { size: 18 })}</span></a></li>`
          : `<li><div class="row-link is-static">${inner}<span></span></div></li>`;
      }).join("")}</ul>
    </section>`;
}

export function renderPoliticianProposals(proposals = []) {
  if (!proposals.length) return `<p class="empty-note">Nessuna proposta o promessa esplicita pubblicata è collegata a questa persona.</p>`;
  return `<ul class="linked-proposals is-list">${proposals.map((proposal) => `<li><a href="./?proposal=${encodeURIComponent(proposal.id)}">${escapeHtml(proposal.title)}</a><span>${escapeHtml(proposalTypeLabel(proposal.proposal_type))} · ${escapeHtml(actorRoleLabel(proposal.role))} · ${escapeHtml(proposalStatusLabel(proposal.current_status))}</span></li>`).join("")}</ul>`;
}

function officeLabel(office) {
  if (office === "mayor") return "Sindaco";
  if (office === "regional_president") return "Presidente di regione";
  return titleCase(office);
}

function holderLabel(holder) {
  if (!holder) return "Non collegato al momento";
  const name = `${holder.given_name} ${holder.family_name}`;
  return holder.politician_id
    ? `<a href="./?politician=${encodeURIComponent(holder.politician_id)}">${escapeHtml(name)}</a>`
    : escapeHtml(name);
}

export function renderTerritorialOffices(offices = []) {
  if (!offices.length) {
    return `<p class="empty-note">Nessun incarico territoriale è al momento collegato a questa persona.</p>`;
  }
  return `<div class="territorial-offices">${offices.map((office) => {
    const sourceUrl = safeExternalUrl(office.source?.url);
    const territory = office.municipality
      ? `<a href="./?municipality=${encodeURIComponent(office.municipality_id)}">${escapeHtml(office.municipality)}</a>`
      : office.region_id
        ? `<a href="./?region=${encodeURIComponent(office.region_id)}">${escapeHtml(office.region)}</a>`
        : escapeHtml(office.region || "Territorio non indicato");
    return `<article class="territorial-office">
      <div><span class="proposal-type">${escapeHtml(officeLabel(office.office))}</span><h3>${territory}</h3>
      <p>${office.municipality && office.region ? `Regione: ${escapeHtml(office.region)} · ` : ""}${office.end_date ? `${formatDate(office.start_date)} – ${formatDate(office.end_date)}` : `Dal ${formatDate(office.start_date)}`}</p></div>
      ${sourceUrl ? `<a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Fonte ufficiale ${icon("external", { size: 14 })}</a>` : ""}
    </article>`;
  }).join("")}</div>`;
}

export function renderRegionCard(region) {
  const president = region.current_president
    ? `${region.current_president.given_name} ${region.current_president.family_name}`
    : "Presidente non collegato al momento";
  return `<article class="proposal-card">
    <span class="proposal-type">ISTAT ${escapeHtml(region.istat_code)}</span>
    <h3>${escapeHtml(region.name)}</h3>
    <p>Presidente: ${escapeHtml(president)}</p>
    <a class="profile-link" href="./?region=${encodeURIComponent(region.id)}">Vedi regione ${icon("arrowRight")}</a>
  </article>`;
}

export function renderMunicipalityCard(municipality) {
  const mayor = municipality.current_mayor
    ? `${municipality.current_mayor.given_name} ${municipality.current_mayor.family_name}`
    : "Sindaco non collegato al momento";
  return `<article class="proposal-card">
    <span class="proposal-type">ISTAT ${escapeHtml(municipality.istat_code)}</span>
    <h3>Comune di ${escapeHtml(municipality.name)}</h3>
    <p>Regione: ${escapeHtml(municipality.region_name)} · Sindaco: ${escapeHtml(mayor)}</p>
    <a class="profile-link" href="./?municipality=${encodeURIComponent(municipality.id)}">Vedi comune ${icon("arrowRight")}</a>
  </article>`;
}

export function renderRegionDetail(region, municipalities = []) {
  const sourceUrl = safeExternalUrl(region.source?.url);
  const ordered = [...municipalities].sort((left, right) => {
    if (left.name === "Roma") return -1;
    if (right.name === "Roma") return 1;
    return left.name.localeCompare(right.name, "it");
  });
  const office = region.current_president
    ? `<p class="office-holder">Presidente in carica: ${holderLabel(region.current_president)}</p>`
    : `<p class="office-holder">Presidente: non ancora collegato a una scheda pubblicata. Serve un mandato ufficiale e la verifica della redazione.</p>`;
  return `<section class="proposal-detail-hero">
      <p class="eyebrow">Regione ISTAT ${escapeHtml(region.istat_code)}</p>
      <h1 id="region-detail-title">${escapeHtml(region.name)}</h1>
      ${office}
      <p>${region.municipality_count} ${region.municipality_count === 1 ? "comune" : "comuni"} nei dati ufficiali di riferimento.</p>
      <p><a class="profile-link" href="./?history_region=${encodeURIComponent(region.id)}">Cosa è successo in questa regione ${icon("arrowRight")}</a></p>
      ${sourceUrl ? `<p><a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Fonte ISTAT ufficiale ${icon("external", { size: 14 })}</a></p>` : ""}
    </section>
    <section class="detail-card"><h2>Comuni in questa regione</h2>
      ${ordered.length ? `<div class="proposal-grid">${ordered.map(renderMunicipalityCard).join("")}</div>` : `<p class="empty-note">Nessun comune è al momento elencato per questa regione.</p>`}
    </section>`;
}

export function renderMunicipalityDetail(municipality) {
  const sourceUrl = safeExternalUrl(municipality.source?.url);
  return `<section class="proposal-detail-hero">
      <p class="eyebrow">Comune ISTAT ${escapeHtml(municipality.istat_code)}</p>
      <h1 id="municipality-detail-title">Comune di ${escapeHtml(municipality.name)}</h1>
      <p>Regione: <a href="./?region=${encodeURIComponent(municipality.region_id)}">${escapeHtml(municipality.region_name)}</a></p>
      ${municipality.current_mayor
        ? `<p class="office-holder">Sindaco in carica: ${holderLabel(municipality.current_mayor)}</p>`
        : `<p class="office-holder">Sindaco: non ancora collegato a una scheda pubblicata. Serve l'elenco DAIT e la verifica della redazione.</p>`}
      <p>Provincia/UTS: <a href="./?province=${encodeURIComponent(municipality.province_abbreviation)}">${escapeHtml(municipality.province_name)} (${escapeHtml(municipality.province_abbreviation)})</a></p>
      ${sourceUrl ? `<p><a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Fonte ISTAT ufficiale ${icon("external", { size: 14 })}</a></p>` : ""}
    </section>`;
}

function fact(label, value, { href = null } = {}) {
  const content = href
    ? `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(value)}</a>`
    : escapeHtml(value);
  return `<div class="fact"><dt>${escapeHtml(label)}</dt><dd>${content}</dd></div>`;
}

function birthPlace(profile) {
  if (!profile.birth_place) return "Non indicato";
  const parts = [];
  for (const part of [profile.birth_place.city, profile.birth_place.subdivision, profile.birth_place.country]) {
    const value = String(part || "").trim();
    if (!value) continue;
    if (parts.some((item) => item.toLocaleLowerCase("it") === value.toLocaleLowerCase("it"))) continue;
    parts.push(value);
  }
  return parts.join(", ") || "Non indicato";
}

export function renderSources(citations) {
  const groups = groupCitations(citations);
  if (!groups.length) return "";
  return groups.map((group) => {
    const chips = `<ul class="supports">${group.fields.map((label) => `<li>${escapeHtml(label)}</li>`).join("")}</ul>`;
    return renderSourceCard({
      kind: "Fonte ufficiale",
      name: group.sourceName,
      url: group.sourceUrl,
      extra: `<p class="supports-label">Sostiene</p>${chips}<small class="source-card-count">${group.referenceCount} ${group.referenceCount === 1 ? "riferimento verificato" : "riferimenti verificati"}</small>`,
    });
  }).join("");
}

// ---------------------------------------------------------------------------
// Commitment record ("detto / fatto"). Methodology: /methodology/scoring.
// Composition comes before the number, roles are never mixed, and the score is
// withheld when too few commitments are closed.

const VERDICTS = {
  kept: { label: "Mantenuta", tone: "kept" },
  partially_kept: { label: "Mantenuta parzialmente", tone: "partial" },
  in_progress: { label: "In corso", tone: "progress" },
  stalled: { label: "Iter bloccato", tone: "stalled" },
  broken: { label: "Non mantenuta", tone: "broken" },
  not_yet_rated: { label: "Non ancora valutata", tone: "unrated" },
};

const VERDICT_LEGEND_ORDER = [
  "kept",
  "partially_kept",
  "in_progress",
  "stalled",
  "broken",
  "not_yet_rated",
];

const ROLE_LABELS = {
  government_single_party: "Governo monocolore",
  government_coalition: "Governo di coalizione",
  opposition: "Opposizione",
  unknown: "Ruolo non stabilito",
};

// Comparative Agendas Project major topics, shown in Italian.
const CAP_TOPICS = {
  1: "Economia", 2: "Diritti civili", 3: "Sanità", 4: "Agricoltura", 5: "Lavoro",
  6: "Istruzione", 7: "Ambiente", 8: "Energia", 9: "Immigrazione", 10: "Trasporti",
  12: "Giustizia e criminalità", 13: "Welfare", 14: "Abitazione", 15: "Imprese",
  16: "Difesa", 17: "Tecnologia e ricerca", 18: "Commercio estero",
  19: "Affari internazionali", 20: "Governo e istituzioni", 21: "Territorio pubblico", 23: "Cultura",
};

const WITHHELD_REASONS = {
  no_closed_pledges: "Nessuna promessa ha ancora una valutazione conclusiva.",
  below_minimum_closed_pledges: "Troppe poche promesse concluse per un punteggio significativo.",
};

function verdictMeta(value) {
  return VERDICTS[value] || { label: titleCase(value), tone: "unrated" };
}

function topicLabel(code) {
  return CAP_TOPICS[Number(code)] || `Tema ${code}`;
}

function percent(value, digits = 0) {
  if (!PERCENT.has(digits)) {
    PERCENT.set(digits, new Intl.NumberFormat("it-IT", { style: "percent", maximumFractionDigits: digits, minimumFractionDigits: digits }));
  }
  return PERCENT.get(digits).format(Number(value));
}

export function renderVerdictChip(value) {
  const meta = verdictMeta(value);
  return `<span class="verdict-chip tone-${meta.tone}">${escapeHtml(meta.label)}</span>`;
}

export function renderVerdictLegend() {
  return `<ul class="verdict-legend" aria-label="Legenda stati delle promesse">${
    VERDICT_LEGEND_ORDER.map((value) => `<li>${renderVerdictChip(value)}</li>`).join("")
  }</ul>`;
}

export function renderCompositionBar(composition = [], { compact = false } = {}) {
  const total = composition.reduce((sum, entry) => sum + entry.count, 0);
  if (!total) return `<p class="empty-note">Nessuna promessa in questo gruppo.</p>`;
  const present = composition.filter((entry) => entry.count > 0);
  const summary = present.map((entry) => `${entry.count} ${verdictMeta(entry.verdict).label.toLowerCase()}`).join(", ");
  const segments = present.map((entry) => `<span class="composition-segment tone-${verdictMeta(entry.verdict).tone}" style="flex-grow:${entry.count}"></span>`).join("");
  const legend = compact ? "" : `<ul class="composition-legend">${present.map((entry) => `<li><span class="legend-dot tone-${verdictMeta(entry.verdict).tone}" aria-hidden="true"></span>${escapeHtml(verdictMeta(entry.verdict).label)} <strong>${entry.count}</strong></li>`).join("")}</ul>`;
  return `<div class="composition${compact ? " is-compact" : ""}"><div class="composition-bar" role="img" aria-label="${escapeHtml(summary)}">${segments}</div>${legend}</div>`;
}

export function renderRateBlock(stratum, credibleLevel) {
  if (stratum.rate === null || stratum.rate === undefined) {
    const range = stratum.credible_interval
      ? `<p class="rate-range">Intervallo plausibile finora: ${percent(stratum.credible_interval[0])} – ${percent(stratum.credible_interval[1])}</p>`
      : "";
    return `<div class="rate-block is-withheld">
      <span class="rate-label">Tasso di mantenimento</span>
      <strong class="rate-value">Non calcolato</strong>
      <p class="rate-note">${escapeHtml(WITHHELD_REASONS[stratum.rate_withheld_reason] || "Promesse concluse insufficienti.")}</p>
      ${range}
    </div>`;
  }
  const [low, high] = stratum.credible_interval;
  return `<div class="rate-block">
    <span class="rate-label">Tasso di mantenimento · ${stratum.closed_pledges} concluse</span>
    <strong class="rate-value">${percent(stratum.rate)}</strong>
    <div class="interval-track" role="img" aria-label="Intervallo plausibile ${percent(credibleLevel)} da ${percent(low)} a ${percent(high)}">
      <span class="interval-range" style="left:${low * 100}%;width:${(high - low) * 100}%"></span>
      <span class="interval-point" style="left:${stratum.rate * 100}%"></span>
    </div>
    <p class="rate-range">Intervallo plausibile ${percent(credibleLevel)}: ${percent(low)} – ${percent(high)}. Mantenuta parzialmente conta per metà.</p>
  </div>`;
}

function renderStratum(stratum, scorecard) {
  const topics = stratum.topics.length
    ? `<div class="topic-chips">${stratum.topics.map((topic) => `<span class="topic-chip">${escapeHtml(topicLabel(topic.cap_topic_code))}<small>${topic.count}</small></span>`).join("")}</div>`
    : "";
  return `<section class="stratum-card">
    <div class="stratum-head">
      <div><h3>${escapeHtml(ROLE_LABELS[stratum.role] || titleCase(stratum.role))}</h3></div>
      <span class="count-pill">${stratum.scored_pledges} nel punteggio · ${stratum.open_pledges} aperte</span>
    </div>
    ${renderCompositionBar(stratum.composition)}
    ${renderRateBlock(stratum, scorecard.credible_level)}
    ${topics}
  </section>`;
}

export function renderPledgeItem(pledge) {
  const assessment = pledge.latest_assessment;
  const meta = verdictMeta(pledge.verdict);
  const declared = pledge.introduced_at ? formatDate(pledge.introduced_at) : "";
  const assessed = assessment?.effective_at ? formatDate(assessment.effective_at) : "";
  const declarationUrl = pledge.declaration_source_url || "";
  const declarationSource = declarationUrl || pledge.declaration_source_name ? renderSourceCard({
    kind: sourceKindFromUrl(declarationUrl),
    name: pledge.declaration_source_name || sourceHostLabel(declarationUrl) || "",
    url: declarationUrl,
    title: "Fonte della dichiarazione",
  }) : "";
  const evidence = assessment ? `<div class="pledge-evidence tone-${meta.tone}">
      <p class="evidence-label">Perché questo stato</p>
      ${assessment.quoted_excerpt ? `<p class="evidence-quote">“${escapeHtml(assessment.quoted_excerpt)}”</p>` : ""}
      ${renderSourceCard({
        kind: "official",
        name: sourceHostLabel(assessment.source_url) || "",
        url: assessment.source_url,
        title: "Fonte della valutazione",
        date: assessed,
      })}
    </div>` : "";
  const details = [
    declared ? `<p class="pledge-origin">Dichiarata il ${escapeHtml(declared)}</p>` : "",
    pledge.exact_statement ? `<blockquote class="pledge-quote">“${escapeHtml(pledge.exact_statement)}”</blockquote>` : "",
    declarationSource,
    evidence,
  ].filter(Boolean).join("");
  return `<article class="pledge-item tone-${meta.tone}" data-verdict="${escapeHtml(pledge.verdict)}" data-scored="${pledge.included_in_score ? "yes" : "no"}">
    <div class="pledge-top">
      ${renderVerdictChip(pledge.verdict)}
      <span class="pledge-tags">${pledge.cap_topic_code ? `<span class="topic-chip is-small">${escapeHtml(topicLabel(pledge.cap_topic_code))}</span>` : ""}${pledge.included_in_score ? "" : `<span class="topic-chip is-small is-muted">Troppo vaga da valutare</span>`}</span>
    </div>
    <h4><a href="./?proposal=${encodeURIComponent(pledge.proposal_id)}">${escapeHtml(pledge.title)}</a></h4>
    ${assessment ? `<p class="evidence-text">${escapeHtml(assessment.rationale)}</p>` : `<p class="empty-note">Non ancora valutata</p>`}
    ${details ? `<details class="pledge-details"><summary>Dettagli e fonti</summary>${details}</details>` : ""}
    <button type="button" class="explain-pledge" data-pledge-id="${encodeURIComponent(pledge.proposal_id)}">Spiegami questa promessa</button>
    <div class="pledge-explanation" hidden></div>
  </article>`;
}

const PLEDGE_FILTER_LABELS = {
  kept: "Mantenute",
  partially_kept: "Mantenute parzialmente",
  in_progress: "In corso",
  stalled: "Iter bloccato",
  broken: "Non mantenute",
  not_yet_rated: "Non ancora valutate",
};

const PLEDGE_FILTERS = [
  ["all", "Tutte"],
  ...VERDICT_LEGEND_ORDER.map((value) => [value, PLEDGE_FILTER_LABELS[value]]),
];

export function countPledgeVerdicts(pledges = []) {
  const counts = { all: pledges.length };
  for (const value of VERDICT_LEGEND_ORDER) {
    counts[value] = 0;
  }
  for (const pledge of pledges) {
    if (pledge.verdict in VERDICTS) {
      counts[pledge.verdict] += 1;
    }
  }
  counts.all = pledges.length;
  return counts;
}

export function renderPledgeStatusSummary(counts, total) {
  const noun = total === 1 ? "promessa monitorata" : "promesse monitorate";
  const items = VERDICT_LEGEND_ORDER.map((value) => {
    const meta = verdictMeta(value);
    const count = counts[value] || 0;
    return `<li class="pledge-summary-item tone-${meta.tone}${count === 0 ? " is-zero" : ""}">
      <span class="pledge-summary-swatch" aria-hidden="true"></span>
      <strong class="pledge-summary-count" data-count-to="${count}">${count}</strong>
      <span class="pledge-summary-label">${escapeHtml(meta.label)}</span>
    </li>`;
  }).join("");
  return `<div class="pledge-status-summary">
    <p class="pledge-summary-total"><strong data-count-to="${total}">${total}</strong> ${noun}</p>
    <ul class="pledge-summary-grid" aria-label="Riepilogo degli stati pubblicati">${items}</ul>
  </div>`;
}

export function renderPledgeDistribution(counts, total) {
  if (!total) {
    return `<p class="empty-note">Nessuna promessa pubblicata da mostrare.</p>`;
  }
  const composition = VERDICT_LEGEND_ORDER.map((verdict) => ({
    verdict,
    count: counts[verdict] || 0,
  }));
  return `<div class="pledge-distribution">
    <p class="pledge-distribution-caption">Distribuzione degli stati pubblicati. Non è un punteggio di performance.</p>
    ${renderCompositionBar(composition, { compact: true })}
  </div>`;
}

function renderPledgeFilters(counts) {
  return `<div class="filter-pills" role="group" aria-label="Filtra le promesse per stato">${
    PLEDGE_FILTERS.map(([key, label], index) => {
      const count = counts[key] || 0;
      const zero = key !== "all" && count === 0;
      return `<button type="button" class="filter-pill${index === 0 ? " is-active" : ""}${zero ? " is-zero" : ""}" data-filter="${key}" aria-pressed="${index === 0}">${escapeHtml(label)} (${count})</button>`;
    }).join("")
  }</div>`;
}

export function renderScorecard(scorecard) {
  if (!scorecard || !scorecard.tracked_pledges) {
    return `<div class="state-card"><div><strong>Nessuna promessa è ancora tracciata per questa persona.</strong><small>Le promesse esplicite pubblicate compaiono qui dopo la classificazione.</small></div></div>`;
  }
  const progress = scorecard.mandate_progress;
  const pledges = scorecard.pledges || [];
  const counts = countPledgeVerdicts(pledges);
  return `<div class="scorecard">
    <div class="method-note">
      <p>Il punteggio conta solo le promesse concluse e si calcola separatamente per ciascun ruolo istituzionale, perché governo e opposizione hanno poteri molto diversi. Ogni valutazione cita un documento ufficiale.</p>
      <a class="profile-link" href="./?view=methodology">Come funziona il punteggio ${icon("arrowRight")}</a>
    </div>
    ${renderVerdictLegend()}
    ${progress ? `<div class="mandate-progress"><div><span>Mandato trascorso</span><strong>${percent(progress.elapsed_fraction)}</strong></div><div class="progress-track"><span style="width:${progress.elapsed_fraction * 100}%"></span></div><small>${escapeHtml(formatDate(progress.start))} – ${escapeHtml(formatDate(progress.end))}</small></div>` : ""}
    <div class="strata">${scorecard.strata.map((stratum) => renderStratum(stratum, scorecard)).join("")}</div>
    <div class="pledge-board">
      <div class="pledge-list-head">
        <h3>Promesse</h3>
      </div>
      ${renderPledgeStatusSummary(counts, counts.all)}
      ${renderPledgeDistribution(counts, counts.all)}
      ${renderPledgeFilters(counts)}
      <div class="pledge-list">${pledges.map(renderPledgeItem).join("")}</div>
      <p class="pledge-filter-empty empty-note" hidden aria-live="polite">Nessuna promessa pubblicata con questo stato.</p>
    </div>
    ${scorecard.excluded_vague_pledges ? `<p class="empty-note">${scorecard.excluded_vague_pledges === 1 ? "1 promessa è troppo vaga da verificare ed è esclusa da ogni punteggio." : `${scorecard.excluded_vague_pledges} promesse sono troppo vaghe da verificare e sono escluse da ogni punteggio.`}</p>` : ""}
    <p class="publication-meta">Metodologia ${escapeHtml(scorecard.methodology_version)} · Dati al ${escapeHtml(formatDate(scorecard.as_of))}</p>
  </div>`;
}

// Keeps the last word and the verified mark on the same line.
function nameWithMark(name) {
  const words = String(name).trim().split(/\s+/);
  const last = words.pop() || "";
  const head = words.length ? `${escapeHtml(words.join(" "))} ` : "";
  return `${head}<span class="name-tail">${escapeHtml(last)}\u00a0`;
}

export function renderProfileStats(scorecard) {
  if (!scorecard || !scorecard.tracked_pledges) {
    return `<div class="stat-row"><div class="stat-tile"><strong>0</strong><span>Promesse</span></div><div class="stat-tile"><strong>0</strong><span>Concluse</span></div><div class="stat-tile"><strong class="is-muted">—</strong><span>Punteggio non calcolato</span></div></div>`;
  }
  const single = scorecard.strata.length === 1 ? scorecard.strata[0] : null;
  const score = single
    ? (single.rate === null || single.rate === undefined
      ? `<div class="stat-tile"><strong class="is-muted">—</strong><span>Punteggio non calcolato</span></div>`
      : `<div class="stat-tile is-accent"><strong>${percent(single.rate)}</strong><span>Tasso di mantenimento</span></div>`)
    : `<div class="stat-tile"><strong>${scorecard.strata.length}</strong><span>Ruoli calcolati a parte</span></div>`;
  const progress = scorecard.mandate_progress
    ? `<div class="stat-tile"><strong>${percent(scorecard.mandate_progress.elapsed_fraction)}</strong><span>Mandato trascorso</span></div>`
    : `<div class="stat-tile"><strong>${scorecard.strata.reduce((sum, item) => sum + item.closed_pledges, 0)}</strong><span>Concluse</span></div>`;
  return `<div class="stat-row"><div class="stat-tile"><strong>${scorecard.tracked_pledges}</strong><span>Promesse</span></div>${score}${progress}</div>`;
}

export function renderCardRecord(scorecard) {
  if (!scorecard || !scorecard.tracked_pledges) {
    return `<p class="card-record-empty">Nessuna promessa tracciata</p>`;
  }
  const composition = new Map();
  for (const stratum of scorecard.strata) {
    for (const entry of stratum.composition) {
      composition.set(entry.verdict, (composition.get(entry.verdict) || 0) + entry.count);
    }
  }
  const entries = [...composition.entries()].map(([verdict, count]) => ({ verdict, count }));
  const closed = scorecard.strata.reduce((sum, item) => sum + item.closed_pledges, 0);
  return `${renderCompositionBar(entries, { compact: true })}<p class="card-record-caption"><strong>${scorecard.tracked_pledges}</strong> ${scorecard.tracked_pledges === 1 ? "promessa" : "promesse"} · ${closed} concluse</p>`;
}

function renderPledgeExplanation(payload) {
  const sources = (payload.sources || []).map((source) => {
    const url = safeExternalUrl(source.url);
    const title = escapeHtml(source.title || "Fonte ufficiale");
    return url
      ? `<li><a class="source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${title} ${icon("external", { size: 14 })}</a></li>`
      : `<li>${title}</li>`;
  }).join("");
  const note = payload.generated_by_ai
    ? "Spiegazione generata automaticamente su dati verificati da VeraPolitica. Non è una nuova valutazione."
    : "Spiegazione basata sui dati pubblicati da VeraPolitica.";
  return `<p class="explanation-text">${escapeHtml(payload.explanation)}</p>
    ${sources ? `<ul class="explanation-sources">${sources}</ul>` : ""}
    <p class="explanation-note">${note}</p>`;
}

function bindExplainPledges(root, api) {
  for (const button of root.querySelectorAll(".explain-pledge")) {
    button.addEventListener("click", async () => {
      const panel = button.parentElement?.querySelector(".pledge-explanation");
      if (!panel) return;
      button.disabled = true;
      panel.hidden = false;
      panel.className = "pledge-explanation is-loading";
      panel.innerHTML = `<p class="explanation-note">Preparazione della spiegazione…</p>`;
      try {
        const payload = await api.explainPledge(button.dataset.pledgeId);
        panel.className = "pledge-explanation";
        panel.innerHTML = renderPledgeExplanation(payload);
      } catch (error) {
        panel.className = "pledge-explanation is-error";
        const missing = error.status === 404;
        panel.innerHTML = `<p class="explanation-note">${
          missing
            ? "VeraPolitica non ha ancora pubblicato una valutazione per questa promessa."
            : "La spiegazione non è al momento disponibile."
        }</p>`;
      } finally {
        button.disabled = false;
      }
    });
  }
}

function bindPledgeFilters(root) {
  const buttons = [...root.querySelectorAll(".filter-pill")];
  const items = [...root.querySelectorAll(".pledge-item")];
  const empty = root.querySelector(".pledge-filter-empty");
  const apply = (filter) => {
    let visible = 0;
    for (const item of items) {
      const match = filter === "all" || item.dataset.verdict === filter;
      item.hidden = !match;
      if (match) visible += 1;
    }
    if (empty) empty.hidden = visible > 0;
  };
  for (const button of buttons) {
    button.addEventListener("click", () => {
      const filter = button.dataset.filter;
      for (const other of buttons) {
        other.classList.toggle("is-active", other === button);
        other.setAttribute("aria-pressed", String(other === button));
      }
      apply(filter);
    });
  }
}

let profileNavResizeBound = false;

function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
}

function stickyHeaderHeight() {
  const header = document.querySelector(".site-header");
  if (!header || !["sticky", "fixed"].includes(getComputedStyle(header).position)) return 0;
  return header.offsetHeight;
}

function navOffset() {
  const nav = document.querySelector(".profile-section-nav");
  return stickyHeaderHeight() + (nav?.offsetHeight || 0) + 12;
}

function syncScrollPadding() {
  const nav = document.querySelector(".profile-section-nav");
  const headerHeight = stickyHeaderHeight();
  const pad = headerHeight + (nav?.offsetHeight || 0) + 12;
  document.documentElement.style.setProperty("--profile-nav-top", `${headerHeight}px`);
  document.documentElement.style.setProperty("--profile-scroll-pad", `${pad}px`);
}

function setActiveSectionLink(nav, id) {
  if (!nav || !id) return;
  for (const link of nav.querySelectorAll("a[href^='#']")) {
    const active = link.getAttribute("href") === `#${id}`;
    link.classList.toggle("is-active", active);
    if (active) {
      link.setAttribute("aria-current", "location");
      const left = link.offsetLeft - Math.max(0, (nav.clientWidth - link.offsetWidth) / 2);
      nav.scrollTo({ left: Math.max(0, left), behavior: "auto" });
    } else {
      link.removeAttribute("aria-current");
    }
  }
}

function bindProfileSectionNav(root) {
  const nav = root.querySelector(".profile-section-nav");
  if (!nav) return;
  const links = [...nav.querySelectorAll("a[href^='#']")];
  const panels = links.map((link) => root.querySelector(link.getAttribute("href"))).filter(Boolean);
  if (!panels.length) return;
  nav.setAttribute("role", "tablist");
  for (const link of links) {
    const panel = root.querySelector(link.getAttribute("href"));
    if (!panel) continue;
    link.id = `tab-${panel.id}`;
    link.setAttribute("role", "tab");
    link.setAttribute("aria-controls", panel.id);
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", link.id);
    panel.tabIndex = 0;
  }
  const select = (id, { focus = false, updateHash = true } = {}) => {
    const panel = panels.find((item) => item.id === id) || panels[0];
    for (const link of links) {
      const active = link.getAttribute("aria-controls") === panel.id;
      link.setAttribute("aria-selected", String(active));
      link.tabIndex = active ? 0 : -1;
      link.classList.toggle("is-active", active);
      if (active) {
        link.setAttribute("aria-current", "location");
        if (focus) link.focus();
        const left = link.offsetLeft - Math.max(0, (nav.clientWidth - link.offsetWidth) / 2);
        nav.scrollTo({ left: Math.max(0, left), behavior: "auto" });
      } else {
        link.removeAttribute("aria-current");
      }
    }
    for (const item of panels) item.hidden = item !== panel;
    if (updateHash) history.replaceState(null, "", `#${panel.id}`);
  };
  nav.addEventListener("click", (event) => {
    const link = event.target instanceof Element ? event.target.closest("a[role='tab']") : null;
    if (!link) return;
    event.preventDefault();
    select(link.getAttribute("aria-controls"));
  });
  nav.addEventListener("keydown", (event) => {
    const index = links.indexOf(document.activeElement);
    if (index === -1) return;
    const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: links.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const link = links[(next + links.length) % links.length];
    select(link.getAttribute("aria-controls"), { focus: true });
  });
  // Topic chips that point at a tab open it instead of jumping.
  root.addEventListener("click", (event) => {
    const chip = event.target instanceof Element ? event.target.closest("[data-tab-link]") : null;
    if (!chip) return;
    event.preventDefault();
    select(chip.dataset.tabLink);
    nav.scrollIntoView({ block: "nearest", behavior: prefersReducedMotion() ? "auto" : "smooth" });
  });
  const initial = window.location.hash.slice(1);
  select(panels.some((item) => item.id === initial) ? initial : panels[0].id, { updateHash: false });
  if (initial && panels.some((item) => item.id === initial)) {
    requestAnimationFrame(() => nav.scrollIntoView({ block: "start" }));
  }
}

function bindProfileShare(root) {
  const button = root.querySelector(".cover-share");
  const status = root.querySelector(".share-status");
  if (!button) return;
  button.addEventListener("click", async () => {
    const url = window.location.href.split("#")[0];
    try {
      if (navigator.share) {
        await navigator.share({ title: button.dataset.shareTitle, url });
        return;
      }
      await navigator.clipboard.writeText(url);
      if (status) status.textContent = "Link del profilo copiato.";
    } catch {
      if (status) status.textContent = "Copia il link dalla barra degli indirizzi.";
    }
  });
}

function bindProfileMotion(root) {
  // Numbers are written in place; no count-up or entrance animation.
  for (const node of root.querySelectorAll("[data-count-to]")) node.textContent = String(node.dataset.countTo);
}

export function renderMethodology(method) {
  const rows = [
    ["Formula", "(kept + ½ × partially_kept) ÷ closed. Invariata: pledge-score/v1."],
    ["Etichette pubbliche", "Mantenuta (kept, conclusa), Mantenuta parzialmente (partially_kept, conclusa), In corso (in_progress, aperta), Iter bloccato (stalled, aperta), Non mantenuta (broken, conclusa), Non ancora valutata (not_yet_rated: nessuna valutazione pubblicata)."],
    ["Denominatore", "Solo le promesse concluse entrano nel punteggio: kept, partially_kept, broken. Gli stati aperti (in_progress, stalled, not_yet_rated) sono elencati ma non conteggiati."],
    ["Ruoli", "I punteggi si calcolano separatamente per governo monocolore, governo di coalizione e opposizione, e non vengono mai sommati o ordinati tra ruoli."],
    ["Numeri piccoli", `Con meno di ${method.min_closed_for_rate} promesse concluse il punteggio non viene calcolato. Viene sempre mostrato un intervallo plausibile al ${percent(method.interval.level)}.`],
    ["Promesse vaghe", "Le promesse troppo vaghe da verificare sono elencate ma escluse da ogni punteggio."],
    ["Elementi di verifica", "Ogni valutazione cita un documento ufficiale parola per parola. Non mantenuta (broken) richiede due controlli editoriali indipendenti. Sul tabellone pubblico compaiono solo le valutazioni pubblicate."],
  ];
  return `<section class="detail-card">
    <p class="eyebrow">Metodologia ${escapeHtml(method.version)}</p>
    <h2>Come funziona il punteggio delle promesse</h2>
    ${renderVerdictLegend()}
    <dl class="facts">${rows.map(([label, value]) => fact(label, value)).join("")}</dl>
  </section>`;
}

export function profileTopics(person, scorecard = null) {
  // Key topics come only from published content: position topics first, then pledge CAP topics.
  const topics = [];
  const seen = new Set();
  for (const item of person.positions || []) {
    const key = String(item.topic || "").toLocaleLowerCase("it");
    if (item.topic && !seen.has(key)) {
      seen.add(key);
      topics.push({ label: item.topic, href: "#posizioni" });
    }
  }
  for (const stratum of scorecard?.strata || []) {
    for (const topic of stratum.topics || []) {
      const label = topicLabel(topic.cap_topic_code);
      const key = label.toLocaleLowerCase("it");
      if (!seen.has(key)) {
        seen.add(key);
        topics.push({ label, href: `./?view=proposals&topic=${encodeURIComponent(topic.cap_topic_code)}` });
      }
    }
  }
  return topics.slice(0, 8);
}

export function renderFollowButton(person) {
  const name = `${person.given_name} ${person.family_name}`.trim();
  const active = typeof localStorage !== "undefined" && isFavorite(person.id);
  return `<button type="button" class="follow-button favorite-toggle${active ? " is-active" : ""}" data-favorite-id="${escapeHtml(person.id)}" data-favorite-name="${escapeHtml(name)}" data-follow="1" aria-pressed="${active}">${active ? `${icon("check")}Segui già` : "Segui"}</button>`;
}

// Rule 8 of the redazione's writing models: date, writer and verifier on every sheet.
export function renderEditorialMeta(editorial, publishedDate) {
  const updated = editorial?.updated_at ? formatPublishedAt(editorial.updated_at) : publishedDate;
  const parts = [updated ? `Aggiornato al ${escapeHtml(updated)}` : "Ultimo aggiornamento non indicato"];
  if (editorial?.written_by?.length) parts.push(`Redattore: ${escapeHtml(editorial.written_by.join(", "))}`);
  if (editorial?.verified_by?.length) parts.push(`Verificatore: ${escapeHtml(editorial.verified_by.join(", "))}`);
  return `<p class="publication-meta">${parts.join(" · ")}</p>`;
}

export function renderRelatedPosts(editorial) {
  const posts = editorial?.related_posts || [];
  if (!posts.length) return "";
  return `<h3 class="overview-subhead">Notizie collegate</h3><ul class="related-posts">${posts.map((post) => `<li><a href="./?post=${encodeURIComponent(post.id)}">${escapeHtml(post.title)}</a>${post.published_on ? ` <span class="feed-meta">${escapeHtml(formatDate(post.published_on))}</span>` : ""}</li>`).join("")}</ul>`;
}

export function renderPoliticianDetail(person, scorecard = null) {
  const profile = person.profile;
  const gender = profile?.gender;
  const name = `${person.given_name} ${person.family_name}`;
  const publishedDate = formatPublishedAt(person.published_at);
  const mandate = currentMandate(person);
  const party = currentParty(person);
  const place = birthPlace(profile);
  const who = renderWhoIs(person);
  const careerItems = careerEntries(person);
  const hasGroups = Boolean((person.parliamentary_groups || []).length);
  const hasParties = Boolean((person.political_parties || []).length);
  const hasProposals = Boolean((person.proposals || []).length);
  const hasCareer = Boolean(careerItems.length || hasGroups || hasParties || hasProposals);
  const citationGroups = groupCitations(person.citations || []);
  const sourcesMarkup = renderSources(person.citations);
  const facts = [
    person.birth_date ? fact("Data di nascita", formatDate(person.birth_date)) : "",
    place !== "Non indicato" ? fact("Luogo di nascita", place) : "",
    mandate?.start_date ? fact("In carica dal", formatDate(mandate.start_date)) : "",
  ].filter(Boolean).join("");
  const topics = profileTopics(person, scorecard);
  const askQuestion = suggestedAskQuestions(person, scorecard)[0] || `Che cosa ha promesso ${name}?`;
  const tabs = renderProfileSectionNav([
    { href: "#profilo", label: "Panoramica" },
    hasCareer ? { href: "#carriera", label: "Carriera" } : null,
    { href: "#posizioni", label: "Posizioni" },
    { href: "#promesse", label: "Promesse" },
    { href: "#procedimenti", label: "Procedimenti" },
    sourcesMarkup ? { href: "#fonti", label: "Fonti" } : null,
  ].filter(Boolean));
  const overview = `<section class="detail-card profile-block profile-overview" id="profilo">
      ${who ? who.replace(/^<section[^>]*>/, "").replace(/<\/section>$/, "") : `<h2>Chi è</h2><p class="empty-note">La biografia non è ancora stata pubblicata.</p>`}
      ${topics.length ? `<h3 class="overview-subhead">Temi chiave</h3><div class="topic-chips">${topics.map((topic) => `<a class="topic-chip" href="${escapeHtml(topic.href)}"${topic.href.startsWith("#") ? ` data-tab-link="${escapeHtml(topic.href.slice(1))}"` : ""}>${escapeHtml(topic.label)}</a>`).join("")}</div>` : ""}
      ${facts ? `<h3 class="overview-subhead">Dati anagrafici</h3><dl class="facts header-facts">${facts}</dl>` : ""}
      ${renderAskSuggestions(person, scorecard)}
      ${renderRelatedPosts(person.editorial)}
      ${renderEditorialMeta(person.editorial, publishedDate)}
    </section>`;
  return `<section class="profile-cover" aria-labelledby="profile-name">
      <div class="cover-media">
        ${portrait(person, { size: "hero" })}
        <div class="cover-shade" aria-hidden="true"></div>
        <a class="cover-button cover-back" href="./?view=politicians" aria-label="Torna ai politici">${icon("arrowLeft", { size: 20 })}</a>
        <button type="button" class="cover-button cover-share" data-share-title="${escapeHtml(name)} — VeraPolitica" aria-label="Condividi il profilo">${icon("share", { size: 20 })}</button>
        <div class="cover-identity">
          <div class="cover-text">
            <h1 id="profile-name">${nameWithMark(name)}<span class="verified-mark" role="img" aria-label="Verificato su fonti ufficiali" title="Verificato su fonti ufficiali">${icon("badgeCheck", { size: 22 })}</span></span></h1>
            <p class="profile-office">${escapeHtml(mandate ? mandateRole(mandate, gender) : "Incarico non indicato")}</p>
            ${party ? `<p class="profile-party">${escapeHtml(party.name)}</p>` : ""}
          </div>
          ${renderFollowButton(person)}
        </div>
      </div>
      ${renderPhotoCredit(person)}
      <p class="share-status" role="status" aria-live="polite"></p>
    </section>
    ${renderProfileStats(scorecard)}
    ${tabs}
    <div class="profile-panels">
    ${overview}
    ${hasCareer ? `<section class="detail-card profile-block profile-career" id="carriera">
      <h2>Cosa ha fatto</h2>
      ${renderCareerTimeline(person)}
      ${hasGroups ? `<h3 class="career-subhead">Gruppi parlamentari</h3><p class="group-disclaimer">I gruppi parlamentari sono organi istituzionali di ciascuna Camera e non coincidono con i partiti politici.</p>${renderParliamentaryGroups(person.parliamentary_groups || [])}` : ""}
      ${hasParties ? `<h3 class="career-subhead">Partito politico</h3><p class="party-disclaimer">I partiti politici e i gruppi parlamentari sono concetti istituzionali distinti.</p>${renderPoliticalParties(person.political_parties || [])}` : ""}
      ${hasProposals ? `<h3 class="career-subhead">Proposte e promesse</h3>${renderPoliticianProposals(person.proposals || [])}` : ""}
    </section>` : ""}
    ${renderKeyPositions(person)}
    <section class="detail-card profile-block commitments-card" id="promesse">
      <h2>Scheda delle promesse</h2>
      ${renderScorecard(scorecard)}
    </section>
    ${renderProceedings(person)}
    ${sourcesMarkup ? `<section class="detail-card profile-block sources-card" id="fonti">
      <div class="sources-heading">
        <div><h2>Fonti ufficiali</h2></div>
        <div class="sources-summary"><strong>${person.citation_count} ${person.citation_count === 1 ? "riferimento verificato" : "riferimenti verificati"}</strong><br />${citationGroups.length} ${citationGroups.length === 1 ? "fonte ufficiale" : "fonti ufficiali"}</div>
      </div>
      <div class="source-list">${sourcesMarkup}</div>
    </section>` : ""}
    </div>
    ${renderTrustBlock()}
    <div class="profile-cta-bar">
      <a class="button button-primary profile-cta" href="./?view=ask&amp;prefill=${encodeURIComponent(askQuestion)}">${icon("ask", { size: 18 })}Chiedi a VeraPolitica</a>
    </div>`;
}

export function createPublicApiClient(fetchImpl = fetch) {
  async function request(path, { method = "GET", body, signal } = {}) {
    let response;
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    try {
      response = await fetchImpl(path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        credentials: "include",
        ...(signal ? { signal } : {}),
      });
    } catch (error) {
      if (error?.name === "AbortError") throw error;
      throw new Error("api_unavailable");
    }
    if (!response.ok) {
      let detail = "";
      try {
        const payload = await response.json();
        detail = typeof payload?.detail === "string"
          ? payload.detail
          : typeof payload?.error?.message === "string"
            ? payload.error.message
            : "";
      } catch { /* no JSON body */ }
      const error = new Error(response.status === 404 ? "not_found" : response.status === 422 ? "invalid_question" : "api_error");
      error.status = response.status;
      error.detail = detail;
      throw error;
    }
    return response.json();
  }
  return {
    listPoliticians: ({ role = "", offset = 0, limit = 50 } = {}) => {
      const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
      if (role) params.set("role", role);
      return request(`/politicians?${params}`);
    },
    getPolitician: (id) => request(`/politicians/${encodeURIComponent(id)}`),
    getScorecard: (id) => request(`/politicians/${encodeURIComponent(id)}/scorecard`),
    explainPledge: (id) => request(`/proposals/${encodeURIComponent(id)}/explanation`),
    ask: (question) => request("/ask", { method: "POST", body: { question } }),
    getPortraits: () => request("/portraits"),
    getScoringMethodology: () => request("/methodology/scoring"),
    listProposals: (filters = {}) => {
      const params = new URLSearchParams({ offset: "0", limit: "50" });
      for (const [key, value] of Object.entries(filters)) if (value) params.set(key, String(value));
      return request(`/proposals?${params}`);
    },
    listProposalTags: () => request("/proposals/tags"),
    getFeed: ({ scope = "all", zone = {}, offset = 0, redazione = false, follows = null } = {}) => {
      const params = new URLSearchParams({ scope, offset: String(offset), limit: "20" });
      if (redazione) params.set("redazione", "true");
      if (follows?.politicians.length) params.set("politicians", follows.politicians.join(","));
      if (follows?.parties.length) params.set("parties", follows.parties.join(","));
      if (zone.municipality_id) params.set("municipality", String(zone.municipality_id));
      else if (zone.province) params.set("province", zone.province);
      else if (zone.region_id) params.set("region", String(zone.region_id));
      return request(`/feed?${params}`);
    },
    getPost: (id) => request(`/feed/posts/${encodeURIComponent(id)}`),
    listParties: ({ all = false } = {}) => request(`/political-parties${all ? "?all=true" : ""}`),
    getPartyScorecard: (id, window = "all") => request(`/political-parties/${encodeURIComponent(id)}/scorecard?window=${encodeURIComponent(window)}`),
    compare: (ids, role) => request(`/compare/politicians?ids=${encodeURIComponent(ids.join(","))}&role=${encodeURIComponent(role)}`),
    listLegislatures: () => request("/archive/legislatures"),
    getLegislature: (number) => request(`/archive/legislatures/${encodeURIComponent(number)}`),
    listParliamentarians: ({ legislature = null, chamber = "", q = "", offset = 0 } = {}) => {
      const params = new URLSearchParams({ offset: String(offset), limit: "50" });
      if (legislature !== null && legislature !== "") params.set("legislature", String(legislature));
      if (chamber) params.set("chamber", chamber);
      if (q) params.set("q", q);
      return request(`/archive/parliamentarians?${params}`);
    },
    listProvinces: (regionId = null) => request(`/archive/provinces${regionId ? `?region=${encodeURIComponent(regionId)}` : ""}`),
    getProvinceHistory: (code) => request(`/archive/provinces/${encodeURIComponent(code)}`),
    getRegionHistory: (id) => request(`/archive/regions/${encodeURIComponent(id)}`),
    listMunicipalitiesInProvince: async (province) => {
      const items = [];
      for (let offset = 0; offset < 2000; offset += 100) {
        const page = await request(`/municipalities?province=${encodeURIComponent(province)}&offset=${offset}&limit=100`);
        items.push(...page.items);
        if (items.length >= page.total || !page.items.length) break;
      }
      return items;
    },
    getProposal: (id) => request(`/proposals/${encodeURIComponent(id)}`),
    listRegions: () => request("/regions?offset=0&limit=50"),
    getRegion: (id) => request(`/regions/${encodeURIComponent(id)}`),
    listMunicipalities: ({ offset = 0, regionId = null, limit = 50 } = {}) => {
      const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
      if (regionId) params.set("region", String(regionId));
      return request(`/municipalities?${params}`);
    },
    getMunicipality: (id) => request(`/municipalities/${encodeURIComponent(id)}`),
    search: ({ q, type = "", offset = 0, limit = 20, signal } = {}) => {
      const params = new URLSearchParams({ q, offset: String(offset), limit: String(limit) });
      if (type) params.set("type", type);
      return request(`/search?${params}`, { signal });
    },
    getParliamentaryGroup: (id) => request(`/parliamentary-groups/${encodeURIComponent(id)}`),
    getPoliticalParty: (id) => request(`/political-parties/${encodeURIComponent(id)}`),
    listReferendums: () => request("/referendums?offset=0&limit=50"),
    getReferendum: (id) => request(`/referendums/${encodeURIComponent(id)}`),
    listVotingGuides: () => request("/voting-guides?offset=0&limit=50"),
    getVotingGuide: (id) => request(`/voting-guides/${encodeURIComponent(id)}`),
    listGlossary: () => request("/glossary?offset=0&limit=50"),
    getGlossaryTerm: (slug) => request(`/glossary/${encodeURIComponent(slug)}`),
    me: async () => {
      try {
        return await request("/auth/me");
      } catch (error) {
        if (error.status === 401) return null;
        throw error;
      }
    },
    register: (body) => request("/auth/register", { method: "POST", body }),
    login: (body) => request("/auth/login", { method: "POST", body }),
    logout: () => request("/auth/logout", { method: "POST", body: {} }),
    saveAccountProfile: (profile) => request("/auth/profile", { method: "PUT", body: profile }),
  };
}

function showState(element, title, detail, isError = false) {
  element.hidden = false;
  element.className = `state-card${isError ? " is-error" : ""}`;
  element.innerHTML = `<div><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail)}</small></div>`;
}

async function fillCardRecords(api, people) {
  await Promise.allSettled(people.map(async (person) => {
    const slot = document.querySelector(`[data-record-for="${CSS.escape(String(person.id))}"]`);
    if (!slot) return;
    try {
      slot.innerHTML = renderCardRecord(await api.getScorecard(person.id));
    } catch {
      slot.innerHTML = `<p class="card-record-empty">Promesse non disponibili</p>`;
    }
  }));
}

const OFFICE_ORDER = ["presidente del consiglio", "vice presidente del consiglio", "ministro", "ministro senza portafoglio"];

function officeRank(person) {
  const office = String(primaryMandate(person)?.office ?? "").toLocaleLowerCase();
  const index = OFFICE_ORDER.indexOf(office);
  return index === -1 ? OFFICE_ORDER.length : index;
}

async function loadPortraits(api) {
  try {
    const data = await api.getPortraits();
    for (const [id, value] of Object.entries(data || {})) portraits.set(id, value);
  } catch {
    // Portraits are optional; monograms are drawn instead.
  }
}

export async function listAllPoliticians(api, { role = "" } = {}) {
  const items = [];
  let total = 0;
  for (let offset = 0; offset < 20000; offset += 100) {
    const page = await api.listPoliticians({ role, offset, limit: 100 });
    total = page.total || 0;
    items.push(...(page.items || []));
    if (items.length >= total || !(page.items || []).length) break;
  }
  return { items, total };
}

function archiveQuery() {
  return (byId("archive-q")?.value || "").trim();
}

function filterArchivePeople(people, query) {
  const tokens = query.toLocaleLowerCase("it").split(/\s+/).filter((token) => token.length >= 2);
  if (!tokens.length) return people;
  return people.filter((person) => {
    const hay = `${person.given_name} ${person.family_name} ${currentParty(person)?.name || ""} ${person.current_office || ""}`.toLocaleLowerCase("it");
    return tokens.every((token) => hay.includes(token));
  });
}

function paintArchive(api, people, total) {
  const query = archiveQuery();
  const shown = filterArchivePeople(people, query);
  byId("archive-count").textContent = query
    ? `${countLabel(shown.length, "risultato", "risultati")} su ${countLabel(total, "profilo", "profili")}`
    : countLabel(total, "profilo verificato", "profili verificati");
  if (!shown.length) {
    showState(
      byId("archive-status"),
      query ? "Nessun profilo corrisponde a questa ricerca." : "Nessun profilo verificato è al momento disponibile.",
      query ? "Apri Cerca per partito o promessa, oppure prova un altro cognome." : "I profili pubblicati compariranno qui dopo la verifica editoriale.",
    );
    byId("politician-list").hidden = true;
    return;
  }
  byId("archive-status").hidden = true;
  byId("politician-list").hidden = false;
  byId("politician-list").innerHTML = shown.map(renderPoliticianCard).join("");
  fillCardRecords(api, shown);
}

async function showArchive(api) {
  byId("archive-view").hidden = false;
  const form = byId("archive-search");
  try {
    const [payload] = await Promise.all([listAllPoliticians(api), loadPortraits(api)]);
    payload.items.sort((left, right) => officeRank(left) - officeRank(right)
      || `${left.family_name} ${left.given_name}`.localeCompare(`${right.family_name} ${right.given_name}`, "it"));
    paintArchive(api, payload.items, payload.total);
    if (form && !form.dataset.bound) {
      form.dataset.bound = "1";
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const query = archiveQuery();
        if (query.length >= 2) {
          window.location.href = `./?view=search&q=${encodeURIComponent(query)}`;
          return;
        }
        paintArchive(api, payload.items, payload.total);
      });
      byId("archive-q")?.addEventListener("input", () => paintArchive(api, payload.items, payload.total));
    }
  } catch {
    byId("archive-count").textContent = "Non disponibile";
    showState(byId("archive-status"), "Non è stato possibile caricare i profili verificati. Riprova.", PUBLIC_UNAVAILABLE, true);
  }
}

async function showDetail(api, politicianId) {
  byId("archive-view").hidden = true;
  byId("detail-view").hidden = false;
  try {
    const [person, scorecard] = await Promise.all([
      api.getPolitician(politicianId),
      api.getScorecard(politicianId).catch(() => null),
      loadPortraits(api),
    ]);
    const detail = byId("profile-detail");
    byId("detail-status").hidden = true;
    detail.hidden = false;
    detail.innerHTML = renderPoliticianDetail(person, scorecard);
    bindProfileSectionNav(detail);
    bindProfileShare(detail);
    bindProfileMotion(detail);
    bindPledgeFilters(detail);
    bindExplainPledges(detail, api);
    document.title = `${person.given_name} ${person.family_name} — VeraPolitica`;
  } catch (error) {
    const missing = error.status === 404;
    showState(
      byId("detail-status"),
      missing ? "Questo profilo verificato non è al momento disponibile." : "Non è stato possibile caricare questo profilo verificato. Riprova.",
      missing ? "Potrebbe non essere ancora stato pubblicato." : PUBLIC_UNAVAILABLE,
      true,
    );
  }
}

async function proposalFilters(api, params) {
  const filters = {};
  const notes = [];
  for (const key of ["status", "topic", "dossier"]) {
    const value = params.get(key);
    if (value) filters[key] = value;
  }
  let legislature = params.get("legislature");
  if (legislature) {
    try {
      const eras = await api.listLegislatures();
      const all = eras.eras.flatMap((era) => era.legislatures);
      const match = legislature === "current" ? all.find((item) => !item.end_date) : all.find((item) => String(item.number) === legislature);
      if (match) {
        filters.introduced_from = match.start_date;
        if (match.end_date) filters.introduced_to = match.end_date;
        notes.push(match.label);
      }
    } catch {
      legislature = null;
    }
  }
  if (filters.status) notes.push(proposalStatusLabel(filters.status));
  return { filters, notes };
}

const PROPOSAL_TYPES = ["explicit_promise", "legislative_proposal", "government_initiative"];
const PROPOSAL_COUNT_LABELS = {
  "": ["atto pubblicato", "atti pubblicati"],
  explicit_promise: ["promessa", "promesse"],
  legislative_proposal: ["proposta di legge", "proposte di legge"],
  government_initiative: ["iniziativa del Governo", "iniziative del Governo"],
};

const PROPOSAL_EMPTY = {
  "": "Nessun atto verificato",
  explicit_promise: "Nessuna promessa verificata",
  legislative_proposal: "Nessuna proposta di legge verificata",
  government_initiative: "Nessuna iniziativa del Governo verificata",
};

function proposalsUrl(params, changes) {
  const next = new URLSearchParams(params);
  next.set("view", "proposals");
  for (const [key, value] of Object.entries(changes)) {
    if (value) next.set(key, value);
    else next.delete(key);
  }
  return `./?${next}`;
}

async function showProposals(api) {
  byId("archive-view").hidden = true;
  byId("proposals-view").hidden = false;
  const params = new URLSearchParams(window.location.search);
  const type = PROPOSAL_TYPES.includes(params.get("type")) ? params.get("type") : "";
  for (const tab of byId("proposals-view").querySelectorAll(".proposals-tabs a")) {
    const active = tab.dataset.type === type;
    tab.setAttribute("aria-current", active ? "page" : "false");
    tab.href = proposalsUrl(params, { type: tab.dataset.type, topic: params.get("topic") });
  }
  try {
    const [{ filters, notes }, tags] = await Promise.all([proposalFilters(api, params), api.listProposalTags().catch(() => null)]);
    if (type) filters.proposal_type = type;
    const dossier = tags?.dossiers.find((item) => item.value === filters.dossier);
    const topic = tags?.topics.find((item) => item.value === filters.topic);
    if (dossier) {
      byId("proposals-title").textContent = dossier.label;
      document.title = `${dossier.label} — VeraPolitica`;
    } else if (params.get("legislature") === "current") {
      byId("proposals-title").textContent = "Proposte di legge attuali";
    }
    if (tags?.topics.length) {
      const chips = byId("proposal-topics");
      chips.hidden = false;
      chips.innerHTML = [`<a class="topic-chip${topic ? "" : " is-active"}" href="${escapeHtml(proposalsUrl(params, { topic: "" }))}"${topic ? "" : ' aria-current="true"'}>Tutti i temi</a>`]
        .concat(tags.topics.map((item) => {
          const active = item.value === filters.topic;
          return `<a class="topic-chip${active ? " is-active" : ""}" href="${escapeHtml(proposalsUrl(params, { topic: item.value }))}"${active ? ' aria-current="true"' : ""}>${escapeHtml(item.label)}</a>`;
        })).join("");
      chips.querySelector(".is-active")?.scrollIntoView?.({ block: "nearest", inline: "center" });
    }
    const [payload] = await Promise.all([api.listProposals({ ...filters, limit: 100 }), loadPortraits(api)]);
    const [one, many] = PROPOSAL_COUNT_LABELS[type];
    byId("proposal-count").textContent = `${countLabel(payload.total, one, many)}${notes.length ? ` · ${notes.join(" · ")}` : ""}`;
    const summary = byId("proposal-summary");
    summary.innerHTML = type === "explicit_promise" || !type ? renderPromiseSummary(payload.items, payload.total) : "";
    summary.hidden = !summary.innerHTML;
    if (!payload.items.length) {
      showState(
        byId("proposals-status"),
        dossier ? `Il dossier «${dossier.label}» non ha ancora atti pubblicati.` : `${PROPOSAL_EMPTY[type]} per questa selezione.`,
        "Compaiono qui dopo la verifica della redazione.",
      );
      byId("proposal-list").hidden = true;
      return;
    }
    byId("proposals-status").hidden = true;
    byId("proposal-list").hidden = false;
    byId("proposal-list").innerHTML = payload.items.map((item) => renderProposalCard(item, { showType: !type })).join("");
  } catch {
    showState(byId("proposals-status"), "Non è stato possibile caricare l'archivio delle proposte.", PUBLIC_UNAVAILABLE, true);
  }
}

async function showProposalDetail(api, proposalId) {
  byId("archive-view").hidden = true;
  byId("proposal-detail-view").hidden = false;
  try {
    const [proposal] = await Promise.all([api.getProposal(proposalId), loadPortraits(api)]);
    byId("proposal-detail-status").hidden = true;
    byId("proposal-detail").hidden = false;
    byId("proposal-detail").innerHTML = renderProposalDetail(proposal);
    bindExplainPledges(byId("proposal-detail"), api);
    document.title = `${proposal.title} — VeraPolitica`;
  } catch (error) {
    const missing = error.status === 404;
    showState(byId("proposal-detail-status"), missing ? "Questa proposta non è disponibile al pubblico." : "Non è stato possibile caricare questa proposta.", missing ? "Potrebbe essere ancora in verifica editoriale." : PUBLIC_UNAVAILABLE, true);
  }
}

async function listAllMunicipalities(api, regionId) {
  const items = [];
  for (let offset = 0; offset < 9000; offset += 100) {
    const page = await api.listMunicipalities({ offset, regionId, limit: 100 });
    items.push(...(page.items || []));
    if (items.length >= (page.total || 0)) break;
  }
  return items;
}

async function showRegions(api) {
  byId("archive-view").hidden = true;
  byId("regions-view").hidden = false;
  try {
    const payload = await api.listRegions();
    byId("region-count").textContent = countLabel(payload.total, "regione", "regioni");
    if (!payload.items.length) {
      showState(byId("regions-status"), "Nessuna regione è al momento disponibile.", "I territori ISTAT ufficiali compariranno dopo l'aggiornamento dell'archivio territoriale.");
      return;
    }
    byId("regions-status").hidden = true;
    byId("region-list").hidden = false;
    byId("region-list").innerHTML = payload.items.map(renderRegionCard).join("");
  } catch {
    showState(byId("regions-status"), "Non è stato possibile caricare le regioni.", PUBLIC_UNAVAILABLE, true);
  }
}

async function showRegionDetail(api, regionId) {
  byId("archive-view").hidden = true;
  byId("region-detail-view").hidden = false;
  try {
    const region = await api.getRegion(regionId);
    const municipalities = await listAllMunicipalities(api, regionId);
    byId("region-detail-status").hidden = true;
    byId("region-detail").hidden = false;
    byId("region-detail").innerHTML = renderRegionDetail(region, municipalities);
    document.title = `${region.name} — VeraPolitica`;
  } catch (error) {
    const missing = error.status === 404;
    showState(byId("region-detail-status"), missing ? "Questa regione non è disponibile." : "Non è stato possibile caricare questa regione.", missing ? "Potrebbe non essere ancora presente in archivio." : PUBLIC_UNAVAILABLE, true);
  }
}

async function showMunicipalities(api, offset) {
  byId("archive-view").hidden = true;
  byId("municipalities-view").hidden = false;
  try {
    const payload = await api.listMunicipalities({ offset });
    byId("municipality-count").textContent = countLabel(payload.total, "comune", "comuni");
    if (!payload.items.length) {
      showState(byId("municipalities-status"), "Nessun comune è al momento disponibile.", "I comuni ISTAT ufficiali compariranno dopo l'aggiornamento dell'archivio territoriale.");
      return;
    }
    byId("municipalities-status").hidden = true;
    byId("municipality-list").hidden = false;
    byId("municipality-list").innerHTML = payload.items.map(renderMunicipalityCard).join("");
    const pagination = byId("municipality-pagination");
    const previous = offset > 0 ? Math.max(0, offset - payload.limit) : null;
    const next = offset + payload.items.length < payload.total ? offset + payload.limit : null;
    pagination.hidden = previous === null && next === null;
    pagination.innerHTML = `${previous !== null ? `<a href="./?view=municipalities&offset=${previous}">Precedente</a>` : ""}<span>Risultati ${offset + 1}–${offset + payload.items.length} di ${payload.total}</span>${next !== null ? `<a href="./?view=municipalities&offset=${next}">Successiva</a>` : ""}`;
  } catch {
    showState(byId("municipalities-status"), "Non è stato possibile caricare i comuni.", PUBLIC_UNAVAILABLE, true);
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
    politician: "Politico",
    proposal: "Proposta",
    municipality: "Comune",
    region: "Regione",
    parliamentary_group: "Gruppo parlamentare",
    political_party: "Partito politico",
    referendum: "Referendum",
    glossary_term: "Glossario",
  }[value] || titleCase(value);
}

function renderAskResult(payload) {
  const results = (payload.results || []).map((item) => {
    const href = item.url || (item.type === "politician" ? `./?politician=${encodeURIComponent(item.id)}` : `./?proposal=${encodeURIComponent(item.id)}`);
    const chip = item.verdict ? renderVerdictChip(item.verdict) : "";
    return `<article class="ask-card">
      ${chip}
      <h3><a href="${escapeHtml(href)}">${escapeHtml(item.title)}</a></h3>
    </article>`;
  }).join("");
  const sources = (payload.sources || []).map((source) => {
    const url = safeExternalUrl(source.url);
    const title = escapeHtml(source.title || "Fonte ufficiale");
    return url
      ? `<li><a class="source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${title} ${icon("external", { size: 14 })}</a></li>`
      : `<li>${title}</li>`;
  }).join("");
  const note = payload.generated_by_ai
    ? "Testo generato automaticamente su dati verificati."
    : "Risposta generata dai dati pubblicati da VeraPolitica.";
  return `<p class="ask-answer">${escapeHtml(payload.answer)}</p>
    ${results ? `<div class="ask-cards">${results}</div>` : ""}
    ${sources ? `<ul class="explanation-sources">${sources}</ul>` : ""}
    <p class="explanation-note">${note}</p>`;
}

function showAsk(api) {
  byId("archive-view").hidden = true;
  byId("ask-view").hidden = false;
  const form = byId("ask-form");
  const field = byId("ask-question");
  const button = byId("ask-submit");
  const status = byId("ask-status");
  const result = byId("ask-result");
  const params = new URLSearchParams(window.location.search);
  const preset = params.get("question");
  const prefill = params.get("prefill");
  if (preset && !field.value) field.value = preset;
  else if (prefill && !field.value) field.value = prefill;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = field.value.trim();
    if (!question) {
      result.hidden = true;
      showState(status, "Scrivi una domanda.", "Il campo non può essere vuoto.");
      return;
    }
    button.disabled = true;
    result.hidden = true;
    status.hidden = false;
    status.className = "state-card loading-state";
    status.innerHTML = `<span class="loading-mark" aria-hidden="true"></span><div><strong>Sto cercando nei dati pubblicati…</strong><small>Solo promesse, stati e fonti già verificati.</small></div>`;
    try {
      const payload = await api.ask(question);
      status.hidden = true;
      result.hidden = false;
      result.innerHTML = renderAskResult(payload);
    } catch (error) {
      result.hidden = true;
      const invalid = error.status === 422;
      showState(
        status,
        invalid ? "La domanda non è valida." : "La risposta non è al momento disponibile.",
        invalid ? "Usa una domanda breve su politici, promesse, stati, temi o fonti pubblicate." : PUBLIC_UNAVAILABLE,
        true,
      );
    } finally {
      button.disabled = false;
    }
  });
  if (preset) form.requestSubmit();
}

// Search ----------------------------------------------------------------------
// Pattern: grouped results by kind with a best match on top (Spotify/Apple
// search), scope chips with counts, recent searches kept on this device only.

export const SEARCH_SCOPES = [
  { type: "politician", label: "Politici", icon: "users" },
  { type: "political_party", label: "Partiti", icon: "flag" },
  { type: "proposal", label: "Promesse e proposte", icon: "proposal" },
  { type: "referendum", label: "Referendum", icon: "vote" },
  { type: "region", label: "Regioni", icon: "map" },
  { type: "municipality", label: "Comuni", icon: "mapPin" },
  { type: "parliamentary_group", label: "Gruppi parlamentari", icon: "users" },
  { type: "glossary_term", label: "Glossario", icon: "book" },
];
const SEARCH_RECENT_KEY = "verapolitica.search.recent.v1";
const SEARCH_GROUP_SIZE = 4;
const searchParties = new Map();

export function readRecentSearches() {
  try {
    const items = JSON.parse(localStorage.getItem(SEARCH_RECENT_KEY) || "[]");
    return Array.isArray(items) ? items.filter((item) => typeof item === "string").slice(0, 8) : [];
  } catch {
    return [];
  }
}

function writeRecentSearches(items) {
  try { localStorage.setItem(SEARCH_RECENT_KEY, JSON.stringify(items.slice(0, 8))); } catch { /* private mode */ }
}

export function rememberSearch(query) {
  const value = query.trim();
  if (value.length < 2) return;
  writeRecentSearches([value, ...readRecentSearches().filter((item) => item.toLocaleLowerCase("it") !== value.toLocaleLowerCase("it"))]);
}

function searchScope(type) {
  return SEARCH_SCOPES.find((scope) => scope.type === type);
}

function searchLeading(item) {
  const id = item.metadata?.id;
  if (item.entity_type === "politician" && id) {
    const words = item.title.trim().split(/\s+/);
    const photo = resolvePortrait(id);
    const mono = initials({ given_name: words[0] || "", family_name: words.length > 1 ? words[words.length - 1] : "" });
    return `<span class="search-lead is-person" aria-hidden="true">${photo ? `<img src="${escapeHtml(photo)}" alt="" loading="lazy" />` : escapeHtml(mono)}</span>`;
  }
  if (item.entity_type === "political_party") {
    const logo = partyLogo(searchParties.get(String(id)), 40);
    if (logo) return `<span class="search-lead is-logo" aria-hidden="true">${logo}</span>`;
  }
  return `<span class="search-lead" aria-hidden="true">${icon(searchScope(item.entity_type)?.icon || "search", { size: 20 })}</span>`;
}

export function renderSearchCard(item, query) {
  return `<li><a class="row-link search-row" href="${escapeHtml(item.url)}">
    ${searchLeading(item)}
    <span class="row-text">
      <strong>${highlight(item.title, query)}</strong>
      <small>${highlight(item.subtitle, query)}</small>
      ${item.snippet ? `<span class="search-snippet">${highlight(item.snippet, query)}</span>` : ""}
    </span>
    <span class="row-chevron" aria-hidden="true">${icon("chevronRight", { size: 18 })}</span>
  </a></li>`;
}

function normalizeSearch(value) {
  return String(value ?? "").normalize("NFD").replace(/\p{M}/gu, "").toLocaleLowerCase("it").trim();
}

// Best match: how well the title matches (exact, starts with, a word starts
// with), with a small preference for people and parties over places.
export function bestSearchMatch(groups, query) {
  const target = normalizeSearch(query);
  let best = null;
  let bestScore = Infinity;
  groups.forEach((group) => {
    const order = SEARCH_SCOPES.findIndex((scope) => scope.type === group.type);
    for (const item of group.items) {
      const title = normalizeSearch(item.title);
      const quality = title === target ? 0
        : title.startsWith(target) ? 1
        : title.split(/[\s'’-]+/).some((word) => word.startsWith(target)) ? 2
        : null;
      if (quality === null) continue;
      const score = quality + Math.max(order, 0) * 0.4;
      if (score < bestScore) { best = item; bestScore = score; }
    }
  });
  return best;
}

function renderBestMatch(item, query) {
  return `<section class="search-best" aria-labelledby="search-best-title">
    <h2 id="search-best-title" class="search-section-title">Risultato migliore</h2>
    <a class="search-best-card" href="${escapeHtml(item.url)}">
      ${searchLeading(item).replace('class="search-lead', 'class="search-lead is-large')}
      <span class="search-best-text">
        <strong>${highlight(item.title, query)}</strong>
        <span class="search-best-kind">${escapeHtml(searchTypeLabel(item.entity_type))}</span>
        <small>${highlight(String(item.subtitle || "").replace(new RegExp(`^${searchTypeLabel(item.entity_type)}\\s*·\\s*`, "i"), ""), query)}</small>
      </span>
      <span class="row-chevron" aria-hidden="true">${icon("chevronRight", { size: 20 })}</span>
    </a>
  </section>`;
}

function scopeHref(query, type) {
  const params = new URLSearchParams({ view: "search" });
  if (query) params.set("q", query);
  if (type) params.set("type", type);
  return `./?${params}`;
}

export function renderSearchGroups(groups, query) {
  const best = bestSearchMatch(groups, query);
  const sections = groups.filter((group) => group.items.length).map((group) => {
    const scope = searchScope(group.type);
    const items = group.items.filter((item) => item !== best);
    if (!items.length) return "";
    const more = group.total > group.items.length
      ? `<a class="block-link" href="${escapeHtml(scopeHref(query, group.type))}" data-scope="${escapeHtml(group.type)}">Vedi tutti ${group.total}</a>`
      : "";
    return `<section class="search-group" aria-labelledby="search-group-${escapeHtml(group.type)}">
      <div class="block-head"><h2 id="search-group-${escapeHtml(group.type)}" class="search-section-title">${escapeHtml(scope.label)}</h2>${more}</div>
      <ul class="row-list">${items.map((item) => renderSearchCard(item, query)).join("")}</ul>
    </section>`;
  }).join("");
  return `${best ? renderBestMatch(best, query) : ""}${sections}`;
}

function renderSearchScopes(query, type, counts = null) {
  const chip = (scopeType, label) => {
    const active = scopeType === type;
    const count = counts && scopeType ? counts[scopeType] : null;
    if (counts && scopeType && !count && !active) return "";
    return `<a class="topic-chip${active ? " is-active" : ""}" href="${escapeHtml(scopeHref(query, scopeType))}" data-scope="${escapeHtml(scopeType)}"${active ? ' aria-current="true"' : ""}>${escapeHtml(label)}${count ? ` <small>${count}</small>` : ""}</a>`;
  };
  return chip("", "Tutto") + SEARCH_SCOPES.map((scope) => chip(scope.type, scope.label)).join("");
}

function renderSearchStart() {
  const recent = readRecentSearches();
  const recentBlock = recent.length
    ? `<section class="politics-block" aria-labelledby="search-recent-title">
        <div class="block-head"><h2 id="search-recent-title" class="search-section-title">Ricerche recenti</h2><button class="block-link link-button" type="button" data-clear-recent>Cancella</button></div>
        <ul class="row-list">${recent.map((query) => `<li class="recent-row"><a class="row-link" href="${escapeHtml(scopeHref(query, ""))}" data-recent="${escapeHtml(query)}"><span class="search-lead is-plain" aria-hidden="true">${icon("clock", { size: 18 })}</span><span class="row-text"><strong>${escapeHtml(query)}</strong></span></a><button class="recent-remove" type="button" data-remove-recent="${escapeHtml(query)}" aria-label="${escapeHtml(`Rimuovi «${query}» dalle ricerche recenti`)}">${icon("x", { size: 16 })}</button></li>`).join("")}</ul>
        <p class="search-privacy">Restano solo su questo dispositivo.</p>
      </section>`
    : "";
  const browse = [
    ["./?view=politicians", "users", "Politici", "Tutti i profili verificati"],
    ["./?view=politics", "flag", "Partiti e Governo", "Chi governa e i partiti nell'elenco"],
    ["./?view=proposals", "proposal", "Promesse e proposte", "Cosa è stato promesso, e a che punto è"],
    ["./?legislature=19", "users", "Legislatura XIX", "Deputati e senatori in carica"],
    ["./?view=regions", "map", "Regioni e comuni", "Territori ISTAT ufficiali"],
    ["./?view=glossary", "book", "Glossario", "Le parole delle istituzioni"],
  ];
  return `${recentBlock}<section class="politics-block" aria-labelledby="search-browse-title">
      <div class="block-head"><h2 id="search-browse-title" class="search-section-title">Esplora</h2></div>
      <ul class="row-list">${browse.map(([href, iconName, title, text]) => `<li><a class="row-link" href="${href}"><span class="row-icon" aria-hidden="true">${icon(iconName, { size: 20 })}</span><span class="row-text"><strong>${escapeHtml(title)}</strong><small>${escapeHtml(text)}</small></span><span class="row-chevron" aria-hidden="true">${icon("chevronRight", { size: 18 })}</span></a></li>`).join("")}</ul>
    </section>`;
}

function renderSearchSkeleton() {
  return `<ul class="row-list search-skeleton" aria-hidden="true">${Array.from({ length: 5 }, () => `<li><span class="row-link"><span class="search-lead"></span><span class="row-text"><span class="skeleton-line"></span><span class="skeleton-line is-short"></span></span><span></span></span></li>`).join("")}</ul>`;
}

async function showSearch(api, initialQuery, initialType) {
  byId("archive-view").hidden = true;
  byId("search-view").hidden = false;
  const form = byId("search-form");
  const field = byId("search-page-q");
  const clear = byId("search-clear");
  const scopes = byId("search-scopes");
  const list = byId("search-list");
  const status = byId("search-status");
  const start = byId("search-start");
  const count = byId("search-count");
  const state = { query: initialQuery, type: SEARCH_SCOPES.some((scope) => scope.type === initialType) ? initialType : "", seq: 0, controller: null, offset: 0 };
  field.value = state.query;

  // Party logos for party rows (cached once; optional).
  api.listParties({ all: true }).then((payload) => {
    for (const party of payload.items) searchParties.set(String(party.id), party);
  }).catch(() => {});
  const portraitsReady = loadPortraits(api).catch(() => {});

  const syncUrl = () => {
    const url = scopeHref(state.query.trim(), state.type);
    if (`${window.location.pathname}${window.location.search}`.endsWith(url.slice(1))) return;
    window.history.replaceState(null, "", url);
  };

  // Keep the active scope chip in view (the row scrolls on phones).
  const focusActiveScope = () => {
    const active = scopes.querySelector(".is-active");
    if (!active || !active.dataset.scope) { scopes.scrollLeft = 0; return; }
    scopes.scrollLeft = Math.max(0, active.offsetLeft - scopes.clientWidth / 2 + active.offsetWidth / 2);
  };

  const showStart = () => {
    list.hidden = true;
    status.hidden = true;
    start.hidden = false;
    start.innerHTML = renderSearchStart();
    scopes.innerHTML = renderSearchScopes("", state.type);
    focusActiveScope();
    count.textContent = "";
    document.title = "Cerca — VeraPolitica";
  };

  const run = async ({ remember = false } = {}) => {
    const query = state.query.trim();
    clear.hidden = !state.query;
    syncUrl();
    if (query.length < 2) {
      showStart();
      return;
    }
    const seq = ++state.seq;
    state.controller?.abort();
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    state.controller = controller;
    const signal = controller?.signal;
    start.hidden = true;
    status.hidden = true;
    list.hidden = false;
    list.setAttribute("aria-busy", "true");
    if (!list.querySelector(".row-list")) list.innerHTML = renderSearchSkeleton();
    try {
      let html;
      let total;
      await portraitsReady;
      const grouped = async () => {
        const groups = await Promise.all(SEARCH_SCOPES.map((scope) => api.search({ q: query, type: scope.type, limit: SEARCH_GROUP_SIZE, signal })
          .then((payload) => ({ type: scope.type, items: payload.items, total: payload.total }))
          .catch((error) => { if (error.name === "AbortError") throw error; return { type: scope.type, items: [], total: 0 }; })));
        return { groups, total: groups.reduce((sum, group) => sum + group.total, 0), counts: Object.fromEntries(groups.map((group) => [group.type, group.total])) };
      };
      let notice = "";
      if (state.type) {
        const payload = await api.search({ q: query, type: state.type, limit: 50, signal });
        if (seq !== state.seq) return;
        if (!payload.items.length) {
          // Nothing in this kind: show where the words do appear instead of a dead end.
          const all = await grouped();
          if (seq !== state.seq) return;
          if (all.total) {
            notice = `<p class="search-notice">Nessun risultato in ${escapeHtml(searchScope(state.type).label.toLocaleLowerCase("it"))}. Ecco cosa c'è nel resto dell'archivio.</p>`;
            state.type = "";
            syncUrl();
            scopes.innerHTML = renderSearchScopes(query, "", all.counts);
            list.innerHTML = notice + renderSearchGroups(all.groups, query);
            list.removeAttribute("aria-busy");
            count.textContent = countLabel(all.total, "risultato", "risultati");
            if (remember) rememberSearch(query);
            focusActiveScope();
            return;
          }
        }
        total = payload.total;
        scopes.innerHTML = renderSearchScopes(query, state.type);
        html = payload.items.length
          ? `<section class="search-group"><div class="block-head"><h2 class="search-section-title">${escapeHtml(searchScope(state.type).label)}</h2><span class="search-total">${escapeHtml(countLabel(payload.total, "risultato", "risultati"))}</span></div>
              <ul class="row-list">${payload.items.map((item) => renderSearchCard(item, query)).join("")}</ul>
              ${payload.total > payload.items.length ? `<p class="search-more-note">Mostrati i primi ${payload.items.length}. Aggiungi una parola per restringere.</p>` : ""}</section>`
          : "";
      } else {
        const all = await grouped();
        if (seq !== state.seq) return;
        total = all.total;
        scopes.innerHTML = renderSearchScopes(query, "", all.counts);
        html = total ? renderSearchGroups(all.groups, query) : "";
      }
      list.removeAttribute("aria-busy");
      focusActiveScope();
      count.textContent = countLabel(total, "risultato", "risultati");
      document.title = `${query} — Cerca — VeraPolitica`;
      if (remember && total) rememberSearch(query);
      if (!html) {
        list.hidden = true;
        list.innerHTML = "";
        status.hidden = false;
        status.className = "state-card search-empty";
        status.innerHTML = `<div><strong>Nessun risultato per «${escapeHtml(query)}»${state.type ? ` in ${escapeHtml(searchScope(state.type).label.toLocaleLowerCase("it"))}` : ""}.</strong>
          <small>Controlla la grafia o prova con meno parole.</small>
          <p class="search-empty-actions">${state.type ? `<a class="topic-chip" href="${escapeHtml(scopeHref(query, ""))}" data-scope="">Cerca in tutto</a>` : ""}<a class="topic-chip" href="./?view=ask&amp;prefill=${encodeURIComponent(query)}">Chiedi a VeraPolitica</a></p></div>`;
        return;
      }
      list.innerHTML = html;
    } catch (error) {
      if (error.name === "AbortError" || seq !== state.seq) return;
      list.hidden = true;
      list.removeAttribute("aria-busy");
      showState(
        status,
        error.status === 422 ? "Questa ricerca non può essere eseguita." : "Non è stato possibile completare la ricerca.",
        error.status === 422 ? "Usa al massimo 200 caratteri." : PUBLIC_UNAVAILABLE,
        true,
      );
    }
  };

  let timer = null;
  field.addEventListener("input", () => {
    state.query = field.value;
    clear.hidden = !field.value;
    window.clearTimeout(timer);
    timer = window.setTimeout(() => run(), 220);
  });
  field.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && field.value) {
      event.preventDefault();
      field.value = "";
      state.query = "";
      run();
    }
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    window.clearTimeout(timer);
    state.query = field.value;
    run({ remember: true });
    field.blur();
  });
  clear.addEventListener("click", () => {
    field.value = "";
    state.query = "";
    run();
    field.focus();
  });
  // Scope chips and "Vedi tutti" switch in place, without a page load.
  byId("search-view").addEventListener("click", (event) => {
    const scope = event.target.closest("[data-scope]");
    if (scope) {
      event.preventDefault();
      state.type = scope.dataset.scope;
      list.innerHTML = "";
      run();
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    const recent = event.target.closest("[data-recent]");
    if (recent) {
      event.preventDefault();
      field.value = recent.dataset.recent;
      state.query = field.value;
      run({ remember: true });
      return;
    }
    const remove = event.target.closest("[data-remove-recent]");
    if (remove) {
      writeRecentSearches(readRecentSearches().filter((item) => item !== remove.dataset.removeRecent));
      start.innerHTML = renderSearchStart();
      return;
    }
    if (event.target.closest("[data-clear-recent]")) {
      writeRecentSearches([]);
      start.innerHTML = renderSearchStart();
      return;
    }
    // Opening a result counts as a search worth remembering.
    if (event.target.closest(".search-row, .search-best-card")) rememberSearch(state.query);
  });

  run({ remember: Boolean(initialQuery) });
  if (!initialQuery) field.focus({ preventScroll: true });
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
      ? "Partito politico"
      : `Gruppo parlamentare · ${record.institution} · legislatura ${record.legislature}`;
    byId("organization-detail").innerHTML = `<article class="proposal-detail-hero">
      <p class="eyebrow">${escapeHtml(kind === "party" ? "Partito politico" : "Gruppo parlamentare")}</p>
      <h1 id="organization-detail-title">${escapeHtml(record.name)}</h1>
      <p class="hero-copy">${escapeHtml(subtitle)}${record.abbreviation ? ` · ${escapeHtml(record.abbreviation)}` : ""}</p>
    </article>`;
    document.title = `${record.name} — VeraPolitica`;
  } catch (error) {
    const missing = error.status === 404;
    showState(byId("organization-detail-status"), missing ? "Questo record non è disponibile." : "Non è stato possibile caricare questo record.", missing ? "Potrebbe non esistere nell'archivio pubblico." : PUBLIC_UNAVAILABLE, true);
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
    showState(byId("municipality-detail-status"), missing ? "Questo comune non è disponibile." : "Non è stato possibile caricare questo comune.", missing ? "Potrebbe non essere ancora presente in archivio." : PUBLIC_UNAVAILABLE, true);
  }
}

export function renderReferendumCard(item) {
  const synthetic = item.is_synthetic
    ? `<span class="institutional-note">Record dimostrativo sintetico</span>`
    : `<span class="institutional-note">Fonte ufficiale</span>`;
  return `<article class="proposal-card">
    <p class="eyebrow">${escapeHtml(mappedLabel(REFERENDUM_TYPE_LABELS, item.referendum_type))} · ${escapeHtml(mappedLabel(REFERENDUM_STATUS_LABELS, item.status))}</p>
    <h3><a href="./?referendum=${encodeURIComponent(item.id)}">${escapeHtml(item.title)}</a></h3>
    <p>${escapeHtml(formatDate(item.vote_date))} · ${escapeHtml(mappedLabel(SCOPE_TYPE_LABELS, item.scope_type))}${item.region_name ? ` · ${escapeHtml(item.region_name)}` : ""}</p>
    ${synthetic}
  </article>`;
}

export function renderReferendumDetail(item) {
  const synthetic = item.is_synthetic
    ? `<p class="hero-copy"><strong>Record dimostrativo sintetico.</strong> Non è una consultazione ufficiale in corso.</p>`
    : "";
  const quorum = item.quorum_description
    ? `<p><strong>Quorum.</strong> ${escapeHtml(item.quorum_description)}</p>`
    : "<p>Nessuna descrizione del quorum è pubblicata per questo record.</p>";
  const sources = (item.sources || []).map((source) => `
    <p><a href="${escapeHtml(source.source_url)}" rel="noreferrer">${escapeHtml(source.source_name)}</a>
    · ${escapeHtml(source.official_identifier)}</p>`).join("");
  const guide = item.voting_guide_id
    ? `<p><a href="./?view=voting-guide">Guida al voto collegata</a></p>`
    : "";
  return `<article class="proposal-detail-hero">
    <p class="eyebrow">${escapeHtml(mappedLabel(REFERENDUM_TYPE_LABELS, item.referendum_type))} · ${escapeHtml(mappedLabel(REFERENDUM_STATUS_LABELS, item.status))}</p>
    <h1 id="referendum-detail-title">${escapeHtml(item.title)}</h1>
    ${synthetic}
    <p class="hero-copy"><strong>Quesito ufficiale.</strong> ${escapeHtml(item.official_question)}</p>
    <p>${escapeHtml(formatDate(item.vote_date))}${item.vote_end_date ? ` – ${escapeHtml(formatDate(item.vote_end_date))}` : ""}${item.start_time ? ` · ${escapeHtml(item.start_time)}` : ""}${item.end_time ? `–${escapeHtml(item.end_time)}` : ""} · ${escapeHtml(mappedLabel(SCOPE_TYPE_LABELS, item.scope_type))}</p>
    ${item.voting_hours_description ? `<p>${escapeHtml(item.voting_hours_description)}</p>` : ""}
    ${quorum}
    ${guide}
    <div class="section-rule"></div>
    ${sources || `<p><a href="${escapeHtml(item.official_source_url)}" rel="noreferrer">${escapeHtml(item.official_source_url)}</a></p>`}
  </article>`;
}

export function renderVotingGuide(guide) {
  const sections = (guide.sections || []).map((section) => `
    <section class="guide-section">
      <h2>${escapeHtml(section.title)}</h2>
      <p>${escapeHtml(section.body)}</p>
      ${section.source_url ? `<p><a href="${escapeHtml(section.source_url)}" rel="noreferrer">Fonte ufficiale</a></p>` : ""}
    </section>`).join("");
  return `<article>
    <p class="eyebrow">${escapeHtml(mappedLabel(SCOPE_TYPE_LABELS, guide.scope))}</p>
    <h2>${escapeHtml(guide.title)}</h2>
    <p class="hero-copy">Indicazioni ricavate da ${escapeHtml(guide.source_name)}. Non raccomanda un voto favorevole o contrario.</p>
    ${sections}
    <p><a href="${escapeHtml(guide.source_url)}" rel="noreferrer">Fonte ufficiale della guida</a></p>
  </article>`;
}

export function renderGlossaryTerm(item) {
  return `<article class="glossary-card" id="${escapeHtml(item.slug)}">
    <h3><a href="./?glossary=${encodeURIComponent(item.slug)}">${escapeHtml(item.term)}</a></h3>
    <p>${escapeHtml(item.short_definition)}</p>
    ${item.extended_definition ? `<p>${escapeHtml(item.extended_definition)}</p>` : ""}
    <p><a href="${escapeHtml(item.source_url)}" rel="noreferrer">Fonte ufficiale</a></p>
  </article>`;
}

async function showReferendums(api) {
  byId("archive-view").hidden = true;
  byId("referendums-view").hidden = false;
  try {
    const payload = await api.listReferendums();
    byId("referendum-count").textContent = countLabel(payload.total, "record pubblicato", "record pubblicati");
    if (!payload.items.length) {
      showState(byId("referendums-status"), "Nessun referendum pubblicato è al momento disponibile.", "I record civici pubblicati compariranno qui dopo la verifica editoriale.");
      return;
    }
    byId("referendums-status").hidden = true;
    byId("referendum-list").hidden = false;
    byId("referendum-list").innerHTML = payload.items.map(renderReferendumCard).join("");
    document.title = "Referendum — VeraPolitica";
  } catch {
    byId("referendum-count").textContent = "Non disponibile";
    showState(byId("referendums-status"), "Non è stato possibile caricare i referendum.", PUBLIC_UNAVAILABLE, true);
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
    showState(byId("referendum-detail-status"), missing ? "Questo referendum non è disponibile." : "Non è stato possibile caricare questo referendum.", missing ? "Potrebbe non essere ancora stato pubblicato." : PUBLIC_UNAVAILABLE, true);
  }
}

async function showVotingGuide(api) {
  byId("archive-view").hidden = true;
  byId("voting-guide-view").hidden = false;
  try {
    const payload = await api.listVotingGuides();
    if (!payload.items.length) {
      showState(byId("voting-guide-status"), "Nessuna guida al voto pubblicata è al momento disponibile.", "Le indicazioni civiche ufficiali compariranno dopo la pubblicazione editoriale.");
      return;
    }
    byId("voting-guide-status").hidden = true;
    byId("voting-guide-detail").hidden = false;
    byId("voting-guide-detail").innerHTML = payload.items.map(renderVotingGuide).join("");
    document.title = "Guide al voto — VeraPolitica";
  } catch {
    showState(byId("voting-guide-status"), "Non è stato possibile caricare la guida al voto.", PUBLIC_UNAVAILABLE, true);
  }
}

async function showGlossary(api, slug) {
  byId("archive-view").hidden = true;
  byId("glossary-view").hidden = false;
  try {
    const payload = await api.listGlossary();
    byId("glossary-count").textContent = countLabel(payload.total, "termine", "termini");
    if (!payload.items.length) {
      showState(byId("glossary-status"), "Nessun termine di glossario è al momento pubblicato.", "Le definizioni verificate in sede editoriale compariranno qui.");
      return;
    }
    byId("glossary-status").hidden = true;
    byId("glossary-list").hidden = false;
    byId("glossary-list").innerHTML = payload.items.map(renderGlossaryTerm).join("");
    document.title = slug ? `${slug} — Glossario — VeraPolitica` : "Glossario — VeraPolitica";
    if (slug) {
      const target = document.getElementById(slug);
      if (target) target.scrollIntoView();
    }
  } catch {
    byId("glossary-count").textContent = "Non disponibile";
    showState(byId("glossary-status"), "Non è stato possibile caricare il glossario.", PUBLIC_UNAVAILABLE, true);
  }
}

async function showMethodology(api) {
  byId("archive-view").hidden = true;
  byId("methodology-view").hidden = false;
  try {
    const method = await api.getScoringMethodology();
    byId("methodology-status").hidden = true;
    byId("methodology-detail").hidden = false;
    byId("methodology-detail").innerHTML = renderMethodology(method);
  } catch {
    showState(byId("methodology-status"), "Non è stato possibile caricare la metodologia.", PUBLIC_UNAVAILABLE, true);
  }
}

// ---------------------------------------------------------------------------
// Reader profile: zone and favourites live only in this browser (no account).
const PROFILE_KEY = "verapolitica.profile.v1";

export function loadReaderProfile(storage = globalThis.localStorage) {
  try {
    const value = JSON.parse(storage?.getItem(PROFILE_KEY) || "{}");
    return {
      zone: value && typeof value.zone === "object" && value.zone ? value.zone : null,
      favorites: Array.isArray(value?.favorites) ? value.favorites.filter((item) => item && /^\d+$/.test(String(item.id))) : [],
      saved: Array.isArray(value?.saved) ? value.saved.filter((item) => item && typeof item.url === "string" && item.url.startsWith("./?post=")) : [],
      parties: Array.isArray(value?.parties) ? value.parties.filter((item) => item && /^\d+$/.test(String(item.id))) : [],
      member: value && typeof value.member === "object" && value.member && typeof value.member.name === "string" ? { name: value.member.name.slice(0, 40), since: value.member.since || null } : null,
    };
  } catch {
    return { zone: null, favorites: [], saved: [], parties: [], member: null };
  }
}

export function saveReaderProfile(profile, storage = globalThis.localStorage) {
  try {
    storage?.setItem(PROFILE_KEY, JSON.stringify({
      zone: profile.zone || null, favorites: profile.favorites || [], saved: profile.saved || [],
      parties: profile.parties || [], member: profile.member || null,
    }));
    return true;
  } catch {
    return false;
  }
}

let civicAccount = null;

function persistReaderProfile(profile) {
  const ok = saveReaderProfile(profile);
  if (civicAccount) {
    api.saveAccountProfile({
      ...profile,
      display_name: profile.member?.name || civicAccount.display_name,
    }).then((account) => { civicAccount = account; }).catch(() => {});
  }
  return ok;
}

function accountErrorMessage(error) {
  if (error?.status === 409) return "Questa email è già registrata.";
  if (error?.status === 429) return "Troppi tentativi. Riprova più tardi.";
  if (error?.status === 401) return "Email o password non corretti.";
  if (error?.status === 422) return "Controlla email e password (almeno 10 caratteri).";
  if (typeof error?.detail === "string" && error.detail) return error.detail;
  return "Operazione non riuscita. Riprova.";
}

export function toggleFavorite(profile, person) {
  const id = String(person.id);
  const exists = profile.favorites.some((item) => String(item.id) === id);
  return {
    ...profile,
    favorites: exists
      ? profile.favorites.filter((item) => String(item.id) !== id)
      : [...profile.favorites, { id, name: person.name }].slice(-24),
  };
}

function isFavorite(id) {
  return loadReaderProfile().favorites.some((item) => String(item.id) === String(id));
}

export function renderFavoriteToggle(person) {
  const name = `${person.given_name} ${person.family_name}`.trim();
  const active = typeof localStorage !== "undefined" && isFavorite(person.id);
  return `<button type="button" class="favorite-toggle${active ? " is-active" : ""}" data-favorite-id="${escapeHtml(person.id)}" data-favorite-name="${escapeHtml(name)}" aria-pressed="${active}" aria-label="${active ? "Rimuovi dai preferiti" : "Aggiungi ai preferiti"}: ${escapeHtml(name)}">${icon("star", { size: 18, filled: active })}</button>`;
}

document.addEventListener("click", (event) => {
  const button = event.target instanceof Element ? event.target.closest(".favorite-toggle") : null;
  if (!button) return;
  event.preventDefault();
  if (!isMember()) return demoNotice();
  const profile = toggleFavorite(loadReaderProfile(), { id: button.dataset.favoriteId, name: button.dataset.favoriteName });
  persistReaderProfile(profile);
  const active = isFavorite(button.dataset.favoriteId);
  for (const twin of document.querySelectorAll(`.favorite-toggle[data-favorite-id="${CSS.escape(button.dataset.favoriteId)}"]`)) {
    twin.classList.toggle("is-active", active);
    twin.setAttribute("aria-pressed", String(active));
    if (!twin.dataset.follow) twin.setAttribute("aria-label", `${active ? "Rimuovi dai preferiti" : "Aggiungi ai preferiti"}: ${button.dataset.favoriteName}`);
    twin.innerHTML = twin.dataset.follow ? (active ? `${icon("check")}Segui già` : "Segui") : icon("star", { size: 18, filled: active });
  }
});

function renderFavoriteChips(favorites) {
  return favorites.map((item) => `<a class="topic-chip" href="./?politician=${encodeURIComponent(item.id)}">${icon("star", { size: 14, filled: true })}${escapeHtml(item.name)}</a>`).join("");
}

export function zoneLabel(zone) {
  if (!zone) return "";
  if (zone.municipality_name) return `${zone.municipality_name}${zone.province ? ` (${zone.province})` : ""} · ${zone.region_name || ""}`;
  if (zone.province_name) return `Provincia di ${zone.province_name} · ${zone.region_name || ""}`;
  return zone.region_name || "";
}

// ---------------------------------------------------------------------------
// Reader mode: a registered profile on this device, or the read-only demo.
const DEMO_KEY = "verapolitica.demo.v1";

export function isMember(profile = loadReaderProfile()) {
  return Boolean(profile.member);
}

function isDemo() {
  try { return globalThis.sessionStorage?.getItem(DEMO_KEY) === "1"; } catch { return false; }
}

function enterDemo() {
  try { globalThis.sessionStorage?.setItem(DEMO_KEY, "1"); } catch { /* the demo still opens */ }
}

export function followsOf(profile) {
  const politicians = (profile.favorites || []).map((item) => Number(item.id)).filter(Number.isInteger).slice(0, 24);
  const parties = (profile.parties || []).map((item) => Number(item.id)).filter(Number.isInteger).slice(0, 24);
  return politicians.length || parties.length ? { politicians, parties } : null;
}

let noticeTimer = null;
function demoNotice() {
  let note = byId("demo-notice");
  if (!note) {
    document.body.insertAdjacentHTML("beforeend", `<div id="demo-notice" class="demo-notice" role="status"></div>`);
    note = byId("demo-notice");
  }
  note.innerHTML = `Senza account puoi solo consultare. <a href="./?view=registrati">Registrati</a> per salvare.`;
  note.classList.add("is-visible");
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => note.classList.remove("is-visible"), 4000);
}

function markReaderMode() {
  const member = isMember();
  document.body.classList.toggle("is-demo", !member);
  const link = document.querySelector(".header-profile");
  if (link && !member) {
    link.href = "./?view=accedi";
    link.querySelector(".header-profile-label").textContent = "Accedi";
  }
}

function openGate(render) {
  document.body.classList.add("is-gate");
  let root = byId("gate");
  if (!root) {
    document.body.insertAdjacentHTML("afterbegin", `<div id="gate"></div>`);
    root = byId("gate");
  }
  render(root);
}

function showWelcome() {
  document.title = "VeraPolitica";
  openGate((root) => renderWelcome(root, {
    onRegister: () => { window.location.href = "./?view=registrati"; },
    onLogin: () => { window.location.href = "./?view=accedi"; },
    onDemo: () => { enterDemo(); window.location.href = "./"; },
  }));
}

function showAccountForm(api, mode, error) {
  document.title = mode === "login" ? "Accedi — VeraPolitica" : "Registrati — VeraPolitica";
  openGate((root) => renderAccountForm(root, {
    mode,
    error,
    onSubmit: async ({ email, password }) => {
      try {
        civicAccount = mode === "login" ? await api.login({ email, password }) : await api.register({ email, password });
        if (civicAccount.profile) saveReaderProfile(civicAccount.profile);
        if (mode === "login" && isMember(civicAccount.profile || {})) {
          window.location.href = "./";
          return;
        }
        showOnboarding(api);
      } catch (failure) {
        showAccountForm(api, mode, accountErrorMessage(failure));
      }
    },
    onSwitch: () => { window.location.href = mode === "login" ? "./?view=registrati" : "./?view=accedi"; },
    onBack: () => { window.location.href = "./?view=benvenuto"; },
  }));
}

async function showOnboarding(api) {
  document.title = "Registrati — VeraPolitica";
  try { await loadPortraits(api); } catch { /* monograms instead */ }
  const current = loadReaderProfile();
  openGate((root) => runOnboarding(root, {
    api,
    portraitFor: resolvePortrait,
    initial: current,
    onClose: () => { window.location.href = current.member ? "./?view=profile" : isDemo() ? "./" : "./?view=benvenuto"; },
    onDone: (patch) => {
      const profile = { ...loadReaderProfile(), ...patch };
      persistReaderProfile(profile);
      window.location.href = "./";
    },
  }));
}

async function showRegistration(api) {
  if (civicAccount) return showOnboarding(api);
  document.title = "Registrati — VeraPolitica";
  try { await loadPortraits(api); } catch { /* monograms instead */ }
  openGate((root) => runOnboarding(root, {
    api,
    portraitFor: resolvePortrait,
    collectAccount: true,
    onClose: () => { window.location.href = "./?view=benvenuto"; },
    onCreateAccount: async ({ email, password, profile }) => {
      try {
        civicAccount = await api.register({ email, password });
      } catch (failure) {
        throw new Error(accountErrorMessage(failure));
      }
      persistReaderProfile({ ...loadReaderProfile(), ...profile });
      window.location.href = "./";
    },
  }));
}

function showLogin(api) {
  if (civicAccount) {
    window.location.href = "./";
    return;
  }
  showAccountForm(api, "login");
}

// Keep the reader's followed parties in step with the redazione's list: names,
// abbreviations and logos change there, and a party may be merged or removed.
async function syncFollows(api) {
  const profile = loadReaderProfile();
  if (!isMember(profile) || !(profile.parties || []).length) return;
  try {
    const current = new Map((await api.listParties({ all: true })).items.map((item) => [String(item.id), item]));
    const parties = profile.parties
      .filter((party) => current.has(String(party.id)))
      .map((party) => {
        const item = current.get(String(party.id));
        return { id: item.id, name: item.name, abbreviation: item.abbreviation || null, logo_url: item.logo_url || null };
      });
    if (JSON.stringify(parties) !== JSON.stringify(profile.parties)) persistReaderProfile({ ...loadReaderProfile(), parties });
  } catch { /* offline: keep what is saved */ }
}

// iOS Safari applies :active press states only when a touch listener exists.
document.addEventListener("touchstart", () => {}, { passive: true });

// ---------------------------------------------------------------------------
// Section tabs: Home, Politica, Archivio, Profilo.
const SECTION_BY_VIEW = {
  politics: "politics", politicians: "politics", proposals: "politics", compare: "politics",
  methodology: "politics", ask: "politics", search: "search",
  history: "history", parliamentarians: "history", provinces: "history", "referendum-archive": "history",
  regions: "history", municipalities: "history",
  profile: "profile",
};

export function sectionFor(params) {
  const view = params.get("view");
  if (view && SECTION_BY_VIEW[view]) return SECTION_BY_VIEW[view];
  if (params.get("politician") || params.get("proposal") || params.get("political_party") || params.get("parliamentary_group")) return "politics";
  if (params.get("legislature") || params.get("province") || params.get("region") || params.get("municipality") || params.get("history_region")) return "history";
  return "home";
}

function markSection(section) {
  for (const link of document.querySelectorAll("[data-section]")) {
    if (link.dataset.section === section) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

// Mobile menu: a modal dialog with focus trap, Escape, scroll lock and focus return.

const VIEW_DESCRIPTIONS = {
  politics: "Partiti, politici e proposte, con promesse valutate secondo un metodo pubblico.",
  history: "Legislature dal 1946, parlamentari, referendum e territori, con fonti ufficiali.",
  profile: "La tua zona e i tuoi politici preferiti, salvati solo su questo dispositivo.",
  proposals: "Proposte di legge e promesse esplicite verificate, con la cronologia ufficiale.",
  methodology: "Come VeraPolitica valuta le promesse: formula, intervalli e revisione editoriale.",
  referendums: "Referendum e consultazioni con quesiti ufficiali e date.",
};

function syncPageMeta(params) {
  const description = VIEW_DESCRIPTIONS[params.get("view")];
  if (description) document.querySelector('meta[name="description"]')?.setAttribute("content", description);
  // Canonical URL: the view, the record id or the search query; no tracking or paging noise.
  const keep = ["view", "politician", "proposal", "referendum", "political_party", "legislature", "province", "region", "municipality", "post", "glossary"];
  const canonical = new URL(window.location.pathname, window.location.origin);
  for (const key of keep) if (params.get(key)) canonical.searchParams.set(key, params.get(key));
  let link = document.querySelector('link[rel="canonical"]');
  if (!link) {
    link = document.createElement("link");
    link.rel = "canonical";
    document.head.append(link);
  }
  link.href = canonical.href;
  document.querySelector('meta[property="og:url"]')?.setAttribute("content", canonical.href);
}

// ---------------------------------------------------------------------------
// Home: verified feed.
const FEED_FILTERS = [
  ["all", "Tutti"], ["national", "Nazionale"], ["region", "Regionale"], ["province", "Provinciale"], ["municipality", "Comunale"],
];
const FEED_KIND_LABELS = {
  proposal_status: "Proposta di legge",
  pledge_verdict: "Promessa",
  referendum: "Referendum",
  editorial: "Redazione",
};

function feedPlace(item) {
  if (item.scope === "municipality") return item.municipality_name ? `Comune di ${item.municipality_name}` : "Comunale";
  if (item.scope === "province") return item.province_abbreviation ? `Provincia ${item.province_abbreviation}` : "Provinciale";
  if (item.scope === "region") return item.region_name || "Regionale";
  return "Nazionale";
}

// Feed: only the redazione's posts, one card each (frontend/app/feed-card.js).
function cardItem(item) {
  return {
    key: item.key,
    url: item.url,
    title: item.title,
    summary: item.card?.summary || item.detail,
    occurred_on: item.occurred_on,
    place: feedPlace(item),
    sources: item.sources || [],
    coverage: item.kind === "editorial" ? sourceCoverage(item.blocks?.fonti || []) : null,
    card: item.card?.composed ? item.card : { category: "notizia", category_label: "Notizia", tone: "navy", badge: { label: item.label === "correction" ? "Correzione" : "Dalla redazione", tone: "plain" } },
  };
}

function resolvePortrait(politicianId) {
  const photo = portraits.get(String(politicianId));
  return photo ? safeImageUrl(photo.url) : null;
}

export function toggleSavedPost(profile, url, title) {
  const saved = profile.saved || [];
  const exists = saved.some((item) => item.url === url);
  return { ...profile, saved: exists ? saved.filter((item) => item.url !== url) : [{ url, title }, ...saved].slice(0, 100) };
}

export function renderFeedTimelineItem(item, profile = { saved: [] }) {
  const entry = cardItem(item);
  return renderFeedCard(entry, { resolvePortrait, saved: (profile.saved || []).some((saved) => saved.url === entry.url) });
}

async function showHome(api) {
  byId("home-view").hidden = false;
  document.title = "Feed — VeraPolitica";
  let profile = loadReaderProfile();
  const zone = profile.zone;
  const segments = byId("feed-choice");
  const choice = { value: "all" };
  let forYouFallback = false;
  if (!isMember()) segments.querySelector('[data-feed="all"]').textContent = "Tutte";
  const list = byId("feed-list");
  const more = byId("feed-more");
  const status = byId("feed-status");
  let offset = 0;
  try { await loadPortraits(api); } catch { /* portraits are optional */ }
  bindFeedCards(list, {
    onSave: (url, title) => {
      if (!isMember()) { demoNotice(); return false; }
      profile = toggleSavedPost(loadReaderProfile(), url, title);
      persistReaderProfile(profile);
      return profile.saved.some((item) => item.url === url);
    },
  });
  const zoneLine = () => {
    byId("home-zone").innerHTML = choice.value === "local"
      ? (zone ? `${escapeHtml(zoneLabel(zone))} · <a href="./?view=profile">Cambia zona</a>` : `<a href="./?view=profile">Imposta la tua zona</a> per vedere le notizie del tuo territorio.`)
      : "";
  };
  const scopeFor = () => {
    if (choice.value === "national") return "national";
    if (choice.value === "local") return zone?.municipality_id ? "municipality" : zone?.province ? "province" : "region";
    return "all";
  };
  const showEmpty = (title, detail) => {
    list.hidden = true;
    more.hidden = true;
    showState(status, title, detail);
  };
  const load = async (append) => {
    zoneLine();
    if (choice.value === "saved") {
      const saved = loadReaderProfile().saved || [];
      more.hidden = true;
      if (!saved.length) return showEmpty("Nessun post salvato.", "Usa il segnalibro su una card per ritrovarla qui.");
      const items = await Promise.all(saved.map((entry) => {
        const id = new URLSearchParams(entry.url.split("?")[1] || "").get("post");
        return id ? api.getPost(id).catch(() => null) : null;
      }));
      status.hidden = true;
      list.hidden = false;
      list.innerHTML = items.filter(Boolean).map((item) => renderFeedTimelineItem(item, loadReaderProfile())).join("") || "";
      return;
    }
    if (choice.value === "local" && !zone) return showEmpty("Nessuna zona impostata.", "Imposta comune, provincia o regione nel Profilo.");
    more.disabled = true;
    if (!append) list.setAttribute("aria-busy", "true");
    try {
      const follows = choice.value === "all" && !forYouFallback ? followsOf(profile) : null;
      let page = await api.getFeed({ scope: scopeFor(), zone: zone || {}, offset, redazione: true, follows });
      if (follows && !append && !page.items.length) {
        // Nothing yet about what the reader follows: show everything, and say so.
        forYouFallback = true;
        page = await api.getFeed({ scope: "all", zone: {}, offset, redazione: true });
      }
      if (forYouFallback && choice.value === "all") {
        byId("home-zone").textContent = "Ancora nessuna notizia su chi segui o sulla tua zona: ecco tutte le notizie della redazione.";
      }
      status.hidden = true;
      if (!append) list.innerHTML = "";
      if (!page.items.length && !append) {
        showEmpty("Nessun post della redazione per questa scelta.", "I post compaiono qui dopo la verifica di una seconda persona della redazione.");
      } else {
        list.hidden = false;
        list.insertAdjacentHTML("beforeend", page.items.map((item) => renderFeedTimelineItem(item, loadReaderProfile())).join(""));
        more.hidden = !page.has_more;
        offset += page.items.length;
      }
    } catch {
      showEmpty("Non è stato possibile caricare il feed.", PUBLIC_UNAVAILABLE);
    } finally {
      more.disabled = false;
      list.removeAttribute("aria-busy");
    }
  };
  segments.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("[data-feed]") : null;
    if (!button || button.dataset.feed === choice.value) return;
    choice.value = button.dataset.feed;
    for (const item of segments.querySelectorAll("[data-feed]")) item.setAttribute("aria-pressed", String(item === button));
    offset = 0;
    forYouFallback = false;
    load(false);
  });
  more.addEventListener("click", () => load(true));
  await load(false);
}

const NEWS_SECTIONS = [
  ["perche", "Perché ne parliamo"],
  ["fatto", "Il fatto"],
  ["cosa_cambia", "Cosa cambia per te"],
  ["destra", "Cosa dice la destra"],
  ["sinistra", "Cosa dice la sinistra"],
  ["altri", "Cosa dicono gli altri"],
  ["numeri", "I numeri e l'impatto economico"],
  ["cosa_succede", "Cosa succede adesso"],
];

function newsText(text) {
  const lines = String(text || "").split("\n").map((line) => line.trim()).filter(Boolean);
  const bullets = lines.filter((line) => /^[-•*]\s/.test(line));
  if (bullets.length && bullets.length === lines.length) {
    return `<ul class="news-points">${bullets.map((line) => `<li>${escapeHtml(line.replace(/^[-•*]\s+/, ""))}</li>`).join("")}</ul>`;
  }
  return lines.map((line) => `<p>${escapeHtml(line)}</p>`).join("");
}

// The nine blocks of the redazione's news model, always in the same order.
export function renderNewsBlocks(blocks) {
  const sections = NEWS_SECTIONS.filter(([key]) => blocks[key]).map(([key, label]) => `<section class="news-block news-${key}">
      <h2>${escapeHtml(label)}</h2>${newsText(blocks[key])}
      ${key === "fatto" && blocks.perche_deciso ? `<p><strong>Perché è stato deciso, secondo chi ha deciso:</strong> ${escapeHtml(blocks.perche_deciso)}</p>` : ""}
    </section>`).join("");
  return `${blocks.sommario ? `<p class="lead">${escapeHtml(blocks.sommario)}</p>` : ""}<div class="news-blocks">${sections}</div>`;
}

async function showPost(api, postId) {
  byId("post-view").hidden = false;
  try {
    const item = await api.getPost(postId);
    byId("post-status").hidden = true;
    byId("post-detail").hidden = false;
    const sources = item.sources.map((source) => {
      const url = safeExternalUrl(source.url);
      return url ? `<li><a class="source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(source.title)} ${icon("external", { size: 14 })}</a></li>` : "";
    }).join("");
    try { await loadPortraits(api); } catch { /* optional */ }
    const detail = byId("post-detail");
    detail.innerHTML = `<h1 class="visually-hidden">${escapeHtml(item.title)}</h1>
    <div class="post-card">${renderFeedTimelineItem(item, loadReaderProfile())}</div>
    <section class="proposal-detail-hero post-deep">
      <p class="eyebrow">Approfondimento</p>
      ${item.label === "correction" ? `<p class="lead">Questo aggiornamento rettifica una pubblicazione precedente.</p>` : ""}
      ${item.blocks ? renderNewsBlocks({ ...item.blocks, sommario: null }) : `<p class="post-body">${escapeHtml(item.detail)}</p>`}
    </section>
    <section class="detail-card"><h2>Fonti</h2><ul class="explanation-sources">${sources}</ul>
    ${item.written_by ? `<p class="publication-meta">Aggiornato al ${escapeHtml(formatDate(item.occurred_on))} · Redattore: ${escapeHtml(item.written_by)} · Verificatore: ${escapeHtml(item.verified_by || "—")}</p>` : ""}
    <p class="empty-note">Ogni aggiornamento è approvato da una persona diversa da chi lo ha scritto e non viene modificato dopo la pubblicazione: le correzioni sono nuovi aggiornamenti.</p></section>`;
    bindFeedCards(detail, {
      onSave: (url, title) => {
        if (!isMember()) { demoNotice(); return false; }
        const profile = toggleSavedPost(loadReaderProfile(), url, title);
        persistReaderProfile(profile);
        return profile.saved.some((entry) => entry.url === url);
      },
    });
    document.title = `${item.title} — VeraPolitica`;
  } catch (error) {
    showState(byId("post-status"), error.status === 404 ? "Questo aggiornamento non è disponibile." : "Non è stato possibile caricare l'aggiornamento.", error.status === 404 ? "Potrebbe non essere ancora pubblicato." : PUBLIC_UNAVAILABLE, true);
  }
}

// ---------------------------------------------------------------------------
// Politica: parties, topics, party pages, comparison.
// Government order: Prime Minister, Deputy Prime Ministers, Ministers, then the rest.
const GOVERNMENT_RANK = ["presidente del consiglio", "vice presidente del consiglio", "ministro", "ministro senza portafoglio", "sottosegretario"];

export function governmentOfficeRank(office) {
  const key = String(office ?? "").toLocaleLowerCase("it").replace(/\s+/g, " ").trim();
  const exact = GOVERNMENT_RANK.indexOf(key);
  if (exact !== -1) return exact;
  if (key.includes("vice presidente") || key.includes("vicepresidente")) return 1;
  if (key.includes("presidente del consiglio")) return 0;
  if (key.includes("ministro senza portafoglio")) return 3;
  if (key.includes("viceministro") || key.includes("vice ministro")) return 3;
  if (key.includes("ministro")) return 2;
  if (key.includes("sottosegretario")) return 4;
  return GOVERNMENT_RANK.length;
}

export function governmentRank(person) {
  return governmentOfficeRank(cabinetMandate(person)?.office ?? primaryMandate(person)?.office);
}

// "Ministro della Difesa" → "Difesa"; titles without a portfolio keep their wording.
export function shortRole(person) {
  const mandate = primaryMandate(person);
  if (!mandate) return "";
  const role = mandateRole(mandate, person.profile?.gender);
  const portfolio = role.match(/^Ministr[oa] (?:della |del |dell['’]|degli |delle |dei |per (?:la |il |l['’]|gli |le |i )?)(.+)$/i);
  if (portfolio && !/^Vice/i.test(role)) return portfolio[1].charAt(0).toLocaleUpperCase("it") + portfolio[1].slice(1);
  return role.replace(/^Vice Presidente/i, "Vicepresidente").replace(/ e Ministro .+$/i, "");
}

// Size of each portrait in the Government cloud, by institutional role only
// (never by opinion, votes or popularity).
export const AUTHORITY_WEIGHT = [1, 0.78, 0.62, 0.52, 0.42];

export function authorityWeight(person) {
  return AUTHORITY_WEIGHT[governmentRank(person)] ?? 0.42;
}

function authorityNode(person, diameter) {
  const name = `${person.given_name} ${person.family_name}`.trim();
  const photo = resolvePortrait(person.id);
  const party = person.current_party;
  const mark = party
    ? partyLogo(party, 18) || `<span class="authority-abbr">${escapeHtml(party.abbreviation || party.name)}</span>`
    : "";
  return `<a class="authority-node" href="./?politician=${encodeURIComponent(person.id)}" style="--d:${diameter}px" aria-label="${escapeHtml(`${name}, ${shortRole(person)}${party ? `, ${party.name}` : ""}`)}">
    <span class="authority-photo">${photo ? `<img src="${escapeHtml(photo)}" alt="" loading="lazy" />` : `<span aria-hidden="true">${escapeHtml(initials(person))}</span>`}</span>
    ${mark ? `<span class="authority-party" title="${escapeHtml(party.name)}">${mark}</span>` : ""}
    <span class="authority-name">${escapeHtml(name)}</span>
  </a>`;
}

// Deterministic packing: highest role in the middle, the others placed along a
// spiral at the first spot where their box (portrait + logo + name) is free.
export function packAuthority(boxes, width) {
  const placed = [];
  const gap = 6;
  const squash = width < 600 ? 0.8 : 1.15; // narrow screens grow a little downwards
  const fits = (x, y, box) => x >= 0 && x + box.w <= width && placed.every((other) =>
    x + box.w + gap <= other.x || other.x + other.w + gap <= x || y + box.h + gap <= other.y || other.y + other.h + gap <= y);
  for (const box of boxes) {
    let x = (width - box.w) / 2;
    let y = 0;
    for (let step = 0; step < 6000; step += 1) {
      const angle = step * 0.21;
      const radius = 2.2 * angle;
      const cx = width / 2 + Math.cos(angle) * radius * squash - box.w / 2;
      const cy = Math.sin(angle) * radius - box.h / 2;
      if (fits(cx, cy, box)) { x = cx; y = cy; break; }
    }
    placed.push({ ...box, x, y });
  }
  const top = Math.min(0, ...placed.map((box) => box.y));
  for (const box of placed) box.y -= top;
  return { placed, height: Math.max(0, ...placed.map((box) => box.y + box.h)) };
}

export function renderAuthorityCloud(container, people) {
  const width = container.clientWidth;
  const ordered = [...people].sort((a, b) => authorityWeight(b) - authorityWeight(a)
    || `${a.family_name} ${a.given_name}`.localeCompare(`${b.family_name} ${b.given_name}`, "it"));
  const largest = Math.round(Math.min(150, Math.max(92, width * 0.27)));
  const diameters = ordered.map((person) => Math.round(largest * authorityWeight(person)));
  container.innerHTML = ordered.map((person, index) => authorityNode(person, diameters[index])).join("");
  if (!width) { container.classList.add("is-static"); return; }
  container.classList.remove("is-static");
  const nodes = [...container.querySelectorAll(".authority-node")];
  // Fix each box's width first, then measure its real height (names wrap).
  const labelWidth = width < 600 ? 78 : 92;
  const boxes = nodes.map((node, index) => {
    const w = Math.max(diameters[index], labelWidth);
    node.style.width = `${w}px`;
    return { w, h: node.offsetHeight, index };
  });
  const { placed, height } = packAuthority(boxes, width);
  for (const box of placed) {
    const node = nodes[box.index];
    node.style.transform = `translate(${Math.round(box.x)}px, ${Math.round(box.y)}px)`;
  }
  container.style.height = `${Math.ceil(height)}px`;
}

export function renderPartyRow(party) {
  const members = party.current_member_count
    ? `${party.current_member_count} ${party.current_member_count === 1 ? "profilo in carica" : "profili in carica"}`
    : "";
  const mark = partyLogo(party, 40) || `<span class="party-mark" aria-hidden="true">${escapeHtml(String(party.abbreviation || party.name).replace(/[^\p{L}\p{N}]/gu, "").slice(0, 3).toUpperCase())}</span>`;
  return `<li><a class="row-link" href="./?political_party=${encodeURIComponent(party.id)}">
    <span class="row-logo">${mark}</span>
    <span class="row-text"><strong>${escapeHtml(party.name)}</strong><small>${[party.abbreviation, members].filter(Boolean).map(escapeHtml).join(" · ")}</small></span>
  </a></li>`;
}

async function showPolitics(api) {
  byId("politics-view").hidden = false;
  document.title = "Politica — VeraPolitica";
  for (const holder of document.querySelectorAll("#politics-view [data-icon]")) holder.innerHTML = icon(holder.dataset.icon, { size: 20 });
  for (const link of document.querySelectorAll("#politics-view .row-link")) link.insertAdjacentHTML("beforeend", `<span class="row-chevron">${icon("chevronRight", { size: 18 })}</span>`);
  api.listProposalTags().then((tags) => {
    byId("topic-list").innerHTML = tags.topics.map((topic) => `<a class="topic-chip" href="./?view=proposals&amp;topic=${encodeURIComponent(topic.value)}">${escapeHtml(topic.label)}</a>`).join("");
    if (tags.dossiers.length) {
      byId("dossier-title").hidden = false;
      byId("dossier-list").hidden = false;
      byId("dossier-list").innerHTML = tags.dossiers.map((item) => `<a class="topic-chip" href="./?view=proposals&amp;dossier=${encodeURIComponent(item.value)}">${escapeHtml(item.label)}</a>`).join("");
    }
  }).catch(() => {
    byId("topic-list").innerHTML = `<p class="empty-note">Temi non disponibili.</p>`;
  });
  const people = Promise.all([api.listPoliticians({ role: "governo", limit: 100 }), loadPortraits(api)]).then(([payload]) => {
    const government = payload.items.filter((person) => governmentRank(person) < GOVERNMENT_RANK.length);
    government.sort((a, b) => governmentRank(a) - governmentRank(b) || `${a.family_name} ${a.given_name}`.localeCompare(`${b.family_name} ${b.given_name}`, "it"));
    const cloud = byId("government-row");
    if (!government.length) {
      cloud.classList.add("is-static");
      cloud.innerHTML = `<p class="empty-note">Nessun profilo del Governo pubblicato.</p>`;
      return;
    }
    renderAuthorityCloud(cloud, government);
    let lastWidth = cloud.clientWidth;
    if (typeof ResizeObserver === "function") {
      new ResizeObserver(() => {
        if (Math.abs(cloud.clientWidth - lastWidth) < 8) return;
        lastWidth = cloud.clientWidth;
        renderAuthorityCloud(cloud, government);
      }).observe(cloud);
    }
  }).catch(() => {
    byId("government-row").innerHTML = `<p class="empty-note">Non è stato possibile caricare i profili.</p>`;
  }).finally(() => byId("government-row").removeAttribute("aria-busy"));
  const parties = api.listParties({ all: true }).then((payload) => {
    const items = [...payload.items].sort((a, b) => b.current_member_count - a.current_member_count || a.name.localeCompare(b.name, "it"));
    byId("party-list").innerHTML = items.length
      ? items.map(renderPartyRow).join("")
      : `<li class="row-empty">La redazione non ha ancora pubblicato l'elenco dei partiti.</li>`;
  }).catch(() => {
    byId("party-list").innerHTML = `<li class="row-empty">Non è stato possibile caricare i partiti.</li>`;
  }).finally(() => byId("party-list").removeAttribute("aria-busy"));
  await Promise.all([people, parties]);
}

function renderMemberList(members, emptyText) {
  if (!members.length) return `<p class="empty-note">${escapeHtml(emptyText)}</p>`;
  return `<div class="favorite-chips">${members.map((member) => `<a class="topic-chip" href="./?politician=${encodeURIComponent(member.politician_id)}">${escapeHtml(member.name)}${member.end_date ? `<small>fino al ${escapeHtml(formatYear(member.end_date))}</small>` : ""}</a>`).join("")}</div>`;
}

export function renderPartyScorecard(card) {
  const contributors = card.contributors.length
    ? `<p class="empty-note">Promesse dei membri incluse: ${card.contributors.map((item) => `<a href="./?politician=${encodeURIComponent(item.politician_id)}">${escapeHtml(item.name)}</a> (${item.pledges})`).join(", ")}.</p>`
    : "";
  return `<div class="method-note party-method">
      <p>Il punteggio del partito <strong>non è una media dei punteggi dei suoi esponenti</strong>: somma le promesse del partito e quelle dei membri iscritti alla data della promessa, poi applica lo stesso metodo, ruolo per ruolo.</p>
    </div>
    ${renderScorecard(card)}
    ${contributors}
    ${card.unattributed_member_pledges ? `<p class="empty-note">${card.unattributed_member_pledges} promesse di membri non hanno una data utilizzabile e non sono attribuite.</p>` : ""}`;
}

async function showParty(api, partyId) {
  byId("organization-detail-view").hidden = false;
  const back = byId("organization-detail-view").querySelector(".back-link");
  if (back) {
    back.href = "./?view=politics";
    back.innerHTML = `<span aria-hidden="true">←</span> Politica`;
  }
  const params = new URLSearchParams(window.location.search);
  const windowName = params.get("window") === "current" ? "current" : "all";
  try {
    const [party, card] = await Promise.all([api.getPoliticalParty(partyId), api.getPartyScorecard(partyId, windowName).catch(() => null)]);
    byId("organization-detail-status").hidden = true;
    const detail = byId("organization-detail");
    detail.hidden = false;
    const toggle = [["current", "Attuale"], ["all", "Storica"]].map(([key, label]) => `<a class="filter-pill${key === windowName ? " is-active" : ""}" href="./?political_party=${encodeURIComponent(partyId)}&amp;window=${key}" aria-current="${key === windowName ? "true" : "false"}">${label}</a>`).join("");
    detail.innerHTML = `<article class="proposal-detail-hero">
      <h1 id="organization-detail-title">${escapeHtml(party.name)}</h1>
      <p class="hero-copy">${party.abbreviation ? `${escapeHtml(party.abbreviation)} · ` : ""}${party.current_members?.length || 0} profili pubblicati in carica</p>
    </article>
    <section class="detail-card"><h2>Esponenti</h2>
      ${renderMemberList(party.current_members || [], "Nessun esponente in carica ha ancora una scheda pubblicata.")}
      ${(party.former_members || []).length ? `<h3 class="career-subhead">In passato</h3>${renderMemberList(party.former_members, "")}` : ""}
    </section>
    <section class="detail-card commitments-card"><h2>Promesse</h2>
      <div class="filter-pills" role="group" aria-label="Periodo">${toggle}</div>
      <p class="empty-note">${windowName === "current" ? "Attuale: solo le promesse il cui mandato è in corso oggi." : "Storica: tutte le promesse pubblicate, di ogni mandato."}</p>
      ${card ? renderPartyScorecard(card) : `<p class="empty-note">Promesse non disponibili.</p>`}
    </section>`;
    bindPledgeFilters(detail);
    bindExplainPledges(detail, api);
    document.title = `${party.name} — VeraPolitica`;
  } catch (error) {
    const missing = error.status === 404;
    showState(byId("organization-detail-status"), missing ? "Questo partito non è disponibile." : "Non è stato possibile caricare questo partito.", missing ? "Potrebbe non esistere nell'archivio pubblico." : PUBLIC_UNAVAILABLE, true);
  }
}

export function renderComparison(result) {
  const rows = result.entries.map((entry) => {
    const stratum = entry.stratum;
    const body = stratum
      ? `${renderCompositionBar(stratum.composition, { compact: true })}${renderRateBlock(stratum, result.credible_level)}`
      : `<p class="empty-note">Nessuna promessa classificata in questo ruolo.</p>`;
    return `<article class="compare-card"><h3><a href="./?politician=${encodeURIComponent(entry.politician_id)}">${escapeHtml(entry.name)}</a></h3>${body}</article>`;
  }).join("");
  const overlap = result.overlapping_intervals
    ? `<p class="method-note">Gli intervalli plausibili si sovrappongono: con i dati attuali la differenza tra queste persone <strong>non è distinguibile</strong> dal caso.</p>`
    : "";
  return `${overlap}<div class="compare-grid">${rows}</div><p class="publication-meta">Ruolo: ${escapeHtml(ROLE_LABELS[result.role] || result.role)} · Metodologia ${escapeHtml(result.methodology_version)} · Dati al ${escapeHtml(formatDate(result.as_of))}</p>`;
}

async function showCompare(api) {
  byId("compare-view").hidden = false;
  document.title = "Confronto — VeraPolitica";
  const params = new URLSearchParams(window.location.search);
  const role = params.get("role") || "government_coalition";
  const chosen = new Set(params.getAll("id").filter((value) => /^\d+$/.test(value)));
  byId("compare-role").innerHTML = Object.entries(ROLE_LABELS).filter(([key]) => key !== "unknown").map(([key, label]) => `<option value="${key}"${key === role ? " selected" : ""}>${escapeHtml(label)}</option>`).join("");
  try {
    const people = await listAllPoliticians(api);
    byId("compare-people").innerHTML = people.items.map((person) => `<label class="compare-person"><input type="checkbox" name="id" value="${escapeHtml(person.id)}"${chosen.has(String(person.id)) ? " checked" : ""} /> ${escapeHtml(person.given_name)} ${escapeHtml(person.family_name)}</label>`).join("");
  } catch {
    byId("compare-people").innerHTML = `<p class="empty-note">${escapeHtml(PUBLIC_UNAVAILABLE)}</p>`;
  }
  if (chosen.size < 2) return;
  if (chosen.size > 6) {
    showState(byId("compare-status"), "Puoi confrontare al massimo 6 persone.", "Togli qualche selezione e riprova.", true);
    return;
  }
  try {
    const result = await api.compare([...chosen], role);
    byId("compare-status").hidden = true;
    byId("compare-result").hidden = false;
    byId("compare-result").innerHTML = renderComparison(result);
  } catch {
    showState(byId("compare-status"), "Non è stato possibile calcolare il confronto.", PUBLIC_UNAVAILABLE, true);
  }
}

// ---------------------------------------------------------------------------
// Archivio storico.
function dateRange(start, end) {
  return `${formatDate(start)} – ${end ? formatDate(end) : "in corso"}`;
}

export function renderLegislatureCard(item) {
  const total = item.camera_mandates + item.senato_mandates;
  const current = !item.end_date;
  return `<a class="legislature-card${current ? " is-current" : ""}" href="./?legislature=${encodeURIComponent(item.number)}">
    <span class="legislature-roman">${escapeHtml(item.roman)}</span>
    <span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(formatYear(item.start_date))}–${item.end_date ? escapeHtml(formatYear(item.end_date)) : "oggi"}${total ? ` · ${total} mandati in archivio` : ""}</small>${current ? `<small class="legislature-now">In corso · apri l'archivio</small>` : ""}</span>
  </a>`;
}

export function renderCurrentLegislatureWalk(item) {
  if (!item) return "";
  return `<section class="detail-card legislature-walk" aria-labelledby="legislature-walk-title">
    <h2 id="legislature-walk-title">Legislatura ${escapeHtml(item.roman)} in corso</h2>
    <p class="empty-note">Elenco ufficiale Camera e Senato. Apri la legislatura, poi una camera, poi la scheda.</p>
    <div class="filter-pills">
      <a class="filter-pill is-active" href="./?legislature=${encodeURIComponent(item.number)}">Apri la ${escapeHtml(item.roman)}</a>
      <a class="filter-pill" href="./?legislature=${encodeURIComponent(item.number)}&amp;chamber=camera">Deputati</a>
      <a class="filter-pill" href="./?legislature=${encodeURIComponent(item.number)}&amp;chamber=senato">Senatori</a>
      <a class="filter-pill" href="./?view=proposals&amp;legislature=${encodeURIComponent(item.number)}">Promesse e proposte</a>
      <a class="filter-pill" href="./?view=parliamentarians&amp;legislature=${encodeURIComponent(item.number)}">Cerca nei mandati</a>
    </div>
  </section>`;
}

async function showHistory(api) {
  byId("history-view").hidden = false;
  document.title = "Archivio storico — VeraPolitica";
  try {
    const payload = await api.listLegislatures();
    byId("history-status").hidden = true;
    byId("era-list").hidden = false;
    const current = payload.eras.flatMap((era) => era.legislatures).find((item) => !item.end_date) || null;
    byId("era-list").innerHTML = `${renderCurrentLegislatureWalk(current)}${payload.eras.map((era) => `<section class="detail-card era-card">
      <h2>${escapeHtml(era.label)}</h2>
      <p class="empty-note">${escapeHtml(era.note)}</p>
      <div class="legislature-grid">${era.legislatures.map(renderLegislatureCard).join("")}</div>
    </section>`).join("")}`;
  } catch {
    showState(byId("history-status"), "Non è stato possibile caricare l'archivio storico.", PUBLIC_UNAVAILABLE, true);
  } finally {
    // Shown after the legislatures so nothing on screen moves when they arrive.
    byId("territory-archive").hidden = false;
  }
}

export function renderRosterRow(item) {
  const name = `${item.given_name} ${item.family_name}`;
  const link = item.politician_id ? `<a href="./?politician=${encodeURIComponent(item.politician_id)}">${escapeHtml(name)}</a>` : escapeHtml(name);
  const source = safeExternalUrl(item.source_url);
  return `<li class="roster-row"><span class="roster-name">${link}</span><span>${escapeHtml(romanLegislature(item.legislature) || String(item.legislature))} · ${item.chamber === "senato" ? "Senato" : "Camera"}${item.election_area ? ` · ${escapeHtml(item.election_area)}` : ""}</span><span>${item.start_date ? escapeHtml(item.end_date ? dateRange(item.start_date, item.end_date) : `Dal ${formatDate(item.start_date)}`) : ""}</span>${source ? `<a class="source-link" href="${escapeHtml(source)}" target="_blank" rel="noopener noreferrer">Fonte ${icon("external", { size: 14 })}</a>` : ""}</li>`;
}

async function renderRoster(api, { legislature = null, chamber = "", q = "", offset = 0, target, status, pagination, baseHref }) {
  try {
    const page = await api.listParliamentarians({ legislature, chamber, q, offset });
    if (!page.items.length) {
      target.hidden = true;
      pagination.hidden = true;
      showState(status, q ? "Nessun parlamentare corrisponde alla ricerca." : "Il registro storico non è ancora stato importato.", q ? "Prova un'altra grafia del cognome." : "I mandati compaiono dopo l'importazione dai dati aperti della Camera.");
      return;
    }
    status.hidden = true;
    target.hidden = false;
    target.innerHTML = `<p class="count-pill">${countLabel(page.total, "mandato", "mandati")}</p><ul class="roster">${page.items.map(renderRosterRow).join("")}</ul>`;
    const previous = offset > 0 ? Math.max(0, offset - page.limit) : null;
    const next = offset + page.items.length < page.total ? offset + page.limit : null;
    pagination.hidden = previous === null && next === null;
    pagination.innerHTML = `${previous !== null ? `<a href="${baseHref}&amp;offset=${previous}">Precedente</a>` : ""}<span>${offset + 1}–${offset + page.items.length} di ${page.total}</span>${next !== null ? `<a href="${baseHref}&amp;offset=${next}">Successiva</a>` : ""}`;
  } catch {
    showState(status, "Non è stato possibile caricare il registro.", PUBLIC_UNAVAILABLE, true);
  }
}

async function showLegislature(api, number) {
  byId("legislature-view").hidden = false;
  const params = new URLSearchParams(window.location.search);
  const chamber = params.get("chamber") === "senato" ? "senato" : params.get("chamber") === "camera" ? "camera" : "";
  const offset = Number.parseInt(params.get("offset") || "0", 10) || 0;
  try {
    const detail = await api.getLegislature(number);
    const item = detail.legislature;
    byId("legislature-status").hidden = true;
    const article = byId("legislature-detail");
    article.hidden = false;
    const referendums = detail.referendums.length
      ? `<ul class="plain-list">${detail.referendums.map((ref) => `<li><a href="./?referendum=${encodeURIComponent(ref.id)}">${escapeHtml(ref.title)}</a> · ${escapeHtml(formatDate(ref.vote_date))}</li>`).join("")}</ul>`
      : `<p class="empty-note">Nessun referendum pubblicato in questo periodo.</p>`;
    const chamberTabs = [["", "Tutte"], ["camera", "Camera"], ["senato", "Senato"]].map(([key, label]) => `<a class="filter-pill${key === chamber ? " is-active" : ""}" href="./?legislature=${item.number}${key ? `&amp;chamber=${key}` : ""}">${label}</a>`).join("");
    const source = safeExternalUrl(item.source_url);
    article.innerHTML = `<section class="proposal-detail-hero">
      <p class="feed-meta">${escapeHtml(item.era_label)}</p>
      <h1 id="legislature-title">${escapeHtml(item.label)}</h1>
      <p class="hero-copy">${escapeHtml(dateRange(item.start_date, item.end_date))}</p>
      ${source ? `<p><a class="source-link" href="${escapeHtml(source)}" target="_blank" rel="noopener noreferrer">Fonte ufficiale ${icon("external", { size: 14 })}</a></p>` : ""}
      <nav class="legislature-nav">${detail.previous !== null ? `<a href="./?legislature=${detail.previous}">Precedente</a>` : "<span></span>"}${detail.next !== null ? `<a href="./?legislature=${detail.next}">Successiva ${icon("arrowRight")}</a>` : ""}</nav>
    </section>
    <section class="detail-card"><h2>Proposte di legge</h2>
      <p>${countLabel(detail.published_proposals, "proposta pubblicata", "proposte pubblicate")} presentate in questo periodo.</p>
      <a class="profile-link" href="./?view=proposals&amp;legislature=${item.number}">Vedi le proposte ${icon("arrowRight")}</a>
    </section>
    <section class="detail-card"><h2>Referendum</h2>${referendums}</section>
    <section class="detail-card"><h2>Parlamentari</h2>
      <div class="filter-pills">${chamberTabs}</div>
      <div id="legislature-roster-status" class="state-card loading-state" role="status"><span class="loading-mark" aria-hidden="true"></span><div><strong>Caricamento del registro…</strong><small>Mandati ufficiali.</small></div></div>
      <div id="legislature-roster" hidden></div>
      <nav id="legislature-roster-pagination" class="territory-pagination" hidden></nav>
    </section>`;
    document.title = `${item.label} — VeraPolitica`;
    await renderRoster(api, {
      legislature: item.number, chamber, offset,
      target: byId("legislature-roster"), status: byId("legislature-roster-status"), pagination: byId("legislature-roster-pagination"),
      baseHref: `./?legislature=${item.number}${chamber ? `&amp;chamber=${chamber}` : ""}`,
    });
  } catch (error) {
    showState(byId("legislature-status"), error.status === 404 ? "Questa legislatura non è in archivio." : "Non è stato possibile caricare la legislatura.", error.status === 404 ? "Le legislature vanno dalla Costituente (0) a oggi." : PUBLIC_UNAVAILABLE, true);
  }
}

async function showParliamentarians(api) {
  byId("parliamentarians-view").hidden = false;
  const params = new URLSearchParams(window.location.search);
  const q = (params.get("q") || "").trim();
  const legislature = params.get("legislature") || (!q ? "19" : "");
  const offset = Number.parseInt(params.get("offset") || "0", 10) || 0;
  if (byId("history-q")) byId("history-q").value = q;
  document.title = `${q ? `${q} — ` : legislature ? `Legislatura ${legislature} — ` : ""}Parlamentari dal 1948 — VeraPolitica`;
  if (q && q.length < 2) {
    showState(byId("parliamentarians-status"), "Scrivi almeno due lettere.", "Cerca per nome o cognome.");
    return;
  }
  const title = byId("parliamentarians-title");
  if (title) title.textContent = legislature && !q ? `Parlamentari della legislatura ${legislature}` : "Parlamentari dal 1948";
  await renderRoster(api, {
    q, offset, legislature: legislature || null,
    target: byId("parliamentarians-list"), status: byId("parliamentarians-status"), pagination: byId("parliamentarians-pagination"),
    baseHref: `./?view=parliamentarians${legislature ? `&amp;legislature=${encodeURIComponent(legislature)}` : ""}${q ? `&amp;q=${encodeURIComponent(q)}` : ""}`,
  });
}

async function showProvinces(api) {
  byId("provinces-view").hidden = false;
  document.title = "Province — VeraPolitica";
  try {
    const payload = await api.listProvinces();
    if (!payload.items.length) {
      showState(byId("provinces-status"), "Nessuna provincia disponibile.", "I comuni ISTAT non sono ancora stati importati.");
      return;
    }
    const groups = new Map();
    for (const item of payload.items) {
      if (!groups.has(item.region_name)) groups.set(item.region_name, []);
      groups.get(item.region_name).push(item);
    }
    byId("provinces-status").hidden = true;
    byId("province-list").hidden = false;
    byId("province-list").innerHTML = [...groups.entries()].sort(([a], [b]) => a.localeCompare(b, "it")).map(([region, items]) => `<section class="province-group"><h2>${escapeHtml(region)}</h2><div class="favorite-chips">${items.map((item) => `<a class="topic-chip" href="./?province=${encodeURIComponent(item.abbreviation)}">${escapeHtml(item.name)}<small>${escapeHtml(item.abbreviation)}</small></a>`).join("")}</div></section>`).join("");
  } catch {
    showState(byId("provinces-status"), "Non è stato possibile caricare le province.", PUBLIC_UNAVAILABLE, true);
  }
}

export function renderTerritoryHistory(history) {
  const holders = history.office_holders.length
    ? `<ol class="proposal-timeline">${history.office_holders.map((item) => `<li><time>${escapeHtml(item.start_date ? formatYear(item.start_date) : "")}</time><div><strong><a href="./?politician=${encodeURIComponent(item.politician_id)}">${escapeHtml(item.name)}</a></strong><p>${escapeHtml(officeLabel(item.office))} · ${escapeHtml(item.territory_name)} · ${escapeHtml(dateRange(item.start_date, item.end_date))}</p>${safeExternalUrl(item.source_url) ? `<a class="source-link" href="${escapeHtml(safeExternalUrl(item.source_url))}" target="_blank" rel="noopener noreferrer">Fonte ufficiale ${icon("external", { size: 14 })}</a>` : ""}</div></li>`).join("")}</ol>`
    : `<p class="empty-note">Nessun incarico ancora pubblicato con fonte.</p>`;
  const referendums = history.referendums.length
    ? `<ul class="plain-list">${history.referendums.map((ref) => `<li><a href="./?referendum=${encodeURIComponent(ref.id)}">${escapeHtml(ref.title)}</a> · ${escapeHtml(formatDate(ref.vote_date))}</li>`).join("")}</ul>`
    : `<p class="empty-note">Nessun referendum pubblicato per questo territorio.</p>`;
  const kind = history.kind === "province" ? `Provincia ${escapeHtml(history.province_abbreviation)}` : "Regione";
  const links = history.kind === "province"
    ? `<a class="profile-link" href="./?region=${encodeURIComponent(history.region_id)}">Vedi la regione ${icon("arrowRight")}</a>`
    : `<a class="profile-link" href="./?region=${encodeURIComponent(history.region_id)}">Comuni della regione ${icon("arrowRight")}</a>`;
  return `<section class="proposal-detail-hero"><p class="feed-meta">${kind}</p><h1 id="territory-history-title">${escapeHtml(history.name)}</h1>${links}</section>
    <section class="detail-card"><h2>${history.kind === "province" ? "Sindaci" : "Presidenti"}</h2>${holders}</section>
    <section class="detail-card"><h2>Referendum</h2>${referendums}</section>
    <p class="empty-note">${escapeHtml(history.coverage_note)}</p>`;
}

async function showTerritoryHistory(api, { province = null, regionId = null }) {
  byId("territory-history-view").hidden = false;
  try {
    const history = province ? await api.getProvinceHistory(province) : await api.getRegionHistory(regionId);
    byId("territory-history-status").hidden = true;
    byId("territory-history").hidden = false;
    byId("territory-history").innerHTML = renderTerritoryHistory(history);
    document.title = `${history.name} — Archivio — VeraPolitica`;
  } catch (error) {
    showState(byId("territory-history-status"), error.status === 404 ? "Questo territorio non è in archivio." : "Non è stato possibile caricare la storia del territorio.", error.status === 404 ? "Controlla il codice." : PUBLIC_UNAVAILABLE, true);
  }
}

async function showReferendumArchive(api) {
  byId("referendum-archive-view").hidden = false;
  document.title = "Referendum per anno — VeraPolitica";
  try {
    const payload = await api.listReferendums();
    if (!payload.items.length) {
      showState(byId("referendum-archive-status"), "Nessun referendum pubblicato.", "Le consultazioni compaiono dopo la verifica editoriale.");
      return;
    }
    const years = new Map();
    for (const item of [...payload.items].sort((a, b) => String(b.vote_date).localeCompare(String(a.vote_date)))) {
      const year = String(item.vote_date).slice(0, 4);
      if (!years.has(year)) years.set(year, []);
      years.get(year).push(item);
    }
    byId("referendum-archive-status").hidden = true;
    byId("referendum-archive").hidden = false;
    byId("referendum-archive").innerHTML = [...years.entries()].map(([year, items]) => `<section class="year-group"><h2>${escapeHtml(year)}</h2><div class="proposal-grid">${items.map(renderReferendumCard).join("")}</div></section>`).join("");
  } catch {
    showState(byId("referendum-archive-status"), "Non è stato possibile caricare i referendum.", PUBLIC_UNAVAILABLE, true);
  }
}

// ---------------------------------------------------------------------------
// Profilo.
async function showProfile(api) {
  byId("profile-view").hidden = false;
  document.title = "Profilo — VeraPolitica";
  let profile = loadReaderProfile();
  const member = isMember(profile);
  byId("profile-demo").hidden = member;
  byId("profile-member").hidden = !member;
  for (const id of ["zone-section", "favorites-section"]) byId(id).hidden = !member;
  if (!member) return;
  byId("profile-title").textContent = profile.member.name;
  byId("profile-copy").textContent = civicAccount
    ? `Account ${civicAccount.email}${profile.member.since ? ` · dal ${formatDate(profile.member.since)}` : ""}.`
    : `Profilo su questo dispositivo${profile.member.since ? ` dal ${formatDate(profile.member.since)}` : ""}.`;
  byId("profile-parties").innerHTML = (profile.parties || []).length
    ? profile.parties.map((party) => `<a class="topic-chip" href="./?political_party=${encodeURIComponent(party.id)}">${partyLogo(party)}${escapeHtml(party.abbreviation || party.name)}</a>`).join("")
    : `<p class="empty-note">Nessun partito.</p>`;
  byId("profile-delete").textContent = civicAccount ? "Esci" : "Cancella il profilo";
  byId("profile-delete").addEventListener("click", async () => {
    try { localStorage.removeItem(PROFILE_KEY); } catch { /* nothing stored */ }
    if (civicAccount) {
      try { await api.logout(); } catch { /* cookie still expires on the next visit */ }
      civicAccount = null;
    }
    window.location.href = "./?view=benvenuto";
  });
  const regionSelect = byId("zone-region");
  const provinceSelect = byId("zone-province");
  const municipalitySelect = byId("zone-municipality");
  const saved = byId("zone-saved");
  const renderFavorites = () => {
    byId("profile-favorites").innerHTML = profile.favorites.length
      ? `${renderFavoriteChips(profile.favorites)}<button type="button" id="favorites-clear" class="ghost-button">Svuota</button>`
      : `<p class="empty-note">Nessun preferito.</p>`;
  };
  const option = (value, label, selected) => `<option value="${escapeHtml(value)}"${selected ? " selected" : ""}>${escapeHtml(label)}</option>`;
  const fillProvinces = async (regionId, selected) => {
    provinceSelect.innerHTML = option("", "Tutta la regione", !selected);
    municipalitySelect.innerHTML = option("", "Tutta la provincia", true);
    municipalitySelect.disabled = true;
    provinceSelect.disabled = !regionId;
    if (!regionId) return;
    const provinces = await api.listProvinces(regionId);
    provinceSelect.insertAdjacentHTML("beforeend", provinces.items.map((item) => option(item.abbreviation, `${item.name} (${item.abbreviation})`, item.abbreviation === selected)).join(""));
  };
  const fillMunicipalities = async (province, selected) => {
    municipalitySelect.innerHTML = option("", "Tutta la provincia", !selected);
    municipalitySelect.disabled = !province;
    if (!province) return;
    const towns = await api.listMunicipalitiesInProvince(province);
    towns.sort((a, b) => a.name.localeCompare(b.name, "it"));
    municipalitySelect.insertAdjacentHTML("beforeend", towns.map((town) => option(town.id, town.name, String(town.id) === String(selected))).join(""));
  };
  renderFavorites();
  saved.textContent = profile.zone ? `Zona salvata: ${zoneLabel(profile.zone)}` : "Nessuna zona salvata.";
  try {
    const regions = await api.listRegions();
    regionSelect.insertAdjacentHTML("beforeend", regions.items.map((region) => option(region.id, region.name, String(region.id) === String(profile.zone?.region_id))).join(""));
    if (profile.zone?.region_id) await fillProvinces(profile.zone.region_id, profile.zone.province);
    if (profile.zone?.province) await fillMunicipalities(profile.zone.province, profile.zone.municipality_id);
  } catch {
    saved.textContent = "Le zone non sono al momento disponibili.";
  }
  regionSelect.addEventListener("change", () => fillProvinces(regionSelect.value, null).catch(() => {}));
  provinceSelect.addEventListener("change", () => fillMunicipalities(provinceSelect.value, null).catch(() => {}));
  byId("zone-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!regionSelect.value) {
      saved.textContent = "Scegli almeno una regione.";
      return;
    }
    const text = (select) => select.selectedOptions[0]?.textContent || "";
    profile = {
      ...profile,
      zone: {
        region_id: Number(regionSelect.value),
        region_name: text(regionSelect),
        province: provinceSelect.value || null,
        province_name: provinceSelect.value ? text(provinceSelect).replace(/\s*\([A-Z]{2}\)$/, "") : null,
        municipality_id: municipalitySelect.value ? Number(municipalitySelect.value) : null,
        municipality_name: municipalitySelect.value ? text(municipalitySelect) : null,
      },
    };
    saved.textContent = persistReaderProfile(profile)
      ? `Zona salvata: ${zoneLabel(profile.zone)}`
      : "Questo browser non permette di salvare la zona.";
  });
  byId("zone-clear").addEventListener("click", () => {
    profile = { ...profile, zone: null };
    persistReaderProfile(profile);
    regionSelect.value = "";
    fillProvinces("", null);
    saved.textContent = "Zona rimossa.";
  });
  byId("profile-favorites").addEventListener("click", (event) => {
    if (!(event.target instanceof Element) || event.target.id !== "favorites-clear") return;
    profile = { ...profile, favorites: [] };
    persistReaderProfile(profile);
    renderFavorites();
  });
}

// Broken portraits fall back to initials. Inline onerror handlers are blocked by
// the Content-Security-Policy, so the cleanup is delegated here.
document.addEventListener("error", (event) => {
  const target = event.target;
  if (target instanceof HTMLImageElement && target.closest(".portrait")) {
    target.closest(".hero-media")?.querySelector(".photo-credit")?.remove();
    target.closest(".portrait").classList.remove("has-photo");
    target.remove();
  }
}, true);

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
const legislatureNumber = params.get("legislature");
const provinceCode = params.get("province");
const historyRegionId = params.get("history_region");
const postId = params.get("post");
const view = params.get("view");
const municipalityOffset = Number.parseInt(params.get("offset") || "0", 10);
const isId = (value) => Boolean(value) && /^\d+$/.test(value);
markSection(sectionFor(params));
syncPageMeta(params);

async function start() {
  try {
    const account = await api.me();
    if (account?.profile) {
      civicAccount = account;
      saveReaderProfile(account.profile);
    }
  } catch { /* offline: keep the local cache */ }
  markReaderMode();
  syncFollows(api);
  // Shared links (a post, a profile...) open directly, read-only.
  const firstVisit = !isMember() && !isDemo() && ![...params.keys()].length;
  if (view === "registrati") {
    showRegistration(api);
  } else if (view === "accedi") {
    showLogin(api);
  } else if (view === "benvenuto" || firstVisit) {
    showWelcome();
  } else if (isId(proposalId)) {
  showProposalDetail(api, proposalId);
} else if (isId(politicianId)) {
  showDetail(api, politicianId);
} else if (isId(referendumId)) {
  showReferendumDetail(api, referendumId);
} else if (isId(postId)) {
  showPost(api, postId);
} else if (glossarySlug) {
  showGlossary(api, glossarySlug);
} else if (isId(municipalityId)) {
  showMunicipalityDetail(api, municipalityId);
} else if (isId(historyRegionId)) {
  showTerritoryHistory(api, { regionId: historyRegionId });
} else if (isId(regionId)) {
  showRegionDetail(api, regionId);
} else if (isId(groupId)) {
  showOrganization(api, "group", groupId);
} else if (isId(partyId)) {
  showParty(api, partyId);
} else if (legislatureNumber && /^\d{1,2}$/.test(legislatureNumber) && view !== "proposals") {
  showLegislature(api, legislatureNumber);
} else if (provinceCode && /^[A-Z]{2}$/.test(provinceCode)) {
  showTerritoryHistory(api, { province: provinceCode });
} else if (view === "politics") {
  showPolitics(api);
} else if (view === "politicians") {
  showArchive(api);
} else if (view === "compare") {
  showCompare(api);
} else if (view === "history") {
  showHistory(api);
} else if (view === "parliamentarians") {
  showParliamentarians(api);
} else if (view === "provinces") {
  showProvinces(api);
} else if (view === "referendum-archive") {
  showReferendumArchive(api);
} else if (view === "profile") {
  showProfile(api);
} else if (view === "proposals") {
  showProposals(api);
} else if (view === "referendums") {
  showReferendums(api);
} else if (view === "voting-guide") {
  showVotingGuide(api);
} else if (view === "glossary") {
  showGlossary(api);
} else if (view === "regions") {
  showRegions(api);
} else if (view === "municipalities") {
  showMunicipalities(api, Number.isFinite(municipalityOffset) ? municipalityOffset : 0);
} else if (view === "methodology") {
  showMethodology(api);
} else if (view === "ask") {
  showAsk(api);
  } else if (view === "search") {
    showSearch(api, params.get("q") || "", params.get("type") || "");
  } else {
    showHome(api);
  }
}

start();
