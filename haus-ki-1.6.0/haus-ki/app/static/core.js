/* Haus-KI – Grundlagen, Zustand und Start. Teil der Oberfläche, die Dateien werden in fester Reihenfolge geladen (siehe index.html). */
"use strict";

// ------------------------------------------------------------------ Grundlagen
const $ = (s, el = document) => el.querySelector(s);
// append() soll wie h() leere Werte und Listen verstehen, statt „null“ als Text einzufügen.
const nativeAppend = Element.prototype.append;
Element.prototype.append = function (...kids) {
  return nativeAppend.apply(this, kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false && k !== ""));
};
function h(tag, props, ...kids) {
  const el = document.createElementNS(tag === "svg" || tag === "path" || tag === "circle" || tag === "rect" ? "http://www.w3.org/2000/svg" : "http://www.w3.org/1999/xhtml", tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "html") el.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "class") el.setAttribute("class", v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "value" && (tag === "input" || tag === "textarea" || tag === "select")) el.value = v;
    else if (k === "checked" || k === "disabled" || k === "selected" || k === "multiple") el[k] = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat(Infinity)) {
    if (c === null || c === undefined || c === false || c === "") continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const ICONS = {
  menu: "M4 6h16M4 12h16M4 18h16", side: "M4 5h16v14H4zM9 5v14", plus: "M12 5v14M5 12h14", search: "M11 18a7 7 0 1 1 0-14 7 7 0 0 1 0 14zM20 20l-4-4",
  chev: "M6 9l6 6 6-6", home: "M3 11l9-7 9 7M5 10v10h14V10", x: "M6 6l12 12M18 6L6 18", dots: "", send: "M12 19V5M5 12l7-7 7 7", stop: "M7 7h10v10H7z",
  clip: "M21 12.5l-8.4 8.4a5 5 0 0 1-7.1-7.1l8.4-8.4a3.5 3.5 0 0 1 5 5l-8.5 8.4a2 2 0 0 1-2.8-2.8l7.8-7.8", db: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  sliders: "M4 7h9M17 7h3M4 17h3M11 17h9M15 5v4M9 15v4", copy: "M9 9h11v11H9zM5 15V4h11", refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7", bookmark: "M6 3h12v18l-6-4-6 4z",
  share: "M18 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8.6 13.5l6.8 4M15.4 6.5l-6.8 4",
  up: "M7 10v11H3V10zM7 10l5-8a3 3 0 0 1 3 3v4h5a2 2 0 0 1 2 2.3l-1.4 8A2 2 0 0 1 18.6 21H7", down: "M17 14V3h4v11zM17 14l-5 8a3 3 0 0 1-3-3v-4H4a2 2 0 0 1-2-2.3l1.4-8A2 2 0 0 1 5.4 3H17",
  edit: "M4 20h4L19 9l-4-4L4 16z", clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2", cols: "M3 5h8v14H3zM13 5h8v14h-8z", folder: "M3 7h6l2 2h10v10H3z",
  bell: "M6 16V11a6 6 0 1 1 12 0v5l2 2H4zM10 21h4", lock: "M6 11h12v10H6zM8 11V7a4 4 0 1 1 8 0v4", check: "M5 12l5 5 9-10", brain: "M12 5a3 3 0 0 0-6 1 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1zM12 5a3 3 0 0 1 6 1 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1z",
  mail: "M3 6h18v12H3zM3 6l9 7 9-7", gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3 15H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 10 4.1V4a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.1a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.6 1z",
  cube: "M12 2l9 5v10l-9 5-9-5V7zM12 12l9-5M12 12L3 7M12 12v10", logout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11", user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  file: "M6 3h8l4 4v14H6zM14 3v4h4", pin: "M12 17v5M8 3h8l-1 6 3 3v2H6v-2l3-3z",
  mic: "M12 3a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3", wave: "M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4",
};
function icon(name, size = 18) {
  if (name === "dots") return h("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "currentColor", "aria-hidden": "true" },
    h("circle", { cx: 5, cy: 12, r: 1.8 }), h("circle", { cx: 12, cy: 12, r: 1.8 }), h("circle", { cx: 19, cy: 12, r: 1.8 }));
  return h("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" },
    h("path", { d: ICONS[name] || "" }));
}

