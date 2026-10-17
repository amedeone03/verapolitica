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
  if (!value) return "Non indicata";
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.valueOf())
    ? String(value)
    : new Intl.DateTimeFormat("it-IT", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(date);
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
    : new Intl.DateTimeFormat("it-IT", { day: "numeric", month: "long", year: "numeric" }).format(date);
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
  return `<div class="portrait glass-portrait is-${size}${imageUrl ? " has-photo" : ""}"${imageUrl ? "" : ` aria-label="Nessun ritratto disponibile"`}>${monogram}${image}</div>`;
}

export function renderPhotoCredit(person) {
  const photo = portraitFor(person);
  if (!photo || !safeImageUrl(photo.url)) return "";
  const link = safeExternalUrl(photo.source_url);
  const label = photo.origin === "Wikimedia Commons"
    ? `Foto: ${photo.credit} · ${photo.license} · Wikimedia Commons`
    : `Foto: ${photo.origin}`;
  return link
    ? `<a class="photo-credit" href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)} ↗</a>`
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

function currentMandate(person) {
  const mandates = [...(person.profile?.mandates || [])];
  const open = mandates.filter((item) => !item.end_date);
  const pool = open.length ? open : mandates;
  pool.sort((left, right) => String(right.start_date || "").localeCompare(String(left.start_date || "")));
  return pool[0] ?? null;
}

function currentParty(person) {
  return (person.political_parties || []).find((item) => !item.end_date) || null;
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
      <span class="verified-badge">Verificato su fonti ufficiali</span>
      <h3>${escapeHtml(person.given_name)} ${escapeHtml(person.family_name)}</h3>
      <p class="mandate">${escapeHtml(mandateTitle(mandate, gender))}</p>
      <p class="area">${escapeHtml(mandate?.institution ?? "Istituzione nazionale")}${mandate?.election_area ? ` · ${escapeHtml(mandate.election_area)}` : ""}</p>
      <div class="card-record" data-record-for="${escapeHtml(person.id)}"><p class="card-record-empty">Caricamento delle promesse…</p></div>
      <p class="source-count">${person.citation_count} ${person.citation_count === 1 ? "riferimento verificato" : "riferimenti verificati"}</p>
      <a class="profile-link" href="./?politician=${encodeURIComponent(person.id)}">Vedi profilo <span aria-hidden="true">→</span></a>
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
  return `<article class="source-card">
    <p class="source-card-kind">${escapeHtml(kindLabel)}</p>
    ${displayName ? `<h3>${escapeHtml(displayName)}</h3>` : ""}
    ${title ? `<p class="source-card-title">${escapeHtml(title)}</p>` : ""}
    ${date ? `<p class="source-card-date">${escapeHtml(date)}</p>` : ""}
    ${extra}
    ${href ? `<a class="source-link" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">Apri la fonte <span aria-hidden="true">→</span></a>` : ""}
  </article>`;
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
    <p class="eyebrow">Profilo</p>
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
    <p class="eyebrow">Profilo</p>
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
    <p class="eyebrow">Posizioni</p>
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
    <p class="eyebrow">Procedimenti</p>
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
    <p class="eyebrow">Metodo</p>
    <h2>Come vengono verificati questi dati?</h2>
    <p>VeraPolitica utilizza fonti pubbliche e documenti verificabili. Le valutazioni delle promesse vengono pubblicate solo dopo revisione.</p>
    <a class="profile-link" href="./?view=methodology">Metodologia <span aria-hidden="true">→</span></a>
  </section>`;
}

function renderProfileSectionNav(sections) {
  const links = sections.filter((item) => item.href && item.label);
  if (!links.length) return "";
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

export function renderProposalCard(proposal) {
  const sourceUrl = safeExternalUrl(proposal.source?.url);
  return `<article class="proposal-card">
    <div class="proposal-card-top"><span class="proposal-type">${escapeHtml(proposalTypeLabel(proposal.proposal_type))}</span><span class="status-chip">${escapeHtml(proposalStatusLabel(proposal.current_status))}</span></div>
    <h3>${escapeHtml(proposal.title)}</h3>
    <div class="proposal-actors">${proposal.actors.length ? proposal.actors.map(renderProposalActor).join("") : "<span>Nessun attore pubblicato</span>"}</div>
    <p>${escapeHtml(formatDate(proposal.introduced_at))}</p>
    <div class="proposal-card-links"><a class="profile-link" href="./?proposal=${encodeURIComponent(proposal.id)}">Vedi cronologia <span aria-hidden="true">→</span></a>${sourceUrl ? `<a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Fonte ufficiale ↗</a>` : ""}</div>
  </article>`;
}

export function renderProposalTimeline(events = []) {
  return `<ol class="proposal-timeline">${events.map((event) => {
    const url = safeExternalUrl(event.source?.url);
    return `<li><time>${escapeHtml(formatDate(event.effective_at))}</time><div><strong>${escapeHtml(proposalStatusLabel(event.status))}</strong><p>Etichetta ufficiale: ${escapeHtml(event.source_status_label)}</p>${url ? `<a class="source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Elementi di verifica ↗</a>` : ""}</div></li>`;
  }).join("")}</ol>`;
}

export function renderProposalDetail(proposal) {
  return `<section class="proposal-detail-hero">
      <span class="proposal-type">${escapeHtml(proposalTypeLabel(proposal.proposal_type))}</span>
      <h1 id="proposal-detail-title">${escapeHtml(proposal.title)}</h1>
      <div class="proposal-actors">${proposal.actors.length ? proposal.actors.map(renderProposalActor).join("") : "<span>Nessun attore pubblicato</span>"}</div>
      <p class="lead">Stato istituzionale attuale: <strong>${escapeHtml(proposalStatusLabel(proposal.current_status))}</strong></p>
      ${proposal.exact_statement ? `<blockquote>${escapeHtml(proposal.exact_statement)}</blockquote>` : proposal.summary ? `<p>${escapeHtml(proposal.summary)}</p>` : ""}
    </section>
    <section class="detail-card proposal-timeline-card"><p class="eyebrow">Cronologia verificata</p><h2>Cronologia di stato</h2>${renderProposalTimeline(proposal.status_history)}</section>
    <section class="detail-card"><p class="eyebrow">Informazione tracciabile</p><h2>Fonti ufficiali</h2><div class="source-list">${proposal.sources.map((source) => {
      const url = safeExternalUrl(source.url);
      return `<article class="source-block"><h3>${escapeHtml(source.name)}</h3>${url ? `<a class="source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Apri fonte ufficiale ↗</a>` : ""}</article>`;
    }).join("")}</div></section>`;
}

export function renderPoliticianProposals(proposals = []) {
  if (!proposals.length) return `<p class="empty-note">Nessuna proposta o promessa esplicita pubblicata è collegata a questa persona.</p>`;
  return `<div class="linked-proposals">${proposals.map((proposal) => `<article><span class="proposal-type">${escapeHtml(proposalTypeLabel(proposal.proposal_type))}</span><h3><a href="./?proposal=${encodeURIComponent(proposal.id)}">${escapeHtml(proposal.title)}</a></h3><p>${escapeHtml(actorRoleLabel(proposal.role))} · ${escapeHtml(proposalStatusLabel(proposal.current_status))}</p></article>`).join("")}</div>`;
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
      ${sourceUrl ? `<a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Fonte ufficiale ↗</a>` : ""}
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
    <a class="profile-link" href="./?region=${encodeURIComponent(region.id)}">Vedi regione <span aria-hidden="true">→</span></a>
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
    <a class="profile-link" href="./?municipality=${encodeURIComponent(municipality.id)}">Vedi comune <span aria-hidden="true">→</span></a>
  </article>`;
}

export function renderRegionDetail(region, municipalities = []) {
  const sourceUrl = safeExternalUrl(region.source?.url);
  return `<section class="proposal-detail-hero">
      <p class="eyebrow">Regione ISTAT ${escapeHtml(region.istat_code)}</p>
      <h1 id="region-detail-title">${escapeHtml(region.name)}</h1>
      <p>Presidente: ${holderLabel(region.current_president)}</p>
      <p>${region.municipality_count} ${region.municipality_count === 1 ? "comune" : "comuni"} nei dati ufficiali di riferimento.</p>
      ${sourceUrl ? `<p><a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Fonte ISTAT ufficiale ↗</a></p>` : ""}
    </section>
    <section class="detail-card">
      <p class="eyebrow">Comuni</p><h2>Comuni in questa regione</h2>
      ${municipalities.length ? `<div class="proposal-grid">${municipalities.map(renderMunicipalityCard).join("")}</div>` : `<p class="empty-note">Nessun comune è al momento elencato per questa regione.</p>`}
    </section>`;
}

export function renderMunicipalityDetail(municipality) {
  const sourceUrl = safeExternalUrl(municipality.source?.url);
  return `<section class="proposal-detail-hero">
      <p class="eyebrow">Comune ISTAT ${escapeHtml(municipality.istat_code)}</p>
      <h1 id="municipality-detail-title">Comune di ${escapeHtml(municipality.name)}</h1>
      <p>Regione: <a href="./?region=${encodeURIComponent(municipality.region_id)}">${escapeHtml(municipality.region_name)}</a></p>
      <p>Sindaco: ${holderLabel(municipality.current_mayor)}</p>
      <p>Provincia/UTS: ${escapeHtml(municipality.province_name)} (${escapeHtml(municipality.province_abbreviation)})</p>
      ${sourceUrl ? `<p><a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Fonte ISTAT ufficiale ↗</a></p>` : ""}
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
  return new Intl.NumberFormat("it-IT", {
    style: "percent",
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(Number(value));
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
      <div><p class="eyebrow">Ruolo al momento della promessa</p><h3>${escapeHtml(ROLE_LABELS[stratum.role] || titleCase(stratum.role))}</h3></div>
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
      <a class="profile-link" href="./?view=methodology">Come funziona il punteggio <span aria-hidden="true">→</span></a>
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

export function renderProfileStats(scorecard) {
  if (!scorecard || !scorecard.tracked_pledges) {
    return `<div class="stat-row"><div class="stat-tile"><strong>0</strong><span>Promesse</span></div></div>`;
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
      ? `<li><a class="source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${title} ↗</a></li>`
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

function navOffset() {
  const header = document.querySelector(".site-header");
  const nav = document.querySelector(".profile-section-nav");
  return (header?.offsetHeight || 0) + (nav?.offsetHeight || 0) + 12;
}

function syncScrollPadding() {
  const header = document.querySelector(".site-header");
  const nav = document.querySelector(".profile-section-nav");
  const headerHeight = header?.offsetHeight || 74;
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
  syncScrollPadding();
  if (!profileNavResizeBound) {
    window.addEventListener("resize", syncScrollPadding, { passive: true });
    profileNavResizeBound = true;
  }
  const links = [...nav.querySelectorAll("a[href^='#']")];
  const sections = links
    .map((link) => root.querySelector(link.getAttribute("href")))
    .filter(Boolean);
  let lockUntil = 0;
  let applyBest = () => {};
  for (const link of links) {
    link.addEventListener("click", (event) => {
      const id = link.getAttribute("href")?.slice(1);
      const target = id ? root.querySelector(`#${CSS.escape(id)}`) : null;
      if (!target) return;
      event.preventDefault();
      lockUntil = Date.now() + 800;
      setActiveSectionLink(nav, id);
      const top = target.getBoundingClientRect().top + window.scrollY - navOffset();
      window.scrollTo({
        top: Math.max(0, top),
        behavior: prefersReducedMotion() ? "auto" : "smooth",
      });
      history.replaceState(null, "", `#${id}`);
      const refresh = () => applyBest();
      window.setTimeout(refresh, 820);
      window.addEventListener("scrollend", refresh, { once: true });
    });
  }
  if ("IntersectionObserver" in window && sections.length) {
    const ratios = new Map();
    applyBest = () => {
      if (Date.now() < lockUntil) return;
      let bestId = "";
      let bestRatio = 0;
      for (const section of sections) {
        const ratio = ratios.get(section.id) || 0;
        if (ratio > bestRatio) {
          bestRatio = ratio;
          bestId = section.id;
        }
      }
      if (bestId) setActiveSectionLink(nav, bestId);
    };
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        ratios.set(entry.target.id, entry.isIntersecting ? entry.intersectionRatio : 0);
      }
      applyBest();
    }, {
      rootMargin: "-28% 0px -55% 0px",
      threshold: [0, 0.2, 0.4, 0.6, 1],
    });
    for (const section of sections) observer.observe(section);
  }
  const initial = window.location.hash.slice(1);
  const target = initial ? root.querySelector(`#${CSS.escape(initial)}`) : null;
  if (target) {
    requestAnimationFrame(() => {
      const top = target.getBoundingClientRect().top + window.scrollY - navOffset();
      window.scrollTo({ top: Math.max(0, top), behavior: "auto" });
      setActiveSectionLink(nav, target.id);
    });
  } else if (sections[0]) {
    setActiveSectionLink(nav, sections[0].id);
  }
}

function animateCount(node) {
  const target = Number(node.dataset.countTo);
  if (!Number.isFinite(target) || node.dataset.countAnimated === "1") return;
  node.dataset.countAnimated = "1";
  const finish = () => { node.textContent = String(target); };
  if (prefersReducedMotion() || target === 0) {
    finish();
    return;
  }
  node.textContent = "0";
  const start = performance.now();
  const duration = 700;
  const tick = (now) => {
    const progress = Math.min(1, (now - start) / duration);
    const eased = 1 - (1 - progress) ** 3;
    node.textContent = String(Math.round(target * eased));
    if (progress < 1) requestAnimationFrame(tick);
    else finish();
  };
  requestAnimationFrame(tick);
}

function bindProfileMotion(root) {
  const counters = [...root.querySelectorAll("[data-count-to]")];
  if (prefersReducedMotion() || !("IntersectionObserver" in window)) {
    for (const node of counters) node.textContent = String(node.dataset.countTo);
    return;
  }
  const reveals = [...root.querySelectorAll(".profile-block, .career-entry, .pledge-summary-item")];
  const observer = new IntersectionObserver((entries, observed) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add("is-revealed");
      if (entry.target.hasAttribute("data-count-to")) animateCount(entry.target);
      for (const counter of entry.target.querySelectorAll(":scope [data-count-to]")) {
        animateCount(counter);
      }
      observed.unobserve(entry.target);
    }
  }, { threshold: 0.16, rootMargin: "0px 0px -8% 0px" });
  reveals.forEach((node, index) => {
    node.classList.add("will-reveal");
    if (node.classList.contains("career-entry") || node.classList.contains("pledge-summary-item")) {
      node.style.setProperty("--reveal-delay", `${Math.min(index % 8, 6) * 40}ms`);
    }
    observer.observe(node);
    window.setTimeout(() => node.classList.add("is-revealed"), 1200);
  });
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

export function renderPoliticianDetail(person, scorecard = null) {
  const profile = person.profile;
  const gender = profile?.gender;
  const publishedDate = formatPublishedAt(person.published_at);
  const mandate = currentMandate(person);
  const party = currentParty(person);
  const place = birthPlace(profile);
  const who = renderWhoIs(person);
  const careerItems = careerEntries(person);
  const hasGroups = Boolean((person.parliamentary_groups || []).length);
  const hasParties = Boolean((person.political_parties || []).length);
  const hasProposals = Boolean((person.proposals || []).length);
  const hasCareer = Boolean(careerItems.length || hasGroups || hasParties);
  const citationGroups = groupCitations(person.citations || []);
  const sourcesMarkup = renderSources(person.citations);
  const headerFacts = [
    person.birth_date ? fact("Data di nascita", formatDate(person.birth_date)) : "",
    place !== "Non indicato" ? fact("Luogo di nascita", place) : "",
    mandate?.start_date ? fact("In carica dal", formatDate(mandate.start_date)) : "",
  ].filter(Boolean).join("");
  const nav = renderProfileSectionNav([
    who ? { href: "#profilo", label: "Chi è" } : null,
    hasCareer ? { href: "#carriera", label: "Cosa ha fatto" } : null,
    { href: "#posizioni", label: "Posizioni" },
    { href: "#promesse", label: "Promesse" },
    { href: "#procedimenti", label: "Procedimenti e controversie" },
    sourcesMarkup ? { href: "#fonti", label: "Fonti" } : null,
  ].filter(Boolean));
  return `<section class="profile-hero">
      <div class="hero-media">
        ${portrait(person, { size: "hero" })}
        ${renderPhotoCredit(person)}
      </div>
      <div class="profile-intro">
        <span class="verified-badge">Verificato su fonti ufficiali</span>
        <h1 id="profile-name">${escapeHtml(person.given_name)} ${escapeHtml(person.family_name)}</h1>
        <p class="profile-office">${escapeHtml(mandate ? mandateRole(mandate, gender) : "Incarico non indicato")}</p>
        ${party ? `<p class="profile-party">${escapeHtml(party.name)}</p>` : ""}
        ${headerFacts ? `<dl class="facts header-facts">${headerFacts}</dl>` : ""}
        ${renderProfileStats(scorecard)}
        <p class="publication-meta">${publishedDate ? `Ultimo aggiornamento ${escapeHtml(publishedDate)}` : "Ultimo aggiornamento non indicato"}</p>
        ${renderAskSuggestions(person, scorecard)}
      </div>
    </section>
    ${nav}
    ${who}
    ${hasCareer ? `<section class="detail-card profile-block profile-career" id="carriera">
      <p class="eyebrow">Carriera</p>
      <h2>Cosa ha fatto</h2>
      ${renderCareerTimeline(person)}
      ${hasGroups ? `<h3 class="career-subhead">Gruppi parlamentari</h3><p class="group-disclaimer">I gruppi parlamentari sono organi istituzionali di ciascuna Camera e non coincidono con i partiti politici.</p>${renderParliamentaryGroups(person.parliamentary_groups || [])}` : ""}
      ${hasParties ? `<h3 class="career-subhead">Partito politico</h3><p class="party-disclaimer">I partiti politici e i gruppi parlamentari sono concetti istituzionali distinti.</p>${renderPoliticalParties(person.political_parties || [])}` : ""}
      ${hasProposals ? `<h3 class="career-subhead">Proposte e promesse</h3>${renderPoliticianProposals(person.proposals || [])}` : ""}
    </section>` : ""}
    ${renderKeyPositions(person)}
    <section class="detail-card profile-block commitments-card" id="promesse">
      <p class="eyebrow">Detto e fatto</p>
      <h2>Scheda delle promesse</h2>
      ${renderScorecard(scorecard)}
    </section>
    ${renderProceedings(person)}
    ${sourcesMarkup ? `<section class="detail-card profile-block sources-card" id="fonti">
      <div class="sources-heading">
        <div><p class="eyebrow">Informazione tracciabile</p><h2>Fonti ufficiali</h2></div>
        <div class="sources-summary"><strong>${person.citation_count} ${person.citation_count === 1 ? "riferimento verificato" : "riferimenti verificati"}</strong><br />${citationGroups.length} ${citationGroups.length === 1 ? "fonte ufficiale" : "fonti ufficiali"}</div>
      </div>
      <div class="source-list">${sourcesMarkup}</div>
    </section>` : ""}
    ${renderTrustBlock()}`;
}

export function createPublicApiClient(fetchImpl = fetch) {
  async function request(path, { method = "GET", body } = {}) {
    let response;
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    try {
      response = await fetchImpl(path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch {
      throw new Error("api_unavailable");
    }
    if (!response.ok) {
      const error = new Error(response.status === 404 ? "not_found" : response.status === 422 ? "invalid_question" : "api_error");
      error.status = response.status;
      throw error;
    }
    return response.json();
  }
  return {
    listPoliticians: () => request("/politicians?offset=0&limit=50"),
    getPolitician: (id) => request(`/politicians/${encodeURIComponent(id)}`),
    getScorecard: (id) => request(`/politicians/${encodeURIComponent(id)}/scorecard`),
    explainPledge: (id) => request(`/proposals/${encodeURIComponent(id)}/explanation`),
    ask: (question) => request("/ask", { method: "POST", body: { question } }),
    getPortraits: () => request("/portraits"),
    getScoringMethodology: () => request("/methodology/scoring"),
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

async function showArchive(api) {
  try {
    const [payload] = await Promise.all([api.listPoliticians(), loadPortraits(api)]);
    payload.items.sort((left, right) => officeRank(left) - officeRank(right)
      || `${left.family_name} ${left.given_name}`.localeCompare(`${right.family_name} ${right.given_name}`, "it"));
    byId("archive-count").textContent = countLabel(payload.total, "profilo verificato", "profili verificati");
    if (!payload.items.length) {
      showState(byId("archive-status"), "Nessun profilo verificato è al momento disponibile.", "I profili pubblicati compariranno qui dopo la verifica editoriale.");
      return;
    }
    byId("archive-status").hidden = true;
    byId("politician-list").hidden = false;
    byId("politician-list").innerHTML = payload.items.map(renderPoliticianCard).join("");
    fillCardRecords(api, payload.items);
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

async function showProposals(api) {
  byId("archive-view").hidden = true;
  byId("proposals-view").hidden = false;
  try {
    const payload = await api.listProposals();
    byId("proposal-count").textContent = countLabel(payload.total, "record pubblicato", "record pubblicati");
    if (!payload.items.length) {
      showState(byId("proposals-status"), "Nessuna proposta verificata è al momento disponibile.", "Le proposte pubblicate compariranno qui dopo la verifica editoriale.");
      return;
    }
    byId("proposals-status").hidden = true;
    byId("proposal-list").hidden = false;
    byId("proposal-list").innerHTML = payload.items.map(renderProposalCard).join("");
  } catch {
    showState(byId("proposals-status"), "Non è stato possibile caricare l'archivio delle proposte.", PUBLIC_UNAVAILABLE, true);
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
    showState(byId("proposal-detail-status"), missing ? "Questa proposta non è disponibile al pubblico." : "Non è stato possibile caricare questa proposta.", missing ? "Potrebbe essere ancora in verifica editoriale." : PUBLIC_UNAVAILABLE, true);
  }
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
    const municipalities = await api.listMunicipalities({ regionId });
    byId("region-detail-status").hidden = true;
    byId("region-detail").hidden = false;
    byId("region-detail").innerHTML = renderRegionDetail(region, municipalities.items || []);
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
      ? `<li><a class="source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${title} ↗</a></li>`
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
    byId("search-count").textContent = "Pronto";
    byId("search-list").hidden = true;
    showState(byId("search-status"), "Inserisci un termine di ricerca.", "Usa il modulo qui sopra per cercare nell'archivio pubblico.");
    return;
  }
  byId("search-status").hidden = false;
  byId("search-status").className = "state-card loading-state";
  byId("search-status").innerHTML = `<span class="loading-mark" aria-hidden="true"></span><div><strong>Ricerca in corso…</strong><small>Consultazione dei record pubblici pubblicati.</small></div>`;
  try {
    const payload = await api.search({ q: query, type });
    byId("search-count").textContent = countLabel(payload.total, "risultato", "risultati");
    if (!payload.items.length) {
      byId("search-list").hidden = true;
      showState(byId("search-status"), "Nessun risultato trovato.", "Prova un'altra grafia o un tipo di record diverso.");
      return;
    }
    byId("search-status").hidden = true;
    byId("search-list").hidden = false;
    byId("search-list").innerHTML = payload.items.map((item) => renderSearchCard(item, query)).join("");
    document.title = `${query} — Ricerca — VeraPolitica`;
  } catch (error) {
    byId("search-count").textContent = "Non disponibile";
    showState(
      byId("search-status"),
      error.status === 422 ? "Questa ricerca non può essere eseguita." : "Non è stato possibile completare la ricerca.",
      error.status === 422 ? "Controlla la lunghezza della query o il tipo selezionato." : PUBLIC_UNAVAILABLE,
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
    <p class="eyebrow">Fonti ufficiali</p>
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
} else if (params.get("view") === "methodology") {
  showMethodology(api);
} else if (params.get("view") === "ask") {
  showAsk(api);
} else if (params.get("view") === "search") {
  showSearch(api, params.get("q") || "", params.get("type") || "");
} else {
  showArchive(api);
}
