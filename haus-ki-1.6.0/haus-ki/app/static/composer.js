/* Haus-KI – Eingabefeld, Anhänge, Quellen, Antwortstil, Planen. Teil der Oberfläche, die Dateien werden in fester Reihenfolge geladen (siehe index.html). */
"use strict";

// ------------------------------------------------------------------ Eingabe
function buildComposer() {
  R.compWrap.innerHTML = "";
  R.comp = h("div", { class: "comp", "data-pop": "1" });
  R.compPop = h("div");
  R.compAtt = h("div");
  R.compTpl = h("div");
  R.ta = h("textarea", { rows: 2, "aria-label": "Nachricht an Haus-KI", placeholder: "Nachricht an Haus-KI. Enter sendet, Umschalt+Enter macht eine neue Zeile." });
  R.ta.addEventListener("input", () => { S.draft = R.ta.value; autosize(); renderTools(); updateCommands(); });
  R.ta.addEventListener("keydown", (e) => {
    if (commandKey(e)) return;  // Befehlssuche mit „/“ bedient Pfeiltasten, Enter, Tab und Esc
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && innerWidth > 720) { e.preventDefault(); send(); }
  });
  R.compTools = h("div", { class: "tools" });
  R.compBanner = h("div");
  R.compVoice = h("div");
  R.box = h("div", { class: "box" }, R.compBanner, R.compVoice, R.compAtt, R.compTpl, R.ta, R.compTools);
  R.box.addEventListener("dragover", (e) => { e.preventDefault(); R.box.classList.add("drag"); });
  R.box.addEventListener("dragleave", () => R.box.classList.remove("drag"));
  R.box.addEventListener("drop", (e) => { e.preventDefault(); R.box.classList.remove("drag"); for (const f of e.dataTransfer.files) addFile(f); });
  R.compCmd = h("div");
  R.comp.append(R.compPop, R.compCmd, R.box);
  R.compFoot = h("p", { class: "foot hide-sm" });
  R.compWrap.append(R.comp, R.compFoot);
}
function renderComposerVoice() {
  if (!R.compVoice) return;
  R.compVoice.innerHTML = "";
  const b = window.HKVoice && window.HKVoice.composerBanner();
  if (b) R.compVoice.appendChild(b);
  renderTools();
}
function autosize() { R.ta.style.height = "auto"; R.ta.style.height = Math.min(R.ta.scrollHeight, innerHeight * 0.4) + "px"; }
function setDraft(t) { S.draft = t; if (R.ta) { R.ta.value = t; autosize(); } }
function saveSources() { localStorage.setItem("hk.sources", JSON.stringify([...S.sources])); }
function renderComposer() {
  if (!R.ta) return;
  // Bearbeiten-Banner
  R.compBanner.innerHTML = "";
  if (S.editing) R.compBanner.appendChild(h("div", { style: { display: "flex", gap: "8px", alignItems: "center", fontSize: "13px", color: "var(--warn)" } },
    icon("edit", 14), h("span", { class: "grow" }, "Du bearbeitest eine Nachricht. Alles danach wird neu beantwortet."), h("button", { class: "act", type: "button", onClick: () => { S.editing = null; setDraft(""); renderComposer(); } }, "Abbrechen")));
  // Anhänge
  R.compAtt.innerHTML = "";
  if (S.attachments.length) R.compAtt.appendChild(h("div", { style: { display: "flex", gap: "6px", flexWrap: "wrap" } }, S.attachments.map((a, i) =>
    h("span", { class: "att" }, icon("file", 14), a.name, h("button", { class: "act", type: "button", "aria-label": a.name + " entfernen", style: { minHeight: "24px", minWidth: "24px", padding: 0 }, onClick: () => { S.attachments.splice(i, 1); renderComposer(); } }, icon("x", 14))))));
  // Vorlage
  R.compTpl.innerHTML = "";
  if (S.tpl) {
    const vars = templateVars(S.tpl.prompt);
    R.compTpl.appendChild(h("div", { class: "tplfields" }, h("span", { class: "badge" }, "Vorlage"), h("b", { class: "small" }, S.tpl.title),
      vars.map((v) => h("label", { class: "f", style: { minWidth: "140px" } }, v, h("input", { class: "inp", value: S.tplVars[v] || "", onInput: (e) => { S.tplVars[v] = e.target.value; } }))),
      h("button", { class: "act", type: "button", onClick: () => { S.tpl = null; renderComposer(); } }, "Vorlage entfernen")));
    R.ta.classList.toggle("hidden", true);
  } else R.ta.classList.toggle("hidden", false);
  R.ta.placeholder = S.chat && S.route.name === "chat" ? "Antworten …" : "Nachricht an Haus-KI. Enter sendet, Umschalt+Enter macht eine neue Zeile.";
  renderTools();
  renderComposerPop();
}
function renderTools() {
  const el = R.compTools;
  el.innerHTML = "";
  if (R.compFoot) R.compFoot.textContent = simple() ? "Tipp: Tippe / für alle Funktionen. Antworten können Fehler enthalten."
    : "Läuft lokal auf eurem Ollama-Server. Antworten können Fehler enthalten. Mit / findest du alle Funktionen.";
  const easy = simple();
  const f = S.me.features;
  const avail = SOURCES.filter(([k]) => f[k]);
  const on = avail.filter(([k]) => S.sources.has(k));
  const pop = (name) => () => { S.pop = S.pop === name ? null : name; renderComposerPop(); renderTools(); };
  el.append(
    h("button", { class: "ib", type: "button", "aria-label": "Anhang hinzufügen", "aria-expanded": S.pop === "attach" ? "true" : "false", onClick: pop("attach") }, icon("clip")),
    h("button", { class: "ib", type: "button", "aria-expanded": S.pop === "sources" ? "true" : "false", "aria-label": "Quellen: " + (on.map((x) => x[1]).join(", ") || "keine"), style: { fontSize: "14px" }, onClick: pop("sources") },
      icon("db"), h("span", { class: "hide-sm" }, on.length ? (on.length <= 2 ? on.map((x) => x[1].split(" ")[0]).join(", ") : `${on.length} Quellen`) : "Quellen")),
    easy ? null : h("button", { class: "ib", type: "button", "aria-expanded": S.pop === "style" ? "true" : "false", "aria-label": "Antwortstil", style: { fontSize: "14px" }, onClick: pop("style") },
      icon("sliders"), h("span", { class: "hide-sm" }, { genau: "Genau", ausgewogen: "Ausgewogen", kreativ: "Kreativ" }[S.style] + (S.think ? ", gründlich" : ""))),
    easy ? null : h("button", { class: "ib", type: "button", "aria-label": "Weitere Aktionen", "aria-expanded": S.pop === "more" ? "true" : "false", onClick: pop("more") }, icon("dots"), S.compare ? h("span", { class: "badge hide-sm" }, "Vergleich") : null),
    h("span", { class: "grow" }),
    easy && S.ctx && S.ctx.max && S.ctx.used / S.ctx.max >= 0.8 ? h("span", { class: "tiny", style: { color: "var(--warn)", marginRight: "6px" } }, `Chat zu ${Math.round((S.ctx.used / S.ctx.max) * 100)} % voll`) : null,
    !easy && S.ctx && S.ctx.max ? h("span", { class: "tiny hide-sm", style: { color: S.ctx.used / S.ctx.max >= 0.8 ? "var(--warn)" : "var(--muted)", fontVariantNumeric: "tabular-nums", fontFamily: "var(--mono)", marginRight: "6px" } }, `${fmtN(S.ctx.used)} / ${fmtN(S.ctx.max)} Token`) : null,
    window.HKVoice && !S.live ? window.HKVoice.micButton() : null,
    S.live ? h("button", { class: "send", type: "button", "aria-label": "Antwort stoppen", onClick: stop }, icon("stop")) :
      h("button", { class: "send", type: "button", "aria-label": "Senden", disabled: !(S.draft.trim() || S.attachments.length || S.tpl), onClick: send }, icon("send")));
}
function renderComposerPop() {
  const el = R.compPop;
  el.innerHTML = "";
  const box = (kids, width) => h("div", { class: "pop pad", style: { bottom: "100%", left: 0, marginBottom: "8px", width: width || "min(420px, 100%)" } }, kids);
  if (S.pop === "attach") {
    const fileIn = h("input", { type: "file", class: "hidden", multiple: true, accept: ".txt,.md,.csv,.log,.json,.py,.js,.ts,.html,.css,.xml,.yaml,.yml,.ini,.conf,.sh,text/*", onChange: (e) => { for (const f of e.target.files) addFile(f); } });
    const imgIn = h("input", { type: "file", class: "hidden", accept: "image/*", onChange: (e) => { for (const f of e.target.files) addFile(f); } });
    const plIn = h("input", { type: "file", class: "hidden", accept: "application/pdf,image/*", capture: "environment", onChange: (e) => { if (e.target.files[0]) paperlessUpload(e.target.files[0]); } });
    el.appendChild(h("div", { class: "pop", style: { bottom: "100%", left: 0, marginBottom: "8px", width: "min(360px,100%)" } }, fileIn, imgIn, plIn,
      h("button", { class: "menu-row", type: "button", onClick: () => fileIn.click() }, h("span", null, "Textdatei anhängen", h("small", null, "Logs, Code, Notizen"))),
      h("button", { class: "menu-row", type: "button", onClick: () => imgIn.click() }, h("span", null, "Bild anhängen", h("small", null, "Nur für Modelle mit Bilderkennung, z. B. gemma3"))),
      S.me.features.paperless_upload ? h("button", { class: "menu-row", type: "button", onClick: () => plIn.click() }, h("span", null, "Dokument in Paperless ablegen", h("small", null, "Foto oder PDF. Paperless erkennt den Text, Haus-KI schlägt Titel und Tags vor."))) : null));
  } else if (S.pop === "sources") {
    const avail = SOURCES.filter(([k]) => S.me.features[k]);
    el.appendChild(box([h("b", null, "Quellen für diese Frage"),
      avail.length ? avail.map(([k, l, help]) => toggle(l, S.sources.has(k), (v) => { v ? S.sources.add(k) : S.sources.delete(k); saveSources(); renderComposerPop(); renderTools(); }, help)) :
        h("p", { class: "small muted", style: { margin: 0 } }, "Für dich sind keine Quellen freigegeben. Haus-KI antwortet aus eigenem Wissen."),
      h("p", { class: "tiny muted", style: { margin: 0 } }, "Abgerufen wird nur aus eingeschalteten Quellen. Aktionen laufen nie ohne deine Bestätigung.")]));
  } else if (S.pop === "style") {
    const adv = S.advanced;
    el.appendChild(box([h("b", null, "Antwortstil"),
      seg([["genau", "Genau"], ["ausgewogen", "Ausgewogen"], ["kreativ", "Kreativ"]], S.style, (v) => { S.style = v; renderComposerPop(); renderTools(); }, "Antwortstil"),
      toggle("Gründlicher nachdenken", S.think, (v) => { S.think = v; renderComposerPop(); renderTools(); }, "Dauert länger, hilft bei Rechnen und Abwägen."),
      isAdmin() ? h("details", null, h("summary", { style: { cursor: "pointer", minHeight: "36px" } }, "Erweitert (nur Administratoren)"),
        h("div", { style: { display: "flex", flexDirection: "column", gap: "8px", paddingTop: "8px" } },
          h("label", { class: "f" }, "Systemanweisung für diese Frage", h("textarea", { class: "inp", rows: 3, value: adv.system || "", onInput: (e) => { adv.system = e.target.value; } })),
          h("div", { class: "grid2", style: { gridTemplateColumns: "repeat(3,1fr)", gap: "8px" } },
            h("label", { class: "f" }, "Temperatur", h("input", { class: "inp", type: "number", step: 0.1, min: 0, max: 2, value: adv.temperature ?? "", onInput: (e) => { adv.temperature = e.target.value === "" ? undefined : +e.target.value; } })),
            h("label", { class: "f" }, "Kontext", h("input", { class: "inp", type: "number", step: 1024, value: adv.num_ctx ?? "", onInput: (e) => { adv.num_ctx = e.target.value === "" ? undefined : +e.target.value; } })),
            h("label", { class: "f" }, "Max. Länge", h("input", { class: "inp", type: "number", step: 128, value: adv.num_predict ?? "", onInput: (e) => { adv.num_predict = e.target.value === "" ? undefined : +e.target.value; } }))),
          toggle("Antwort als JSON", !!adv.json, (v) => { adv.json = v; renderComposerPop(); }))) : null]));
  } else if (S.pop === "more") {
    el.appendChild(h("div", { class: "pop", style: { bottom: "100%", left: "120px", marginBottom: "8px", width: "280px" } },
      window.HKVoice && window.HKVoice.enabled() && S.me.voice && S.me.voice.talk ? h("button", { class: "menu-row", type: "button", onClick: () => { S.pop = null; renderComposerPop(); renderTools(); window.HKVoice.openTalk(); } },
        icon("wave"), h("span", null, "Gesprächsmodus", h("small", null, "Sprechen, zuhören, weitersprechen"))) : null,
      h("button", { class: "menu-row", type: "button", onClick: () => { S.pop = "schedule"; S.schedForm = { name: (S.tpl ? S.tpl.title : S.draft.split("\n")[0]).slice(0, 40), freq: "weekly", day: "Mo", time: "07:00", deliver: "notify" }; renderComposerPop(); } },
        icon("clock"), h("span", null, "Prompt planen", h("small", null, "Regelmäßig oder zu einer festen Zeit"))),
      isAdmin() ? h("button", { class: "menu-row", type: "button", onClick: () => { S.pop = "compare"; renderComposerPop(); } }, icon("cols"),
        h("span", null, S.compare ? "Vergleich: " + S.compare : "Mit zweitem Modell vergleichen", h("small", null, "Zwei Modelle antworten nebeneinander"))) : null));
  } else if (S.pop === "compare") {
    el.appendChild(box([h("b", null, "Zweites Modell zum Vergleich"),
      h("select", { class: "inp", "aria-label": "Zweites Modell", value: S.compare, onChange: (e) => { S.compare = e.target.value; S.pop = null; renderComposer(); } },
        h("option", { value: "" }, "Kein Vergleich"), (S.me.models || S.adminModels || []).filter((m) => m !== S.model).map((m) => h("option", { value: m, selected: m === S.compare }, m))),
      !S.me.models ? h("p", { class: "tiny muted", style: { margin: 0 } }, "Administratoren sehen alle Modelle aus Ollama.") : null]));
    if (!S.me.models && !S.adminModels) api("GET", "/api/admin/models").then((d) => { S.adminModels = d.models.map((m) => m.name); renderComposerPop(); });
  } else if (S.pop === "schedule") {
    const f = S.schedForm;
    const DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
    const prompt = S.tpl ? fillTemplate(S.tpl.prompt, S.tplVars) : S.draft;
    el.appendChild(box([h("b", null, "Prompt planen"),
      !prompt.trim() ? h("p", { class: "small", style: { color: "var(--warn)", margin: 0 } }, "Schreib zuerst den Prompt ins Eingabefeld oder wähle eine Vorlage.") : null,
      h("label", { class: "f" }, "Name", h("input", { class: "inp", value: f.name, onInput: (e) => { f.name = e.target.value; } })),
      h("div", null, h("div", { class: "tiny muted", style: { marginBottom: "6px" } }, "Wie oft"), seg([["once", "Einmalig"], ["daily", "Täglich"], ["weekly", "Wöchentlich"], ["monthly", "Monatlich"]], f.freq, (v) => { f.freq = v; renderComposerPop(); })),
      f.freq === "weekly" ? seg(DAYS.map((d) => [d, d]), f.day, (v) => { f.day = v; renderComposerPop(); }, "Wochentag") : null,
      h("div", { style: { display: "flex", gap: "12px", flexWrap: "wrap", alignItems: "flex-end" } },
        h("label", { class: "f", style: { width: "120px" } }, "Uhrzeit", h("input", { class: "inp", type: "time", value: f.time, onInput: (e) => { f.time = e.target.value; } })),
        h("div", null, h("div", { class: "tiny muted", style: { marginBottom: "6px" } }, "Ergebnis"), seg([["notify", "Benachrichtigen"], ["quiet", "Nur im Verlauf"]], f.deliver, (v) => { f.deliver = v; renderComposerPop(); }))),
      h("p", { class: "tiny muted", style: { margin: 0 } }, "Quellen und Antwortstil werden mitgespeichert. Ist Ollama gerade belegt, läuft der Prompt bis zu 30 Minuten später."),
      h("div", { style: { display: "flex", gap: "8px" } },
        h("button", { class: "btn", type: "button", disabled: !prompt.trim(), onClick: async () => {
          try { await api("POST", "/api/schedules", { ...f, prompt, options: { sources: [...S.sources], style: S.style, model: S.model } }); S.pop = null; renderComposerPop(); renderTools(); toast(`„${f.name}“ geplant. Du findest ihn unter Geplante Prompts im Benutzermenü.`); }
          catch (e) { toast(e.message, true); } } }, "Planen"),
        h("button", { class: "btn sec", type: "button", onClick: () => { S.pop = null; renderComposerPop(); } }, "Abbrechen"))]));
  }
}
function addFile(f) {
  const isImg = f.type.startsWith("image/");
  if (f.size > (isImg ? 8e6 : 2e6)) { toast(`${f.name} ist zu groß.`, true); return; }
  const r = new FileReader();
  r.onload = () => {
    if (isImg) S.attachments.push({ name: f.name, image: true, data: String(r.result).split(",")[1] });
    else S.attachments.push({ name: f.name, text: String(r.result) });
    S.pop = null; renderComposer();
  };
  isImg ? r.readAsDataURL(f) : r.readAsText(f);
}
async function paperlessUpload(file) {
  S.pop = null;
  const fd = new FormData();
  fd.append("file", file);
  if (S.route.name === "chat" && S.chat && !S.chat.readonly) fd.append("chat_id", S.chat.chat.id);
  try {
    const r = await api("POST", "/api/paperless/upload", fd);
    await loadChats();
    if (S.chat && S.chat.chat.id === r.chat_id) { S.chat = await api("GET", "/api/chats/" + r.chat_id); attachJob(r.job_id, r.chat_id); }
    else location.hash = "#chat/" + r.chat_id;
  } catch (e) { toast(e.message, true); }
}
function templateVars(p) { return [...new Set([...(p || "").matchAll(/\{\{\s*([\wäöüÄÖÜß ]+?)\s*\}\}/g)].map((m) => m[1]))]; }
function fillTemplate(p, vars) { return (p || "").replace(/\{\{\s*([\wäöüÄÖÜß ]+?)\s*\}\}/g, (_, k) => vars[k] || ""); }
function useTemplate(t) {
  const vars = templateVars(t.prompt);
  if (vars.length) { S.tpl = t; S.tplVars = {}; }
  else { S.tpl = null; setDraft(t.prompt); }
  if (t.model && (!S.me.models || S.me.models.includes(t.model))) S.model = t.model;
  S.sideOpen = false; applySideClasses();
  if (S.route.name !== "start" && S.route.name !== "chat") go("#start");
  renderComposer(); renderHead();
  if (!vars.length) R.ta.focus();
}
