import { displayPersonName } from "./feed-card.js";

// VeraPolitica — welcome screen and sign-up journey (story-style, one question per screen).
// Pattern references (Appllama, Spotify): dark full-screen welcome with centred logo and
// pill buttons; one large question per screen; circular avatar grid with check badges;
// floating "Avanti" pill. New accounts stay in this wrap through email and password.

const logo = (url, size = 28) => (typeof url === "string" && /^\/media\/\d+$/.test(url) ? `<img class="ob-logo" src="${url}" alt="" width="${size}" height="${size}" loading="lazy" />` : "");
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);

const CHECK = `<svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>`;
const CLOSE = `<svg aria-hidden="true" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>`;
const SEARCH = `<svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>`;

function monogram(name) {
  const words = String(name || "").trim().split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? `${[...words[0]][0]}${[...words[words.length - 1]][0]}` : [...(words[0] || "VP")].slice(0, 2).join("");
  return letters.toLocaleUpperCase();
}

function personPhoto(person, portraitFor) {
  return portraitFor?.(person.id) || "";
}

function avatar(person, portraitFor, size = "") {
  const url = personPhoto(person, portraitFor);
  return `<span class="ob-avatar${size}">${url ? `<img src="${escape(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" />` : `<span aria-hidden="true">${escape(monogram(person.name))}</span>`}</span>`;
}

export function renderWelcome(root, { onRegister, onLogin, onDemo }) {
  root.innerHTML = `
    <div class="gate welcome" role="main" aria-labelledby="welcome-title">
      <svg class="welcome-italy" viewBox="0 0 48 64" aria-hidden="true" focusable="false">
        <path fill="currentColor" d="M26.5 1.2c3.2.6 6.2 3.4 6 6.8-.2 2.6 1.8 3.6 3.2 5.6 1.8 2.6 1.4 5.6 3.8 7.6 2 1.6 4.8 1.4 5.8 3.8 1 2.4-.6 4.4-.2 6.6.4 2.6 3 3.6 2.4 6.2-.6 2.6-3.6 2.4-4.6 4.6-1 2.2.6 4.2-.6 6.2-1.2 2-4.2 1.4-5.8 3.4-1.4 1.6-.8 4.6-3 5.6-2.6 1.2-4.6-.4-6.6 1.2-1.6 1.6-1.4 4.6-4 5.2-2.6.6-4.2-2-6.8-1.6-2.2.4-3.2 2.8-5.8 2.2-2.6-.6-3-4-2-6 .8-2 4.2-2 4.8-4.2.6-2.2-2-3.2-1.6-5.8.4-2.6 4-3 4.6-5.6.6-2.6-2-3.6-1-6.2 1-2.6 4.6-2 5.2-5 .6-2.6-1.6-4.2-.6-6.8 1-2.8 4-3.4 6.6-3z"/>
        <path fill="currentColor" d="M8.2 34.5c2.2.6 3.6 3 3 5.2-.6 2-3 2.2-3.6 4.2-.6 1.6.6 3.6-1 4.6-2 1.2-4-.4-4.6-2.4-.6-2.2 1-4 1.4-5.8.4-2-.6-4 1-5.2 1.2-1 2.6-1 3.8-.6z"/>
        <path fill="currentColor" d="M14.4 45.6c2.6.4 4 2.6 3.6 5-.4 2.6-2.6 3.6-2.2 6 .4 2 2.6 2.6 2 4.6-.6 2-3.2 1.4-4.8 2.4-1.6 1-2 3.6-4 3.6-2.2 0-3-3-2-4.6 1-1.6 3.6-1.6 4-3.6.4-2-2-2.6-1.6-4.6.4-2 2.6-3 5-8.8z"/>
      </svg>
      <div class="welcome-center">
        <img class="welcome-logo" src="./favicon.svg" alt="" width="96" height="96" />
        <h1 id="welcome-title" class="welcome-name">VeraPolitica</h1>
        <p class="welcome-line">La politica italiana, con le fonti.</p>
      </div>
      <div class="welcome-actions">
        <button type="button" class="gate-pill is-solid" data-welcome="register">Registrati</button>
        <button type="button" class="gate-pill is-solid" data-welcome="login">Accedi</button>
        <button type="button" class="gate-pill is-outline is-wide" data-welcome="demo">Consulta senza account</button>
      </div>
      <p class="welcome-note">Senza account puoi consultare le notizie pubblicate. Con l'account salvi ciò che segui.</p>
    </div>`;
  root.querySelector('[data-welcome="register"]').addEventListener("click", onRegister);
  root.querySelector('[data-welcome="login"]').addEventListener("click", onLogin);
  root.querySelector('[data-welcome="demo"]').addEventListener("click", onDemo);
}

