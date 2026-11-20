/* Haus-KI – Administration: System (Ollama-Server, Proxmox, Updates und Sicherung). Wird nach admin.js geladen. */
"use strict";
(function () {
  const { h, api, toast, toggle, seg, fmtN, fmtDate, fmtGB, av, confirmDialog, go } = window.HK;
  const { A, form, saveFields, rerender, val, isSecret } = window.HKAdmin.kit;

  Object.assign(window.HKAdmin.sections, {
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
        c.appendChild(h("section", { class: "panel" }, h("h3", null, "Agent installieren"), h("p", { class: "small u-m0" }, "Im Ollama-Container als root ausführen (in Proxmox: Container › Konsole):"),
          h("pre", { class: "md u-m0" }, h("code", null, `curl -fsSL ${A.settings.base_url}/agent/install.sh | sudo bash`)),
          h("p", { class: "tiny muted u-m0" }, "Das Skript zeigt am Ende Adresse und Token. Beides oben eintragen."),
          h("button", { class: "btn sec u-start", type: "button", onClick: async () => { await api("POST", "/api/admin/agent/reset-fingerprint"); toast("Zertifikat zurückgesetzt."); } }, "Gemerktes Zertifikat zurücksetzen")));
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
          h("button", { class: "btn u-start", type: "button", onClick: async () => {
            try { const r = await api("PUT", "/api/admin/agent/guard", { enabled, allow: allow.value.split(/[ ,;]+/).filter(Boolean) });
              toast(r.enabled ? (r.active ? "Schutz aktiv." : "Schutz konnte nicht aktiviert werden: " + (r.error || "")) : "Schutz ausgeschaltet.", r.enabled && !r.active); rerender(); }
            catch (e) { toast(e.message, true); } } }, "Speichern")));
      } catch (e) { c.append(h("div", { class: "note warn" }, "Der Schutz für Ollama lässt sich nur mit aktuellem Agenten verwalten: " + e.message)); }
      const vars = { ...env.vars };
      const rows = h("div");
      const preview = h("pre", { class: "md u-m0" });
      const draw = () => {
        rows.innerHTML = "";
        for (const [k, help] of KNOWN) rows.appendChild(h("label", { class: "f", style: { padding: "6px 0" } }, k, h("input", { class: "inp", value: vars[k] || "", placeholder: "nicht gesetzt", onInput: (e) => { if (e.target.value) vars[k] = e.target.value; else delete vars[k]; drawPreview(); } }), h("span", { class: "h" }, help)));
      };
      const drawPreview = () => { preview.innerHTML = ""; preview.appendChild(h("code", null, "[Service]\n" + Object.entries(vars).map(([k, v]) => `Environment="${k}=${v}"`).join("\n"))); };
      draw(); drawPreview();
      c.append(h("section", { class: "panel" }, h("h3", null, "Umgebungsvariablen"), h("p", { class: "small muted u-m0" }, `Datei ${env.path} in ${env.hostname}`), rows,
        h("div", { class: "tiny muted" }, "Vorschau"), preview,
        h("div", { class: "u-row u-wrap" },
          h("button", { class: "btn", type: "button", onClick: async () => {
            if (!(await confirmDialog("Speichern und Ollama neu starten?", "Laufende Antworten brechen ab. Der Neustart dauert etwa 20 Sekunden, danach wird das Standardmodell neu geladen.", "Neu starten"))) return;
            try { await api("PUT", "/api/admin/agent/env", { vars, restart: true }); toast("Gespeichert, Ollama läuft wieder."); } catch (e) { toast(e.message, true); } } }, "Speichern und neu starten"),
          h("button", { class: "btn sec", type: "button", onClick: async () => { try { await api("PUT", "/api/admin/agent/env", { vars }); toast("Gespeichert. Wirkt nach dem nächsten Neustart."); } catch (e) { toast(e.message, true); } } }, "Nur speichern"))));
      const upd = h("span", { class: "small", role: "status" });
      c.append(h("section", { class: "panel" }, h("h3", null, "Ollama aktualisieren"), h("p", { class: "small muted u-m0" }, `Installiert: ${env.ollama_version || "unbekannt"}. Die Aktualisierung nutzt das offizielle Installationsskript von ollama.com.`),
        h("div", { class: "u-row u-wrap u-center" },
          h("button", { class: "btn sec", type: "button", onClick: async () => {
            if (!(await confirmDialog("Ollama aktualisieren?", "Ollama wird dabei neu gestartet.", "Aktualisieren"))) return;
            await api("POST", "/api/admin/agent/update"); upd.textContent = "Läuft …";
            const t = setInterval(async () => { const s = await api("POST", "/api/admin/agent/update-status"); upd.textContent = s.status === "running" ? "Läuft …" : s.status === "done" ? "Fertig, Version " + (s.version || "") : "Fehler: " + (s.output || "").slice(-200); if (s.status !== "running") clearInterval(t); }, 4000);
          } }, "Jetzt aktualisieren"), upd),
        h("button", { class: "act u-start", type: "button", onClick: async (e) => { const l = await api("POST", "/api/admin/agent/logs"); e.target.replaceWith(h("pre", { class: "md", style: { maxHeight: "300px", overflow: "auto", margin: 0 } }, h("code", null, l.lines))); } }, "Letzte Log-Zeilen anzeigen")));
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
          h("p", { class: "small muted u-m0" }, "Während der Container neu startet, kann Haus-KI nicht antworten. Haus-Schnellsteuerung und alte Chats funktionieren weiter."),
          h("div", { class: "u-row u-wrap" }, cmd("start", "Starten", "Der Container wird gestartet."), cmd("reboot", "Neu starten", "Laufende Antworten brechen ab."), cmd("shutdown", "Herunterfahren", "Haus-KI kann danach keine Fragen mehr beantworten, bis die VM wieder läuft."))));
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
            av.configured ? h("p", { class: "small muted u-m0" }, `Aktuell, zuletzt geprüft ${av.checked ? fmtDate(av.checked) : "nie"}.`) : null,
          h("div", { class: "u-row u-wrap" },
            h("button", { class: "btn sec", type: "button", onClick: async () => { try { const r = await api("POST", "/api/admin/update/check"); toast(r.available ? `Version ${r.version} ist verfügbar.` : "Haus-KI ist aktuell."); rerender(); } catch (e) { toast(e.message, true); } } }, "Jetzt prüfen"),
            av.available ? h("button", { class: "btn", type: "button", onClick: async () => {
              if (!(await confirmDialog(`Auf ${av.version} aktualisieren?`, "Das Paket wird heruntergeladen und über seine Prüfsumme kontrolliert. Vorher wird gesichert. Startet die neue Version nicht, kehrt Haus-KI von selbst zurück.", "Aktualisieren"))) return;
              try { await api("POST", "/api/admin/update/install-available"); toast("Update wird installiert. Die Seite lädt in etwa einer Minute neu."); setTimeout(() => location.reload(), 60000); } catch (e) { toast(e.message, true); } } }, `Auf ${av.version} aktualisieren`) : null)) }));
      c.append(h("section", { class: "panel" }, h("h3", null, "Haus-KI aktualisieren"), h("p", { class: "small u-m0" }, `Installierte Version: ${u.version}`),
        u.status && u.status.state ? h("div", { class: "note " + (u.status.state === "ok" ? "ok" : u.status.state === "error" ? "err" : "") }, u.status.message || u.status.state) : null,
        h("p", { class: "small muted u-m0" }, "Lade ein Haus-KI-Paket hoch. Vor dem Update wird automatisch gesichert. Startet die neue Version nicht, kehrt Haus-KI von selbst zur vorherigen zurück."),
        pkg, h("div", { class: "u-row u-wrap" },
          h("button", { class: "btn", type: "button", onClick: async () => { if (!pkg.files[0]) return toast("Bitte ein Paket wählen.", true); const fd = new FormData(); fd.append("file", pkg.files[0]); try { await api("POST", "/api/admin/update", fd); toast("Update wird installiert. Die Seite lädt in etwa einer Minute neu."); setTimeout(() => location.reload(), 60000); } catch (e) { toast(e.message, true); } } }, "Update installieren"),
          h("button", { class: "btn sec", type: "button", onClick: async () => { if (await confirmDialog("Zur vorherigen Version zurück?", "Haus-KI startet dabei neu.", "Zurückkehren")) { await api("POST", "/api/admin/update/rollback"); toast("Wird zurückgesetzt."); } } }, "Vorherige Version"))),
        form("Nächtliche Sicherung", [["backup.enabled", "Jede Nacht sichern", "toggle", "Datenbank mit Chats, Einstellungen und Protokoll. Für den ganzen Container zusätzlich die Proxmox-Sicherung nutzen."], ["backup.keep", "Aufbewahren (Anzahl)", "number"], ["night.start", "Nachtplan startet um", "text", "z. B. 02:00"]]),
        h("section", { class: "panel" }, h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px", flexWrap: "wrap" } }, h("h3", null, "Vorhandene Sicherungen"),
          h("button", { class: "btn sec", type: "button", onClick: async () => { await api("POST", "/api/admin/backups"); toast("Sicherung erstellt."); rerender(); } }, "Jetzt sichern")),
          b.backups.length ? b.backups.map((x) => h("div", { class: "list-row" }, h("span", { class: "grow" }, fmtDate(x.created), h("span", { class: "tiny muted" }, ` · ${fmtN(x.size / 1e6, 1)} MB`)),
            h("a", { class: "act", href: "/api/admin/backups/" + encodeURIComponent(x.name) }, "Herunterladen"),
            h("button", { class: "act", type: "button", style: { color: "var(--warn)" }, onClick: async () => { if (!(await confirmDialog("Wiederherstellen?", "Der aktuelle Stand wird vorher gesichert und dann durch diese Sicherung ersetzt.", "Wiederherstellen"))) return; await api("POST", "/api/admin/backups/restore", { name: x.name }); toast("Wiederhergestellt."); setTimeout(() => location.reload(), 1500); } }, "Wiederherstellen"))) :
            h("p", { class: "small muted u-m0" }, "Noch keine Sicherung.")));
    },
  });
})();
