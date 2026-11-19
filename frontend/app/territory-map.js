// «Territorio»: a light map of Italy with the regions and provinces on top.
// Tap a region or a province and its scheda opens in the sheet; Indietro goes
// back one level, and the browser's back button does the same (the state is
// in the URL: ?view=territory&regione=<ISTAT>&provincia=<SIGLA>&citta=<ISTAT comune>).
// Inside a province, only the cities VeraPolitica follows are selectable (key-cities.js).
//
// The map is a convenience, never the only way in: the search field and the
// list in the sheet reach every region and province with the keyboard, and
// the faces on the map are real buttons.
//
// Basemap: OpenFreeMap vector tiles (OpenStreetMap data, no key, no cookies)
// drawn with our own light style. Boundaries: ISTAT, simplified, served from
// ./geo. MapLibre is self-hosted in ./vendor so the page keeps script-src 'self'.

import { KEY_CITIES, keyCity } from "./key-cities.js";

const ITALY_BOUNDS = [[6.4, 36.4], [18.8, 47.2]];
const TILES = "https://tiles.openfreemap.org/planet";
const GLYPHS = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";
const FONT = ["Noto Sans Regular"];
const FONT_BOLD = ["Noto Sans Bold"];
const PROVINCE_PIN_ZOOM = 6.4;

// Dark map (mockup "Dark Mode"): deep water, land one step lighter,
// faint roads, soft blue-grey labels and light-blue seams between the regions.
// Quiet on purpose, so the coalition colours and the faces are what you read first.
const PALETTE = {
  land: "#073660", abroad: "#052C50", wood: "#08385F", grass: "#08385F", urban: "#0A3E6B", water: "#021B33",
  road: "#0E4677", roadCase: "#073660", motorway: "#155A92", motorwayCase: "#0B4272",
  border: "#3E6A94", borderSoft: "#2A5480", label: "#C9D6E3", labelSoft: "#8FA6BE", halo: "#032442",
  seam: "#6F98C2", seamSoft: "#2F5F8C",
};

// Sea and neighbouring countries drawn from a small local file (Natural Earth 1:50m),
// so the first paint already shows Italy in its sea, even before or without tiles.
const EUROPA = "./geo/europa.geojson";
const CITY_ICON = `<svg class="tmap-city-icon" aria-hidden="true" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M5 21V8l6-4v17M19 21V11l-8-4"/><path d="M8 10h.01M8 14h.01M15 14h.01M15 17h.01"/></svg>`;
const CHEVRON = `<svg class="tmap-chev" aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>`;
const absolute = (path) => (globalThis.location ? new URL(path, globalThis.location.href).href : path);