export function renderAccountForm(root, { mode = "register", error = "", onSubmit, onSwitch, onBack }) {
  const register = mode === "register";
  root.innerHTML = `
    <div class="gate account-gate" role="main" aria-labelledby="account-title">
      <div class="account-brand">
        <img class="welcome-logo" src="./favicon.svg" alt="" width="72" height="72" />
        <p class="welcome-name">VeraPolitica</p>
        <p class="welcome-line">La politica italiana, con le fonti.</p>
      </div>
      <div class="account-panel">
        <p class="ob-kicker">${register ? "Crea il tuo account" : "Bentornato"}</p>
        <h1 id="account-title" class="account-title">${register ? "Registrati" : "Accedi"}</h1>
        <form id="account-form" class="acc-form" novalidate>
          <label class="ob-label" for="acc-email">Email</label>
          <input id="acc-email" class="ob-input is-compact" type="email" name="email" autocomplete="username" required maxlength="254" placeholder="nome@email.it" />
          <label class="ob-label" for="acc-password">Password</label>
          <input id="acc-password" class="ob-input is-compact" type="password" name="password" autocomplete="${register ? "new-password" : "current-password"}" required minlength="10" maxlength="128" />
          ${register ? `<p class="ob-note">Almeno 10 caratteri. Poi scegli chi seguire.</p>` : `<p class="ob-note">Usa l'email con cui ti sei registrato.</p>`}
          ${error ? `<p class="ob-error" role="alert">${escape(error)}</p>` : ""}
          <button type="submit" class="gate-pill is-solid acc-submit">${register ? "Continua" : "Entra"}</button>
        </form>
        <p class="welcome-note"><button type="button" class="acc-switch" data-account="switch">${register ? "Hai già un account? Accedi" : "Non hai un account? Registrati"}</button></p>
        <p class="welcome-note"><button type="button" class="acc-switch" data-account="back">Indietro</button></p>
      </div>
    </div>`;
  const form = root.querySelector("#account-form");
  const submit = root.querySelector(".acc-submit");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const email = root.querySelector("#acc-email").value.trim();
    const password = root.querySelector("#acc-password").value;
    submit.disabled = true;
    Promise.resolve(onSubmit({ email, password })).catch(() => {}).finally(() => { submit.disabled = false; });
  });
  root.querySelector("[data-account=switch]").addEventListener("click", onSwitch);
  root.querySelector("[data-account=back]").addEventListener("click", onBack);
}

const EDIT_STEPS = ["name", "zone", "politicians", "parties", "summary"];
const REGISTER_STEPS = ["name", "zone", "politicians", "parties", "email", "password"];
const TONES = { name: "tone-navy", zone: "tone-navy", politicians: "tone-blue", parties: "tone-green", email: "tone-navy", password: "tone-navy", summary: "tone-light" };
const EMAIL_OK = /[^@\s]+@[^@\s]+\.[^@\s]+/;

/**
 * Story-style sign-up. `initial` pre-fills the answers when the reader edits them later.
 * New accounts stay in this wrap through email and password (`collectAccount`).
 * `onDone(profilePatch)` receives { member, favorites, parties, zone }.
 * `onCreateAccount({ email, password, profile })` creates the account at the end.
 */
export function runOnboarding(root, { api, portraitFor = () => null, initial = {}, collectAccount = false, onDone, onCreateAccount, onClose }) {
  const STEPS = collectAccount ? REGISTER_STEPS : EDIT_STEPS;
  const state = {
    step: 0,
    name: initial.member?.name || "",
    politicians: new Map((initial.favorites || []).map((item) => [String(item.id), { id: String(item.id), name: item.name }])),
    parties: new Map((initial.parties || []).map((item) => [String(item.id), item])),
    region: initial.zone?.region_id ? { id: initial.zone.region_id, name: initial.zone.region_name } : null,
    province: initial.zone?.province ? { code: initial.zone.province, name: initial.zone.province_name } : null,
    people: null,
    partyList: null,
    regions: null,
    provinces: new Map(),
    query: "",
    email: "",
    password: "",
    accountError: "",
  };
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  root.innerHTML = `
    <div class="gate ob" role="dialog" aria-modal="true" aria-labelledby="ob-title">
      <div class="ob-top">
        <ol class="ob-progress" aria-label="Avanzamento">${STEPS.map((_, index) => `<li><span></span></li>`).join("")}</ol>
        <button type="button" class="ob-close" aria-label="Chiudi la registrazione">${CLOSE}</button>
      </div>
      <form class="ob-body" novalidate></form>
      <div class="ob-bar">
        <button type="button" class="ob-back">Indietro</button>
        <button type="button" class="gate-pill is-solid ob-next">Avanti</button>
      </div>
      <p class="visually-hidden" aria-live="polite" id="ob-live"></p>
    </div>`;
  const shell = root.querySelector(".ob");
  const body = root.querySelector(".ob-body");
  const next = root.querySelector(".ob-next");
  const back = root.querySelector(".ob-back");
  const live = root.querySelector("#ob-live");

  const valid = () => {
    const key = STEPS[state.step];
    if (key === "name") return state.name.trim().length >= 2;
    if (key === "politicians") return state.politicians.size > 0 || (Array.isArray(state.people) && !state.people.length);
    // Without the ISTAT list (not loaded yet, or not reachable) the zone can be set later.
    if (key === "zone") return Boolean(state.region && state.province) || (Array.isArray(state.regions) && !state.regions.length);
    if (key === "email") return EMAIL_OK.test(state.email.trim());
    if (key === "password") return state.password.length >= 10 && state.password.length <= 128;
    return true;
  };
  const syncBar = () => {
    const key = STEPS[state.step];
    next.disabled = !valid();
    next.textContent = key === "summary" ? "Vai al tuo feed"
      : key === "password" ? "Crea l'account"
      : key === "politicians" && state.politicians.size ? `Avanti · ${state.politicians.size}`
      : key === "politicians" && Array.isArray(state.people) && !state.people.length ? "Salta"
      : key === "parties" && !state.parties.size ? "Salta"
      : key === "parties" ? `Avanti · ${state.parties.size}`
      : "Avanti";
    back.hidden = state.step === 0;
    next.title = key === "name" && !valid() ? "Scrivi almeno due lettere" : "";
    shell.className = `gate ob ${TONES[key]}${["name", "email", "password"].includes(key) ? " is-centered" : ""}`;
    root.querySelectorAll(".ob-progress li").forEach((item, index) => {
      item.classList.toggle("is-done", index < state.step);
      item.classList.toggle("is-current", index === state.step);
    });
  };

  // ---------------------------------------------------------------- screens
  const screens = {
    name: () => `
      <div class="ob-faces-slot">${nameFaces()}</div>
      <p class="ob-kicker">Benvenuto</p>
      <h1 id="ob-title" class="ob-title">Come ti chiami?</h1>
      <label class="ob-label" for="ob-name">Il tuo nome</label>
      <input id="ob-name" class="ob-input" name="name" autocomplete="given-name" maxlength="40" value="${escape(state.name)}" placeholder="es. Anna" />
      <p class="ob-note">Il nome compare nel tuo profilo. Lo modifichi o cancelli l'account dal Profilo.</p>`,
    zone: () => `
      <p class="ob-kicker">Di dove sei</p>
      <h1 id="ob-title" class="ob-title">Dove sei?</h1>
      <p class="ob-sub">Regione e provincia: le notizie del tuo territorio entrano nel Per te.</p>
      <h2 class="ob-label">Regione</h2>
      <div class="ob-chips is-compact" role="group" aria-label="Regione">${state.regions === null ? `<p class="ob-sub">Caricamento…</p>` : regionChips()}</div>
      <div class="ob-provinces">${provinceBlock()}</div>`,
    politicians: () => `
      <p class="ob-kicker">Chi segui</p>
      <h1 id="ob-title" class="ob-title">Chi vuoi seguire?</h1>
      <p class="ob-sub">Scegli almeno un politico. Le notizie che li riguardano arrivano nel tuo Per te.</p>
      <div class="ob-search">${SEARCH}<label class="visually-hidden" for="ob-q">Cerca un politico</label><input id="ob-q" type="search" placeholder="Cerca" value="${escape(state.query)}" autocomplete="off" /></div>
      <div class="ob-people" role="group" aria-label="Politici">${state.people === null ? `<p class="ob-sub">Caricamento…</p>` : peopleGrid()}</div>`,
    parties: () => `
      <p class="ob-kicker">Chi segui</p>
      <h1 id="ob-title" class="ob-title">Quali partiti ti interessano?</h1>
      <p class="ob-sub">Facoltativo. Vedrai le notizie che li coinvolgono, di qualunque area.</p>
      <div class="ob-chips" role="group" aria-label="Partiti">${state.partyList === null ? `<p class="ob-sub">Caricamento…</p>` : partyChips()}</div>`,
    email: () => `
      <p class="ob-kicker">Il tuo account</p>
      <h1 id="ob-title" class="ob-title">Qual è la tua email?</h1>
      <label class="visually-hidden" for="ob-email">Email</label>
      <input id="ob-email" class="ob-input" name="email" type="email" autocomplete="username" maxlength="254" value="${escape(state.email)}" placeholder="la tua migliore email" />
      <p class="ob-note">Serve per accedere da un altro telefono. Non la mostriamo nel profilo pubblico.</p>`,
    password: () => `
      <p class="ob-kicker">Il tuo account</p>
      <h1 id="ob-title" class="ob-title">Scegli una password</h1>
      <label class="visually-hidden" for="ob-password">Password</label>
      <input id="ob-password" class="ob-input" name="password" type="password" autocomplete="new-password" minlength="10" maxlength="128" value="${escape(state.password)}" />
      <p class="ob-note">Almeno 10 caratteri.</p>
      ${state.accountError ? `<p class="ob-error" role="alert">${escape(state.accountError)}</p>` : ""}`,
    summary: () => summary(),
  };

  function nameFaces() {
    if (!Array.isArray(state.people) || !state.people.length) return "";
    const photographed = state.people.filter((person) => personPhoto(person, portraitFor));
    const rest = state.people.filter((person) => !personPhoto(person, portraitFor));
    const pool = photographed.length >= 8 ? photographed : [...photographed, ...rest];
    const limit = 12;
    const picked = pool.length <= limit ? pool
      : Array.from({ length: limit }, (_, index) => pool[Math.floor((index * pool.length) / limit)]);
    return `<div class="ob-faces" aria-hidden="true">${picked.map((person) => avatar(person, portraitFor, " is-face")).join("")}</div>`;
  }

  function peopleGrid() {
    const q = state.query.trim().toLocaleLowerCase("it");
    if (!state.people.length) return `<p class="ob-empty">L'elenco dei politici non è ancora disponibile: lo pubblica la redazione. Puoi andare avanti e sceglierli più tardi dal Profilo.</p>`;
    const people = state.people.filter((person) => !q || person.name.toLocaleLowerCase("it").includes(q));
    if (!people.length) return `<p class="ob-sub">Nessun politico trovato.</p>`;
    return people.map((person) => {
      const on = state.politicians.has(person.id);
      return `<button type="button" class="ob-person${on ? " is-on" : ""}" data-person="${escape(person.id)}" aria-pressed="${on}">
        <span class="ob-person-photo">${avatar(person, portraitFor)}<span class="ob-check">${CHECK}</span></span>
        <span class="ob-person-name">${escape(person.name)}</span>
      </button>`;
    }).join("");
  }

  function partyChips() {
    if (!state.partyList.length) return `<p class="ob-empty">L'elenco dei partiti non è ancora disponibile: lo pubblica la redazione. Puoi andare avanti e sceglierli più tardi dal Profilo.</p>`;
    return state.partyList.map((party) => {
      const on = state.parties.has(String(party.id));
      return `<button type="button" class="ob-chip${on ? " is-on" : ""}" data-party="${escape(party.id)}" aria-pressed="${on}">
        ${on ? CHECK : ""}${logo(party.logo_url)}${party.abbreviation ? `<strong>${escape(party.abbreviation)}</strong>` : ""}<span>${escape(party.name)}</span>
      </button>`;
    }).join("");
  }

  function regionChips() {
    if (!state.regions.length) return `<p class="ob-empty">L'elenco di regioni e province non è ancora disponibile. Puoi andare avanti e impostare la zona più tardi dal Profilo.</p>`;
    return state.regions.map((region) => {
      const on = state.region && String(state.region.id) === String(region.id);
      return `<button type="button" class="ob-chip${on ? " is-on" : ""}" data-region="${escape(region.id)}" aria-pressed="${on}">${logo(region.logo_url, 22)}${escape(region.name)}</button>`;
    }).join("");
  }

  function provinceBlock() {
    if (!state.region) return "";
    const list = state.provinces.get(String(state.region.id));
    const chips = list === undefined ? `<p class="ob-sub">Caricamento…</p>`
      : !list.length ? `<p class="ob-sub">Nessuna provincia disponibile per questa regione.</p>`
      : list.map((item) => {
        const on = state.province?.code === item.abbreviation;
        return `<button type="button" class="ob-chip${on ? " is-on" : ""}" data-province="${escape(item.abbreviation)}" data-province-name="${escape(item.name)}" aria-pressed="${on}">${logo(item.logo_url, 22)}${escape(item.name)} <small>${escape(item.abbreviation)}</small></button>`;
      }).join("");
    return `<h2 class="ob-label">Provincia</h2><div class="ob-chips is-compact" role="group" aria-label="Provincia">${chips}</div>`;
  }

  function summary() {
    const people = [...state.politicians.values()];
    const parties = [...state.parties.values()];
    return `
      <p class="ob-kicker">La tua scheda</p>
      <h1 id="ob-title" class="ob-title">${escape(state.name.trim())}, ecco cosa segui.</h1>
      <div class="ob-wrap">
        <section class="ob-stat" style="--i:0">
          <p class="ob-stat-num">${people.length}</p>
          <p class="ob-stat-label">${people.length === 1 ? "politico" : "politici"}</p>
          <div class="ob-stack">${people.slice(0, 6).map((person) => avatar(person, portraitFor, " is-small")).join("")}</div>
          <p class="ob-stat-names">${people.map((person) => escape(person.name)).join(" · ")}</p>
        </section>
        <section class="ob-stat" style="--i:1">
          <p class="ob-stat-num">${parties.length}</p>
          <p class="ob-stat-label">${parties.length === 1 ? "partito" : "partiti"}</p>
          ${parties.length ? `<p class="ob-stat-names ob-stat-parties">${parties.map((party) => `<span>${logo(party.logo_url, 24)}${escape(party.abbreviation || party.name)}</span>`).join("")}</p>` : `<p class="ob-stat-names">Nessuno: li aggiungi quando vuoi.</p>`}
        </section>
        <section class="ob-stat" style="--i:2">
          <p class="ob-stat-label">${logo(state.province?.logo_url || state.region?.logo_url, 36)}La tua zona</p>
          ${state.province ? `<p class="ob-stat-place">${escape(state.province.name)}</p>
          <p class="ob-stat-names">${escape(state.region?.name || "")}</p>` : `<p class="ob-stat-names">Da impostare nel Profilo.</p>`}
        </section>
      </div>
      <p class="ob-note">Il tuo Per te mostra le notizie della redazione su queste persone e questi partiti, più quelle della tua provincia. VeraPolitica non dà indicazioni di voto.</p>`;
  }

  // ---------------------------------------------------------------- data
  const inflight = {};
  const loaders = {
    name: () => loaders.politicians().catch(() => {}),
    politicians: () => {
      if (state.people !== null) return Promise.resolve();
      if (!inflight.people) {
        inflight.people = (async () => {
          const items = [];
          for (let offset = 0; offset < 20000; offset += 100) {
            const payload = await api.listPoliticians({ offset, limit: 100 });
            items.push(...(payload.items || []));
            if (items.length >= (payload.total || 0) || !(payload.items || []).length) break;
          }
          state.people = items
            .map((item) => ({
              id: String(item.id),
              name: displayPersonName(item.given_name, item.family_name),
            }))
            .sort((a, b) => a.name.localeCompare(b.name, "it"));
        })().finally(() => { delete inflight.people; });
      }
      return inflight.people;
    },
    parties: () => {
      if (state.partyList !== null) return Promise.resolve();
      if (!inflight.parties) {
        inflight.parties = (async () => {
          const payload = await api.listParties({ all: true });
          state.partyList = payload.items
            .map((item) => ({ id: item.id, name: item.name, abbreviation: item.abbreviation || null, logo_url: item.logo_url || null }))
            .sort((a, b) => a.name.localeCompare(b.name, "it"));
        })().finally(() => { delete inflight.parties; });
      }
      return inflight.parties;
    },
    zone: () => {
      if (!inflight.zone) {
        inflight.zone = (async () => {
          if (state.regions === null) {
            const payload = await api.listRegions();
            state.regions = payload.items.map((item) => ({ id: item.id, name: item.name, logo_url: item.logo_url || null })).sort((a, b) => a.name.localeCompare(b.name, "it"));
          }
          if (state.region) await loadProvinces(state.region.id);
        })().finally(() => { delete inflight.zone; });
      }
      return inflight.zone;
    },
  };
  async function loadProvinces(regionId) {
    if (state.provinces.has(String(regionId))) return;
    const payload = await api.listProvinces(regionId);
    state.provinces.set(String(regionId), payload.items.map((item) => ({ abbreviation: item.abbreviation, name: item.name, logo_url: item.logo_url || null })).sort((a, b) => a.name.localeCompare(b.name, "it")));
  }

  // ---------------------------------------------------------------- render
  function render({ focusTitle = true } = {}) {
    const key = STEPS[state.step];
    body.innerHTML = `<div class="ob-screen${reduceMotion ? "" : " is-entering"}">${screens[key]()}</div>`;
    syncBar();
    live.textContent = `Passo ${state.step + 1} di ${STEPS.length}`;
    if (key === "name") body.querySelector("#ob-name").focus();
    else if (key === "email") body.querySelector("#ob-email").focus();
    else if (key === "password") body.querySelector("#ob-password").focus();
    else if (focusTitle) {
      const title = body.querySelector(".ob-title");
      title?.setAttribute("tabindex", "-1");
      title?.focus();
    }
    const loader = loaders[key];
    if (loader) {
      loader().then(() => { if (STEPS[state.step] === key) refresh(key); }).catch(() => {
        if (STEPS[state.step] !== key) return;
        body.querySelector(".ob-screen").insertAdjacentHTML("beforeend", `<p class="ob-error" role="alert">Non è stato possibile caricare l'elenco. Riprova più tardi.</p>`);
      });
    }
  }
  function refresh(key) {
    if (key === "name") {
      const slot = body.querySelector(".ob-faces-slot");
      if (slot) slot.innerHTML = nameFaces();
    }
    if (key === "politicians") body.querySelector(".ob-people").innerHTML = peopleGrid();
    if (key === "parties") body.querySelector(".ob-chips").innerHTML = partyChips();
    if (key === "zone") {
      body.querySelector(".ob-chips").innerHTML = regionChips();
      body.querySelector(".ob-provinces").innerHTML = provinceBlock();
    }
    syncBar();
  }

  // ---------------------------------------------------------------- events
  body.addEventListener("input", (event) => {
    if (event.target.id === "ob-name") { state.name = event.target.value; syncBar(); }
    if (event.target.id === "ob-email") { state.email = event.target.value; syncBar(); }
    if (event.target.id === "ob-password") { state.password = event.target.value; syncBar(); }
    if (event.target.id === "ob-q") { state.query = event.target.value; body.querySelector(".ob-people").innerHTML = state.people ? peopleGrid() : ""; }
  });
  body.addEventListener("submit", (event) => { event.preventDefault(); if (valid()) go(1); });
  body.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const person = target?.closest("[data-person]");
    if (person) {
      const id = person.dataset.person;
      if (state.politicians.has(id)) state.politicians.delete(id);
      else if (state.politicians.size < 24) state.politicians.set(id, state.people.find((item) => item.id === id));
      const on = state.politicians.has(id);
      person.classList.toggle("is-on", on);
      person.setAttribute("aria-pressed", String(on));
      return syncBar();
    }
    const party = target?.closest("[data-party]");
    if (party) {
      const id = party.dataset.party;
      if (state.parties.has(id)) state.parties.delete(id);
      else state.parties.set(id, state.partyList.find((item) => String(item.id) === id));
      return refresh("parties");
    }
    const region = target?.closest("[data-region]");
    if (region) {
      const picked = state.regions.find((item) => String(item.id) === region.dataset.region);
      if (String(state.region?.id) !== String(picked.id)) state.province = null;
      state.region = picked;
      refresh("zone");
      loadProvinces(picked.id).then(() => {
        if (STEPS[state.step] !== "zone") return;
        refresh("zone");
        body.querySelector(".ob-provinces")?.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
      }).catch(() => {
        state.provinces.set(String(picked.id), []);
        refresh("zone");
      });
      return;
    }
    const province = target?.closest("[data-province]");
    if (province) {
      const list = state.provinces.get(String(state.region.id)) || [];
      const picked = list.find((item) => item.abbreviation === province.dataset.province);
      state.province = { code: province.dataset.province, name: province.dataset.provinceName, logo_url: picked?.logo_url || null };
      refresh("zone");
    }
  });

  function profilePatch() {
    return {
      member: { name: state.name.trim(), since: initial.member?.since || new Date().toISOString().slice(0, 10) },
      favorites: [...state.politicians.values()].map((item) => ({ id: String(item.id), name: item.name })),
      parties: [...state.parties.values()].map((item) => ({ id: Number(item.id), name: item.name, abbreviation: item.abbreviation || null, logo_url: item.logo_url || null })),
      zone: state.region && state.province ? {
        region_id: Number(state.region.id),
        region_name: state.region.name,
        province: state.province.code,
        province_name: state.province.name,
        municipality_id: null,
        municipality_name: null,
      } : null,
    };
  }

  function go(delta) {
    const nextStep = state.step + delta;
    if (nextStep >= STEPS.length) {
      const profile = profilePatch();
      if (collectAccount) {
        next.disabled = true;
        Promise.resolve(onCreateAccount({ email: state.email.trim(), password: state.password, profile })).catch((error) => {
          state.accountError = error?.message && error.message !== "api_error"
            ? error.message
            : "Non è stato possibile creare l'account.";
          next.disabled = false;
          render();
        });
        return;
      }
      onDone(profile);
      return;
    }
    if (nextStep < 0) return;
    state.step = nextStep;
    render();
    shell.scrollTop = 0;
  }
  next.addEventListener("click", () => { if (valid()) go(1); });
  back.addEventListener("click", () => go(-1));
  root.querySelector(".ob-close").addEventListener("click", onClose);
  shell.addEventListener("keydown", (event) => { if (event.key === "Escape") onClose(); });
  Promise.all([
    loaders.politicians().catch(() => { if (state.people === null) state.people = []; }),
    loaders.parties().catch(() => { if (state.partyList === null) state.partyList = []; }),
    loaders.zone().catch(() => { if (state.regions === null) state.regions = []; }),
  ]).then(() => {
    const key = STEPS[state.step];
    if (["name", "zone", "politicians", "parties"].includes(key)) refresh(key);
  });
  render({ focusTitle: false });
}
