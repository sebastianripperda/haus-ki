/* Haus-KI – Gerüst, Seitenleiste und Kopfzeile. Teil der Oberfläche, die Dateien werden in fester Reihenfolge geladen (siehe index.html). */
"use strict";

// ------------------------------------------------------------------ Gerüst
const R = {};
function buildShell() {
  const root = $("#root");
  root.innerHTML = "";
  R.side = h("aside", { id: "side", "aria-label": "Chats und Vorlagen" });
  R.head = h("header", { id: "head" });
  R.body = h("div", { id: "body" });
  R.compWrap = h("div", { id: "composer" });
  R.modal = h("div");
  R.scrim = h("div", { id: "scrim", onClick: () => { S.sideOpen = false; applySideClasses(); } });
  root.append(h("div", { id: "app" }, R.side, h("main", { id: "main" }, R.head, R.body, R.compWrap)), R.scrim, R.modal);
  buildComposer();
  R.body.addEventListener("scroll", () => { S.stick = R.body.scrollHeight - R.body.scrollTop - R.body.clientHeight < 80; });
}
function applySideClasses() {
  document.body.classList.toggle("side-open", S.sideOpen);
  document.body.classList.toggle("app-collapsed", S.sideCollapsed);
}
function renderAll() { renderSide(); renderHead(); renderBody(); renderComposer(); renderModal(); }

async function loadChats() {
  const d = await api("GET", "/api/chats" + (S.viewAs ? "?of=" + S.viewAs : ""));
  S.chats = d.chats;
  S.retention = d.retention_days;
}
async function loadProjects() { S.projects = await api("GET", "/api/projects"); }
async function loadTemplates() { S.templates = await api("GET", "/api/templates"); }

function route() {
  const hsh = location.hash.replace(/^#/, "");
  const [name, id] = hsh.split("/");
  S.pop = null;
  S.sideOpen = false;
  applySideClasses();
  if (name === "chat" && id) { S.route = { name: "chat", id: +id }; openChat(+id); }
  else if (name === "project" && id) { S.route = { name: "project", id: +id }; S.chat = null; S.live = null; }
  else if ((name === "admin" || name === "models") && isAdmin()) { S.route = { name: "admin", id: name === "models" ? "models" : (id || "overview") }; }
  else {
    S.route = { name: "start" };
    S.chat = null;
    S.live = null;
    loadStart();
    if (name === "konten") S.modal = "accounts";
    if (name === "share") { history.replaceState(null, "", "#start"); openShareInbox(); }
    if (name === "talk" && window.HKVoice) { history.replaceState(null, "", "#start"); setTimeout(() => window.HKVoice.openTalk(), 300); }
  }
  renderAll();
}
function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }

async function loadStart() {
  try { S.start = await api("GET", "/api/start"); } catch (e) { S.start = { suggestions: [], deadlines: [], calendar: [] }; }
  if (S.route.name === "start") renderBody();
}

