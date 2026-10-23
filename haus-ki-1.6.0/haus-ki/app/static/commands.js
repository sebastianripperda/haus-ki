/* Haus-KI – Befehlssuche mit „/“ im Eingabefeld. Macht alle Funktionen auffindbar, auch die,
   die in der einfachen Ansicht ausgeblendet sind. Teil der Oberfläche (siehe index.html). */
"use strict";

const CMD = { open: false, items: [], sel: 0 };
const norm = (t) => (t || "").toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss");

function pickFile(accept, onFile, capture) {
  const inp = h("input", { type: "file", class: "hidden", accept, capture: capture || null, onChange: (e) => { if (e.target.files[0]) onFile(e.target.files[0]); inp.remove(); } });
  document.body.appendChild(inp);
  inp.click();
}

/* Alle Befehle. arg: Platzhalter, wenn hinter dem Befehl Text erwartet wird. */
function allCommands() {
  const f = S.me.features, voice = window.HKVoice && window.HKVoice.enabled();
  const openPop = (name) => () => { S.pop = name; renderComposerPop(); renderTools(); };
  const modal = (name) => () => { S.modal = name; renderAll(); };
  const lastAnswer = () => S.chat && [...S.chat.messages].reverse().find((m) => m.role === "assistant");
  return [
    { name: "neu", label: "Neuer Chat", run: () => newChat() },
    { name: "suche", label: "In meinen Chats suchen", arg: "Begriff", run: (a) => {
      S.sideTab = "chats"; S.q = a; S.sideOpen = true; applySideClasses();
      api("GET", "/api/search?q=" + encodeURIComponent(a)).then((r) => { S.searchHits = r; renderSide(); }); } },
    { name: "merken", label: "Im Gedächtnis speichern (nur für mich)", arg: "Fakt", show: f.memory, run: async (a) => {
      if (!a) return modal("memory")(); await api("POST", "/api/memory", { text: a }); toast("Gemerkt: " + a); } },
    { name: "familie", label: "Im Familienwissen speichern (für alle)", arg: "Fakt", run: async (a) => {
      if (!a) return modal("family")(); await api("POST", "/api/family", { text: a }); toast("Für alle gemerkt: " + a); } },
    { name: "gespräch", label: "Gesprächsmodus starten", show: voice && S.me.voice && S.me.voice.talk, run: () => window.HKVoice.openTalk() },
    { name: "vorlesen", label: "Letzte Antwort vorlesen", show: voice, run: () => {
      const m = lastAnswer(); if (!m) return toast("Hier gibt es noch keine Antwort.", true);
      window.HKVoice.speak(m.content, { key: "m" + m.id }).catch((e) => toast(e.message, true)); } },
    { name: "paperless", label: "Dokument in Paperless ablegen", show: f.paperless_upload, run: () => pickFile("application/pdf,image/*", (file) => paperlessUpload(file), "environment") },
    { name: "anhang", label: "Datei oder Bild anhängen", run: () => pickFile("image/*,text/*,.txt,.md,.csv,.log,.json", (file) => addFile(file)) },
    { name: "quellen", label: "Quellen auswählen", run: openPop("sources") },
    { name: "stil", label: "Antwortstil: genau, ausgewogen, kreativ", run: openPop("style") },
    { name: "planen", label: "Prompt planen (regelmäßig ausführen)", arg: "Prompt", run: (a) => {
      setDraft(a || "");
      S.schedForm = { name: (a || S.draft).split("\n")[0].slice(0, 40), freq: "weekly", day: "Mo", time: "07:00", deliver: "notify" };
      openPop("schedule")(); }, keep: true },
    { name: "vorlage", label: "Vorlage einfügen", arg: "Name", run: (a) => {
      setDraft("");
      const t = S.templates.find((x) => norm(x.title).includes(norm(a))) || S.templates[0];
      if (t) useTemplate(t); else toast("Noch keine Vorlagen.", true); }, keep: true },
    { name: "vergleich", label: "Mit zweitem Modell vergleichen", show: isAdmin(), run: openPop("compare") },
    { name: "haus", label: "Haus-Schnellsteuerung", show: f.knx, run: () => { S.pop = "knx"; renderHead(); loadKnx(); } },
    { name: "gedächtnis", label: "Mein Gedächtnis ansehen", show: f.memory, run: modal("memory") },
    { name: "familienwissen", label: "Familienwissen ansehen", run: modal("family") },
    { name: "geplant", label: "Geplante Prompts", run: modal("schedules") },
    { name: "konten", label: "Meine Konten (Postfächer)", run: modal("accounts") },
    { name: "sprache", label: "Stimme und Sprache einstellen", show: voice, run: modal("voice") },
    { name: "einstellungen", label: "Einstellungen für mich", run: modal("prefs") },
    { name: "hell", label: "Helles Design", run: () => window.HKTheme && window.HKTheme.set("light") },
    { name: "dunkel", label: "Dunkles Design", run: () => window.HKTheme && window.HKTheme.set("dark") },
    { name: "einfach", label: "Einfache Ansicht", show: !simple(), run: () => setSimple(true) },
    { name: "voll", label: "Volle Ansicht mit allen Knöpfen", show: simple(), run: () => setSimple(false) },
    { name: "admin", label: "Administration", show: isAdmin(), run: () => go("#admin/overview") },
    { name: "modelle", label: "Modelle verwalten", show: isAdmin(), run: () => go("#models") },
    { name: "einführung", label: "Einführung noch einmal zeigen", run: () => { S.modal = "intro"; S.introStep = 0; renderAll(); } },
    { name: "hilfe", label: "Alle Befehle anzeigen", run: () => { setDraft("/"); updateCommands(); }, keep: true },
  ].filter((c) => c.show === undefined || c.show);
}
async function setSimple(on) {
  S.me.prefs = await api("PUT", "/api/me/prefs", { simple_ui: on });
  toast(on ? "Einfache Ansicht. Alle Funktionen findest du mit /." : "Volle Ansicht mit allen Knöpfen.");
  renderAll();
}

