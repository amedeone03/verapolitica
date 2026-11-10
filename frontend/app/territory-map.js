// «Territorio»: a light map of Italy with the regions and provinces on top.
// Tap a region or a province and its scheda opens in the sheet; Indietro goes
// back one level, and the browser's back button does the same (the state is
// in the URL: ?view=territory&regione=<ISTAT>&provincia=<SIGLA>).
//
// The map is a convenience, never the only way in: the search field and the
// list in the sheet reach every region and province with the keyboard, and
// the faces on the map are real buttons.
//
// Basemap: OpenFreeMap vector tiles (OpenStreetMap data, no key, no cookies)
// drawn with our own light style. Boundaries: ISTAT, simplified, served from
// ./geo. MapLibre is self-hosted in ./vendor so the page keeps script-src 'self'.

const ITALY_BOUNDS = [[6.4, 36.4], [18.8, 47.2]];
const TILES = "https://tiles.openfreemap.org/planet";
const GLYPHS = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";
const FONT = ["Noto Sans Regular"];
const FONT_BOLD = ["Noto Sans Bold"];
const FONT_ITALIC = ["Noto Sans Italic"];
const PROVINCE_PIN_ZOOM = 6.4;

// Colours of a car's light map: soft green land, clear water, white roads,
// grey borders and dark labels with a white halo.
const PALETTE = {
  land: "#e7eee2", wood: "#d4e6c8", grass: "#dcebd2", urban: "#ebedea", water: "#a9d5f3",
  road: "#ffffff", roadCase: "#d6dbd5", motorway: "#fbe8c4", motorwayCase: "#ead2a4",
  border: "#8f9aa2", borderSoft: "#b7bfc5", label: "#3a4046", labelSoft: "#79838b", halo: "#ffffff",
};

