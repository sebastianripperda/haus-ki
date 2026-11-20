/* Haus-KI – Administration: KI und Antworten (Übersicht, Qualität, Sprache, Anfrage-Standards, Modelle, Profile). Wird nach admin.js geladen. */
"use strict";
(function () {
  const { h, api, toast, toggle, seg, fmtN, fmtDate, fmtGB, av, confirmDialog, go } = window.HK;
  const { A, form, saveFields, rerender, val, isSecret } = window.HKAdmin.kit;

  function voiceList(d) {
    const box = h("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } });
    box.appendChild(h("div", { class: "small muted" }, "Installierte Stimmen"));
    if (!d.voices.length) box.appendChild(h("p", { class: "tiny muted u-m0" }, "Noch keine. Die Standardstimme wird beim ersten Vorlesen oder mit „Modelle jetzt laden“ heruntergeladen."));
    for (const v of d.voices) box.appendChild(h("div", { class: "list-row" }, h("span", { class: "grow" }, h("b", null, v.name), h("span", { class: "tiny muted mono" }, "  " + v.id)),
      v.id === d.default_voice ? h("span", { class: "badge" }, "Standard") : null));
    const missing = d.known.filter((k) => !d.voices.some((v) => v.id === k.id));
    if (missing.length) box.appendChild(h("div", { class: "follow" }, missing.map((k) => h("button", { class: "chip", type: "button", onClick: async (e) => {
      e.target.textContent = "Lädt …";
      try { await api("POST", "/api/admin/voice/install", { id: k.id }); toast(`Stimme ${k.name} installiert.`); rerender(); } catch (err) { toast(err.message, true); e.target.textContent = `${k.name} installieren`; } } }, `${k.name} installieren`))));
    const cat = h("button", { class: "btn sec u-start", type: "button", onClick: async () => {
      cat.textContent = "Katalog wird geladen …";
      try {
        const list = await api("GET", "/api/admin/voice/catalog");
        const sel = h("select", { class: "inp", "aria-label": "Weitere deutsche Stimmen" }, list.map((x) => h("option", { value: x.id, "data-path": x.path }, `${x.id} (${x.quality}, ${fmtN(x.size / 1e6, 0)} MB)`)));
        const btn = h("button", { class: "btn", type: "button", onClick: async () => { const o = sel.selectedOptions[0]; btn.textContent = "Lädt …";
          try { await api("POST", "/api/admin/voice/install", { id: o.value, path: o.dataset.path }); toast("Stimme installiert."); rerender(); } catch (err) { toast(err.message, true); btn.textContent = "Installieren"; } } }, "Installieren");
        cat.replaceWith(h("div", { class: "u-row" }, sel, btn));
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
      h("p", { class: "small muted u-m0" }, "Dieselben Fragen an zwei Modelle, Antworten nebeneinander mit Zeit und Tempo. Läuft im Hintergrund hinter allen Fragen der Familie. Bewerte die Antworten in den Testchats mit dem Daumen, das Ergebnis erscheint hier."),
      h("div", { class: "note" }, h("b", null, "Für eure Ausstattung (nur CPU, viel RAM) lohnen sich MoE-Modelle: "), "Sie haben viel Wissen, rechnen pro Wort aber nur einen kleinen Teil. ",
        h("span", { class: "mono" }, "qwen3:30b-a3b"), " (etwa 19 GB) ist auf der CPU ähnlich schnell wie qwen3:8b und antwortet meist besser, ", h("span", { class: "mono" }, "gpt-oss:20b"),
        " (etwa 14 GB) ist stark bei Werkzeugen. Laden unter Modelle, dann hier vergleichen."),
      models.length < 2 ? h("div", { class: "note warn" }, models.length ? "Für einen Vergleich braucht es mindestens zwei Modelle. Lade ein zweites unter Modelle." : "Ollama ist gerade nicht erreichbar.") :
        h("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: "8px" } }, h("label", { class: "f" }, "Modell A", selA), h("label", { class: "f" }, "Modell B", selB)),
      setBox,
      h("button", { class: "btn u-start", type: "button", onClick: async () => {
        try { const r = await api("POST", "/api/admin/quality/compare", { model_a: selA.value, model_b: selB.value, set }); toast(`${r.questions} Testchats angelegt. Die Antworten kommen nach und nach.`); await window.HK.loadChats(); rerender(); }
        catch (e) { toast(e.message, true); } } }, "Vergleich starten"),
      runs.length ? h("div", { class: "tablewrap" }, h("table", { class: "t" },
        h("thead", null, h("tr", null, ["Lauf", "Modell", "Antworten", "Ø Dauer", "Ø Tempo", "👍 / 👎"].map((x) => h("th", null, x)))),
        h("tbody", null, runs.flatMap((r) => r.models.map((m, i) => h("tr", null,
          h("td", { class: "small" }, i === 0 ? `${fmtDate(r.started)} · ${r.done} von ${r.n} fertig` : ""),
          h("td", { class: "mono" }, m.model), h("td", { class: "mono" }, `${m.answers}`),
          h("td", { class: "mono" }, m.answers ? `${fmtN(m.avg_seconds, 1)} s` : "–"), h("td", { class: "mono" }, m.answers ? `${fmtN(m.avg_tps, 1)} Token/s` : "–"),
          h("td", { class: "mono" }, `${m.up} / ${m.down}`))))))) : null,
      runs.length ? h("p", { class: "tiny muted u-m0" }, "Die Testchats stehen in deiner Seitenleiste unter „Vergleich: …“.") : null);
  }

  function autoPanel() {
    const CATS = [["knx_light", "Licht schalten und dimmen", "Erkannt am Namen der Gruppenadresse, z. B. „Licht“, „Lampe“, „Spot“."],
      ["knx_blind", "Rollläden und Jalousien", "Erkannt an „Rollladen“, „Jalousie“, „Raffstore“, „Markise“."],
      ["knx_climate", "Heizung: Solltemperatur", "Nur Sollwerte (DPT 9.001) mit „Soll“, „Temperatur“ oder „Heizung“ im Namen."],
      ["jellyfin_play", "Filme und Musik abspielen", "Startet die Wiedergabe auf einem Jellyfin-Gerät."],
      ["todo_add", "Einträge in To Do anlegen", "Zum Beispiel die Einkaufsliste aus dem Wochenplan."]];
    const cur = new Set(val("actions.auto_allowed") || []);
    const box = h("section", { class: "panel" }, h("h3", null, "Ohne Rückfrage erlaubt"),
      h("p", { class: "small muted u-m0" }, "Was hier erlaubt ist, kann jede Person mit der Freigabe „Harmloses ohne Rückfrage“ unter „Einstellungen für mich“ für sich einschalten. Haustür, Garage, Alarm, Mails, Entwürfe und Paperless fragen immer nach. Nach Webinhalten gibt es nie Aktionen."));
    for (const [id, label, help] of CATS) box.appendChild(toggle(label, cur.has(id), async (v) => {
      if (v) cur.add(id); else cur.delete(id);
      await api("PUT", "/api/admin/settings", { "actions.auto_allowed": [...cur] });
      A.settings = null; toast("Gespeichert."); rerender();
    }, help));
    return box;
  }


  Object.assign(window.HKAdmin.sections, {
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
              h("p", { class: "small muted u-m0" }, o.vm && o.vm.error ? o.vm.error : "Proxmox ist nicht verbunden."))),
        o.warnings.length ? h("div", { class: "panel" }, h("h3", null, "Hinweise"), o.warnings.map((w) => h("div", { class: "note warn" }, w))) : null,
        h("div", { class: "panel" }, h("h3", null, "Nutzung, letzte 30 Tage"),
          o.usage.map((u) => h("div", { style: { display: "grid", gridTemplateColumns: "32px 100px 1fr 60px", gap: "10px", alignItems: "center" } }, av({ ...u, initial: u.name[0] }), h("span", null, u.name),
            h("span", { class: "bar" }, h("span", { style: { width: (u.questions / maxQ) * 100 + "%" } })), h("span", { class: "small", style: { textAlign: "right" } }, fmtN(u.questions))))),
        h("div", { class: "panel" },
          h("div", { style: { display: "flex", justifyContent: "space-between", gap: "12px", flexWrap: "wrap", alignItems: "baseline" } }, h("h3", null, "Nachtplan" + (o.night.date ? `, Nacht zum ${o.night.date.split("-").reverse().join(".")}` : "")),
            h("button", { class: "btn sec", type: "button", onClick: async () => { await api("POST", "/api/admin/night/run"); toast("Nachtplan gestartet. Die Aufgaben laufen nacheinander."); } }, "Jetzt ausführen")),
          h("p", { class: "small muted u-m0" }, `Startet um ${A.settings.values["night.start"]} Uhr. Die Aufgaben laufen nacheinander, damit sich die CPU nicht verzettelt. Fragen haben immer Vorrang.`),
          o.night.runs.length ? h("div", { class: "tablewrap" }, h("table", { class: "t" }, h("thead", null, h("tr", null, ["Start", "Aufgabe", "Dauer", "Ergebnis"].map((x) => h("th", null, x)))),
            h("tbody", null, o.night.runs.map((r) => h("tr", null, h("td", null, new Date(r.started * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })), h("td", null, r.task),
              h("td", null, r.finished ? Math.max(1, Math.round((r.finished - r.started) / 60)) + " Min" : "läuft"), h("td", { style: { color: r.status === "error" ? "var(--err)" : null } }, r.detail || r.status)))))) : h("p", { class: "small muted u-m0" }, "Noch kein Lauf.")),
        h("div", { class: "grid2" },
          h("div", { class: "panel" }, h("h3", null, "Bewertungen, letzte 30 Tage"), h("div", { style: { display: "flex", gap: "24px" } },
            h("div", null, h("div", { class: "tiny muted" }, "Daumen hoch"), h("b", { style: { fontSize: "24px", color: "var(--ok)" } }, o.feedback.up)),
            h("div", null, h("div", { class: "tiny muted" }, "Daumen runter"), h("b", { style: { fontSize: "24px", color: "var(--err)" } }, o.feedback.down))),
            o.feedback.worst.length ? [h("div", { class: "tiny muted" }, "Am häufigsten schlecht bewertet"), o.feedback.worst.map((w) => h("div", { class: "small" }, `${w.title} (${w.n})`))] : null),
          h("div", { class: "panel" }, h("h3", null, "Fehler, letzte 30 Tage"), o.errors.length ? o.errors.map((e) => h("div", { class: "small" }, h("span", { class: "muted" }, fmtDate(e.ts) + " "), e.text)) : h("p", { class: "small muted u-m0" }, "Keine."))));
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
            h("p", { class: "small muted u-m0" }, "Noch keine Werkzeugaufrufe."),
          h("p", { class: "tiny muted u-m0" }, "Viele Fehler bei einem Werkzeug deuten meist auf ein zu kleines Modell oder eine nicht erreichbare Quelle hin.")),
        h("section", { class: "panel" }, h("div", { style: { display: "flex", justifyContent: "space-between", gap: "12px", flexWrap: "wrap", alignItems: "baseline" } },
            h("h3", null, "Schlecht bewertete Antworten"), h("a", { class: "btn sec", href: "/api/admin/quality/export" }, "Als Testliste exportieren")),
          q.bad.length ? q.bad.map((b) => h("div", { style: { borderTop: "1px solid var(--row)", padding: "10px 0", display: "flex", flexDirection: "column", gap: "4px" } },
            h("div", { class: "tiny muted" }, `${fmtDate(b.created)} · ${b.user} · ${b.model}${b.routed ? " (schnelles Modell)" : ""}${b.sources.length ? " · " + b.sources.join(", ") : ""}`),
            h("b", null, b.question || "(Frage nicht mehr vorhanden)"),
            b.comment ? h("div", { class: "note warn" }, b.comment) : null,
            h("details", null, h("summary", { class: "small", style: { cursor: "pointer" } }, "Antwort anzeigen"), h("div", { class: "md small", html: MD.render(b.answer) })),
            h("div", { class: "u-row u-wrap" },
              h("a", { class: "act", href: "#chat/" + b.chat_id }, "Chat öffnen"),
              h("button", { class: "act", type: "button", style: { color: "var(--accent)" }, onClick: async () => { const r = await api("POST", `/api/admin/quality/rerun/${b.message_id}`); await window.HK.loadChats(); go("#chat/" + r.chat_id); } }, "Mit heutigen Einstellungen erneut testen")))) :
            h("p", { class: "small muted u-m0" }, "Keine. Antworten bewertet die Familie mit dem Daumen unter jeder Antwort.")),
        h("section", { class: "panel" }, h("h3", null, "Paperless-Suche nach Bedeutung"),
          h("p", { class: "small u-m0" }, sem.enabled ? `${sem.docs} Dokumente in ${sem.chunks} Abschnitten indiziert, Modell ${sem.model}. ${sem.since ? "Zuletzt aktualisiert " + sem.since.replace("T", " ") + "." : "Noch kein Lauf."}` : "Ausgeschaltet. Einschalten unter Quellen › Paperless."),
          h("p", { class: "tiny muted u-m0" }, "Der Index wird nachts im Nachtplan ergänzt. Der erste Aufbau dauert je nach Anzahl der Dokumente einige Minuten. Treffer werden immer mit den Paperless-Rechten der fragenden Person geprüft."),
          sem.enabled ? h("button", { class: "btn sec u-start", type: "button", onClick: async () => { await api("POST", "/api/admin/semantic/rebuild"); toast("Der Index wird neu aufgebaut. Fortschritt im Nachtplan in der Übersicht."); } }, "Index jetzt neu aufbauen") : null),
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
        h("button", { class: "btn sec u-start", type: "button", onClick: async () => { await api("POST", "/api/admin/voice/prepare"); toast("Modelle werden geladen. Das dauert je nach Leitung ein bis zwei Minuten."); setTimeout(rerender, 4000); } }, "Modelle jetzt laden"));
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
            .map((t) => h("div", { class: "small u-row" }, window.HK.icon("lock", 16), t))));
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
          h("p", { class: "small muted u-m0" }, "Empfehlungen für 8 CPU-Kerne ohne Grafikkarte: qwen3:8b (Standard), llama3.2:3b (schnelles Hilfsmodell), gemma3:4b (Bilder erkennen). Modelle über 14B sind auf der CPU sehr langsam."),
          h("div", { class: "u-row" }, pullName, h("button", { class: "btn", type: "button", onClick: async () => {
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
          h("p", { class: "tiny muted u-m0" }, "Das Standardmodell bleibt dauerhaft geladen. Ein zweites großes Modell verdrängt es aus dem Speicher.")));
    },
    // ------------------------------------------------------------ Modell-Profile
    async profiles(c) {
      const d = await api("GET", "/api/admin/models");
      const f = { name: h("input", { class: "inp", placeholder: "z. B. haus-ki-genau" }), from: h("select", { class: "inp" }, d.models.map((m) => h("option", { value: m.name, selected: m.name === d.default }, m.name))),
        system: h("textarea", { class: "inp", rows: 4, placeholder: "Feste Anweisung für dieses Profil" }), temp: h("input", { class: "inp", type: "number", step: 0.1, placeholder: "z. B. 0.3" }), ctx: h("input", { class: "inp", type: "number", step: 1024, placeholder: "z. B. 8192" }) };
      c.append(h("section", { class: "panel" }, h("h3", null, "Neues Profil"),
        h("p", { class: "small muted u-m0" }, "Ein Profil ist ein eigenes Modell in Ollama (Modelfile) mit fester Anweisung und eigenen Werten. Es teilt sich den Speicher mit dem Basismodell."),
        h("div", { class: "grid2" }, h("label", { class: "f" }, "Name", f.name), h("label", { class: "f" }, "Basismodell", f.from)),
        h("label", { class: "f" }, "Systemanweisung", f.system),
        h("div", { class: "grid2" }, h("label", { class: "f" }, "Temperatur", f.temp), h("label", { class: "f" }, "Kontextlänge", f.ctx)),
        h("button", { class: "btn u-start", type: "button", onClick: async () => {
          try { await api("POST", "/api/admin/models/profile", { name: f.name.value, from: f.from.value, system: f.system.value, parameters: { temperature: f.temp.value ? +f.temp.value : null, num_ctx: f.ctx.value ? +f.ctx.value : null } }); toast("Profil erstellt. Es erscheint jetzt unter Modelle."); go("#models"); }
          catch (e) { toast(e.message, true); } } }, "Profil erstellen")));
    },
  });
})();