// ------------------------------------------------------------------ Seitenleiste
function renderSide() {
  const el = R.side;
  el.innerHTML = "";
  el.append(
    h("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "4px 6px" } },
      h("a", { class: "brand", href: "#start", style: { textDecoration: "none", color: "var(--text)" } }, h("span", { class: "logo" }, "HK"), "Haus-KI"),
      h("button", { class: "ib", type: "button", "aria-label": "Seitenleiste ausblenden", onClick: () => { if (innerWidth <= 960) S.sideOpen = false; else S.sideCollapsed = true; applySideClasses(); renderHead(); } }, icon("side"))),
    h("button", { class: "pill", type: "button", style: { fontWeight: 700, justifyContent: "flex-start" }, onClick: () => { S.viewAs = null; newChat(); } }, icon("plus"), "Neuer Chat"),
    h("label", { class: "sr", for: "q" }, S.sideTab === "tpl" ? "Vorlagen suchen" : "Chats suchen"),
    h("input", { id: "q", class: "inp", type: "search", placeholder: S.sideTab === "tpl" ? "Vorlagen suchen" : "Chats suchen", value: S.q, style: { background: "var(--card)" },
      onInput: debounce(async (e) => { S.q = e.target.value; S.searchHits = S.q.trim().length > 1 && S.sideTab === "chats" ? await api("GET", "/api/search?q=" + encodeURIComponent(S.q)) : null; renderSide(); $("#q").focus(); $("#q").setSelectionRange(S.q.length, S.q.length); }, 250) }));
  if (!S.viewAs && !simple()) el.appendChild(h("div", { class: "tabs", role: "tablist", "aria-label": "Seitenleiste" },
    [["chats", "Chats"], ["tpl", "Vorlagen"]].map(([k, l]) => h("button", { type: "button", role: "tab", "aria-selected": S.sideTab === k ? "true" : "false", onClick: () => { S.sideTab = k; S.q = ""; S.searchHits = null; renderSide(); } }, l))));
  if (isAdmin() && S.me.features.admin_read && S.me.family.length > 1) {
    el.appendChild(h("div", { class: "group" }, h("span", { class: "over" }, "Chats von"),
      h("div", { class: "avs" }, S.me.family.map((u) => h("button", { type: "button", "aria-pressed": (S.viewAs || S.me.id) === u.id ? "true" : "false", "aria-label": "Chats von " + u.name, title: u.name,
        onClick: async () => { S.viewAs = u.id === S.me.id ? null : u.id; S.sideTab = "chats"; await loadChats(); go("#start"); } }, av(u))))));
  }
  if (S.sideTab === "tpl" && !S.viewAs) return renderSideTemplates(el);
  if (S.searchHits) {
    el.appendChild(group("Suchergebnisse", S.searchHits.map((c) => chatRow(c, c.by_meaning ? "passt inhaltlich" : null)), "Nichts gefunden."));
    return;
  }
  if (!S.viewAs && !simple()) {
    el.appendChild(h("button", { class: "menu-row", type: "button", style: { color: "var(--accent)", minHeight: "40px" }, onClick: newProject }, icon("folder"), "Neues Projekt"));
    if (S.projects.length) el.appendChild(group("Projekte", S.projects.map((p) => h("div", { class: "row" + (S.route.name === "project" && S.route.id === p.id ? " on" : "") },
      h("a", { href: "#project/" + p.id }, h("span", { class: "t" }, p.title))))));
  }
  const chats = S.chats.filter((c) => !S.q || c.title.toLowerCase().includes(S.q.toLowerCase()));
  const shared = chats.filter((c) => c.kind === "shared");
  const pinned = chats.filter((c) => c.pinned && c.kind !== "shared");
  const rest = chats.filter((c) => !c.pinned && c.kind !== "shared" && !c.project_id);
  if (S.viewAs) el.appendChild(h("div", { class: "note warn small" }, "Nur lesen. Jede Einsicht steht im Protokoll."));
  if (shared.length) el.appendChild(group("Geteilt mit mir", shared.map((c) => chatRow(c, "von " + (c.shared_by_name || "")))));
  if (pinned.length) el.appendChild(group("Angeheftet", pinned.map((c) => chatRow(c))));
  const now = new Date(), day0 = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
  const buckets = [["Heute", day0], ["Gestern", day0 - 86400], ["Letzte 7 Tage", day0 - 6 * 86400], ["Älter", 0]];
  for (let i = 0; i < buckets.length; i++) {
    const [label, from] = buckets[i], to = i ? buckets[i - 1][1] : Infinity;
    const list = rest.filter((c) => c.updated >= from && c.updated < to);
    if (list.length) el.appendChild(group(label, list.map((c) => chatRow(c))));
  }
  if (!chats.length) el.appendChild(h("p", { class: "small muted", style: { padding: "0 10px" } }, S.viewAs ? "Keine Chats." : "Noch keine Chats. Stell einfach eine Frage."));
  el.appendChild(h("p", { class: "side-note" }, `Chats werden nach ${S.retention || 90} Tagen gelöscht${S.me.features ? ", angeheftete bleiben" : ""}.`));
}
function group(label, rows, empty) {
  return h("div", { class: "group" }, h("span", { class: "over" }, label), rows.length ? rows : h("p", { class: "small muted", style: { padding: "0 10px", margin: 0 } }, empty || ""));
}
function chatRow(c, sub) {
  const open = S.menuFor === "c" + c.id;
  return h("div", { class: "row" + (S.route.name === "chat" && S.route.id === c.id ? " on" : ""), "data-pop": "1" },
    h("a", { href: "#chat/" + c.id }, h("span", { class: "t" }, c.title), sub ? h("span", { class: "s" }, sub) : null),
    S.viewAs ? null : h("button", { class: "ib dots", type: "button", "aria-label": "Aktionen für " + c.title, "aria-expanded": open ? "true" : "false",
      onClick: (e) => { e.stopPropagation(); S.menuFor = open ? null : "c" + c.id; S.pop = S.menuFor ? "row" : null; renderSide(); } }, icon("dots")),
    open ? chatMenu(c) : null);
}
function chatMenu(c) {
  const close = () => { S.menuFor = null; S.pop = null; };
  return h("div", { class: "pop", style: { right: "4px", top: "40px" } },
    h("button", { class: "menu-row", type: "button", onClick: async () => { close(); const t = await promptDialog("Chat umbenennen", "Name", c.title); if (t) { await api("PATCH", "/api/chats/" + c.id, { title: t }); await loadChats(); renderSide(); } } }, "Umbenennen"),
    h("button", { class: "menu-row", type: "button", onClick: async () => { close(); await api("PATCH", "/api/chats/" + c.id, { pinned: !c.pinned }); await loadChats(); renderSide(); } }, c.pinned ? "Lösen" : "Anheften"),
    S.projects.length ? h("div", null, h("div", { class: "menu-sep" }), h("div", { class: "tiny muted", style: { padding: "4px 10px" } }, "In Projekt verschieben"),
      [{ id: null, title: "Kein Projekt" }, ...S.projects].map((p) => h("button", { class: "menu-row", type: "button", style: { minHeight: "36px" }, "aria-pressed": c.project_id === p.id ? "true" : "false",
        onClick: async () => { close(); await api("PATCH", "/api/chats/" + c.id, { project_id: p.id }); await loadChats(); renderAll(); } }, p.title))) : null,
    h("div", { class: "menu-sep" }),
    h("a", { class: "menu-row", href: "/api/chats/" + c.id + "/export", download: "" }, "Als Markdown exportieren"),
    h("button", { class: "menu-row", type: "button", style: { color: "var(--err)" }, onClick: async () => {
      close(); if (!(await confirmDialog("Chat löschen?", `„${c.title}“ wird endgültig gelöscht.`, "Löschen"))) return;
      await api("DELETE", "/api/chats/" + c.id); await loadChats(); if (S.route.id === c.id) go("#start"); else renderSide(); } }, "Löschen"));
}
function renderSideTemplates(el) {
  const f = (t) => !S.q || t.title.toLowerCase().includes(S.q.toLowerCase());
  const mine = S.templates.filter((t) => t.owner_id === S.me.id && f(t)), fam = S.templates.filter((t) => t.owner_id === null && f(t));
  const row = (t) => {
    const open = S.menuFor === "t" + t.id, canEdit = t.owner_id === S.me.id || isAdmin();
    return h("div", { class: "row", "data-pop": "1" },
      h("button", { class: "main", type: "button", onClick: () => useTemplate(t) }, h("span", { class: "t" }, t.title)),
      canEdit ? h("button", { class: "ib dots", type: "button", "aria-label": "Aktionen für Vorlage " + t.title, "aria-expanded": open ? "true" : "false",
        onClick: (e) => { e.stopPropagation(); S.menuFor = open ? null : "t" + t.id; S.pop = S.menuFor ? "row" : null; renderSide(); } }, icon("dots")) : null,
      open ? h("div", { class: "pop", style: { right: "4px", top: "40px" } },
        h("button", { class: "menu-row", type: "button", onClick: () => { S.menuFor = null; S.pop = null; S.modal = { kind: "template", t }; renderAll(); } }, "Bearbeiten"),
        h("button", { class: "menu-row", type: "button", style: { color: "var(--err)" }, onClick: async () => { S.menuFor = null; S.pop = null; if (await confirmDialog("Vorlage löschen?", t.title, "Löschen")) { await api("DELETE", "/api/templates/" + t.id); await loadTemplates(); renderSide(); } } }, "Löschen")) : null);
  };
  el.append(group("Meine Vorlagen", mine.map(row), "Speichere eine Antwort als Vorlage, um sie wiederzuverwenden."),
    group("Familienvorlagen", fam.map(row), isAdmin() ? "Administratoren können Vorlagen für alle anlegen." : "Noch keine."),
    h("button", { class: "menu-row", type: "button", style: { color: "var(--accent)" }, onClick: () => { S.modal = { kind: "template", t: null }; renderModal(); } }, icon("plus"), "Neue Vorlage"));
}