async function api(method, path, body, opts = {}) {
  const init = { method, headers: { "x-haus-ki": "1" }, credentials: "same-origin" };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) { init.headers["content-type"] = "application/json"; init.body = JSON.stringify(body); }
  const r = await fetch(path, init);
  if (r.status === 401 && !opts.quiet401) { location.reload(); throw new Error("Bitte melde dich an."); }
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.detail) || `Fehler ${r.status}`);
  return data;
}
function toast(text, err) {
  const t = h("div", { class: "toast" + (err ? " err" : "") }, text);
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), err ? 7000 : 4000);
}
const fmtN = (n, d = 0) => Number(n || 0).toLocaleString("de-DE", { maximumFractionDigits: d, minimumFractionDigits: d });
const fmtDate = (ts) => new Date(ts * 1000).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
const fmtGB = (b) => fmtN(b / 1e9, 1) + " GB";
const av = (u, cls = "") => h("span", { class: "av " + cls, style: { background: u.color || "#3f4a5a" }, "aria-hidden": "true" }, u.initial || (u.name || "?")[0]);
function toggle(label, on, onChange, help) {
  return h("button", { type: "button", class: "tg", role: "switch", "aria-checked": on ? "true" : "false", onClick: () => onChange(!on) },
    h("span", { class: "track", "aria-hidden": "true" }), h("span", { class: "tt" }, h("span", null, label), help ? h("small", null, help) : null));
}
function seg(options, value, onPick, label) {
  return h("div", { class: "seg", role: "group", "aria-label": label || null },
    options.map(([v, l]) => h("button", { type: "button", "aria-pressed": v === value ? "true" : "false", onClick: () => onPick(v) }, l)));
}
function themeSwitch(extraClass) {
  const cur = window.HKTheme ? window.HKTheme.get() : "light";
  const pick = (t) => { window.HKTheme.set(t); };
  return h("div", { class: "theme-seg " + (extraClass || ""), role: "group", "aria-label": "Darstellung" },
    [["light", "Hell"], ["dark", "Dunkel"]].map(([v, l]) => h("button", { type: "button", "aria-pressed": cur === v ? "true" : "false", onClick: () => pick(v) }, l)));
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

// ------------------------------------------------------------------ Zustand
const S = {
  me: null, chats: [], projects: [], templates: [], start: null, status: null,
  route: { name: "start" }, chat: null, live: null,
  draft: "", attachments: [], sources: new Set(), style: "ausgewogen", think: false, advanced: {}, compare: "", model: "",
  tpl: null, tplVars: {}, editing: null,
  sideTab: "chats", q: "", searchHits: null, viewAs: null, pop: null, modal: null, menuFor: null,
  blickAll: false, knx: null, trip: null, sideOpen: false, sideCollapsed: false, ctx: null,
};
const SOURCES = [
  ["paperless", "Paperless-ngx", "Rechnungen, Verträge, Briefe"], ["jellyfin", "Jellyfin", "Filme, Serien, Musik"],
  ["knx", "Haus", "Licht, Rollläden, Temperaturen"], ["m365", "Microsoft 365", "Outlook, Kalender, OneDrive, SharePoint"],
  ["mail", "Weitere Postfächer", "GMX, Gmail, Outlook.com"], ["web", "Internet", "Websuche, Seiten lesen"],
];
const SRC_LABEL = Object.fromEntries(SOURCES.map(([k, l]) => [k, l]));
const isAdmin = () => S.me && S.me.role === "admin";
// Einfache Ansicht: weniger Knöpfe, Klartext statt Fachbegriffen. Für Mitglieder voreingestellt.
const simple = () => !!(S.me && S.me.prefs && S.me.prefs.simple_ui);

// ------------------------------------------------------------------ Start
async function boot() {
  let me = null;
  try { me = await api("GET", "/api/me", undefined, { quiet401: true }); } catch (e) { /* nicht angemeldet */ }
  if (!me) return renderLogin();
  S.me = me;
  S.model = me.default_model;
  try { S.sources = new Set(JSON.parse(localStorage.getItem("hk.sources") || "null") || defaultSources()); } catch (e) { S.sources = new Set(defaultSources()); }
  for (const s of [...S.sources]) if (!me.features[s]) S.sources.delete(s);
  buildShell();
  await Promise.all([loadChats(), loadProjects(), loadTemplates()]);
  window.addEventListener("hashchange", route);
  route();
  pollStatus();
  setInterval(pollStatus, 20000);
  listenEvents();
  if (!S.me.prefs.onboarded && !S.modal) { S.modal = "intro"; S.introStep = 0; renderModal(); }  // Einführung beim ersten Anmelden
  if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});
  document.addEventListener("click", (e) => {
    if (S.pop && !e.composedPath().some((n) => n.dataset && n.dataset.pop)) { S.pop = null; S.menuFor = null; renderAll(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { if (S.modal) { S.modal = null; renderModal(); } else if (S.pop) { S.pop = null; S.menuFor = null; renderAll(); } }
  });
}
function defaultSources() { return ["paperless", "m365", "knx"]; }