function updateCommands() {
  const m = S.draft.match(/^\/(\S*)(?:\s+([\s\S]*))?$/);
  if (!m || S.draft.includes("\n") || S.tpl) { if (CMD.open) closeCommands(); return; }
  const word = norm(m[1]), arg = (m[2] || "").trim(), typedSpace = /\s/.test(S.draft);
  let items = allCommands();
  if (typedSpace) {
    items = items.filter((c) => norm(c.name) === word && c.arg);              // „/merken Text“: genau dieser Befehl
    if (word === "vorlage") items = S.templates.filter((t) => !arg || norm(t.title).includes(norm(arg)))
      .map((t) => ({ name: "vorlage", label: t.title, arg: "", run: () => { setDraft(""); useTemplate(t); }, keep: true, template: true }));
  } else if (word) {
    items = items.filter((c) => norm(c.name).startsWith(word)).concat(items.filter((c) => !norm(c.name).startsWith(word) && (norm(c.name).includes(word) || norm(c.label).includes(word))));
  }
  CMD.items = items.map((c) => ({ ...c, argText: typedSpace ? arg : "" }));
  CMD.sel = Math.min(CMD.sel, Math.max(0, CMD.items.length - 1));
  CMD.open = true;
  renderCommands();
}
function closeCommands() { CMD.open = false; CMD.items = []; CMD.sel = 0; if (R.compCmd) R.compCmd.innerHTML = ""; R.ta.removeAttribute("aria-activedescendant"); R.ta.setAttribute("aria-expanded", "false"); }
async function runCommand(c) {
  closeCommands();
  if (!c.keep) setDraft("");
  try { await c.run(c.argText || ""); } catch (e) { toast(e.message, true); }
  renderComposer();
}
function commandKey(e) {
  if (!CMD.open) return false;
  if (e.key === "Escape") { e.preventDefault(); closeCommands(); return true; }
  if (!CMD.items.length) return e.key === "Enter" ? (e.preventDefault(), true) : false;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    CMD.sel = (CMD.sel + (e.key === "ArrowDown" ? 1 : -1) + CMD.items.length) % CMD.items.length;
    renderCommands();
    return true;
  }
  if (e.key === "Tab") {  // vervollständigen
    e.preventDefault();
    const c = CMD.items[CMD.sel];
    if (!c.template) { setDraft("/" + c.name + (c.arg ? " " : "")); updateCommands(); }
    return true;
  }
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    const c = CMD.items[CMD.sel];
    if (c.arg && !c.argText && !["merken", "familie", "planen", "vorlage", "suche"].includes(c.name)) return true;
    if (c.arg && !c.argText && ["suche"].includes(c.name)) { setDraft("/" + c.name + " "); updateCommands(); return true; }
    runCommand(c);
    return true;
  }
  return false;
}
function renderCommands() {
  const el = R.compCmd;
  el.innerHTML = "";
  if (!CMD.open) return;
  R.ta.setAttribute("aria-expanded", "true");
  R.ta.setAttribute("aria-controls", "cmd-list");
  const list = h("div", { class: "pop cmd", id: "cmd-list", role: "listbox", "aria-label": "Befehle", style: { bottom: "100%", left: 0, marginBottom: "8px", width: "min(480px, 100%)" } },
    CMD.items.length ? CMD.items.slice(0, 12).map((c, i) => h("div", { class: "cmd-row", role: "option", id: "cmd-" + i, "aria-selected": i === CMD.sel ? "true" : "false",
      onMousedown: (e) => { e.preventDefault(); CMD.sel = i; runCommand(c); } },
      h("span", { class: "mono" }, c.template ? "Vorlage" : "/" + c.name + (c.arg ? " …" : "")),
      h("span", { class: "grow" }, c.label, c.arg && c.argText ? h("span", { class: "muted" }, ": " + c.argText) : null))) :
      h("div", { class: "small muted", style: { padding: "8px 10px" } }, "Kein passender Befehl. Esc schließt, ohne „/“ wird die Nachricht normal gesendet."),
    h("div", { class: "tiny muted", style: { padding: "6px 10px", borderTop: "1px solid var(--row)" } }, "↑ ↓ wählen · Enter ausführen · Tab vervollständigen · Esc schließen"));
  el.appendChild(list);
  if (CMD.items.length) R.ta.setAttribute("aria-activedescendant", "cmd-" + CMD.sel);
  const active = list.querySelector('[aria-selected="true"]');
  if (active) active.scrollIntoView({ block: "nearest" });
}
