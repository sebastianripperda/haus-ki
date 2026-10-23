/* Haus-KI – Administration und Modelle */
"use strict";
(function () {
  const { h, api, toast, toggle, seg, fmtN, fmtDate, fmtGB, av, confirmDialog, go } = window.HK;
  const A = { settings: null, dirty: {}, cache: {} };
  const NAV = [
    ["KI und Antworten", [["overview", "Übersicht"], ["requests", "Anfrage-Standards"], ["models", "Modelle"], ["profiles", "Modell-Profile"], ["quality", "Antwortqualität"], ["voice", "Sprache"]]],
    ["Anbindungen", [["sources", "Quellen"], ["knx", "Haus (KNX)"], ["m365", "Microsoft 365"]]],
    ["System", [["ollama", "Ollama-Server"], ["proxmox", "Proxmox"], ["backup", "Updates und Sicherung"]]],
    ["Menschen und Protokoll", [["users", "Benutzer"], ["audit", "Protokoll"]]],
  ];
  const TITLES = Object.fromEntries(NAV.flatMap((g) => g[1]));

  async function render(el, section) {
    if (!A.settings) {
      try { A.settings = await api("GET", "/api/admin/settings"); } catch (e) { el.textContent = e.message; return; }
    }
    const content = h("div", { class: "acontent" });
    el.appendChild(h("div", { class: "admin" },
      h("nav", { class: "anav", "aria-label": "Bereiche der Administration" }, NAV.map(([g, items]) => [h("div", { class: "over hide-sm", style: { padding: "12px 12px 4px" } }, g),
        items.map(([k, l]) => h("a", { href: k === "models" ? "#models" : "#admin/" + k, "aria-current": k === section ? "page" : null }, l))])),
      content));
    content.append(h("div", { class: "over" }, "Administration"), h("h1", null, TITLES[section] || "Übersicht"));
    const fn = SECTIONS[section] || SECTIONS.overview;
    try { await fn(content); } catch (e) { content.appendChild(h("div", { class: "note err" }, e.message)); }
  }
  const val = (k) => (k in A.dirty ? A.dirty[k] : A.settings.values[k]);
  const isSecret = (k) => A.settings.secrets.includes(k);

  // Generisches Formular. Felder: [key, label, type, help, options]
  function form(title, fields, opts = {}) {
    const panel = h("section", { class: "panel" }, title ? h("h3", null, title) : null, opts.intro ? h("p", { class: "small muted", style: { margin: 0 } }, opts.intro) : null);
    const body = h("div", { style: { display: "flex", flexDirection: "column", gap: "4px" } });
    const draw = () => {
      body.innerHTML = "";
      for (const [key, label, type, help, options] of fields) {
        const v = val(key);
        const set = (x) => { A.dirty[key] = x; if (type === "toggle" || type === "seg") draw(); };
        if (type === "hidden") continue;
        if (type === "toggle") { body.appendChild(toggle(label, !!v, set, help)); continue; }
        if (type === "seg") { body.appendChild(h("div", { style: { padding: "8px 0" } }, h("div", { class: "small muted", style: { marginBottom: "6px" } }, label), seg(options, v, set), help ? h("div", { class: "tiny muted", style: { marginTop: "4px" } }, help) : null)); continue; }
        let input;
        const id = "f_" + key.replace(/\W/g, "_");
        if (type === "select") input = h("select", { class: "inp", id, onChange: (e) => set(e.target.value) }, options.map(([o, l]) => h("option", { value: o, selected: String(v) === String(o) }, l)));
        else if (type === "textarea") input = h("textarea", { class: "inp", id, rows: 4, value: Array.isArray(v) ? v.join("\n") : v || "", onInput: (e) => set(options === "lines" ? e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) : e.target.value) });
        else if (isSecret(key)) input = h("input", { class: "inp", id, type: "password", autocomplete: "new-password", placeholder: v && v.set ? "•••••••• (gespeichert, leer lassen = unverändert)" : "nicht gesetzt", onInput: (e) => set(e.target.value || null) });
        else if (type === "list") input = h("input", { class: "inp", id, value: (v || []).join(", "), onInput: (e) => set(e.target.value.split(",").map((s) => s.trim()).filter(Boolean)) });
        else input = h("input", { class: "inp", id, type: type === "number" ? "number" : "text", step: type === "number" ? "any" : null, value: v ?? "", onInput: (e) => set(type === "number" ? (e.target.value === "" ? "" : +e.target.value) : e.target.value) });
        body.appendChild(h("label", { class: "f", for: id, style: { padding: "6px 0" } }, label, input, help ? h("span", { class: "h" }, help) : null));
      }
    };
    draw();
    if (opts.top) panel.appendChild(opts.top);
    panel.appendChild(body);
    const row = h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center" } },
      h("button", { class: "btn", type: "button", onClick: () => saveFields(fields.map((f) => f[0])) }, "Speichern"));
    if (opts.test) {
      const out = h("span", { class: "small", role: "status" });
      row.append(h("button", { class: "btn sec", type: "button", onClick: async () => {
        await saveFields(fields.map((f) => f[0]), true);
        out.textContent = "Prüfe …"; out.style.color = "var(--muted)";
        const r = await api("POST", "/api/admin/test/" + opts.test);
        out.textContent = r.text; out.style.color = r.ok ? "var(--ok)" : "var(--err)";
        if (opts.onTest) opts.onTest(r);
      } }, "Verbindung testen"), out);
    }
    panel.appendChild(row);
    if (opts.extra) panel.appendChild(opts.extra);
    return panel;
  }
  async function saveFields(keys, quiet) {
    const body = {};
    for (const k of keys) if (k in A.dirty) body[k] = A.dirty[k];
    if (!Object.keys(body).length) { if (!quiet) toast("Nichts geändert."); return; }
    try {
      await api("PUT", "/api/admin/settings", body);
      for (const k of Object.keys(body)) delete A.dirty[k];
      A.settings = await api("GET", "/api/admin/settings");
      if (!quiet) toast("Gespeichert.");
    } catch (e) { toast(e.message, true); }
  }
  const rerender = () => window.HK.renderBody();

  function voiceList(d) {
    const box = h("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } });
    box.appendChild(h("div", { class: "small muted" }, "Installierte Stimmen"));
    if (!d.voices.length) box.appendChild(h("p", { class: "tiny muted", style: { margin: 0 } }, "Noch keine. Die Standardstimme wird beim ersten Vorlesen oder mit „Modelle jetzt laden“ heruntergeladen."));
    for (const v of d.voices) box.appendChild(h("div", { class: "list-row" }, h("span", { class: "grow" }, h("b", null, v.name), h("span", { class: "tiny muted mono" }, "  " + v.id)),
      v.id === d.default_voice ? h("span", { class: "badge" }, "Standard") : null));
    const missing = d.known.filter((k) => !d.voices.some((v) => v.id === k.id));
    if (missing.length) box.appendChild(h("div", { class: "follow" }, missing.map((k) => h("button", { class: "chip", type: "button", onClick: async (e) => {
      e.target.textContent = "Lädt …";
      try { await api("POST", "/api/admin/voice/install", { id: k.id }); toast(`Stimme ${k.name} installiert.`); rerender(); } catch (err) { toast(err.message, true); e.target.textContent = `${k.name} installieren`; } } }, `${k.name} installieren`))));
    const cat = h("button", { class: "btn sec", type: "button", style: { alignSelf: "flex-start" }, onClick: async () => {
      cat.textContent = "Katalog wird geladen …";
      try {
        const list = await api("GET", "/api/admin/voice/catalog");
        const sel = h("select", { class: "inp", "aria-label": "Weitere deutsche Stimmen" }, list.map((x) => h("option", { value: x.id, "data-path": x.path }, `${x.id} (${x.quality}, ${fmtN(x.size / 1e6, 0)} MB)`)));
        const btn = h("button", { class: "btn", type: "button", onClick: async () => { const o = sel.selectedOptions[0]; btn.textContent = "Lädt …";
          try { await api("POST", "/api/admin/voice/install", { id: o.value, path: o.dataset.path }); toast("Stimme installiert."); rerender(); } catch (err) { toast(err.message, true); btn.textContent = "Installieren"; } } }, "Installieren");
        cat.replaceWith(h("div", { style: { display: "flex", gap: "8px" } }, sel, btn));
      } catch (err) { toast(err.message, true); cat.textContent = "Weitere Stimme herunterladen"; }
    } }, "Weitere Stimme herunterladen");
    box.appendChild(cat);
    return box;
  }

  async function comparePanel() {
    const runs = await api("GET", "/api/admin/quality/compare");
    let models = [];
    try { models = (await api("GET", "/api/admin/models")).models.map((m) => m.name); } catch (e) { /* Ollama nicht erreichbar */ }
    const selA = h("select", { class: "inp", "aria-label": "Modell A" }, models.map((m) => h("option", { value: m, selected: m === window.HK.S.me.default_model ? "selected" : null }, m)));
    const def = window.HK.S.me.default_model;
    const pickB = models.find((m) => m !== def && /30b|20b|14b/.test(m)) || models.find((m) => m !== def);
    const selB = h("select", { class: "inp", "aria-label": "Modell B" }, models.map((m) => h("option", { value: m, selected: m === pickB ? "selected" : null }, m)));
    let set = "standard";
    const setBox = h("div");
    const drawSet = () => { setBox.innerHTML = ""; setBox.appendChild(seg([["standard", "6 Standardfragen"], ["bad", "Schlecht bewertete (bis 10)"]], set, (v) => { set = v; drawSet(); }, "Fragen")); };
    drawSet();
    return h("section", { class: "panel" }, h("h3", null, "Modelle vergleichen"),
      h("p", { class: "small muted", style: { margin: 0 } }, "Dieselben Fragen an zwei Modelle, Antworten nebeneinander mit Zeit und Tempo. Läuft im Hintergrund hinter allen Fragen der Familie. Bewerte die Antworten in den Testchats mit dem Daumen, das Ergebnis erscheint hier."),
      h("div", { class: "note" }, h("b", null, "Für eure Ausstattung (nur CPU, viel RAM) lohnen sich MoE-Modelle: "), "Sie haben viel Wissen, rechnen pro Wort aber nur einen kleinen Teil. ",
        h("span", { class: "mono" }, "qwen3:30b-a3b"), " (etwa 19 GB) ist auf der CPU ähnlich schnell wie qwen3:8b und antwortet meist besser, ", h("span", { class: "mono" }, "gpt-oss:20b"),
        " (etwa 14 GB) ist stark bei Werkzeugen. Laden unter Modelle, dann hier vergleichen."),
      models.length < 2 ? h("div", { class: "note warn" }, models.length ? "Für einen Vergleich braucht es mindestens zwei Modelle. Lade ein zweites unter Modelle." : "Ollama ist gerade nicht erreichbar.") :
        h("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: "8px" } }, h("label", { class: "f" }, "Modell A", selA), h("label", { class: "f" }, "Modell B", selB)),
      setBox,
      h("button", { class: "btn", type: "button", style: { alignSelf: "flex-start" }, onClick: async () => {
        try { const r = await api("POST", "/api/admin/quality/compare", { model_a: selA.value, model_b: selB.value, set }); toast(`${r.questions} Testchats angelegt. Die Antworten kommen nach und nach.`); await window.HK.loadChats(); rerender(); }
        catch (e) { toast(e.message, true); } } }, "Vergleich starten"),
      runs.length ? h("div", { class: "tablewrap" }, h("table", { class: "t" },
        h("thead", null, h("tr", null, ["Lauf", "Modell", "Antworten", "Ø Dauer", "Ø Tempo", "👍 / 👎"].map((x) => h("th", null, x)))),
        h("tbody", null, runs.flatMap((r) => r.models.map((m, i) => h("tr", null,
          h("td", { class: "small" }, i === 0 ? `${fmtDate(r.started)} · ${r.done} von ${r.n} fertig` : ""),
          h("td", { class: "mono" }, m.model), h("td", { class: "mono" }, `${m.answers}`),
          h("td", { class: "mono" }, m.answers ? `${fmtN(m.avg_seconds, 1)} s` : "–"), h("td", { class: "mono" }, m.answers ? `${fmtN(m.avg_tps, 1)} Token/s` : "–"),
          h("td", { class: "mono" }, `${m.up} / ${m.down}`))))))) : null,
      runs.length ? h("p", { class: "tiny muted", style: { margin: 0 } }, "Die Testchats stehen in deiner Seitenleiste unter „Vergleich: …“.") : null);
  }

  function autoPanel() {
    const CATS = [["knx_light", "Licht schalten und dimmen", "Erkannt am Namen der Gruppenadresse, z. B. „Licht“, „Lampe“, „Spot“."],
      ["knx_blind", "Rollläden und Jalousien", "Erkannt an „Rollladen“, „Jalousie“, „Raffstore“, „Markise“."],
      ["knx_climate", "Heizung: Solltemperatur", "Nur Sollwerte (DPT 9.001) mit „Soll“, „Temperatur“ oder „Heizung“ im Namen."],
      ["jellyfin_play", "Filme und Musik abspielen", "Startet die Wiedergabe auf einem Jellyfin-Gerät."],
      ["todo_add", "Einträge in To Do anlegen", "Zum Beispiel die Einkaufsliste aus dem Wochenplan."]];
    const cur = new Set(val("actions.auto_allowed") || []);
    const box = h("section", { class: "panel" }, h("h3", null, "Ohne Rückfrage erlaubt"),
      h("p", { class: "small muted", style: { margin: 0 } }, "Was hier erlaubt ist, kann jede Person mit der Freigabe „Harmloses ohne Rückfrage“ unter „Einstellungen für mich“ für sich einschalten. Haustür, Garage, Alarm, Mails, Entwürfe und Paperless fragen immer nach. Nach Webinhalten gibt es nie Aktionen."));
    for (const [id, label, help] of CATS) box.appendChild(toggle(label, cur.has(id), async (v) => {
      if (v) cur.add(id); else cur.delete(id);
      await api("PUT", "/api/admin/settings", { "actions.auto_allowed": [...cur] });
      A.settings = null; toast("Gespeichert."); rerender();
    }, help));
    return box;
  }

  const SECTIONS = {
    // ------------------------------------------------------------ Übersicht
    async overview(c) {
      const o = await api("GET", "/api/admin/overview");
      const vm = o.vm && !o.vm.error ? o.vm : null;
      const maxQ = Math.max(1, ...o.usage.map((u) => u.questions));
      c.append(
        h("div", { class: "grid2" },
          h("div", { class: "panel" }, h("h3", null, "Dienste"),
            h("div", { style: { display: "flex", gap: "8px", alignItems: "center" } }, h("span", { class: "status-dot" + (o.ollama.ok === false ? " off" : o.ollama.ok ? "" : " unk") }), `Ollama ${o.ollama.version || ""}`, h("span", { class: "tiny muted" }, o.ollama.ok === false ? "antwortet nicht" : "läuft")),
            h("div", { class: "small muted" }, `Haus-KI ${o.version}`),
            h("div", { class: "small" }, o.queue.running.length ? `Rechnet: ${o.queue.running.map((r) => r.label).join(", ")}` : "Gerade nichts in Arbeit.", o.queue.waiting ? `, ${o.queue.waiting} warten` : "")),
          h("div", { class: "panel" }, h("h3", null, "Ollama-Container"),
            vm ? [h("div", { class: "small" }, `CPU ${vm.cpu} % von ${vm.cpus} Kernen`), h("div", { class: "bar" }, h("span", { style: { width: vm.cpu + "%" } })),
              h("div", { class: "small" }, `RAM ${fmtGB(vm.mem)} von ${fmtGB(vm.maxmem)}`), h("div", { class: "bar" }, h("span", { style: { width: Math.round((vm.mem / vm.maxmem) * 100) + "%" } }))] :
              h("p", { class: "small muted", style: { margin: 0 } }, o.vm && o.vm.error ? o.vm.error : "Proxmox ist nicht verbunden."))),
        o.warnings.length ? h("div", { class: "panel" }, h("h3", null, "Hinweise"), o.warnings.map((w) => h("div", { class: "note warn" }, w))) : null,
        h("div", { class: "panel" }, h("h3", null, "Nutzung, letzte 30 Tage"),
          o.usage.map((u) => h("div", { style: { display: "grid", gridTemplateColumns: "32px 100px 1fr 60px", gap: "10px", alignItems: "center" } }, av({ ...u, initial: u.name[0] }), h("span", null, u.name),
            h("span", { class: "bar" }, h("span", { style: { width: (u.questions / maxQ) * 100 + "%" } })), h("span", { class: "small", style: { textAlign: "right" } }, fmtN(u.questions))))),
        h("div", { class: "panel" },
          h("div", { style: { display: "flex", justifyContent: "space-between", gap: "12px", flexWrap: "wrap", alignItems: "baseline" } }, h("h3", null, "Nachtplan" + (o.night.date ? `, Nacht zum ${o.night.date.split("-").reverse().join(".")}` : "")),
            h("button", { class: "btn sec", type: "button", onClick: async () => { await api("POST", "/api/admin/night/run"); toast("Nachtplan gestartet. Die Aufgaben laufen nacheinander."); } }, "Jetzt ausführen")),
          h("p", { class: "small muted", style: { margin: 0 } }, `Startet um ${A.settings.values["night.start"]} Uhr. Die Aufgaben laufen nacheinander, damit sich die CPU nicht verzettelt. Fragen haben immer Vorrang.`),
          o.night.runs.length ? h("div", { class: "tablewrap" }, h("table", { class: "t" }, h("thead", null, h("tr", null, ["Start", "Aufgabe", "Dauer", "Ergebnis"].map((x) => h("th", null, x)))),
            h("tbody", null, o.night.runs.map((r) => h("tr", null, h("td", null, new Date(r.started * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })), h("td", null, r.task),
              h("td", null, r.finished ? Math.max(1, Math.round((r.finished - r.started) / 60)) + " Min" : "läuft"), h("td", { style: { color: r.status === "error" ? "var(--err)" : null } }, r.detail || r.status)))))) : h("p", { class: "small muted", style: { margin: 0 } }, "Noch kein Lauf.")),
        h("div", { class: "grid2" },
          h("div", { class: "panel" }, h("h3", null, "Bewertungen, letzte 30 Tage"), h("div", { style: { display: "flex", gap: "24px" } },
            h("div", null, h("div", { class: "tiny muted" }, "Daumen hoch"), h("b", { style: { fontSize: "24px", color: "var(--ok)" } }, o.feedback.up)),
            h("div", null, h("div", { class: "tiny muted" }, "Daumen runter"), h("b", { style: { fontSize: "24px", color: "var(--err)" } }, o.feedback.down))),
            o.feedback.worst.length ? [h("div", { class: "tiny muted" }, "Am häufigsten schlecht bewertet"), o.feedback.worst.map((w) => h("div", { class: "small" }, `${w.title} (${w.n})`))] : null),
          h("div", { class: "panel" }, h("h3", null, "Fehler, letzte 30 Tage"), o.errors.length ? o.errors.map((e) => h("div", { class: "small" }, h("span", { class: "muted" }, fmtDate(e.ts) + " "), e.text)) : h("p", { class: "small muted", style: { margin: 0 } }, "Keine."))));
    },
    // ------------------------------------------------------------ Antwortqualität
    async quality(c) {
      const q = await api("GET", "/api/admin/quality");
      const sem = q.semantic;
      c.append(h("p", { class: "muted", style: { margin: 0, maxWidth: "72ch" } }, "Wo Antworten schiefgehen: Werkzeugfehler, schlecht bewertete Antworten und der Stand der Paperless-Suche. Letzte 30 Tage."),
        h("div", { class: "grid2", style: { gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))" } },
          [["Schlecht bewertet", String(q.bad.length), "Antworten mit Daumen runter", "var(--accent)"],
           ["Werkzeugaufrufe", String(q.tools.reduce((a, t) => a + t.calls, 0)), `${q.tools.reduce((a, t) => a + (t.errors || 0), 0)} davon fehlgeschlagen`, "var(--primary)"],
           ["An schnelles Modell", String(q.routed), "einfache Fragen", "var(--primary)"],
           ["Paperless-Index", String(sem.docs), `Dokumente, ${sem.chunks} Abschnitte`, sem.docs ? "var(--ok)" : "var(--warn)"]]
            .map(([l, v, sub, top]) => h("div", { style: { background: "var(--fill)", borderTop: `3px solid ${top}`, padding: "12px 14px", display: "flex", flexDirection: "column", gap: "2px" } },
              h("span", { class: "small muted" }, l), h("span", { class: "mono", style: { fontSize: "20px" } }, v), h("span", { class: "tiny muted" }, sub)))),
        h("section", { class: "panel" }, h("h3", null, "Werkzeuge"),
          q.tools.length ? h("div", { class: "tablewrap" }, h("table", { class: "t" }, h("thead", null, h("tr", null, ["Werkzeug", "Aufrufe", "Fehler", "Ø Dauer", "Letzter Fehler"].map((x) => h("th", null, x)))),
            h("tbody", null, q.tools.map((t) => h("tr", null, h("td", { class: "mono" }, t.tool), h("td", { class: "mono" }, t.calls),
              h("td", { class: "mono", style: { color: t.errors ? "var(--err)" : null } }, `${t.errors || 0} (${Math.round(((t.errors || 0) / t.calls) * 100)} %)`),
              h("td", { class: "mono" }, `${fmtN(t.avg_ms / 1000, 1)} s`), h("td", { class: "small" }, t.last_error ? `${t.last_error}${t.last_model ? " · " + t.last_model : ""}` : "–")))))) :
            h("p", { class: "small muted", style: { margin: 0 } }, "Noch keine Werkzeugaufrufe."),
          h("p", { class: "tiny muted", style: { margin: 0 } }, "Viele Fehler bei einem Werkzeug deuten meist auf ein zu kleines Modell oder eine nicht erreichbare Quelle hin.")),
        h("section", { class: "panel" }, h("div", { style: { display: "flex", justifyContent: "space-between", gap: "12px", flexWrap: "wrap", alignItems: "baseline" } },
            h("h3", null, "Schlecht bewertete Antworten"), h("a", { class: "btn sec", href: "/api/admin/quality/export" }, "Als Testliste exportieren")),
          q.bad.length ? q.bad.map((b) => h("div", { style: { borderTop: "1px solid var(--row)", padding: "10px 0", display: "flex", flexDirection: "column", gap: "4px" } },
            h("div", { class: "tiny muted" }, `${fmtDate(b.created)} · ${b.user} · ${b.model}${b.routed ? " (schnelles Modell)" : ""}${b.sources.length ? " · " + b.sources.join(", ") : ""}`),
            h("b", null, b.question || "(Frage nicht mehr vorhanden)"),
            b.comment ? h("div", { class: "note warn" }, b.comment) : null,
            h("details", null, h("summary", { class: "small", style: { cursor: "pointer" } }, "Antwort anzeigen"), h("div", { class: "md small", html: MD.render(b.answer) })),
            h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" } },
              h("a", { class: "act", href: "#chat/" + b.chat_id }, "Chat öffnen"),
              h("button", { class: "act", type: "button", style: { color: "var(--accent)" }, onClick: async () => { const r = await api("POST", `/api/admin/quality/rerun/${b.message_id}`); await window.HK.loadChats(); go("#chat/" + r.chat_id); } }, "Mit heutigen Einstellungen erneut testen")))) :
            h("p", { class: "small muted", style: { margin: 0 } }, "Keine. Antworten bewertet die Familie mit dem Daumen unter jeder Antwort.")),
        h("section", { class: "panel" }, h("h3", null, "Paperless-Suche nach Bedeutung"),
          h("p", { class: "small", style: { margin: 0 } }, sem.enabled ? `${sem.docs} Dokumente in ${sem.chunks} Abschnitten indiziert, Modell ${sem.model}. ${sem.since ? "Zuletzt aktualisiert " + sem.since.replace("T", " ") + "." : "Noch kein Lauf."}` : "Ausgeschaltet. Einschalten unter Quellen › Paperless."),
          h("p", { class: "tiny muted", style: { margin: 0 } }, "Der Index wird nachts im Nachtplan ergänzt. Der erste Aufbau dauert je nach Anzahl der Dokumente einige Minuten. Treffer werden immer mit den Paperless-Rechten der fragenden Person geprüft."),
          sem.enabled ? h("button", { class: "btn sec", type: "button", style: { alignSelf: "flex-start" }, onClick: async () => { await api("POST", "/api/admin/semantic/rebuild"); toast("Der Index wird neu aufgebaut. Fortschritt im Nachtplan in der Übersicht."); } }, "Index jetzt neu aufbauen") : null),
        await comparePanel(),
        form("Suche in alten Chats", [
          ["history.semantic", "Frühere Chats nach Bedeutung durchsuchbar machen", "toggle", "„Was hatten wir letztes Mal zum Gartenhaus besprochen?“ Jede Person findet dabei nur ihre eigenen Chats, auch Administratoren nicht die anderer. Gelöschte Chats verschwinden aus dem Index."]],
          { intro: `${q.history.answers} Antworten im Index. Neue Antworten kommen sofort dazu, wenn Ollama gerade frei ist, sonst im Nachtplan.` }));
    },
    // ------------------------------------------------------------ Sprache
    async voice(c) {
      const d = await api("GET", "/api/admin/voice");
      const tile = (label, value, sub, top) => h("div", { style: { background: "var(--fill)", borderTop: `3px solid ${top}`, padding: "12px 14px", display: "flex", flexDirection: "column", gap: "2px", minWidth: 0 } },
        h("span", { class: "small muted" }, label), h("span", { class: "mono", style: { fontSize: "20px" } }, value), h("span", { class: "tiny muted" }, sub));
      c.append(
        h("p", { class: "muted", style: { margin: 0, maxWidth: "72ch" } }, "Spracheingabe mit Whisper, Vorlesen mit Piper. Beides läuft im Haus-KI-Container auf der CPU, kein Ton verlässt das Haus."),
        h("div", { class: "grid2", style: { gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))" } },
          tile("Spracherkennung", d.stt_model, d.loaded ? "geladen" : d.stt_ready ? "bereit, wird bei Bedarf geladen" : d.prefetch === "läuft" ? "wird heruntergeladen …" : "noch nicht heruntergeladen", d.stt_ready || d.loaded ? "var(--ok)" : "var(--warn)"),
          tile("Stimmen", String(d.voices.length), d.voices.length ? d.voices.map((x) => x.name).join(", ") : "noch keine installiert", "var(--primary)"),
          tile("Heute", String(d.stats.stt_count), `Spracheingaben, Ø ${fmtN(d.stats.stt_avg, 1)} s`, "var(--primary)"),
          tile("Vorgelesen heute", `${fmtN(d.stats.tts_minutes, 1)} Min`, `Ø ${fmtN(d.stats.tts_avg, 1)} s bis zum Ton`, "var(--line2)")),
        d.error ? h("div", { class: "note err" }, "Die Sprachmodelle konnten nicht geladen werden: " + d.error) : null,
        d.resources && (d.resources.cpus < 4 || d.resources.mem < 3.5e9) ? h("div", { class: "note warn" },
          `Der Haus-KI-Container hat ${d.resources.cpus} ${d.resources.cpus === 1 ? "Kern" : "Kerne"} und ${fmtGB(d.resources.mem)} RAM. Für Whisper „small“ empfehle ich 4 Kerne und 4 GB. Auf dem Proxmox-Host: `,
          h("code", null, `pct set <ID> --cores 4 --memory 4096`), ", danach den Container neu starten.") : null,
        h("button", { class: "btn sec", type: "button", style: { alignSelf: "flex-start" }, onClick: async () => { await api("POST", "/api/admin/voice/prepare"); toast("Modelle werden geladen. Das dauert je nach Leitung ein bis zwei Minuten."); setTimeout(rerender, 4000); } }, "Modelle jetzt laden"));
      const models = h("div", { class: "grid2", style: { gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: "8px" } },
        Object.entries(d.models).map(([k, m]) => {
          const on = val("voice.stt_model") === k;
          return h("button", { type: "button", "aria-pressed": on ? "true" : "false", onClick: () => { A.dirty["voice.stt_model"] = k; rerender(); },
            style: { textAlign: "left", border: `1px solid ${on ? "var(--primary)" : "var(--line)"}`, background: on ? "var(--fill)" : "var(--card)", borderRadius: "var(--r)", padding: "10px 12px", display: "flex", flexDirection: "column", gap: "2px", color: "var(--text)" } },
            h("b", { class: "mono" }, k), h("span", { class: "tiny muted" }, m.size), h("span", { class: "tiny" }, m.speed),
            h("span", { class: "tiny", style: { color: k === "small" ? "var(--ok)" : k === "tiny" ? "var(--err)" : "var(--warn)" } }, m.quality));
        }));
      c.append(form("Spracherkennung (Whisper)", [
        ["voice.enabled", "Sprache für die Familie einschalten", "toggle", "Pro Person zusätzlich unter Benutzer freigeben."],
        ["voice.threads", "Rechenkerne", "seg", "Mehr Kerne erkennen schneller, nehmen aber Ollama Rechenzeit weg.", [[2, "2"], [4, "4"], [8, "8"]]],
        ["voice.keep_loaded", "Modell dauerhaft im Speicher halten", "toggle", "Spart bei jeder Eingabe etwa 3 Sekunden, belegt aber dauerhaft RAM."],
        ["voice.vad", "Ende der Frage automatisch erkennen", "toggle", "Nach etwa einer Sekunde Stille ist die Aufnahme beendet. Sonst Knopf zum Beenden."],
        ["voice.stt_model", "", "hidden"],
      ], { top: h("div", null, h("div", { class: "small muted", style: { margin: "6px 0" } }, "Modell"), models,
        h("p", { class: "tiny muted" }, "Zeiten für einen Satz von etwa 5 Sekunden auf 4 Kernen. Für Deutsch empfehle ich „small“. Ein Wechsel lädt das neue Modell beim nächsten Mal herunter.")) }),
        form("Sprachausgabe (Piper)", [
          ["voice.default_voice", "Standardstimme", "select", "Gilt, bis eine Person unter „Sprache“ eine eigene wählt.", (d.voices.length ? d.voices : d.known).map((x) => [x.id, `${x.name} (${x.id})`])],
          ["voice.skip_cites", "Quellenverweise überspringen", "toggle", "[1], [2] und Links werden nicht vorgelesen, Tabellen nur zusammengefasst."],
          ["voice.numbers", "Zahlen und Beträge ausschreiben", "toggle", "„1.184,20 €“ wird als „eintausendeinhundertvierundachtzig Euro zwanzig“ gelesen."],
        ], { extra: voiceList(d) }),
        form("Gesprächsmodus und Aktionen", [
          ["voice.talk", "Gesprächsmodus erlauben", "toggle", "Zuhören, antworten, wieder zuhören. Der Verlauf erscheint als normaler Chat."],
          ["voice.confirm", "Aktionen per Sprache bestätigen", "toggle", "Haus-KI wiederholt die Aktion und schaltet erst bei einem deutlich erkannten „Ja“. Bei Unsicherheit fragt es nach oder zeigt den Knopf."],
        ]),
        h("section", { class: "panel", style: { background: "var(--fill)", borderTop: "3px solid var(--accent)" } }, h("h3", null, "Feste Regeln"),
          ["Aufnahmen werden nur im Arbeitsspeicher verarbeitet und nie gespeichert, auch nicht im Protokoll.",
           "Das Mikrofon funktioniert nur über HTTPS mit vertrautem Zertifikat (/ca.crt auf dem Gerät installieren).",
           "Haustür, Garagentor und Alarmanlage lassen sich auch per Sprache nicht schalten. Per Sprache bestätigte Aktionen stehen mit Vermerk im Protokoll."]
            .map((t) => h("div", { class: "small", style: { display: "flex", gap: "8px" } }, window.HK.icon("lock", 16), t))));
    },
    // ------------------------------------------------------------ Anfrage-Standards
    async requests(c) {
      c.append(form("Standardwerte für jede Anfrage", [
        ["req.temperature", "Temperatur", "number", "0 = sehr genau, 1 = kreativ. Standard 0,6."],
        ["req.top_p", "Top-P", "number"], ["req.top_k", "Top-K", "number"], ["req.repeat_penalty", "Wiederholungsstrafe", "number"],
        ["req.num_ctx", "Kontextlänge (Token)", "number", "Mehr Kontext braucht mehr RAM. Für qwen3:8b auf 16 GB sind 8192 ein guter Wert."],
        ["req.num_predict", "Maximale Antwortlänge (Token)", "number"], ["req.seed", "Seed (0 = zufällig)", "number"],
        ["req.think", "Gründlich nachdenken als Standard", "toggle", "Nur für Modelle, die das können (qwen3). Antworten dauern deutlich länger."],
        ["req.keep_alive", "Modell im Speicher halten", "select", "Wie lange ein Modell nach der letzten Anfrage geladen bleibt.", [["-1", "Dauerhaft"], ["30m", "30 Minuten"], ["5m", "5 Minuten"], ["0", "Sofort entladen"]]],
        ["req.num_thread", "CPU-Threads (0 = automatisch)", "number", "Bei 8 Kernen meist 0 oder 8."],
      ]), form("Verbindung und Warteschlange", [
        ["ollama.url", "Adresse von Ollama", "text", "z. B. http://192.168.1.20:11434"],
        ["ollama.parallel", "Gleichzeitige Anfragen", "number", "Auf der CPU ist 1 am schnellsten. Änderung wirkt nach einem Neustart von Haus-KI."],
        ["chat.followups", "Folgefragen vorschlagen", "toggle", "Nach jeder Antwort erzeugt das Hilfsmodell zwei Weiterfragen, aber nur, wenn niemand wartet."],
      ], { test: "ollama" }), form("Einfache Fragen schneller beantworten", [
        ["ollama.route_simple", "Kurze Hausbefehle an ein schnelles Modell geben", "toggle", "„Mach das Licht an“, „Wie warm ist es?“ oder „Danke“ gehen an das schnelle Modell, alles andere an das Standardmodell. Nur bei kurzen Fragen am Anfang eines Chats."],
        ["ollama.fast_model", "Schnelles Modell", "text", "Leer = Hilfsmodell. Empfohlen: qwen3:4b, das Werkzeuge zuverlässiger nutzt als llama3.2:3b."],
      ]), autoPanel());
    },
    // ------------------------------------------------------------ Modelle
    async models(c) {
      const d = await api("GET", "/api/admin/models");
      const members = new Set(d.members || []);
      const pullName = h("input", { class: "inp", placeholder: "z. B. qwen3:8b oder gemma3:4b", "aria-label": "Modellname" });
      const prog = h("div", { class: "small", role: "status" });
      c.append(
        h("section", { class: "panel" }, h("h3", null, "Modell herunterladen"),
          h("p", { class: "small muted", style: { margin: 0 } }, "Empfehlungen für 8 CPU-Kerne ohne Grafikkarte: qwen3:8b (Standard), llama3.2:3b (schnelles Hilfsmodell), gemma3:4b (Bilder erkennen). Modelle über 14B sind auf der CPU sehr langsam."),
          h("div", { style: { display: "flex", gap: "8px" } }, pullName, h("button", { class: "btn", type: "button", onClick: async () => {
            const r = await fetch("/api/admin/models/pull", { method: "POST", headers: { "x-haus-ki": "1", "content-type": "application/json" }, body: JSON.stringify({ name: pullName.value }) });
            const reader = r.body.getReader(), dec = new TextDecoder(); let buf = "";
            while (true) {
              const { done, value } = await reader.read(); if (done) break;
              buf += dec.decode(value, { stream: true });
              for (const line of buf.split("\n\n").slice(0, -1)) {
                const ev = JSON.parse(line.replace(/^data: /, ""));
                prog.textContent = ev.error ? "Fehler: " + ev.error : ev.total ? `${ev.status}: ${Math.round((ev.completed || 0) / ev.total * 100)} % von ${fmtGB(ev.total)}` : ev.status;
              }
              buf = buf.split("\n\n").pop();
            }
            rerender();
          } }, "Herunterladen")), prog),
        h("section", { class: "panel" }, h("h3", null, "Installierte Modelle"),
          h("div", { class: "tablewrap" }, h("table", { class: "t" }, h("thead", null, h("tr", null, ["Modell", "Größe", "Passt in RAM", "Rolle", "Für Mitglieder", ""].map((x) => h("th", null, x)))),
            h("tbody", null, d.models.map((m) => h("tr", null,
              h("td", null, h("b", null, m.name), h("div", { class: "tiny muted" }, [m.params, m.quant, m.loaded ? "geladen" : ""].filter(Boolean).join(", "))),
              h("td", null, fmtGB(m.size)),
              h("td", null, m.fits === null ? h("span", { class: "muted" }, "unbekannt") : m.fits ? h("span", { style: { color: "var(--ok)" } }, "ja") : h("span", { style: { color: "var(--warn)" } }, `knapp, etwa ${fmtGB(m.ram_need)}`)),
              h("td", null, m.name === d.default ? h("span", { class: "badge" }, "Standard") : m.name === d.helper ? h("span", { class: "badge ok" }, "Hilfsmodell") :
                h("span", null, h("button", { class: "act", type: "button", onClick: async () => { await api("PUT", "/api/admin/settings", { "ollama.default_model": m.name }); A.settings = null; toast(`${m.name} ist jetzt Standard.`); rerender(); } }, "Als Standard"),
                  h("button", { class: "act", type: "button", onClick: async () => { await api("PUT", "/api/admin/settings", { "ollama.helper_model": m.name }); A.settings = null; rerender(); } }, "Als Hilfsmodell"))),
              h("td", null, h("button", { type: "button", class: "tg", role: "switch", "aria-checked": members.has(m.name) || m.name === d.default ? "true" : "false", "aria-label": "Für Mitglieder: " + m.name, style: { width: "auto", padding: 0 }, disabled: m.name === d.default,
                onClick: async () => { members.has(m.name) ? members.delete(m.name) : members.add(m.name); await api("PUT", "/api/admin/settings", { "ollama.member_models": [...members] }); A.settings = null; rerender(); } }, h("span", { class: "track" }))),
              h("td", null, m.name !== d.default && m.name !== d.helper ? h("button", { class: "act", type: "button", style: { color: "var(--err)" }, onClick: async () => {
                if (!(await confirmDialog("Modell löschen?", `${m.name} wird aus Ollama entfernt.`, "Löschen"))) return;
                try { await api("DELETE", "/api/admin/models/" + encodeURIComponent(m.name)); rerender(); } catch (e) { toast(e.message, true); } } }, "Löschen") : null)))))),
          h("p", { class: "tiny muted", style: { margin: 0 } }, "Das Standardmodell bleibt dauerhaft geladen. Ein zweites großes Modell verdrängt es aus dem Speicher.")));
    },
    // ------------------------------------------------------------ Modell-Profile
    async profiles(c) {
      const d = await api("GET", "/api/admin/models");
      const f = { name: h("input", { class: "inp", placeholder: "z. B. haus-ki-genau" }), from: h("select", { class: "inp" }, d.models.map((m) => h("option", { value: m.name, selected: m.name === d.default }, m.name))),
        system: h("textarea", { class: "inp", rows: 4, placeholder: "Feste Anweisung für dieses Profil" }), temp: h("input", { class: "inp", type: "number", step: 0.1, placeholder: "z. B. 0.3" }), ctx: h("input", { class: "inp", type: "number", step: 1024, placeholder: "z. B. 8192" }) };
      c.append(h("section", { class: "panel" }, h("h3", null, "Neues Profil"),
        h("p", { class: "small muted", style: { margin: 0 } }, "Ein Profil ist ein eigenes Modell in Ollama (Modelfile) mit fester Anweisung und eigenen Werten. Es teilt sich den Speicher mit dem Basismodell."),
        h("div", { class: "grid2" }, h("label", { class: "f" }, "Name", f.name), h("label", { class: "f" }, "Basismodell", f.from)),
        h("label", { class: "f" }, "Systemanweisung", f.system),
        h("div", { class: "grid2" }, h("label", { class: "f" }, "Temperatur", f.temp), h("label", { class: "f" }, "Kontextlänge", f.ctx)),
        h("button", { class: "btn", type: "button", style: { alignSelf: "flex-start" }, onClick: async () => {
          try { await api("POST", "/api/admin/models/profile", { name: f.name.value, from: f.from.value, system: f.system.value, parameters: { temperature: f.temp.value ? +f.temp.value : null, num_ctx: f.ctx.value ? +f.ctx.value : null } }); toast("Profil erstellt. Es erscheint jetzt unter Modelle."); go("#models"); }
          catch (e) { toast(e.message, true); } } }, "Profil erstellen")));
    },
    // ------------------------------------------------------------ Quellen
    async sources(c) {
      c.append(
        form("Paperless-ngx", [["paperless.enabled", "Paperless verwenden", "toggle"], ["paperless.url", "Adresse", "text", "z. B. http://paperless.home:8000"],
          ["paperless.token", "Zentraler API-Token", "text", "Für den Fristen-Wächter und alle ohne eigenen Token. In Paperless unter Profil › API-Token."],
          ["paperless.personal_tokens", "Eigene Tokens pro Person verwenden", "toggle", "Dann sieht jede Person nur, was sie in Paperless sehen darf. Token unter Benutzer eintragen."],
          ["paperless.deadlines", "Fristen-Wächter", "toggle", "Prüft nachts neue Dokumente auf Fristen und Zahlungsziele."], ["paperless.deadline_days", "Vorlauf in Tagen", "number"],
          ["paperless.upload", "Dokumente aus dem Chat ablegen", "toggle", "Abgelegt wird erst nach Bestätigung."],
          ["paperless.write_tags", "Tags setzen erlauben", "toggle", "Haus-KI darf nach Bestätigung Tags an Dokumenten ergänzen."],
          ["paperless.semantic", "Auch nach Bedeutung suchen", "toggle", "Findet „Hausratversicherung“ auch, wenn im Dokument nur „Versicherungsschein“ steht. Der Index wird nachts aufgebaut, Stand unter Antwortqualität."],
          ["paperless.embed_model", "Modell für die Suche nach Bedeutung", "text", "bge-m3 versteht Deutsch gut. Muss in Ollama installiert sein."]], { test: "paperless" }),
        form("Jellyfin", [["jellyfin.enabled", "Jellyfin verwenden", "toggle"], ["jellyfin.url", "Adresse", "text", "z. B. http://jellyfin.home:8096"],
          ["jellyfin.api_key", "API-Schlüssel", "text", "In Jellyfin unter Dashboard › API-Schlüssel."], ["jellyfin.playback", "Wiedergabe starten erlauben", "toggle", "Nur nach Bestätigung, auf eingeschalteten Geräten."]], { test: "jellyfin" }),
        form("Weitere Postfächer", [["mail.allow_gmx", "GMX erlauben", "toggle"], ["mail.allow_gmail", "Gmail erlauben", "toggle"],
          ["mail.allow_outlookcom", "Outlook.com erlauben", "toggle", "Braucht eine App-Registrierung, die auch private Microsoft-Konten zulässt."], ["mail.drafts", "Entwürfe erlauben", "toggle", "Jede Person schaltet das pro Postfach zusätzlich selbst ein."]],
          { intro: "Jede Person verbindet ihre Postfächer selbst unter Meine Konten." }),
        form("Internet", [["web.enabled", "Internet verwenden", "toggle"], ["web.provider", "Suchdienst", "seg", null, [["ollama", "Ollama Web Search"], ["searxng", "Eigenes SearXNG"]]],
          ["web.ollama_key", "Ollama-API-Schlüssel", "text", "Kostenloses Konto auf ollama.com › Settings › Keys."], ["web.searxng_url", "SearXNG-Adresse", "text", "Nur bei eigenem SearXNG, JSON-Ausgabe muss aktiv sein."],
          ["web.max_results", "Treffer pro Suche", "number"]], { test: "web" }),
        h("section", { class: "panel" }, h("h3", null, "Feste Sicherheitsregeln"), h("p", { class: "small muted", style: { margin: 0 } }, "Diese Regeln sind eingebaut und lassen sich nicht abschalten."),
          ["Jede Aktion braucht eine Bestätigung im Chat.", "Inhalte aus dem Internet lösen nie Aktionen aus und schreiben nichts ins Gedächtnis.", "Spam-Ordner werden nie gelesen.", "Mails werden nie gesendet, nur als Entwurf gespeichert.", "Haustür, Garagentor und Alarmanlage sind nur lesbar."].map((t) => h("div", { class: "small", style: { display: "flex", gap: "8px" } }, window.HK.icon("lock", 16), t))));
    },
    // ------------------------------------------------------------ KNX
    async knx(c) {
      const d = await api("GET", "/api/admin/knx");
      const keyIn = h("input", { type: "file", accept: ".knxkeys", class: "hidden", onChange: async (e) => { const fd = new FormData(); fd.append("file", e.target.files[0]); await api("POST", "/api/admin/knx/keyring", fd); toast("Keyring gespeichert."); rerender(); } });
      const projIn = h("input", { type: "file", accept: ".knxproj", class: "inp" });
      const projPw = h("input", { type: "password", class: "inp", placeholder: "Projektpasswort, falls gesetzt" });
      c.append(form("Verbindung", [["knx.enabled", "KNX verwenden", "toggle"], ["knx.mode", "Verbindungsart", "seg", null, [["tunnel", "Tunnel (UDP)"], ["tunnel_tcp", "Tunnel (TCP)"], ["routing", "Routing"]]],
        ["knx.gateway_ip", "IP der KNX-Schnittstelle", "text"], ["knx.gateway_port", "Port", "number"], ["knx.local_ip", "Eigene IP (optional)", "text", "Nur nötig, wenn der Container mehrere Netzwerke hat."],
        ["knx.secure", "KNX Secure", "toggle", "Braucht den Keyring aus der ETS (.knxkeys)."], ["knx.keyring_password", "Keyring-Passwort", "text"]], { test: "knx",
        extra: h("div", { style: { display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" } }, keyIn, h("button", { class: "btn sec", type: "button", onClick: () => keyIn.click() }, "Keyring hochladen"), h("span", { class: "small muted" }, d.keyring ? "Keyring vorhanden" : "Kein Keyring")) }),
        h("section", { class: "panel" }, h("h3", null, "ETS-Projekt importieren"),
          h("p", { class: "small muted", style: { margin: 0 } }, "Liest Gruppenadressen, Namen und Datentypen. Bestehende Freigaben bleiben erhalten. Haustür, Garagentor und Alarm werden erkannt und fest auf „nur lesen“ gesetzt."),
          h("div", { class: "grid2" }, projIn, projPw),
          h("button", { class: "btn", type: "button", style: { alignSelf: "flex-start" }, onClick: async () => {
            if (!projIn.files[0]) return toast("Bitte eine .knxproj-Datei wählen.", true);
            const fd = new FormData(); fd.append("file", projIn.files[0]); fd.append("password", projPw.value);
            try { const r = await api("POST", "/api/admin/knx/import", fd); toast(`${r.added} neu, ${r.updated} aktualisiert.`); rerender(); } catch (e) { toast(e.message, true); } } }, "Importieren")));
      // Freigaben
      const filter = h("input", { class: "inp", placeholder: "Filtern nach Name, Raum oder Adresse", "aria-label": "Gruppenadressen filtern" });
      const changes = {};
      const tbody = h("tbody");
      const draw = () => {
        const q = filter.value.toLowerCase();
        tbody.innerHTML = "";
        for (const g of d.gas.filter((g) => !q || (g.name + " " + (g.room || "") + " " + g.address).toLowerCase().includes(q)).slice(0, 400)) {
          const cur = changes[g.address] || g.permission;
          tbody.appendChild(h("tr", null, h("td", { style: { fontVariantNumeric: "tabular-nums", fontFamily: "var(--mono)" } }, g.address), h("td", null, g.name), h("td", null, g.room || ""), h("td", { class: "small muted" }, g.dpt || "?"),
            h("td", null, g.locked ? h("span", { class: "small muted", style: { display: "inline-flex", gap: "6px" } }, window.HK.icon("lock", 14), "nur lesen") :
              seg([["none", "Nichts"], ["read", "Lesen"], ["write", "Schalten"]], cur, (v) => { changes[g.address] = v; draw(); }, "Freigabe " + g.name))));
        }
      };
      filter.addEventListener("input", draw);
      draw();
      c.append(h("section", { class: "panel" }, h("h3", null, `Freigaben pro Gruppenadresse (${d.gas.length})`),
        d.gas.length ? [filter, h("div", { class: "tablewrap" }, h("table", { class: "t" }, h("thead", null, h("tr", null, ["Adresse", "Name", "Raum", "Typ", "Freigabe"].map((x) => h("th", null, x)))), tbody)),
          h("button", { class: "btn", type: "button", style: { alignSelf: "flex-start" }, onClick: async () => { const r = await api("PUT", "/api/admin/knx/ga", { permissions: changes }); toast(`${r.changed} Freigaben gespeichert.`); rerender(); } }, "Freigaben speichern")] :
          h("p", { class: "small muted", style: { margin: 0 } }, "Noch keine Gruppenadressen. Importiere zuerst das ETS-Projekt.")));
      // Szenen und Fenster
      const scenes = h("textarea", { class: "inp", rows: 6, value: (val("knx.scenes") || []).map((s) => s.name + ": " + s.writes.map((w) => `${w.address}=${w.value}`).join(", ")).join("\n") });
      c.append(h("section", { class: "panel" }, h("h3", null, "Schnellsteuerung"),
        h("label", { class: "f" }, "Szenen, eine pro Zeile: Name: Adresse=Wert, Adresse=Wert (nur Administratoren können sie auslösen)", scenes),
        h("p", { class: "tiny muted", style: { margin: 0 } }, "Beispiel: Filmabend: 1/1/5=false, 2/1/3=80, 1/1/9=true"),
        h("button", { class: "btn", type: "button", style: { alignSelf: "flex-start" }, onClick: async () => {
          const parsed = scenes.value.split("\n").filter((l) => l.includes(":")).map((l) => { const [name, rest] = l.split(/:(.*)/s); return { name: name.trim(), writes: rest.split(",").map((x) => x.trim()).filter(Boolean).map((x) => { const [address, v] = x.split("="); const vv = v.trim(); return { address: address.trim(), value: vv === "true" ? true : vv === "false" ? false : isNaN(+vv) ? vv : +vv }; }) }; });
          await api("PUT", "/api/admin/settings", { "knx.scenes": parsed }); A.settings = null; toast("Szenen gespeichert."); } }, "Szenen speichern")),
        form("„Bevor wir fahren“", [["knx.trip_check", "Gruppenadressen für den Check, eine pro Zeile", "textarea", "Leer = alle freigegebenen Adressen mit „Fenster“ im Namen.", "lines"]]));
    },
    // ------------------------------------------------------------ Microsoft 365
    async m365(c) {
      c.append(h("section", { class: "panel" }, h("h3", null, "So richtest du die App-Registrierung ein"),
        h("ol", { class: "small", style: { margin: 0, paddingLeft: "20px", display: "flex", flexDirection: "column", gap: "4px" } },
          h("li", null, "Entra Admin Center › App-Registrierungen › Neue Registrierung „Haus-KI“. Kontotyp: Nur dieses Verzeichnis, oder für Outlook.com zusätzlich private Microsoft-Konten."),
          h("li", null, "Umleitungs-URI (Web): ", h("code", null, A.settings.base_url + "/auth/callback")),
          h("li", null, "Zertifikate und Geheimnisse › Neuer geheimer Clientschlüssel. Ablaufdatum notieren."),
          h("li", null, "App-Rollen anlegen: Wert ", h("code", null, "HausKI.Admin"), " und ", h("code", null, "HausKI.Member"), ", zulässig für Benutzer und Gruppen."),
          h("li", null, "Unternehmensanwendungen › Haus-KI › Benutzer und Gruppen: Personen den Rollen zuweisen."),
          h("li", null, "API-Berechtigungen (delegiert): die unten eingeschalteten Bereiche, dann Administratorzustimmung erteilen.")),
        h("p", { class: "tiny muted", style: { margin: 0 } }, "Benutzer werden über die Objekt-ID ihres Entra-Kontos zugeordnet, nicht über die E-Mail.")),
        form("Verbindung", [["ms.enabled", "Microsoft 365 verwenden (Anmeldung und Datenquelle)", "toggle"], ["ms.tenant_id", "Verzeichnis-ID (Tenant)", "text"], ["ms.client_id", "Anwendungs-ID (Client)", "text"], ["ms.client_secret", "Geheimer Clientschlüssel", "text"]], { test: "ms" }),
        form("Berechtigungen", [["ms.mail", "Outlook lesen (Mail.Read)", "toggle"], ["ms.mail_drafts", "Entwürfe speichern (Mail.ReadWrite)", "toggle"], ["ms.calendar", "Kalender lesen (Calendars.Read)", "toggle"],
          ["ms.files", "OneDrive und SharePoint (Files.Read.All, Sites.Read.All)", "toggle"], ["ms.todo", "To Do: Aufgaben und Einkaufslisten (Tasks.ReadWrite)", "toggle"],
          ["ms.cal_check", "Familienkalender-Abgleich (Calendars.Read.Shared)", "toggle", "Prüft jeden Morgen die nächsten 7 Tage. Aus persönlichen Kalendern nur „belegt“, Titel nur aus dem gemeinsamen Kalender."],
          ["ms.family_calendar_owner", "Wem gehört der gemeinsame Kalender (E-Mail)", "text"], ["ms.family_calendar_name", "Name des gemeinsamen Kalenders", "text"], ["ms.todo_list", "To-Do-Liste für Einkaufslisten", "text"]],
          { intro: "Geänderte Berechtigungen gelten nach der nächsten Anmeldung jeder Person." }));
    },
    // ------------------------------------------------------------ Ollama-Server
    async ollama(c) {
      const KNOWN = [["OLLAMA_KEEP_ALIVE", "Wie lange Modelle geladen bleiben, z. B. -1 für dauerhaft"], ["OLLAMA_NUM_PARALLEL", "Gleichzeitige Anfragen pro Modell, auf CPU 1"],
        ["OLLAMA_MAX_LOADED_MODELS", "Höchstzahl gleichzeitig geladener Modelle, bei 16 GB meist 2"], ["OLLAMA_CONTEXT_LENGTH", "Standard-Kontextlänge"],
        ["OLLAMA_FLASH_ATTENTION", "1 = spart Speicher beim Kontext"], ["OLLAMA_KV_CACHE_TYPE", "q8_0 halbiert den Kontextspeicher, braucht Flash Attention"], ["OLLAMA_HOST", "Adresse, auf der Ollama lauscht, z. B. 0.0.0.0:11434"]];
      c.append(form("Agent im Ollama-Container", [["agent.url", "Adresse des Agenten", "text", "z. B. https://192.168.1.20:8765"], ["agent.token", "Agent-Token", "text", "Steht in der Ausgabe des Installationsskripts."]],
        { test: "agent", intro: "Der Agent schreibt Ollama-Einstellungen und startet den Dienst neu. Ohne ihn lassen sich die Werte nur lesen." }));
      let env = null;
      try { env = await api("GET", "/api/admin/agent/env"); } catch (e) {
        c.appendChild(h("div", { class: "note warn" }, "Der Agent ist nicht erreichbar: " + e.message));
        c.appendChild(h("section", { class: "panel" }, h("h3", null, "Agent installieren"), h("p", { class: "small", style: { margin: 0 } }, "Im Ollama-Container als root ausführen (in Proxmox: Container › Konsole):"),
          h("pre", { class: "md", style: { margin: 0 } }, h("code", null, `curl -fsSL ${A.settings.base_url}/agent/install.sh | sudo bash`)),
          h("p", { class: "tiny muted", style: { margin: 0 } }, "Das Skript zeigt am Ende Adresse und Token. Beides oben eintragen."),
          h("button", { class: "btn sec", type: "button", style: { alignSelf: "flex-start" }, onClick: async () => { await api("POST", "/api/admin/agent/reset-fingerprint"); toast("Zertifikat zurückgesetzt."); } }, "Gemerktes Zertifikat zurücksetzen")));
        return;
      }
      // Schutz für Ollama
      try {
        const g = await api("GET", "/api/admin/agent/guard");
        const allow = h("input", { class: "inp", value: (g.allow || []).join(", "), "aria-label": "Erlaubte Adressen" });
        let enabled = !!g.enabled;
        const tgBox = h("div");
        const drawTg = () => { tgBox.innerHTML = ""; tgBox.appendChild(toggle("Ollama schützen", enabled, (v) => { enabled = v; drawTg(); }, "Port 11434 ist nur für die eingetragenen Adressen offen. Die Adresse von Haus-KI bleibt immer erlaubt.")); };
        drawTg();
        c.append(h("section", { class: "panel", style: { borderTop: `3px solid ${g.active ? "var(--ok)" : "var(--warn)"}` } }, h("h3", null, "Zugriff auf Ollama"),
          h("div", { class: "note " + (g.active ? "ok" : "warn") }, g.active ? "Geschützt: Andere Geräte im Heimnetz erreichen Ollama nicht." : "Nicht geschützt: Jedes Gerät im Heimnetz kann Ollama ohne Anmeldung nutzen."),
          tgBox, h("label", { class: "f" }, "Erlaubte Adressen, mit Komma getrennt", allow),
          h("button", { class: "btn", type: "button", style: { alignSelf: "flex-start" }, onClick: async () => {
            try { const r = await api("PUT", "/api/admin/agent/guard", { enabled, allow: allow.value.split(/[ ,;]+/).filter(Boolean) });
              toast(r.enabled ? (r.active ? "Schutz aktiv." : "Schutz konnte nicht aktiviert werden: " + (r.error || "")) : "Schutz ausgeschaltet.", r.enabled && !r.active); rerender(); }
            catch (e) { toast(e.message, true); } } }, "Speichern")));
      } catch (e) { c.append(h("div", { class: "note warn" }, "Der Schutz für Ollama lässt sich nur mit aktuellem Agenten verwalten: " + e.message)); }
      const vars = { ...env.vars };
      const rows = h("div");
      const preview = h("pre", { class: "md", style: { margin: 0 } });
      const draw = () => {
        rows.innerHTML = "";
        for (const [k, help] of KNOWN) rows.appendChild(h("label", { class: "f", style: { padding: "6px 0" } }, k, h("input", { class: "inp", value: vars[k] || "", placeholder: "nicht gesetzt", onInput: (e) => { if (e.target.value) vars[k] = e.target.value; else delete vars[k]; drawPreview(); } }), h("span", { class: "h" }, help)));
      };
      const drawPreview = () => { preview.innerHTML = ""; preview.appendChild(h("code", null, "[Service]\n" + Object.entries(vars).map(([k, v]) => `Environment="${k}=${v}"`).join("\n"))); };
      draw(); drawPreview();
      c.append(h("section", { class: "panel" }, h("h3", null, "Umgebungsvariablen"), h("p", { class: "small muted", style: { margin: 0 } }, `Datei ${env.path} in ${env.hostname}`), rows,
        h("div", { class: "tiny muted" }, "Vorschau"), preview,
        h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" } },
          h("button", { class: "btn", type: "button", onClick: async () => {
            if (!(await confirmDialog("Speichern und Ollama neu starten?", "Laufende Antworten brechen ab. Der Neustart dauert etwa 20 Sekunden, danach wird das Standardmodell neu geladen.", "Neu starten"))) return;
            try { await api("PUT", "/api/admin/agent/env", { vars, restart: true }); toast("Gespeichert, Ollama läuft wieder."); } catch (e) { toast(e.message, true); } } }, "Speichern und neu starten"),
          h("button", { class: "btn sec", type: "button", onClick: async () => { try { await api("PUT", "/api/admin/agent/env", { vars }); toast("Gespeichert. Wirkt nach dem nächsten Neustart."); } catch (e) { toast(e.message, true); } } }, "Nur speichern"))));
      const upd = h("span", { class: "small", role: "status" });
      c.append(h("section", { class: "panel" }, h("h3", null, "Ollama aktualisieren"), h("p", { class: "small muted", style: { margin: 0 } }, `Installiert: ${env.ollama_version || "unbekannt"}. Die Aktualisierung nutzt das offizielle Installationsskript von ollama.com.`),
        h("div", { style: { display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" } },
          h("button", { class: "btn sec", type: "button", onClick: async () => {
            if (!(await confirmDialog("Ollama aktualisieren?", "Ollama wird dabei neu gestartet.", "Aktualisieren"))) return;
            await api("POST", "/api/admin/agent/update"); upd.textContent = "Läuft …";
            const t = setInterval(async () => { const s = await api("POST", "/api/admin/agent/update-status"); upd.textContent = s.status === "running" ? "Läuft …" : s.status === "done" ? "Fertig, Version " + (s.version || "") : "Fehler: " + (s.output || "").slice(-200); if (s.status !== "running") clearInterval(t); }, 4000);
          } }, "Jetzt aktualisieren"), upd),
        h("button", { class: "act", type: "button", style: { alignSelf: "flex-start" }, onClick: async (e) => { const l = await api("POST", "/api/admin/agent/logs"); e.target.replaceWith(h("pre", { class: "md", style: { maxHeight: "300px", overflow: "auto", margin: 0 } }, h("code", null, l.lines))); } }, "Letzte Log-Zeilen anzeigen")));
    },
    // ------------------------------------------------------------ Proxmox
    async proxmox(c) {
      const guests = h("div");
      c.append(form("Proxmox-API", [["proxmox.url", "Adresse", "text", "z. B. https://pve.home:8006"], ["proxmox.token_id", "Token-ID", "text", "z. B. hauski@pve!app. Das Installationsskript legt ihn an."], ["proxmox.token_secret", "Token-Secret", "text"],
        ["proxmox.verify_tls", "Zertifikat prüfen", "toggle", "Aus lassen bei selbstsigniertem Proxmox-Zertifikat."], ["proxmox.node", "Knoten", "text"], ["proxmox.kind", "Art des Ollama-Gasts", "seg", null, [["lxc", "Container (LXC)"], ["qemu", "VM"]]], ["proxmox.vmid", "ID des Ollama-Containers", "number"]], {
        test: "proxmox", onTest: (r) => {
          guests.innerHTML = "";
          if (r.guests) guests.appendChild(h("div", null, h("div", { class: "tiny muted" }, "Gast übernehmen:"), h("div", { class: "follow", style: { marginTop: "6px" } }, r.guests.map((g) => h("button", { class: "chip", type: "button", onClick: async () => { await api("PUT", "/api/admin/settings", { "proxmox.node": g.node, "proxmox.vmid": g.vmid, "proxmox.kind": g.kind }); A.settings = null; toast(`${g.name} (${g.vmid}) übernommen.`); rerender(); } }, `${g.vmid} ${g.name} · ${g.kind === "lxc" ? "Container" : "VM"}`)))));
        }, extra: guests }));
      if (A.settings.values["proxmox.vmid"]) {
        const cmd = (k, label, text) => h("button", { class: k === "start" ? "btn sec" : "btn danger", type: "button", onClick: async () => { if (await confirmDialog(label + "?", text, label)) { try { await api("POST", "/api/admin/proxmox/" + k); toast(label + " angestoßen."); } catch (e) { toast(e.message, true); } } } }, label);
        c.append(h("section", { class: "panel" }, h("h3", null, "Ollama-Container steuern"),
          h("p", { class: "small muted", style: { margin: 0 } }, "Während der Container neu startet, kann Haus-KI nicht antworten. Haus-Schnellsteuerung und alte Chats funktionieren weiter."),
          h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" } }, cmd("start", "Starten", "Der Container wird gestartet."), cmd("reboot", "Neu starten", "Laufende Antworten brechen ab."), cmd("shutdown", "Herunterfahren", "Haus-KI kann danach keine Fragen mehr beantworten, bis die VM wieder läuft."))));
      }
    },
    // ------------------------------------------------------------ Updates und Sicherung
    async backup(c) {
      const u = await api("GET", "/api/admin/update");
      const b = await api("GET", "/api/admin/backups");
      const pkg = h("input", { type: "file", accept: ".tar.gz,.tgz", class: "inp" });
      const av = u.available || {};
      c.append(form("Automatisch nach Updates suchen", [
        ["update.source", "Update-Quelle", "text", "github:besitzer/repo für Veröffentlichungen auf GitHub, oder die https-Adresse einer latest.json. Leer = nur Hochladen von Hand."],
        ["update.auto_check", "Täglich nachsehen", "toggle", "Administratoren bekommen eine Benachrichtigung, wenn es eine neue Version gibt."]],
        { extra: h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } },
          av.available ? h("div", { class: "note ok" }, h("b", null, `Haus-KI ${av.version} ist verfügbar.`), av.notes ? h("div", { class: "small", style: { whiteSpace: "pre-wrap", marginTop: "6px" } }, av.notes.slice(0, 600)) : null) :
            av.configured ? h("p", { class: "small muted", style: { margin: 0 } }, `Aktuell, zuletzt geprüft ${av.checked ? fmtDate(av.checked) : "nie"}.`) : null,
          h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" } },
            h("button", { class: "btn sec", type: "button", onClick: async () => { try { const r = await api("POST", "/api/admin/update/check"); toast(r.available ? `Version ${r.version} ist verfügbar.` : "Haus-KI ist aktuell."); rerender(); } catch (e) { toast(e.message, true); } } }, "Jetzt prüfen"),
            av.available ? h("button", { class: "btn", type: "button", onClick: async () => {
              if (!(await confirmDialog(`Auf ${av.version} aktualisieren?`, "Das Paket wird heruntergeladen und über seine Prüfsumme kontrolliert. Vorher wird gesichert. Startet die neue Version nicht, kehrt Haus-KI von selbst zurück.", "Aktualisieren"))) return;
              try { await api("POST", "/api/admin/update/install-available"); toast("Update wird installiert. Die Seite lädt in etwa einer Minute neu."); setTimeout(() => location.reload(), 60000); } catch (e) { toast(e.message, true); } } }, `Auf ${av.version} aktualisieren`) : null)) }));
      c.append(h("section", { class: "panel" }, h("h3", null, "Haus-KI aktualisieren"), h("p", { class: "small", style: { margin: 0 } }, `Installierte Version: ${u.version}`),
        u.status && u.status.state ? h("div", { class: "note " + (u.status.state === "ok" ? "ok" : u.status.state === "error" ? "err" : "") }, u.status.message || u.status.state) : null,
        h("p", { class: "small muted", style: { margin: 0 } }, "Lade ein Haus-KI-Paket hoch. Vor dem Update wird automatisch gesichert. Startet die neue Version nicht, kehrt Haus-KI von selbst zur vorherigen zurück."),
        pkg, h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" } },
          h("button", { class: "btn", type: "button", onClick: async () => { if (!pkg.files[0]) return toast("Bitte ein Paket wählen.", true); const fd = new FormData(); fd.append("file", pkg.files[0]); try { await api("POST", "/api/admin/update", fd); toast("Update wird installiert. Die Seite lädt in etwa einer Minute neu."); setTimeout(() => location.reload(), 60000); } catch (e) { toast(e.message, true); } } }, "Update installieren"),
          h("button", { class: "btn sec", type: "button", onClick: async () => { if (await confirmDialog("Zur vorherigen Version zurück?", "Haus-KI startet dabei neu.", "Zurückkehren")) { await api("POST", "/api/admin/update/rollback"); toast("Wird zurückgesetzt."); } } }, "Vorherige Version"))),
        form("Nächtliche Sicherung", [["backup.enabled", "Jede Nacht sichern", "toggle", "Datenbank mit Chats, Einstellungen und Protokoll. Für den ganzen Container zusätzlich die Proxmox-Sicherung nutzen."], ["backup.keep", "Aufbewahren (Anzahl)", "number"], ["night.start", "Nachtplan startet um", "text", "z. B. 02:00"]]),
        h("section", { class: "panel" }, h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px", flexWrap: "wrap" } }, h("h3", null, "Vorhandene Sicherungen"),
          h("button", { class: "btn sec", type: "button", onClick: async () => { await api("POST", "/api/admin/backups"); toast("Sicherung erstellt."); rerender(); } }, "Jetzt sichern")),
          b.backups.length ? b.backups.map((x) => h("div", { class: "list-row" }, h("span", { class: "grow" }, fmtDate(x.created), h("span", { class: "tiny muted" }, ` · ${fmtN(x.size / 1e6, 1)} MB`)),
            h("a", { class: "act", href: "/api/admin/backups/" + encodeURIComponent(x.name) }, "Herunterladen"),
            h("button", { class: "act", type: "button", style: { color: "var(--warn)" }, onClick: async () => { if (!(await confirmDialog("Wiederherstellen?", "Der aktuelle Stand wird vorher gesichert und dann durch diese Sicherung ersetzt.", "Wiederherstellen"))) return; await api("POST", "/api/admin/backups/restore", { name: x.name }); toast("Wiederhergestellt."); setTimeout(() => location.reload(), 1500); } }, "Wiederherstellen"))) :
            h("p", { class: "small muted", style: { margin: 0 } }, "Noch keine Sicherung.")));
    },
    // ------------------------------------------------------------ Benutzer
    async users(c) {
      const list = await api("GET", "/api/admin/users");
      const knx = await api("GET", "/api/admin/knx").catch(() => ({ rooms: [] }));
      A.cache.sel = A.cache.sel || (list[0] && list[0].id);
      const u = list.find((x) => x.id === A.cache.sel) || list[0];
      const pick = h("div", { class: "follow" }, list.map((x) => h("button", { class: "chip", type: "button", "aria-pressed": x.id === u.id ? "true" : "false", style: x.id === u.id ? { borderColor: "var(--primary)" } : null, onClick: () => { A.cache.sel = x.id; rerender(); } }, av(x), x.name, x.disabled ? " (gesperrt)" : "")),
        h("button", { class: "chip", type: "button", onClick: async () => { const n = await window.HK.promptDialog("Benutzer vorab anlegen", "Vorname", ""); if (!n) return; const em = await window.HK.promptDialog("Benutzer vorab anlegen", "E-Mail des Microsoft-Kontos (zum Verknüpfen bei der ersten Anmeldung)", ""); await api("POST", "/api/admin/users", { name: n, email: em || "" }); rerender(); } }, "+ Benutzer"));
      const p = u.perms;
      const save = async (body) => { try { await api("PUT", "/api/admin/users/" + u.id, body); toast("Gespeichert."); rerender(); } catch (e) { toast(e.message, true); } };
      const perm = (k, label, help) => toggle(label, !!p[k], (v) => save({ perms: { [k]: v } }), help);
      const jfUser = h("input", { class: "inp", value: p.jellyfin_user || "", placeholder: "Jellyfin-Benutzer-ID" });
      const plTok = h("input", { class: "inp", type: "password", placeholder: u.paperless_token ? "•••• gespeichert" : "nicht gesetzt" });
      const pw = h("input", { class: "inp", type: "password", autocomplete: "new-password", placeholder: u.has_password ? "•••• gesetzt" : "nicht gesetzt" });
      const rooms = new Set(p.knx_rooms || []);
      c.append(pick,
        h("section", { class: "panel" }, h("div", { style: { display: "flex", gap: "12px", alignItems: "center" } }, av(u, "lg"), h("div", null, h("h3", null, u.name), h("div", { class: "tiny muted" }, `${u.role === "admin" ? "Administrator" : "Mitglied"} · ${u.email || "keine E-Mail"} · ${u.ms_connected ? "Microsoft verbunden" : "Microsoft nicht verbunden"} · zuletzt ${u.last_seen ? fmtDate(u.last_seen) : "nie"}`))),
          h("div", { class: "small muted" }, "Rolle (wird bei jeder Microsoft-Anmeldung aus Entra übernommen)"),
          seg([["admin", "Administrator"], ["member", "Mitglied"]], u.role, (v) => save({ role: v })),
          h("div", { class: "tiny muted" }, "Microsoft-Objekt-ID: " + (u.oid || "noch nicht verknüpft"))),
        h("section", { class: "panel" }, h("h3", null, "Freigaben"),
          perm("paperless", "Paperless"), perm("jellyfin", "Jellyfin"), perm("m365", "Microsoft 365"), perm("mail", "Weitere Postfächer"), perm("web", "Internet"), perm("memory", "Gedächtnis"),
          perm("voice", "Sprache", "Spracheingabe, Vorlesen und Gesprächsmodus."),
          perm("auto_actions", "Harmloses ohne Rückfrage", "Darf selbst wählen, ob Licht, Rollläden und Ähnliches direkt ausgeführt werden (Auswahl unter Anfrage-Standards)."),
          perm("learn", "Lernmodus", "Keine fertigen Lösungen für Hausaufgaben, stattdessen Schritt für Schritt erklären."), perm("knx", "Haus (KNX)"),
          p.knx && u.role !== "admin" ? h("div", null, h("div", { class: "small muted", style: { marginBottom: "6px" } }, "Räume, die sichtbar und schaltbar sind"),
            h("div", { class: "follow" }, knx.rooms.map((r) => h("button", { class: "chip", type: "button", "aria-pressed": rooms.has(r) ? "true" : "false", style: rooms.has(r) ? { background: "var(--okbg)", borderColor: "var(--okbd)" } : null,
              onClick: () => { rooms.has(r) ? rooms.delete(r) : rooms.add(r); save({ perms: { knx_rooms: [...rooms] } }); } }, r))), !knx.rooms.length ? h("p", { class: "tiny muted" }, "Erst ETS-Projekt importieren.") : null) : null),
        h("section", { class: "panel" }, h("h3", null, "Zugänge"),
          h("div", { class: "grid2" }, h("label", { class: "f" }, "Eigener Paperless-Token", plTok), h("label", { class: "f" }, "Jellyfin-Benutzer-ID (für „gesehen“)", jfUser)),
          u.role === "admin" ? h("label", { class: "f" }, "Notfall-Passwort (mindestens 12 Zeichen)", pw) : null,
          h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" } },
            h("button", { class: "btn", type: "button", onClick: () => { const b = { perms: { jellyfin_user: jfUser.value.trim() } }; if (plTok.value) b.paperless_token = plTok.value; if (pw.value) b.password = pw.value; save(b); } }, "Zugänge speichern"),
            u.paperless_token ? h("button", { class: "btn sec", type: "button", onClick: () => save({ paperless_token: "" }) }, "Paperless-Token entfernen") : null,
            h("button", { class: "btn sec", type: "button", onClick: () => save({ unlock: true }) }, "Sperre nach Fehlversuchen aufheben"),
            h("button", { class: u.disabled ? "btn sec" : "btn danger", type: "button", onClick: () => save({ disabled: !u.disabled }) }, u.disabled ? "Konto entsperren" : "Konto sperren"))),
        form("Für alle Benutzer", [
          ["chat.admin_read", "Administratoren dürfen Chats anderer lesen", "toggle", "Nur lesen. Jede Einsicht steht im Protokoll, und Mitglieder sehen einen Hinweis darauf."],
          ["chat.retention_days", "Chats löschen nach", "seg", null, [[30, "30 Tagen"], [90, "90 Tagen"], [180, "180 Tagen"]]],
          ["chat.keep_pinned", "Angeheftete Chats behalten", "toggle"],
          ["suggestions.mode", "Vorschläge erstellen", "seg", "Das Hilfsmodell liest die letzten Chats und schlägt neue Fragen vor.", [["night", "Im Nachtplan"], ["idle", "Wenn frei"], ["off", "Aus"]]],
          ["session.idle_hours", "Automatisch abmelden nach (Stunden ohne Aktivität)", "number"],
          ["login.max_failed", "Notfall-Zugang: Sperre nach Fehlversuchen", "number"], ["login.lock_minutes", "Sperrdauer in Minuten", "number"],
          ["schedules.max_per_user", "Geplante Prompts pro Person", "number"]]));
    },
    // ------------------------------------------------------------ Protokoll
    async audit(c) {
      A.cache.audit = A.cache.audit || { category: "", q: "", days: 30 };
      const f = A.cache.audit;
      const rows = await api("GET", `/api/admin/audit?category=${encodeURIComponent(f.category)}&q=${encodeURIComponent(f.q)}&days=${f.days}`);
      const q = h("input", { class: "inp", value: f.q, placeholder: "Suchen", "aria-label": "Protokoll durchsuchen", style: { maxWidth: "260px" } });
      q.addEventListener("change", () => { f.q = q.value; rerender(); });
      c.append(h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center" } },
        seg([["", "Alles"], ["Aktion", "Aktionen"], ["Einstellung", "Einstellungen"], ["Anmeldung", "Anmeldungen"], ["Einsicht", "Einsicht"], ["System", "System"], ["Sicherung", "Sicherung"]], f.category, (v) => { f.category = v; rerender(); }, "Bereich"),
        q, h("a", { class: "btn sec", href: "/api/admin/audit.csv" }, "Als CSV exportieren")),
        h("p", { class: "tiny muted", style: { margin: 0 } }, "Einträge bleiben 365 Tage erhalten."),
        h("div", { class: "panel", style: { padding: "8px 12px" } }, h("div", { class: "tablewrap" }, h("table", { class: "t" }, h("thead", null, h("tr", null, ["Zeit", "Wer", "Bereich", "Was"].map((x) => h("th", null, x)))),
          h("tbody", null, rows.map((r) => h("tr", null, h("td", { style: { whiteSpace: "nowrap" } }, fmtDate(r.ts)), h("td", null, r.user), h("td", null, r.category), h("td", null, r.text))))))),
        !rows.length ? h("p", { class: "muted" }, "Keine Einträge.") : null);
    },
  };

  window.HKAdmin = { render };
})();
