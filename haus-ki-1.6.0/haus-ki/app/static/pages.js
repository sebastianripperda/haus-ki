/* Haus-KI – Hauptbereich: Startseite und Projekte. Teil der Oberfläche, die Dateien werden in fester Reihenfolge geladen (siehe index.html). */
"use strict";

// ------------------------------------------------------------------ Hauptbereich
function renderBody() {
  const el = R.body;
  const atBottom = S.stick !== false;
  el.innerHTML = "";
  if (S.route.name === "admin") { R.compWrap.classList.add("hidden"); return window.HKAdmin.render(el, S.route.id); }
  R.compWrap.classList.toggle("hidden", !!(S.chat && S.chat.readonly));
  const wrap = h("div", { class: "wrap" });
  el.appendChild(wrap);
  if (S.route.name === "project") renderProject(wrap);
  else if (S.route.name === "chat") renderChat(wrap);
  else renderStart(wrap);
  if (S.route.name === "chat" && atBottom) el.scrollTop = el.scrollHeight;
}

function renderStart(wrap) {
  const st = S.start || { suggestions: [], deadlines: [], calendar: [] };
  const hero = h("div", { class: "hero" }, h("div", { class: "wm", "aria-hidden": "true" }, "HAUS-KI"),
    h("div", null, h("div", { class: "over" }, "Hallo " + S.me.name),
      h("h1", { style: { marginTop: "8px" } }, "Frag deine Daten.", h("span", { class: "l2" }, "Lokal beantwortet.")),
      h("p", { style: { margin: "10px 0 0", color: "var(--soft)", maxWidth: "62ch" } }, "Paperless, Jellyfin, Haus, Microsoft 365 und Internet, beantwortet auf eurem Proxmox-Server.")));
  wrap.appendChild(hero);
  const sugg = st.suggestions.length ? st.suggestions.map((s) => ({ text: s.text, why: s.why, sources: s.sources || [] })) : fallbackSuggestions();
  hero.appendChild(h("section", { style: { display: "flex", flexDirection: "column", gap: "10px" } },
    h("div", null, h("h2", { style: { fontSize: "20px", fontWeight: 800 } }, st.suggestions.length ? "Für dich vorgeschlagen" : "Probier zum Beispiel"),
      st.suggestions.length ? h("p", { class: "tiny muted", style: { margin: "4px 0 0" } }, "Aus deinen letzten Chats, nachts erstellt. Nur du siehst sie.") : null),
    h("div", { class: "sug" }, sugg.slice(0, 4).map((s) => h("button", { type: "button", onClick: () => { setDraft(s.text); if (s.sources.length) { S.sources = new Set(s.sources.filter((x) => S.me.features[x])); saveSources(); } renderComposer(); R.ta.focus(); } },
      h("span", { class: "over" }, s.sources.map((x) => SRC_LABEL[x] || x).join(" + ") || "Allgemein"), h("span", { class: "q" }, s.text), s.why ? h("span", { class: "small muted" }, s.why) : null)))));
  // Im Blick
  const items = [];
  for (const c of st.calendar) items.push({ sort: c.when, when: c.when.slice(8, 10) + "." + c.when.slice(5, 7) + " " + c.when.slice(11, 16), kind: "Kalender", title: c.family, detail: `${c.user}: belegt ${c.busy}`, bg: "var(--badge-warn-bg)", fg: "var(--badge-warn-fg)",
    actions: [["Im Chat klären", () => { setDraft(`Am ${c.when.slice(8, 10)}.${c.when.slice(5, 7)}. um ${c.when.slice(11, 16)} ist „${c.family}“, und ${c.user} ist da belegt. Wie bekommen wir das hin?`); S.sources = new Set(["m365"].filter((x) => S.me.features[x])); renderComposer(); R.ta.focus(); }], ["Erledigt", () => doneInsight(c.id)]] });
  for (const d of st.deadlines) {
    const days = Math.round((new Date(d.due) - new Date(new Date().toDateString())) / 86400000);
    items.push({ sort: d.due, when: days <= 0 ? "heute" : days <= 14 ? `Frist ${days} T` : `Frist ${Math.round(days / 7)} Wo`, kind: "Frist", title: d.title, detail: d.doc || "", url: d.url,
      bg: days <= 7 ? "var(--errbg)" : days <= 14 ? "var(--badge-warn-bg)" : "var(--fill)", fg: days <= 7 ? "var(--err)" : days <= 14 ? "var(--badge-warn-fg)" : "var(--info)",
      actions: [["Erledigt", () => doneInsight(d.id)]] });
  }
  items.sort((a, b) => (a.sort < b.sort ? -1 : 1));
  if (items.length) {
    const shown = S.blickAll ? items : items.slice(0, 3);
    hero.appendChild(h("section", { class: "card blick-card", style: { padding: "14px 16px" } },
      h("div", { style: { display: "flex", justifyContent: "space-between", gap: "12px", flexWrap: "wrap", marginBottom: "6px" } }, h("h2", { style: { fontSize: "17px", fontWeight: 700 } }, "Im Blick"),
        h("span", { class: "tiny muted" }, "Fristen aus Paperless und Überschneidungen im Familienkalender")),
      shown.map((it) => h("div", { class: "blick-row" }, h("span", { class: "when", style: { background: it.bg, color: it.fg } }, it.when),
        h("span", { style: { flex: "1 1 auto", minWidth: 0 } }, it.url ? h("a", { class: "ell", href: it.url, target: "_blank", rel: "noopener", style: { display: "block", fontWeight: 600, color: "var(--text)" } }, it.title) : h("span", { class: "ell", style: { display: "block", fontWeight: 600 } }, it.title),
          h("span", { class: "ell tiny muted", style: { display: "block" } }, it.kind + (it.detail ? ": " + it.detail : ""))),
        it.actions.map(([l, fn]) => h("button", { class: "act", type: "button", style: { color: "var(--accent)", flex: "none" }, onClick: fn }, l)))),
      items.length > 3 ? h("button", { class: "act", type: "button", style: { color: "var(--accent)", marginLeft: "-10px" }, onClick: () => { S.blickAll = !S.blickAll; renderBody(); } }, S.blickAll ? "Weniger anzeigen" : `Alle ${items.length} anzeigen`) : null));
  }
  if (S.status && S.status.ollama && S.status.ollama.ok === false) wrap.prepend(stateBanner());
}
async function doneInsight(id) { await api("POST", `/api/insights/${id}/done`); loadStart(); }
function fallbackSuggestions() {
  const f = S.me.features, out = [];
  if (f.paperless) out.push({ text: "Was habe ich letztes Jahr für Strom bezahlt?", sources: ["paperless"] });
  if (f.m365) out.push({ text: "Was steht diese Woche im Kalender?", sources: ["m365"] });
  if (f.knx) out.push({ text: "Ist irgendwo ein Fenster offen, und wie warm ist es in den Zimmern?", sources: ["knx"] });
  if (f.jellyfin) out.push({ text: "Welchen Film könnten wir heute Abend schauen, höchstens zwei Stunden?", sources: ["jellyfin"] });
  out.push({ text: "Erkläre mir einfach, wie eine Wärmepumpe funktioniert.", sources: [] });
  out.push({ text: "Formuliere eine freundliche Erinnerung an die Hausverwaltung.", sources: [] });
  return out;
}
function stateBanner() {
  return h("div", { class: "banner note err", role: "status" }, h("span", { class: "status-dot off" }),
    h("span", { class: "grow" }, h("b", null, "Haus-KI kann gerade nicht antworten. "), "Ollama im Container reagiert nicht. Deine Nachricht wird gesendet, sobald Haus-KI wieder da ist."),
    isAdmin() ? h("button", { class: "btn sec", type: "button", onClick: async () => { try { await api("POST", "/api/admin/agent/restart"); toast("Ollama wird neu gestartet."); } catch (e) { toast(e.message, true); } } }, "Ollama neu starten") : null);
}