export function lightMapStyle() {
  const p = PALETTE;
  const motion = ["interpolate", ["exponential", 1.4], ["zoom"]];
  return {
    version: 8,
    glyphs: GLYPHS,
    sources: { omt: { type: "vector", url: TILES, attribution: "" } },
    layers: [
      { id: "land", type: "background", paint: { "background-color": p.land } },
      { id: "wood", type: "fill", source: "omt", "source-layer": "landcover", filter: ["in", ["get", "class"], ["literal", ["wood", "forest"]]], paint: { "fill-color": p.wood, "fill-opacity": 0.7 } },
      { id: "grass", type: "fill", source: "omt", "source-layer": "landcover", filter: ["in", ["get", "class"], ["literal", ["grass", "farmland", "scrub"]]], paint: { "fill-color": p.grass, "fill-opacity": 0.5 } },
      { id: "urban", type: "fill", source: "omt", "source-layer": "landuse", filter: ["in", ["get", "class"], ["literal", ["residential", "suburb", "neighbourhood", "commercial", "industrial"]]], paint: { "fill-color": p.urban, "fill-opacity": ["interpolate", ["linear"], ["zoom"], 6, 0.4, 11, 0.9] } },
      { id: "park", type: "fill", source: "omt", "source-layer": "park", paint: { "fill-color": p.wood, "fill-opacity": 0.6 } },
      { id: "water", type: "fill", source: "omt", "source-layer": "water", paint: { "fill-color": p.water } },
      { id: "waterway", type: "line", source: "omt", "source-layer": "waterway", minzoom: 8, paint: { "line-color": p.water, "line-width": 1.2 } },
      { id: "road-case", type: "line", source: "omt", "source-layer": "transportation", minzoom: 7, filter: ["in", ["get", "class"], ["literal", ["trunk", "primary", "secondary"]]], layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": p.roadCase, "line-width": [...motion, 7, 1.6, 14, 12] } },
      { id: "road", type: "line", source: "omt", "source-layer": "transportation", minzoom: 7, filter: ["in", ["get", "class"], ["literal", ["trunk", "primary", "secondary", "tertiary", "minor"]]], layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": p.road, "line-width": [...motion, 7, 0.8, 14, 9] } },
      { id: "motorway-case", type: "line", source: "omt", "source-layer": "transportation", minzoom: 5, filter: ["==", ["get", "class"], "motorway"], layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": p.motorwayCase, "line-width": [...motion, 5, 1.4, 14, 14] } },
      { id: "motorway", type: "line", source: "omt", "source-layer": "transportation", minzoom: 5, filter: ["==", ["get", "class"], "motorway"], layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": p.motorway, "line-width": [...motion, 5, 0.8, 14, 11] } },
      { id: "border-state", type: "line", source: "omt", "source-layer": "boundary", filter: ["all", ["==", ["get", "admin_level"], 4], ["!=", ["get", "maritime"], 1]], paint: { "line-color": p.borderSoft, "line-width": 0.8, "line-dasharray": [3, 2] } },
      { id: "border-country", type: "line", source: "omt", "source-layer": "boundary", filter: ["all", ["==", ["get", "admin_level"], 2], ["!=", ["get", "maritime"], 1]], paint: { "line-color": p.border, "line-width": [...motion, 3, 1, 10, 2.4] } },
      // Our regions and provinces are inserted here, under the labels.
      { id: "water-name", type: "symbol", source: "omt", "source-layer": "water_name", layout: { "text-field": ["get", "name:it"], "text-font": FONT_ITALIC, "text-size": 12, "text-letter-spacing": 0.15 }, paint: { "text-color": "#5d8fb3", "text-halo-color": "rgba(255,255,255,.6)", "text-halo-width": 1 } },
      { id: "country-name", type: "symbol", source: "omt", "source-layer": "place", filter: ["==", ["get", "class"], "country"], layout: { "text-field": ["upcase", ["coalesce", ["get", "name:it"], ["get", "name"]]], "text-font": FONT_BOLD, "text-size": 12, "text-letter-spacing": 0.25, "text-max-width": 8 }, paint: { "text-color": p.labelSoft, "text-halo-color": p.halo, "text-halo-width": 1.4 } },
      { id: "city-name", type: "symbol", source: "omt", "source-layer": "place", filter: ["==", ["get", "class"], "city"], layout: { "text-field": ["coalesce", ["get", "name:it"], ["get", "name"]], "text-font": FONT, "text-size": ["interpolate", ["linear"], ["zoom"], 5, 12, 10, 16], "text-anchor": "top", "text-offset": [0, 0.3], "text-max-width": 8 }, paint: { "text-color": p.label, "text-halo-color": p.halo, "text-halo-width": 1.6 } },
      { id: "town-name", type: "symbol", source: "omt", "source-layer": "place", minzoom: 8, filter: ["in", ["get", "class"], ["literal", ["town", "village"]]], layout: { "text-field": ["coalesce", ["get", "name:it"], ["get", "name"]], "text-font": FONT, "text-size": 12, "text-max-width": 8 }, paint: { "text-color": p.label, "text-halo-color": p.halo, "text-halo-width": 1.4 } },
    ],
  };
}

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests).

export function geometryBounds(geometry) {
  let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity;
  const walk = (coords) => {
    if (typeof coords[0] === "number") {
      if (coords[0] < minX) minX = coords[0];
      if (coords[0] > maxX) maxX = coords[0];
      if (coords[1] < minY) minY = coords[1];
      if (coords[1] > maxY) maxY = coords[1];
      return;
    }
    for (const item of coords) walk(item);
  };
  walk(geometry.coordinates);
  return [[minX, minY], [maxX, maxY]];
}

export function readTerritoryState(params) {
  const regione = (params.get("regione") || "").replace(/\D/g, "").padStart(2, "0");
  const provincia = (params.get("provincia") || "").toUpperCase().replace(/[^A-Z]/g, "").slice(0, 2);
  return { regione: params.get("regione") ? regione : "", provincia };
}

export function territoryHref({ regione = "", provincia = "" } = {}) {
  const params = new URLSearchParams({ view: "territory" });
  if (regione) params.set("regione", regione);
  if (provincia) params.set("provincia", provincia);
  return `./?${params}`;
}

const fold = (text) => String(text || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLocaleLowerCase("it");

// Regions and provinces matched locally (instant); words may start anywhere.
export function matchPlaces(index, query, limit = 8) {
  const q = fold(query).trim();
  if (!q) return [];
  const scored = [];
  for (const item of index) {
    const name = fold(item.name);
    const sigla = fold(item.sigla || "");
    let score = -1;
    if (name === q || sigla === q) score = 0;
    else if (name.startsWith(q)) score = 1;
    else if (name.split(/[\s'/-]+/).some((word) => word.startsWith(q))) score = 2;
    else if (name.includes(q)) score = 3;
    if (score >= 0) scored.push([score, item]);
  }
  scored.sort((a, b) => a[0] - b[0] || (a[1].kind === b[1].kind ? 0 : a[1].kind === "regione" ? -1 : 1) || a[1].name.localeCompare(b[1].name, "it"));
  return scored.slice(0, limit).map(([, item]) => item);
}

// ---------------------------------------------------------------------------
// Loading MapLibre only when the Territorio tab is opened.

let maplibrePromise = null;
function loadMapLibre() {
  if (globalThis.maplibregl) return Promise.resolve(globalThis.maplibregl);
  if (maplibrePromise) return maplibrePromise;
  maplibrePromise = new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "./vendor/maplibre/maplibre-gl.css";
    document.head.append(css);
    const script = document.createElement("script");
    script.src = "./vendor/maplibre/maplibre-gl-csp.js";
    script.onload = () => {
      const lib = globalThis.maplibregl;
      if (!lib) { reject(new Error("maplibre")); return; }
      lib.setWorkerUrl("./vendor/maplibre/maplibre-gl-csp-worker.js");
      resolve(lib);
    };
    script.onerror = () => reject(new Error("maplibre"));
    document.head.append(script);
  });
  return maplibrePromise;
}

function webglAvailable() {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------

export async function mountTerritoryMap({ api, root, escapeHtml, portrait, coalitionColor, zone, towns, caption = "" }) {
  const $ = (id) => root.querySelector(`#${id}`);
  const canvas = $("tmap-canvas");
  const sheet = $("tmap-sheet-body");
  const back = $("tmap-back");
  const scopeButton = $("tmap-scope");
  const zoneButton = $("tmap-zone");
  const reduced = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const desktop = () => typeof matchMedia === "function" && matchMedia("(min-width: 900px)").matches;
  const esc = escapeHtml;
  const color = (key) => coalitionColor[key || "da_compilare"] || coalitionColor.da_compilare;

  // Data: shapes are local files; people and coalitions come from the API.
  const [regionShapes, provinceShapes, regionPoints, provincePoints, overview, provinceList] = await Promise.all([
    fetch("./geo/regioni.geojson").then((r) => r.json()),
    fetch("./geo/province.geojson").then((r) => r.json()),
    fetch("./geo/regioni-centri.geojson").then((r) => r.json()),
    fetch("./geo/province-centri.geojson").then((r) => r.json()),
    api.getRegionsOverview().catch(() => ({ items: [], counts: {}, labels: {} })),
    api.listProvinces().catch(() => ({ items: [] })),
  ]);
  const labels = { ...overview.labels, da_compilare: "Da compilare" };
  const regionByIstat = new Map(overview.items.map((item) => [String(item.istat_code).padStart(2, "0"), item]));
  const regions = regionShapes.features.map((feature) => {
    const istat = feature.properties.istat;
    const data = regionByIstat.get(istat) || {};
    const point = regionPoints.features.find((item) => item.properties.istat === istat);
    return {
      kind: "regione", istat, name: data.name || feature.properties.name, id: data.id || null,
      coalition: data.coalition || "da_compilare", president: data.president || null,
      nextElection: data.next_election || null, short: data.short || feature.properties.name.slice(0, 3).toUpperCase(),
      bounds: geometryBounds(feature.geometry), center: point ? point.geometry.coordinates : null,
    };
  }).sort((a, b) => a.name.localeCompare(b.name, "it"));
  const region = (istat) => regions.find((item) => item.istat === istat) || null;
  const dbProvince = new Map(provinceList.items.map((item) => [item.abbreviation, item]));
  const provinces = provinceShapes.features.map((feature) => {
    const { sigla, region_istat: regionIstat } = feature.properties;
    const point = provincePoints.features.find((item) => item.properties.sigla === sigla);
    const db = dbProvince.get(sigla);
    return {
      kind: "provincia", sigla, regionIstat, name: db?.name || feature.properties.name,
      municipalities: db?.municipalities ?? null, inDatabase: Boolean(db),
      bounds: geometryBounds(feature.geometry), center: point ? point.geometry.coordinates : null,
    };
  }).sort((a, b) => a.name.localeCompare(b.name, "it"));
  const province = (sigla) => provinces.find((item) => item.sigla === sigla) || null;
  // Colour every shape by the coalition of its region.
  for (const feature of regionShapes.features) feature.properties.color = color(region(feature.properties.istat)?.coalition);
  for (const feature of provinceShapes.features) feature.properties.color = color(region(feature.properties.region_istat)?.coalition);

  const state = { regione: "", provincia: "", layer: "regioni" };

  // --- Sheet -----------------------------------------------------------------
  const initials = (name) => String(name || "").split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  const face = (person, size = 44) => {
    const url = person?.politician_id ? portrait(person.politician_id) : null;
    return `<span class="tmap-avatar" style="--s:${size}px">${url ? `<img src="${esc(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" />` : `<span aria-hidden="true">${esc(initials(person?.name) || "?")}</span>`}</span>`;
  };
  const chip = (key) => `<span class="tmap-chip" style="--c:${color(key)}">${esc(labels[key] || "Da compilare")}</span>`;

  const italySheet = () => {
    const counts = { centrosinistra: 0, centrodestra: 0, altro: 0, da_compilare: 0 };
    for (const item of regions) counts[item.coalition] = (counts[item.coalition] || 0) + 1;
    const order = ["centrosinistra", "altro", "da_compilare", "centrodestra"];
    const bar = order.filter((key) => counts[key]).map((key) => `<span class="tmap-bar-seg${key === "da_compilare" ? " is-empty" : ""}" style="flex-grow:${counts[key]};--c:${color(key)}"></span>`).join("");
    const listed = state.layer === "province" ? provinces : regions;
    return `<div class="tmap-score" role="img" aria-label="${esc(`Regioni per coalizione del presidente: centrosinistra ${counts.centrosinistra}, centrodestra ${counts.centrodestra}${counts.altro ? `, altre ${counts.altro}` : ""}${counts.da_compilare ? `, da compilare ${counts.da_compilare}` : ""}`)}">
        <span class="tmap-score-side" style="--c:${color("centrosinistra")}"><b>${counts.centrosinistra}</b><small>Centrosinistra</small></span>
        <span class="tmap-bar" aria-hidden="true">${bar}</span>
        <span class="tmap-score-side is-right" style="--c:${color("centrodestra")}"><b>${counts.centrodestra}</b><small>Centrodestra</small></span>
      </div>
      <p class="tmap-note">${esc(caption || "Colore: coalizione con cui è stato eletto il presidente della regione.")}${counts.altro || counts.da_compilare ? ` ${esc([counts.altro ? `${counts.altro} con altre coalizioni` : "", counts.da_compilare ? `${counts.da_compilare} da compilare` : ""].filter(Boolean).join(" · "))}.` : ""}</p>
      <div class="tmap-tabs" role="group" aria-label="Livello">
        <button type="button" data-layer="regioni" aria-pressed="${state.layer === "regioni"}"><b>R</b><span>Regioni</span></button>
        <button type="button" data-layer="province" aria-pressed="${state.layer === "province"}"><b>P</b><span>Province</span></button>
      </div>
      <h2 id="tmap-sheet-title" class="visually-hidden">Italia</h2>
      <details class="tmap-list-wrap">
        <summary>Elenco ${state.layer === "province" ? `delle ${listed.length} province` : "delle 20 regioni"}</summary>
        <ul class="tmap-list">${state.layer === "province"
          ? listed.map((item) => `<li><button type="button" data-provincia="${esc(item.sigla)}"><span class="tmap-sigla" style="--c:${color(region(item.regionIstat)?.coalition)}">${esc(item.sigla)}</span><span><strong>${esc(item.name)}</strong><small>${esc(region(item.regionIstat)?.name || "")}</small></span></button></li>`).join("")
          : listed.map((item) => `<li><button type="button" data-regione="${esc(item.istat)}">${face(item.president, 36)}<span><strong>${esc(item.name)}</strong><small>${item.president ? esc(item.president.name) : "Presidente non collegato"}</small></span>${chip(item.coalition)}</button></li>`).join("")}</ul>
      </details>`;
  };

  const regionSheet = (item) => {
    const list = provinces.filter((p) => p.regionIstat === item.istat);
    return `<div class="tmap-head"><p class="tmap-eyebrow">Regione</p><h2 id="tmap-sheet-title" tabindex="-1">${esc(item.name)}</h2>${chip(item.coalition)}</div>
      <div class="tmap-person">${face(item.president, 52)}<span><small>Presidente</small><strong>${item.president?.politician_id ? `<a href="./?politician=${encodeURIComponent(item.president.politician_id)}">${esc(item.president.name)}</a>` : esc(item.president?.name || "Non ancora collegato a una scheda")}</strong>${item.nextElection ? `<small>Prossime elezioni: ${esc(item.nextElection)}</small>` : ""}</span></div>
      ${list.length ? `<p class="tmap-sub">Province</p><div class="tmap-pills">${list.map((p) => `<button type="button" data-provincia="${esc(p.sigla)}">${esc(p.name)}<small>${esc(p.sigla)}</small></button>`).join("")}</div>` : ""}
      ${item.id ? `<a class="tmap-primary" href="./?region=${encodeURIComponent(item.id)}">Apri la scheda della regione</a>` : `<p class="tmap-note">La scheda di questa regione non è ancora pubblicata.</p>`}`;
  };

  const provinceSheet = async (item) => {
    const parent = region(item.regionIstat);
    const list = item.inDatabase ? await api.listMunicipalitiesInProvince(item.sigla).catch(() => []) : [];
    const ordered = [...list].sort((a, b) => a.name.localeCompare(b.name, "it"));
    const mine = zone?.municipality_id ? ordered.find((town) => String(town.id) === String(zone.municipality_id)) : null;
    return `<div class="tmap-head"><p class="tmap-eyebrow">Provincia · ${esc(parent?.name || "")}</p><h2 id="tmap-sheet-title" tabindex="-1">${esc(item.name)} <small>${esc(item.sigla)}</small></h2></div>
      ${mine ? `<div class="tmap-person">${face(mine.current_mayor ? { name: `${mine.current_mayor.given_name || ""} ${mine.current_mayor.family_name || ""}`.trim(), politician_id: mine.current_mayor.politician_id } : null, 44)}<span><small>Il tuo comune · ${esc(mine.name)}</small><strong>${mine.current_mayor ? esc(`${mine.current_mayor.given_name || ""} ${mine.current_mayor.family_name || ""}`.trim()) : "Sindaco non ancora collegato"}</strong></span></div>` : ""}
      ${ordered.length ? towns.render(item, ordered) : `<p class="tmap-note">${item.inDatabase ? "Nessun comune elencato." : "Questa provincia non è ancora nei dati ISTAT importati."}</p>`}
      ${item.inDatabase ? `<a class="tmap-primary" href="./?province=${encodeURIComponent(item.sigla)}">Apri la scheda della provincia</a>` : ""}`;
  };

  let renderSeq = 0;
  // Keyboard actions and the first paint swap content instantly (no motion).
  const renderSheet = async ({ animate = true } = {}) => {
    const seq = ++renderSeq;
    sheet.setAttribute("aria-busy", "true");
    let html;
    if (state.provincia && province(state.provincia)) html = await provinceSheet(province(state.provincia));
    else if (state.regione && region(state.regione)) html = regionSheet(region(state.regione));
    else html = italySheet();
    if (seq !== renderSeq) return;
    sheet.innerHTML = html;
    sheet.removeAttribute("aria-busy");
    towns.bind(sheet);
    sheet.classList.remove("is-in");
    if (animate && !reduced) {
      void sheet.offsetWidth;
      sheet.classList.add("is-in");
    }
    sheet.parentElement.scrollTop = 0;
  };

  // --- Controls ----------------------------------------------------------------
  const syncControls = () => {
    const current = state.provincia ? province(state.provincia) : state.regione ? region(state.regione) : null;
    back.hidden = !current;
    back.querySelector(".visually-hidden").textContent = state.provincia ? `Torna a ${region(state.regione)?.name || "regione"}` : "Torna all'Italia";
    scopeButton.textContent = state.provincia || (state.regione ? region(state.regione)?.short : "IT");
    scopeButton.setAttribute("aria-label", current ? `Stai guardando ${current.name}. Mostra tutta l'Italia` : "Mostra tutta l'Italia");
    root.classList.toggle("is-zoomed", Boolean(current));
  };

  // --- Map -----------------------------------------------------------------------
  let map = null;
  let markers = [];
  const padding = () => {
    if (desktop()) return { top: 80, bottom: 40, left: 420, right: 80 };
    // Keep the shape above the sheet (which itself sits above the tab bar).
    const covered = canvas.getBoundingClientRect().bottom - $("tmap-sheet").getBoundingClientRect().top;
    return { top: 84, bottom: Math.max(24, Math.min(covered + 16, canvas.clientHeight * 0.62)), left: 24, right: 68 };
  };
  // Moving on screen: MapLibre's ease-in-out, short; instant for keyboard and reduced motion.
  const fit = (bounds, instant = false) => {
    if (!map) return;
    map.fitBounds(bounds, { padding: padding(), duration: reduced || instant ? 0 : 600, maxZoom: 9.5, essential: false });
  };
  const paintSelection = () => {
    if (!map || !map.getLayer("vp-region-fill")) return;
    const reg = state.regione || "";
    const pro = state.provincia || "";
    const showProvinces = Boolean(reg) || state.layer === "province";
    map.setPaintProperty("vp-region-fill", "fill-opacity", reg ? ["case", ["==", ["get", "istat"], reg], 0.04, 0.03] : (state.layer === "province" ? 0.08 : ["case", ["boolean", ["feature-state", "hover"], false], 0.3, 0.18]));
    map.setPaintProperty("vp-region-line", "line-opacity", reg ? ["case", ["==", ["get", "istat"], reg], 1, 0.35] : 1);
    map.setPaintProperty("vp-region-line", "line-width", reg ? ["case", ["==", ["get", "istat"], reg], 2.6, 1] : 1.6);
    map.setLayoutProperty("vp-province-fill", "visibility", showProvinces ? "visible" : "none");
    map.setLayoutProperty("vp-province-line", "visibility", showProvinces ? "visible" : "none");
    map.setFilter("vp-province-fill", reg ? ["==", ["get", "region_istat"], reg] : null);
    map.setFilter("vp-province-line", reg ? ["==", ["get", "region_istat"], reg] : null);
    map.setPaintProperty("vp-province-fill", "fill-opacity", pro
      ? ["case", ["==", ["get", "sigla"], pro], 0.34, 0.08]
      : ["case", ["boolean", ["feature-state", "hover"], false], 0.3, 0.14]);
    for (const marker of markers) {
      const el = marker.getElement();
      const kind = el.dataset.kind;
      let visible;
      if (kind === "regione") visible = !reg && state.layer === "regioni";
      else visible = reg ? el.dataset.region === reg : state.layer === "province" && map.getZoom() >= PROVINCE_PIN_ZOOM;
      el.hidden = !visible;
      el.classList.toggle("is-active", kind === "provincia" && el.dataset.sigla === pro);
    }
  };

  const go = (next, { push = true, move = true, instant = false } = {}) => {
    state.regione = next.regione || "";
    state.provincia = next.provincia || "";
    if (state.provincia && !state.regione) state.regione = province(state.provincia)?.regionIstat || "";
    if (push) history.pushState({ territory: true }, "", territoryHref(state));
    syncControls();
    paintSelection();
    const done = renderSheet({ animate: !instant });
    if (move) {
      const target = state.provincia ? province(state.provincia) : state.regione ? region(state.regione) : null;
      fit(target ? target.bounds : ITALY_BOUNDS, instant);
    }
    return done;
  };
  const up = () => go(state.provincia ? { regione: state.regione } : {});

  const buildMarkers = (lib) => {
    for (const item of regions) {
      if (!item.center) continue;
      const el = document.createElement("button");
      el.type = "button";
      el.className = "tmap-face";
      el.dataset.kind = "regione";
      el.dataset.regione = item.istat;
      el.style.setProperty("--c", color(item.coalition));
      el.setAttribute("aria-label", `${item.name}${item.president ? `, presidente ${item.president.name}` : ""}, ${labels[item.coalition] || "da compilare"}`);
      el.innerHTML = `<span class="tmap-face-inner">${face(item.president, 40)}</span>`;
      markers.push(new lib.Marker({ element: el, anchor: "center" }).setLngLat(item.center).addTo(map));
    }
    for (const item of provinces) {
      if (!item.center) continue;
      const el = document.createElement("button");
      el.type = "button";
      el.className = "tmap-pin";
      el.dataset.kind = "provincia";
      el.dataset.provincia = item.sigla;
      el.dataset.sigla = item.sigla;
      el.dataset.region = item.regionIstat;
      el.style.setProperty("--c", color(region(item.regionIstat)?.coalition));
      el.setAttribute("aria-label", `Provincia di ${item.name}`);
      el.innerHTML = `<span class="tmap-pin-inner">${esc(item.sigla)}</span>`;
      el.hidden = true;
      markers.push(new lib.Marker({ element: el, anchor: "center" }).setLngLat(item.center).addTo(map));
    }
  };

  const startMap = async () => {
    if (!webglAvailable()) throw new Error("webgl");
    const lib = await loadMapLibre();
    map = new lib.Map({
      container: canvas,
      style: lightMapStyle(),
      bounds: ITALY_BOUNDS,
      fitBoundsOptions: { padding: padding() },
      minZoom: 4,
      maxZoom: 13,
      maxBounds: [[-12, 26], [38, 58]],
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      cooperativeGestures: false,
    });
    map.touchZoomRotate.disableRotation();
    map.keyboard.enable();
    // Tiles that fail (offline, blocked) leave the shapes on the plain land colour.
    map.on("error", () => {});
    // «style.load», not «load»: our shapes must appear even if the basemap tiles
    // are slow or unreachable (they only fill in the background).
    await new Promise((resolve) => (map.isStyleLoaded() ? resolve() : map.once("style.load", resolve)));
    map.addSource("vp-regioni", { type: "geojson", data: regionShapes, promoteId: "istat" });
    map.addSource("vp-province", { type: "geojson", data: provinceShapes, promoteId: "sigla" });
    const before = "water-name";
    map.addLayer({ id: "vp-region-fill", type: "fill", source: "vp-regioni", paint: { "fill-color": ["get", "color"], "fill-opacity": 0.18 } }, before);
    map.addLayer({ id: "vp-province-fill", type: "fill", source: "vp-province", layout: { visibility: "none" }, paint: { "fill-color": ["get", "color"], "fill-opacity": 0.14 } }, before);
    map.addLayer({ id: "vp-province-line", type: "line", source: "vp-province", layout: { visibility: "none", "line-join": "round" }, paint: { "line-color": ["get", "color"], "line-width": 1, "line-opacity": 0.8 } }, before);
    map.addLayer({ id: "vp-region-line", type: "line", source: "vp-regioni", layout: { "line-join": "round" }, paint: { "line-color": ["get", "color"], "line-width": 1.6 } }, before);
    buildMarkers(lib);

    // Hover (pointer devices) and tap on the shapes.
    let hovered = null;
    const setHover = (source, id) => {
      if (hovered) map.setFeatureState(hovered, { hover: false });
      hovered = id ? { source, id } : null;
      if (hovered) map.setFeatureState(hovered, { hover: true });
    };
    const pick = (point) => {
      const layers = (state.regione || state.layer === "province") ? ["vp-province-fill", "vp-region-fill"] : ["vp-region-fill"];
      return map.queryRenderedFeatures(point, { layers: layers.filter((id) => map.getLayoutProperty(id, "visibility") !== "none") })[0] || null;
    };
    map.on("mousemove", (event) => {
      const feature = pick(event.point);
      map.getCanvas().style.cursor = feature ? "pointer" : "";
      setHover(feature ? feature.source : null, feature ? feature.id : null);
    });
    map.on("mouseout", () => setHover(null, null));
    map.on("click", (event) => {
      const feature = pick(event.point);
      if (!feature) return;
      if (feature.source === "vp-province") go({ regione: feature.properties.region_istat, provincia: feature.properties.sigla });
      else if (feature.properties.istat !== state.regione || state.provincia) go({ regione: feature.properties.istat });
    });
    map.on("zoomend", paintSelection);
    paintSelection();
  };

  // --- Wiring ----------------------------------------------------------------------
  root.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("[data-regione], [data-provincia], [data-layer]") : null;
    if (!target || !root.contains(target) || target.closest(".tmap-results")) return;
    if (target.dataset.layer) {
      state.layer = target.dataset.layer;
      paintSelection();
      renderSheet({ animate: false });
      return;
    }
    // Keyboard activation (detail 0) moves focus to the new scheda; a tap leaves it alone.
    const keyboard = event.detail === 0;
    const done = target.dataset.provincia ? go({ provincia: target.dataset.provincia }, { instant: keyboard }) : go({ regione: target.dataset.regione }, { instant: keyboard });
    if (keyboard) done.then(() => $("tmap-sheet-title")?.focus({ preventScroll: true }));
  });
  back.addEventListener("click", up);
  scopeButton.addEventListener("click", () => go({}));
  zoneButton.addEventListener("click", () => {
    const istat = zone?.region_id ? regions.find((item) => String(item.id) === String(zone.region_id))?.istat : "";
    if (!istat) { window.location.href = "./?view=profile"; return; }
    go({ regione: istat, provincia: zone.province || "" });
  });
  zoneButton.setAttribute("aria-label", zone ? `Vai alla tua zona: ${zone.municipality_name || zone.province_name || zone.region_name}` : "Scegli la tua zona");
  root.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !event.target.closest?.(".tmap-search") && (state.regione || state.provincia)) {
      event.preventDefault();
      go(state.provincia ? { regione: state.regione } : {}, { instant: true });
    }
  });
  window.addEventListener("popstate", () => {
    const next = readTerritoryState(new URLSearchParams(window.location.search));
    go(next, { push: false });
  });

  bindSearch({ root, input: $("tmap-q"), list: $("tmap-results"), api, esc, color, regions, provinces, region, onPick: (item, viaKeyboard) => {
    if (item.kind === "regione") go({ regione: item.istat }, { instant: viaKeyboard });
    else if (item.kind === "provincia") go({ provincia: item.sigla }, { instant: viaKeyboard });
    else window.location.href = `./?municipality=${encodeURIComponent(item.id)}`;
  } });

  // First state: the URL, else the reader's zone (region + province), else Italy.
  const fromUrl = readTerritoryState(new URLSearchParams(window.location.search));
  const zoneIstat = zone?.region_id ? regions.find((item) => String(item.id) === String(zone.region_id))?.istat || "" : "";
  const first = fromUrl.regione || fromUrl.provincia ? fromUrl : { regione: zoneIstat, provincia: zoneIstat ? (zone.province || "") : "" };
  state.regione = first.regione;
  state.provincia = first.provincia;
  if (state.provincia && !state.regione) state.regione = province(state.provincia)?.regionIstat || "";
  history.replaceState({ territory: true }, "", territoryHref(state));
  syncControls();
  await renderSheet({ animate: false });
  try {
    await startMap();
    const target = state.provincia ? province(state.provincia) : state.regione ? region(state.regione) : null;
    map.fitBounds(target ? target.bounds : ITALY_BOUNDS, { padding: padding(), duration: 0, maxZoom: 9.5 });
    paintSelection();
  } catch {
    canvas.classList.add("is-unavailable");
    canvas.innerHTML = `<p class="tmap-fallback">La mappa non è disponibile su questo dispositivo. Usa la ricerca o l'elenco qui sotto.</p>`;
  }
  return { go, state, get map() { return map; } };
}

// Search: regions and provinces locally and instantly; comuni from the API.
function bindSearch({ root, input, list, api, esc, color, regions, provinces, region, onPick }) {
  const index = [...regions, ...provinces];
  let items = [];
  let active = -1;
  let timer = null;
  let controller = null;
  const close = () => {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  };
  const paint = (towns = []) => {
    items = [...matchPlaces(index, input.value), ...towns];
    if (!input.value.trim()) { close(); return; }
    list.innerHTML = items.length
      ? items.map((item, i) => {
        const sub = item.kind === "regione" ? "Regione" : item.kind === "provincia" ? `Provincia · ${region(item.regionIstat)?.name || ""}` : `Comune${item.subtitle ? ` · ${item.subtitle}` : ""}`;
        const mark = item.kind === "provincia" ? item.sigla : item.kind === "regione" ? item.short : "";
        const tone = item.kind === "provincia" ? color(region(item.regionIstat)?.coalition) : item.kind === "regione" ? color(item.coalition) : "#7D8E8B";
        return `<li id="tmap-opt-${i}" role="option" aria-selected="${i === active}" data-index="${i}"><span class="tmap-sigla" style="--c:${tone}">${esc(mark || "•")}</span><span><strong>${esc(item.name)}</strong><small>${esc(sub)}</small></span></li>`;
      }).join("")
      : `<li class="tmap-empty" role="option" aria-disabled="true">Nessun risultato</li>`;
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  };
  const choose = (i, viaKeyboard = false) => {
    const item = items[i];
    if (!item) return;
    input.value = "";
    close();
    input.blur();
    onPick(item, viaKeyboard);
  };
  input.addEventListener("input", () => {
    active = -1;
    paint();
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) return;
    timer = setTimeout(async () => {
      controller?.abort();
      controller = new AbortController();
      try {
        const payload = await api.search({ q, type: "municipality", limit: 5, signal: controller.signal });
        const towns = (payload.items || []).filter((item) => item.metadata?.id).map((item) => ({ kind: "comune", id: item.metadata.id, name: item.title, subtitle: item.subtitle || "" }));
        if (input.value.trim() === q) paint(towns);
      } catch { /* the local results stay */ }
    }, 220);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (list.hidden || !items.length) return;
      event.preventDefault();
      active = (active + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      for (const option of list.querySelectorAll("[role=option]")) option.setAttribute("aria-selected", String(option.dataset.index === String(active)));
      input.setAttribute("aria-activedescendant", `tmap-opt-${active}`);
      list.querySelector(`#tmap-opt-${active}`)?.scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter") {
      if (list.hidden) return;
      event.preventDefault();
      choose(active >= 0 ? active : 0, true);
    } else if (event.key === "Escape") {
      if (!list.hidden) { event.preventDefault(); close(); } else if (input.value) { input.value = ""; }
    }
  });
  list.addEventListener("pointerdown", (event) => event.preventDefault());
  list.addEventListener("click", (event) => {
    const option = event.target instanceof Element ? event.target.closest("[data-index]") : null;
    if (option) choose(Number(option.dataset.index));
  });
  input.addEventListener("blur", () => setTimeout(close, 120));
  root.addEventListener("focusin", (event) => { if (!event.target.closest(".tmap-search")) close(); });
}