// ------------------------------------------------------------------ Kopfzeile
function renderHead() {
  const el = R.head;
  el.innerHTML = "";
  const narrow = innerWidth <= 960;
  if (narrow || S.sideCollapsed) el.appendChild(h("button", { class: "ib", type: "button", "aria-label": "Seitenleiste einblenden", onClick: () => { if (narrow) S.sideOpen = true; else S.sideCollapsed = false; applySideClasses(); renderHead(); } }, icon(narrow ? "menu" : "side")));
  // Modellauswahl (in der einfachen Ansicht nur der Name)
  if (simple()) el.appendChild(h("span", { style: { fontWeight: 700, fontSize: "16px", padding: "0 8px" } }, "Haus-KI"));
  const models = S.me.models || [S.model];
  const loaded = new Set(((S.status && S.status.loaded) || []).map((m) => m.name));
  if (!simple()) el.appendChild(h("div", { class: "rel", "data-pop": "1" },
    h("button", { class: "ib", type: "button", "aria-expanded": S.pop === "model" ? "true" : "false", style: { fontWeight: 700, fontSize: "16px" }, onClick: () => { S.pop = S.pop === "model" ? null : "model"; renderHead(); } },
      S.model, S.model === S.me.default_model ? h("span", { class: "badge hide-sm" }, "Standard") : null, icon("chev", 16)),
    S.pop === "model" ? h("div", { class: "pop", style: { top: "46px", left: 0, width: "300px" } },
      h("div", { class: "tiny muted", style: { padding: "6px 10px" } }, "Modell für neue Fragen"),
      (models || []).map((m) => h("button", { class: "menu-row", type: "button", "aria-pressed": m === S.model ? "true" : "false", onClick: () => { S.model = m; S.pop = null; renderHead(); } },
        h("span", { class: "grow" }, m, h("small", null, m === S.me.default_model ? "Standard, dauerhaft geladen" : loaded.has(m) ? "geladen" : "wird beim ersten Mal geladen, etwa 20 Sekunden")),
        m === S.model ? icon("check") : null)),
      isAdmin() ? h("a", { class: "menu-row", href: "#models", style: { color: "var(--accent)" } }, "Modelle verwalten") : null) : null));
  el.appendChild(h("span", { class: "grow" }));
  // Haus
  if (S.me.features.knx) {
    const openWin = (S.trip || []).filter((t) => t.open).length;
    el.appendChild(h("div", { class: "rel", "data-pop": "1" },
      h("button", { class: "pill", type: "button", "aria-label": "Haus-Schnellsteuerung" + (openWin ? `, ${openWin} Fenster offen` : ""), "aria-expanded": S.pop === "knx" ? "true" : "false",
        onClick: () => { S.pop = S.pop === "knx" ? null : "knx"; renderHead(); if (S.pop) loadKnx(); } },
        icon("home"), openWin ? h("span", { class: "badge warn hide-sm" }, `${openWin} Fenster offen`) : null,
        openWin ? h("span", { class: "dot-sm", style: { width: "8px", height: "8px", borderRadius: "50%", background: "var(--warn)" } }) : null),
      S.pop === "knx" ? knxPopover() : null));
  }
  // Auslastung
  const st = S.status;
  const vm = st && st.vm && !st.vm.error ? st.vm : null;
  const ollamaDown = st && st.ollama && st.ollama.ok === false;
  const running = st ? st.queue.running.length : 0;
  if (simple()) { if (ollamaDown) el.appendChild(h("span", { class: "badge err", style: { marginRight: "6px" } }, "Haus-KI macht Pause")); }
  else el.appendChild(h("div", { class: "rel", "data-pop": "1" },
    h("button", { class: "pill", type: "button", "aria-expanded": S.pop === "vm" ? "true" : "false", "aria-label": "Auslastung des Ollama-Containers", onClick: () => { S.pop = S.pop === "vm" ? null : "vm"; renderHead(); } },
      ollamaDown ? h("span", { class: "badge err" }, "Ollama aus") : running ? h("span", { class: "badge warn hide-sm" }, `${running} aktiv`) : null,
      vm ? [h("span", { class: "small muted hide-sm" }, "CPU"), h("span", { class: "bar hide-sm", style: { width: "54px" } }, h("span", { style: { width: vm.cpu + "%", background: vm.cpu > 85 ? "var(--warn)" : "var(--accent)" } })),
        h("span", { class: "small", style: { fontVariantNumeric: "tabular-nums", fontFamily: "var(--mono)" } }, vm.cpu + " %")] : h("span", { class: "small" }, st ? (st.ollama.ok ? "Bereit" : "…") : "…")),
    S.pop === "vm" ? vmPopover() : null));
  // Hell / Dunkel
  el.appendChild(themeSwitch("hide-sm"));
  // Benutzer
  el.appendChild(h("div", { class: "rel", "data-pop": "1" },
    h("button", { class: "ib", type: "button", "aria-label": "Benutzermenü", "aria-expanded": S.pop === "user" ? "true" : "false", style: { padding: 0, borderRadius: "50%", position: "relative" }, onClick: () => { S.pop = S.pop === "user" ? null : "user"; renderHead(); } },
      av(S.me, "lg"), st && st.unread ? h("span", { style: { position: "absolute", top: "2px", right: "2px", width: "10px", height: "10px", borderRadius: "50%", background: "var(--warn)", border: "2px solid var(--bg)" } }) : null),
    S.pop === "user" ? userMenu() : null));
}
function vmPopover() {
  const st = S.status || { queue: { running: [], waiting: 0 }, loaded: [], ollama: {} };
  const vm = st.vm && !st.vm.error ? st.vm : null;
  return h("div", { class: "pop pad", style: { top: "48px", right: 0, width: "min(330px, calc(100vw - 32px))" } },
    h("div", { style: { display: "flex", alignItems: "center", gap: "8px" } }, h("span", { class: "status-dot" + (st.ollama.ok === false ? " off" : st.ollama.ok ? "" : " unk") }),
      h("b", null, st.ollama.ok === false ? "Ollama antwortet nicht" : "Ollama bereit"), h("span", { class: "tiny muted" }, st.ollama.version ? "Version " + st.ollama.version : "")),
    vm ? h("div", { class: "grid2", style: { gridTemplateColumns: "1fr 1fr", gap: "10px" } },
      h("div", null, h("div", { class: "tiny muted" }, `CPU, ${vm.cpus || "?"} Kerne`), h("b", null, vm.cpu + " %")),
      h("div", null, h("div", { class: "tiny muted" }, "Arbeitsspeicher"), h("b", null, `${fmtGB(vm.mem)} / ${fmtGB(vm.maxmem)}`))) :
      h("p", { class: "small muted", style: { margin: 0 } }, st.vm && st.vm.error ? "Proxmox: " + st.vm.error : "Proxmox ist nicht verbunden, daher keine CPU- und RAM-Werte."),
    h("div", null, h("div", { class: "tiny muted" }, "Geladene Modelle"), st.loaded.length ? st.loaded.map((m) => h("div", { class: "small" }, `${m.name}, ${fmtGB(m.size)}`)) : h("div", { class: "small" }, "keins")),
    h("div", null, h("div", { class: "tiny muted" }, "Warteschlange"),
      st.queue.running.length ? st.queue.running.map((r) => h("div", { class: "small" }, `Rechnet gerade: ${r.label} für ${r.user}`)) : h("div", { class: "small" }, "Nichts in Arbeit."),
      st.queue.waiting ? h("div", { class: "small" }, `${st.queue.waiting} warten, etwa ${st.queue.avg_seconds} Sekunden je Anfrage`) : null));
}
function userMenu() {
  const close = () => { S.pop = null; };
  const item = (ic, label, fn, extra) => h("button", { class: "menu-row", type: "button", onClick: () => { close(); fn(); } }, icon(ic), h("span", { class: "grow" }, label), extra || null);
  return h("div", { class: "pop", style: { top: "52px", right: 0, width: "290px" } },
    h("div", { style: { display: "flex", gap: "10px", alignItems: "center", padding: "8px 10px" } }, av(S.me, "lg"),
      h("div", null, h("b", null, S.me.name), h("div", { class: "tiny muted" }, (S.me.email || "") + " · " + (isAdmin() ? "Administrator" : "Mitglied")))),
    h("div", { class: "menu-sep" }),
    item("bell", "Benachrichtigungen", () => { S.modal = "notifications"; renderAll(); }, S.status && S.status.unread ? h("span", { class: "badge warn" }, S.status.unread) : null),
    item("clock", "Geplante Prompts", () => { S.modal = "schedules"; renderAll(); }),
    S.me.features.voice ? item("mic", "Sprache", () => { S.modal = "voice"; renderAll(); }) : null,
    S.me.features.memory ? item("brain", "Gedächtnis", () => { S.modal = "memory"; renderAll(); }) : null,
    item("home", "Familienwissen", () => { S.modal = "family"; renderAll(); }),
    item("mail", "Meine Konten", () => { S.modal = "accounts"; renderAll(); }),
    item("user", "Einstellungen für mich", () => { S.modal = "prefs"; renderAll(); }),
    isAdmin() ? [h("div", { class: "menu-sep" }), item("cube", "Modelle", () => go("#models")), item("gear", "Administration", () => go("#admin/overview"))] : null,
    h("div", { class: "menu-sep" }),
    h("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px", padding: "6px 10px" } }, h("span", null, "Darstellung"), themeSwitch()),
    h("div", { class: "menu-sep" }),
    item("logout", "Abmelden", async () => { await api("POST", "/auth/logout"); location.href = "/"; }));
}