// ------------------------------------------------------------------ Projekte
async function newProject() {
  const t = await promptDialog("Neues Projekt", "Name, z. B. Gartenhaus", "");
  if (!t) return;
  const r = await api("POST", "/api/projects", { title: t });
  await loadProjects();
  go("#project/" + r.id);
}
function renderProject(wrap) {
  const p = S.projects.find((x) => x.id === S.route.id);
  if (!p) { wrap.appendChild(h("p", null, "Dieses Projekt gibt es nicht mehr.")); return; }
  const save = debounce((field, v) => api("PUT", "/api/projects/" + p.id, { [field]: v }).then(() => { p[field] = v; }), 600);
  const chats = S.chats.filter((c) => c.project_id === p.id);
  wrap.append(
    h("div", { class: "over" }, "Projekt"),
    h("input", { class: "inp", value: p.title, "aria-label": "Projektname", style: { fontSize: "30px", fontWeight: 800, border: 0, background: "transparent", padding: "4px 0", marginTop: "4px" }, onInput: (e) => save("title", e.target.value) }),
    h("input", { class: "inp", value: p.description, placeholder: "Worum geht es? (ein Satz)", "aria-label": "Beschreibung", style: { border: 0, background: "transparent", padding: "0", color: "var(--soft)" }, onInput: (e) => save("description", e.target.value) }),
    h("p", { class: "small muted" }, "Neue Fragen, die du hier stellst, landen automatisch in diesem Projekt."),
    h("div", { class: "grid2", style: { marginTop: "12px" } },
      h("label", { class: "f" }, "Notizen (fließen in jede Antwort ein)", h("textarea", { class: "inp", rows: 6, value: p.notes, onInput: (e) => save("notes", e.target.value) })),
      h("label", { class: "f" }, "Eigene Anweisung für dieses Projekt", h("textarea", { class: "inp", rows: 6, value: p.system, placeholder: "z. B. Antworte immer mit Kosten in einer Tabelle.", onInput: (e) => save("system", e.target.value) }))),
    S.me.features.paperless ? h("div", { class: "panel", style: { marginTop: "12px" } }, h("h3", null, "Angeheftete Dokumente"),
      p.docs.length ? p.docs.map((d, i) => h("div", { class: "list-row" }, icon("file"), h("span", { class: "grow" }, d.title, h("span", { class: "tiny muted" }, " · Paperless " + d.id)),
        h("button", { class: "act", type: "button", onClick: async () => { p.docs.splice(i, 1); await api("PUT", "/api/projects/" + p.id, { docs: p.docs }); renderBody(); } }, "Entfernen"))) : h("p", { class: "small muted", style: { margin: 0 } }, "Noch keine. Angeheftete Dokumente kann Haus-KI in jedem Chat dieses Projekts lesen."),
      h("button", { class: "btn sec", type: "button", style: { alignSelf: "flex-start" }, onClick: async () => {
        const id = await promptDialog("Dokument anheften", "Paperless-Dokument-ID (steht in der Adresse des Dokuments)", "");
        if (!id) return; const title = await promptDialog("Dokument anheften", "Kurzer Titel", "Dokument " + id);
        p.docs.push({ id: +id, title: title || "Dokument " + id }); await api("PUT", "/api/projects/" + p.id, { docs: p.docs }); renderBody(); } }, "Dokument anheften")) : null,
    h("div", { class: "group", style: { marginTop: "16px" } }, h("span", { class: "over" }, "Chats im Projekt"), chats.length ? chats.map((c) => chatRow(c)) : h("p", { class: "small muted" }, "Noch keine.")),
    h("button", { class: "act", type: "button", style: { color: "var(--err)", marginTop: "12px" }, onClick: async () => {
      if (!(await confirmDialog("Projekt löschen?", "Die Chats bleiben erhalten und wandern in den normalen Verlauf.", "Löschen"))) return;
      await api("DELETE", "/api/projects/" + p.id); await loadProjects(); await loadChats(); go("#start"); } }, "Projekt löschen"));
}