export function lightMapStyle() {
  const p = PALETTE;
  const motion = ["interpolate", ["exponential", 1.4], ["zoom"]];
  return {
    version: 8,
    glyphs: GLYPHS,
    sources: { omt: { type: "vector", url: TILES, attribution: "" }, europa: { type: "geojson", data: absolute(EUROPA) } },
    layers: [
      { id: "land", type: "background", paint: { "background-color": p.land } },
      // Coarse sea, faded out as the detailed tile water takes over (zoom 7+).
      { id: "europa-sea", type: "fill", source: "europa", filter: ["==", ["get", "kind"], "sea"], paint: { "fill-color": p.water, "fill-opacity": ["interpolate", ["linear"], ["zoom"], 7.5, 1, 9.5, 0] } },
      // Neighbours a shade darker than Italy, so the country stands out.
      { id: "europa-country", type: "fill", source: "europa", filter: ["==", ["get", "kind"], "country"], paint: { "fill-color": p.abroad, "fill-opacity": ["interpolate", ["linear"], ["zoom"], 6, 1, 9, 0.6] } },
      { id: "europa-border", type: "line", source: "europa", filter: ["==", ["get", "kind"], "country"], layout: { "line-join": "round" }, paint: { "line-color": p.borderSoft, "line-width": ["interpolate", ["linear"], ["zoom"], 4, 0.8, 8, 1.6] } },
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
      { id: "country-name", type: "symbol", source: "omt", "source-layer": "place", filter: ["==", ["get", "class"], "country"], layout: { "text-field": ["upcase", ["coalesce", ["get", "name:it"], ["get", "name"]]], "text-font": FONT_BOLD, "text-size": 11, "text-letter-spacing": 0.2, "text-max-width": 8 }, paint: { "text-color": p.labelSoft, "text-halo-color": p.halo, "text-halo-width": 1.4 } },
      // Cities only from zoom 7, when the region faces have given way to the provinces.
      { id: "city-name", type: "symbol", source: "omt", "source-layer": "place", minzoom: 7, filter: ["==", ["get", "class"], "city"], layout: { "text-field": ["coalesce", ["get", "name:it"], ["get", "name"]], "text-font": FONT, "text-size": ["interpolate", ["linear"], ["zoom"], 7, 11, 11, 15], "text-anchor": "top", "text-offset": [0, 0.3], "text-max-width": 8 }, paint: { "text-color": p.labelSoft, "text-halo-color": p.halo, "text-halo-width": 1.6 } },
      { id: "town-name", type: "symbol", source: "omt", "source-layer": "place", minzoom: 9.5, filter: ["in", ["get", "class"], ["literal", ["town", "village"]]], layout: { "text-field": ["coalesce", ["get", "name:it"], ["get", "name"]], "text-font": FONT, "text-size": 11, "text-max-width": 8 }, paint: { "text-color": p.labelSoft, "text-halo-color": p.halo, "text-halo-width": 1.4 } },
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
  const citta = (params.get("citta") || "").replace(/\D/g, "").slice(0, 6);
  return { regione: params.get("regione") ? regione : "", provincia, citta: keyCity(citta) ? citta : "" };
}

export function territoryHref({ regione = "", provincia = "", citta = "" } = {}) {
  const params = new URLSearchParams({ view: "territory" });
  if (regione) params.set("regione", regione);
  if (provincia) params.set("provincia", provincia);
  if (citta) params.set("citta", citta);
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
  const rank = { regione: 0, citta: 1, provincia: 2 };
  scored.sort((a, b) => a[0] - b[0] || (rank[a[1].kind] ?? 3) - (rank[b[1].kind] ?? 3) || a[1].name.localeCompare(b[1].name, "it"));
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

export async function mountTerritoryMap({ api, root, escapeHtml, portrait, coalitionColor, zone, caption = "" }) {
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
  // The cities VeraPolitica follows; the comune record (mayor, scheda) is looked up once per province.
  const cities = KEY_CITIES.filter((city) => province(city.sigla)).map((city) => ({ ...city, kind: "citta", regionIstat: city.region }));
  const city = (istat) => cities.find((item) => item.istat === istat) || null;
  const comuniCache = new Map();
  const comuneRecord = async (item) => {
    if (!province(item.sigla)?.inDatabase) return null;
    if (!comuniCache.has(item.sigla)) comuniCache.set(item.sigla, api.listMunicipalitiesInProvince(item.sigla).catch(() => []));
    return (await comuniCache.get(item.sigla)).find((town) => String(town.istat_code) === item.istat) || null;
  };
  const cityPills = (list) => `<div class="tmap-pills tmap-city-pills">${list.map((c) => `<button type="button" data-citta="${esc(c.istat)}">${CITY_ICON}${esc(c.name)}</button>`).join("")}</div>`;
  // Colour every shape by the coalition of its region.
  for (const feature of regionShapes.features) feature.properties.color = color(region(feature.properties.istat)?.coalition);
  for (const feature of provinceShapes.features) feature.properties.color = color(region(feature.properties.region_istat)?.coalition);

  const state = { regione: "", provincia: "", citta: "", layer: "regioni" };

  // --- Sheet -----------------------------------------------------------------
  const initials = (name) => String(name || "").split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  const face = (person, size = 44) => {
    const url = person?.politician_id ? portrait(person.politician_id) : null;
    return `<span class="tmap-avatar" style="--s:${size}px">${url ? `<img src="${esc(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" />` : (initials(person?.name) ? `<span aria-hidden="true">${esc(initials(person.name))}</span>` : `<svg class="tmap-nobody" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><circle cx="12" cy="8" r="4"/><path d="M5 20a7 7 0 0 1 14 0"/></svg>`)}</span>`;
  };
  const chip = (key) => `<span class="tmap-chip" style="--c:${color(key)}">${esc(labels[key] || "Da compilare")}</span>`;

  const italySheet = () => {
    const counts = { centrosinistra: 0, centrodestra: 0, altro: 0, da_compilare: 0 };
    for (const item of regions) counts[item.coalition] = (counts[item.coalition] || 0) + 1;
    const order = ["centrosinistra", "altro", "da_compilare", "centrodestra"];
    const bar = order.filter((key) => counts[key]).map((key) => `<span class="tmap-bar-seg${key === "da_compilare" ? " is-empty" : ""}" style="flex-grow:${counts[key]};--c:${color(key)}"></span>`).join("");
    const listed = state.layer === "province" ? provinces : regions;
    const prov = state.layer === "province";
    return `<h2 id="tmap-sheet-title" class="visually-hidden">Italia</h2>
      <div class="tmap-tabs" role="group" aria-label="Livello">
        <button type="button" data-layer="regioni" aria-pressed="${!prov}">Regioni</button>
        <button type="button" data-layer="province" aria-pressed="${prov}">Province</button>
      </div>
      <div class="tmap-score" role="img" aria-label="${esc(`Regioni per coalizione del presidente: centrosinistra ${counts.centrosinistra}, centrodestra ${counts.centrodestra}${counts.altro ? `, altre ${counts.altro}` : ""}${counts.da_compilare ? `, da compilare ${counts.da_compilare}` : ""}`)}">
        <span class="tmap-score-side" style="--c:${color("centrosinistra")}"><b>${counts.centrosinistra}</b> Centrosinistra</span>
        <span class="tmap-bar" aria-hidden="true">${bar}</span>
        <span class="tmap-score-side is-right" style="--c:${color("centrodestra")}">Centrodestra <b>${counts.centrodestra}</b></span>
      </div>
      <p class="tmap-hint">${esc(caption || `Tocca ${prov ? "una provincia" : "una regione"} sulla mappa o scegli dall'elenco. Il colore è la coalizione del presidente.`)}</p>
      <ul class="tmap-list" aria-label="${prov ? `Le ${listed.length} province` : "Le 20 regioni"}">${prov
        ? listed.map((item) => `<li><button type="button" data-provincia="${esc(item.sigla)}"><span class="tmap-sigla" style="--c:${color(region(item.regionIstat)?.coalition)}" aria-hidden="true"></span><span><strong>${esc(item.name)}</strong><small>${esc(region(item.regionIstat)?.name || "")}</small></span>${CHEVRON}</button></li>`).join("")
        : listed.map((item) => `<li><button type="button" data-regione="${esc(item.istat)}">${face(item.president, 36)}<span><strong>${esc(item.name)}</strong><small>${item.president ? esc(item.president.name) : "Presidente non collegato"}</small></span>${CHEVRON}</button></li>`).join("")}</ul>`;
  };

  const regionSheet = (item) => {
    const list = provinces.filter((p) => p.regionIstat === item.istat);
    const who = `${face(item.president, 48)}<span><small>Presidente</small><strong>${esc(item.president?.name || "Non ancora collegato")}</strong>${item.nextElection ? `<small>Prossime elezioni: ${esc(item.nextElection)}</small>` : ""}</span>`;
    return `<div class="tmap-head"><h2 id="tmap-sheet-title" tabindex="-1">${esc(item.name)}</h2>${chip(item.coalition)}</div>
      ${item.president?.politician_id ? `<a class="tmap-person is-link" href="./?politician=${encodeURIComponent(item.president.politician_id)}">${who}${CHEVRON}</a>` : `<div class="tmap-person">${who}</div>`}
      ${cities.some((c) => c.regionIstat === item.istat) ? `<p class="tmap-sub">Città</p>${cityPills(cities.filter((c) => c.regionIstat === item.istat))}` : ""}
      ${list.length ? `<p class="tmap-sub">Province</p><div class="tmap-pills">${list.map((p) => `<button type="button" data-provincia="${esc(p.sigla)}">${esc(p.name)}</button>`).join("")}</div>` : ""}
      ${item.id ? `<a class="tmap-primary" href="./?region=${encodeURIComponent(item.id)}">Apri la scheda della regione</a>` : `<p class="tmap-note">La scheda di questa regione non è ancora pubblicata.</p>`}`;
  };

  const provinceSheet = async (item) => {
    // Regions and provinces only: no list of comuni on the map.
    const parent = region(item.regionIstat);
    const siblings = provinces.filter((p) => p.regionIstat === item.regionIstat && p.sigla !== item.sigla);
    return `<div class="tmap-head"><h2 id="tmap-sheet-title" tabindex="-1">${esc(item.name)}</h2><p class="tmap-eyebrow">Provincia · ${esc(parent?.name || "")}</p></div>
      ${parent ? `<button type="button" class="tmap-person is-link" data-regione="${esc(parent.istat)}">${face(parent.president, 48)}<span><small>Regione ${esc(parent.name)}</small><strong>${esc(parent.president?.name || "Presidente non collegato")}</strong></span>${CHEVRON}</button>` : ""}
      ${cities.some((c) => c.sigla === item.sigla) ? `<p class="tmap-sub">Città</p>${cityPills(cities.filter((c) => c.sigla === item.sigla))}` : ""}
      ${siblings.length ? `<p class="tmap-sub">Altre province</p><div class="tmap-pills">${siblings.map((p) => `<button type="button" data-provincia="${esc(p.sigla)}">${esc(p.name)}</button>`).join("")}</div>` : ""}
      ${item.inDatabase ? `<a class="tmap-primary" href="./?province=${encodeURIComponent(item.sigla)}">Apri la scheda della provincia</a>` : `<p class="tmap-note">La scheda di questa provincia non è ancora pubblicata.</p>`}`;
  };

  const citySheet = async (item) => {
    const prov = province(item.sigla);
    const record = await comuneRecord(item);
    const mayor = record?.current_mayor ? { name: `${record.current_mayor.given_name || ""} ${record.current_mayor.family_name || ""}`.trim(), politician_id: record.current_mayor.politician_id } : null;
    const who = `${face(mayor, 48)}<span><small>Sindaco</small><strong>${esc(mayor?.name || "Non ancora collegato")}</strong></span>`;
    const others = cities.filter((c) => c.regionIstat === item.regionIstat && c.istat !== item.istat);
    return `<div class="tmap-head"><h2 id="tmap-sheet-title" tabindex="-1">${esc(item.name)}</h2>${item.capital ? `<span class="tmap-chip">Capoluogo di regione</span>` : ""}<p class="tmap-eyebrow">Città · Provincia di ${esc(prov?.name || item.sigla)}</p></div>
      ${mayor?.politician_id ? `<a class="tmap-person is-link" href="./?politician=${encodeURIComponent(mayor.politician_id)}">${who}${CHEVRON}</a>` : `<div class="tmap-person">${who}</div>`}
      ${others.length ? `<p class="tmap-sub">Altre città della regione</p>${cityPills(others)}` : ""}
      ${record ? `<a class="tmap-primary" href="./?municipality=${encodeURIComponent(record.id)}">Apri la scheda della città</a>` : `<p class="tmap-note">La scheda di questa città non è ancora pubblicata.</p>`}`;
  };

  // Mobile sheet (Apple Maps pattern): a peek with the controls, a grip
  // that opens it to read the list; tap or swipe the grip. Desktop: always open.
  const sheetBox = $("tmap-sheet");
  const grip = $("tmap-grip");
  const setOpen = (open) => {
    sheetBox.classList.toggle("is-open", open);
    grip?.setAttribute("aria-expanded", String(open));
    if (grip) grip.querySelector("span").textContent = open ? "Riduci il pannello" : "Espandi il pannello";
  };
  grip?.addEventListener("click", () => setOpen(!sheetBox.classList.contains("is-open")));
  let dragY = null;
  grip?.addEventListener("touchstart", (event) => { dragY = event.touches[0].clientY; }, { passive: true });
  grip?.addEventListener("touchend", (event) => {
    if (dragY === null) return;
    const dy = event.changedTouches[0].clientY - dragY;
    dragY = null;
    if (Math.abs(dy) > 24) { event.preventDefault(); setOpen(dy < 0); }
  });

  let renderSeq = 0;
  // Keyboard actions and the first paint swap content instantly (no motion).
  const renderSheet = async ({ animate = true } = {}) => {
    const seq = ++renderSeq;
    sheet.setAttribute("aria-busy", "true");
    let html;
    if (state.citta && city(state.citta)) html = await citySheet(city(state.citta));
    else if (state.provincia && province(state.provincia)) html = await provinceSheet(province(state.provincia));
    else if (state.regione && region(state.regione)) html = regionSheet(region(state.regione));
    else html = italySheet();
    if (seq !== renderSeq) return;
    sheet.innerHTML = html;
    sheet.removeAttribute("aria-busy");
    setOpen(Boolean(state.regione || state.provincia || state.citta));
    sheet.classList.remove("is-in");
    if (animate && !reduced) {
      void sheet.offsetWidth;
      sheet.classList.add("is-in");
    }
    sheet.parentElement.scrollTop = 0;
  };

  // --- Controls ----------------------------------------------------------------
  const syncControls = () => {
    const current = state.citta ? city(state.citta) : state.provincia ? province(state.provincia) : state.regione ? region(state.regione) : null;
    back.hidden = !current;
    back.querySelector(".visually-hidden").textContent = state.citta ? `Torna alla provincia di ${province(state.provincia)?.name || ""}` : state.provincia ? `Torna a ${region(state.regione)?.name || "regione"}` : "Torna all'Italia";
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
    return { top: 76, bottom: Math.max(24, Math.min(covered + 12, canvas.clientHeight * 0.74)), left: 16, right: 64 };
  };
  // Moving on screen: MapLibre's ease-in-out, short; instant for keyboard and reduced motion.
  const fit = (bounds, instant = false) => {
    if (!map) return;
    map.fitBounds(bounds, { padding: padding(), duration: reduced || instant ? 0 : 600, maxZoom: state.citta ? 11 : 9.5, essential: false });
  };
  const paintSelection = () => {
    if (!map || !map.getLayer("vp-region-fill")) return;
    const reg = state.regione || "";
    const pro = state.provincia || "";
    const showProvinces = Boolean(reg) || state.layer === "province";
    map.setPaintProperty("vp-region-fill", "fill-opacity", reg ? ["case", ["==", ["get", "istat"], reg], 0.04, 0.03] : (state.layer === "province" ? 0.08 : ["case", ["boolean", ["feature-state", "hover"], false], 0.3, 0.18]));
    map.setPaintProperty("vp-region-line", "line-opacity", reg ? ["case", ["==", ["get", "istat"], reg], 1, 0.35] : 1);
    map.setPaintProperty("vp-region-line", "line-width", reg ? ["case", ["==", ["get", "istat"], reg], 2.6, 0.8] : 1.2);
    map.setLayoutProperty("vp-province-fill", "visibility", showProvinces ? "visible" : "none");
    map.setLayoutProperty("vp-province-line", "visibility", showProvinces ? "visible" : "none");
    map.setLayoutProperty("vp-province-name", "visibility", showProvinces ? "visible" : "none");
    map.setFilter("vp-province-name", reg ? ["==", ["get", "region_istat"], reg] : null);
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
      else if (kind === "citta") visible = reg ? el.dataset.region === reg : map.getZoom() >= 7.5;
      else visible = reg ? el.dataset.region === reg : state.layer === "province" && map.getZoom() >= PROVINCE_PIN_ZOOM;
      el.hidden = !visible;
      el.classList.toggle("is-active", (kind === "provincia" && el.dataset.sigla === pro && !state.citta) || (kind === "regione" && el.dataset.regione === reg) || (kind === "citta" && el.dataset.citta === state.citta));
    }
  };

  const go = (next, { push = true, move = true, instant = false } = {}) => {
    state.regione = next.regione || "";
    state.provincia = next.provincia || "";
    state.citta = next.citta && city(next.citta) ? next.citta : "";
    if (state.citta) { state.provincia = city(state.citta).sigla; state.regione = city(state.citta).regionIstat; }
    if (state.provincia && !state.regione) state.regione = province(state.provincia)?.regionIstat || "";
    if (push) history.pushState({ territory: true }, "", territoryHref(state));
    syncControls();
    paintSelection();
    const done = renderSheet({ animate: !instant });
    if (move) fit(targetBounds(), instant);
    return done;
  };
  // A city frames a small box around its centre; a province or a region its own shape.
  const targetBounds = () => {
    if (state.citta) { const [lng, lat] = city(state.citta).center; return [[lng - 0.22, lat - 0.16], [lng + 0.22, lat + 0.16]]; }
    const target = state.provincia ? province(state.provincia) : state.regione ? region(state.regione) : null;
    return target ? target.bounds : ITALY_BOUNDS;
  };
  const up = () => go(state.citta ? { provincia: state.provincia } : state.provincia ? { regione: state.regione } : {});

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
      // No president linked yet: a coloured dot, not a «?» badge.
      if (!item.president) el.classList.add("is-empty");
      el.innerHTML = item.president ? `<span class="tmap-face-inner">${face(item.president, 40)}</span>` : `<span class="tmap-face-inner"><span class="tmap-dot" aria-hidden="true"></span></span>`;
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
      // A dot; the name is drawn by the map (vp-province-name), the code is not shown.
      el.innerHTML = `<span class="tmap-pin-inner" aria-hidden="true"></span>`;
      el.hidden = true;
      markers.push(new lib.Marker({ element: el, anchor: "center" }).setLngLat(item.center).addTo(map));
    }
    // Cities: a white square mark with the name beside it (few, so they never crowd).
    for (const item of cities) {
      const el = document.createElement("button");
      el.type = "button";
      el.className = "tmap-city";
      el.dataset.kind = "citta";
      el.dataset.citta = item.istat;
      el.dataset.region = item.regionIstat;
      el.setAttribute("aria-label", `Città di ${item.name}`);
      el.innerHTML = `<span class="tmap-city-mark" aria-hidden="true"></span><span class="tmap-city-name" aria-hidden="true">${esc(item.name)}</span>`;
      el.hidden = true;
      markers.push(new lib.Marker({ element: el, anchor: "left", offset: [-9, 0] }).setLngLat(item.center).addTo(map));
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
      maxBounds: [[-16, 12], [42, 62]],
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
    map.addSource("vp-province-centri", { type: "geojson", data: provincePoints });
    const before = "country-name";
    map.addLayer({ id: "vp-region-fill", type: "fill", source: "vp-regioni", paint: { "fill-color": ["get", "color"], "fill-opacity": 0.3 } }, before);
    map.addLayer({ id: "vp-province-fill", type: "fill", source: "vp-province", layout: { visibility: "none" }, paint: { "fill-color": ["get", "color"], "fill-opacity": 0.24 } }, before);
    // White seams between shapes (as on a phone map), the coalition colour as a thin edge on top.
    map.addLayer({ id: "vp-province-line", type: "line", source: "vp-province", layout: { visibility: "none", "line-join": "round" }, paint: { "line-color": PALETTE.seamSoft, "line-width": 1, "line-opacity": 0.9 } }, before);
    map.addLayer({ id: "vp-region-gap", type: "line", source: "vp-regioni", layout: { "line-join": "round" }, paint: { "line-color": PALETTE.seam, "line-width": ["interpolate", ["linear"], ["zoom"], 4, 1, 9, 2] } }, before);
    map.addLayer({ id: "vp-region-line", type: "line", source: "vp-regioni", layout: { "line-join": "round" }, paint: { "line-color": ["get", "color"], "line-width": 1.2, "line-opacity": 0.85 } }, before);
    // Province names instead of their codes; MapLibre drops the ones that would overlap.
    map.addLayer({ id: "vp-province-name", type: "symbol", source: "vp-province-centri", minzoom: PROVINCE_PIN_ZOOM, layout: { visibility: "none", "text-field": ["get", "name"], "text-font": FONT_BOLD, "text-size": ["interpolate", ["linear"], ["zoom"], 6.4, 10.5, 10, 14], "text-anchor": "top", "text-offset": [0, 0.9], "text-max-width": 7, "text-padding": 4 }, paint: { "text-color": PALETTE.label, "text-halo-color": PALETTE.halo, "text-halo-width": 1.6 } });
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
    const target = event.target instanceof Element ? event.target.closest("[data-regione], [data-provincia], [data-citta], [data-layer]") : null;
    if (!target || !root.contains(target) || target.closest(".tmap-results")) return;
    if (target.dataset.layer) {
      state.layer = target.dataset.layer;
      paintSelection();
      renderSheet({ animate: false });
      return;
    }
    // Keyboard activation (detail 0) moves focus to the new scheda; a tap leaves it alone.
    const keyboard = event.detail === 0;
    const done = target.dataset.citta ? go({ citta: target.dataset.citta }, { instant: keyboard })
      : target.dataset.provincia ? go({ provincia: target.dataset.provincia }, { instant: keyboard })
      : go({ regione: target.dataset.regione }, { instant: keyboard });
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
      go(state.citta ? { provincia: state.provincia } : state.provincia ? { regione: state.regione } : {}, { instant: true });
    }
  });
  window.addEventListener("popstate", () => {
    const next = readTerritoryState(new URLSearchParams(window.location.search));
    go(next, { push: false });
  });

  bindSearch({ root, input: $("tmap-q"), list: $("tmap-results"), api, esc, color, regions, provinces, cities, region, province, onPick: (item, viaKeyboard) => {
    if (item.kind === "regione") go({ regione: item.istat }, { instant: viaKeyboard });
    else if (item.kind === "citta") go({ citta: item.istat }, { instant: viaKeyboard });
    else go({ provincia: item.sigla }, { instant: viaKeyboard });
  } });

  // First state: the URL, else the reader's zone (region + province), else Italy.
  const fromUrl = readTerritoryState(new URLSearchParams(window.location.search));
  const zoneIstat = zone?.region_id ? regions.find((item) => String(item.id) === String(zone.region_id))?.istat || "" : "";
  const first = fromUrl.regione || fromUrl.provincia || fromUrl.citta ? fromUrl : { regione: zoneIstat, provincia: zoneIstat ? (zone.province || "") : "" };
  state.regione = first.regione;
  state.provincia = first.provincia;
  state.citta = first.citta && city(first.citta) ? first.citta : "";
  if (state.citta) { state.provincia = city(state.citta).sigla; state.regione = city(state.citta).regionIstat; }
  if (state.provincia && !state.regione) state.regione = province(state.provincia)?.regionIstat || "";
  history.replaceState({ territory: true }, "", territoryHref(state));
  syncControls();
  await renderSheet({ animate: false });
  try {
    await startMap();
    map.fitBounds(targetBounds(), { padding: padding(), duration: 0, maxZoom: 11 });
    paintSelection();
  } catch {
    canvas.classList.add("is-unavailable");
    canvas.innerHTML = `<p class="tmap-fallback">La mappa non è disponibile su questo dispositivo. Usa la ricerca o l'elenco qui sotto.</p>`;
  }
  return { go, state, get map() { return map; } };
}

// Search: regions and provinces only, locally and instantly (no comuni on the map).
function bindSearch({ root, input, list, api, esc, color, regions, provinces, cities, region, province, onPick }) {
  const index = [...regions, ...cities, ...provinces];
  let items = [];
  let active = -1;
  const close = () => {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  };
  const paint = () => {
    items = matchPlaces(index, input.value);
    if (!input.value.trim()) { close(); return; }
    list.innerHTML = items.length
      ? items.map((item, i) => {
        const sub = item.kind === "regione" ? "Regione" : item.kind === "citta" ? `Città · Provincia di ${province(item.sigla)?.name || item.sigla}` : `Provincia · ${region(item.regionIstat)?.name || ""}`;
        const tone = item.kind === "regione" ? color(item.coalition) : color(region(item.regionIstat)?.coalition);
        return `<li id="tmap-opt-${i}" role="option" aria-selected="${i === active}" data-index="${i}"><span class="tmap-sigla${item.kind === "citta" ? " is-city" : ""}" style="--c:${tone}" aria-hidden="true"></span><span><strong>${esc(item.name)}</strong><small>${esc(sub)}</small></span></li>`;
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
