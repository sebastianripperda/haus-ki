/* Haus-KI – Administration: Anbindungen (Quellen, Haus/KNX, Microsoft 365). Wird nach admin.js geladen. */
"use strict";
(function () {
  const { h, api, toast, toggle, seg, fmtN, fmtDate, fmtGB, av, confirmDialog, go } = window.HK;
  const { A, form, saveFields, rerender, val, isSecret } = window.HKAdmin.kit;

  Object.assign(window.HKAdmin.sections, {
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
        form("Weitere Postfächer", [["mail.allow_gmx", "GMX erlauben", "toggle"], ["mail.allow_gmail", "Gmail erlauben", "toggle", "Braucht ein App-Passwort von Google."],
          ["mail.allow_imap", "Weitere Anbieter mit Benutzername und Passwort erlauben", "toggle", "WEB.DE, T-Online, iCloud, Yahoo und eigene Mailserver (IMAP, verschlüsselt)."],
          ["mail.allow_outlookcom", "Outlook.com erlauben", "toggle", "Braucht eine App-Registrierung, die auch private Microsoft-Konten zulässt."], ["mail.night_scan", "Nachts auf Rechnungen und Fristen prüfen", "toggle", "Neue Mails im Posteingang werden auf Rechnung, Mahnung, Fälligkeit und Betrag durchsucht und erscheinen unter „Im Blick“."], ["mail.drafts", "Entwürfe erlauben", "toggle", "Jede Person schaltet das pro Postfach zusätzlich selbst ein."]],
          { intro: "Jede Person verbindet ihre Postfächer selbst unter Meine Konten." }),
        form("Internet", [["web.enabled", "Internet verwenden", "toggle"], ["web.provider", "Suchdienst", "seg", null, [["ollama", "Ollama Web Search"], ["searxng", "Eigenes SearXNG"]]],
          ["web.ollama_key", "Ollama-API-Schlüssel", "text", "Kostenloses Konto auf ollama.com › Settings › Keys."], ["web.searxng_url", "SearXNG-Adresse", "text", "Nur bei eigenem SearXNG, JSON-Ausgabe muss aktiv sein."],
          ["web.max_results", "Treffer pro Suche", "number"]], { test: "web" }),
        h("section", { class: "panel" }, h("h3", null, "Feste Sicherheitsregeln"), h("p", { class: "small muted u-m0" }, "Diese Regeln sind eingebaut und lassen sich nicht abschalten."),
          ["Jede Aktion braucht eine Bestätigung im Chat.", "Inhalte aus dem Internet lösen nie Aktionen aus und schreiben nichts ins Gedächtnis.", "Spam-Ordner werden nie gelesen.", "Mails werden nie gesendet, nur als Entwurf gespeichert.", "Haustür, Garagentor und Alarmanlage sind nur lesbar."].map((t) => h("div", { class: "small u-row" }, window.HK.icon("lock", 16), t))));
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
        extra: h("div", { class: "u-row u-wrap u-center" }, keyIn, h("button", { class: "btn sec", type: "button", onClick: () => keyIn.click() }, "Keyring hochladen"), h("span", { class: "small muted" }, d.keyring ? "Keyring vorhanden" : "Kein Keyring")) }),
        h("section", { class: "panel" }, h("h3", null, "ETS-Projekt importieren"),
          h("p", { class: "small muted u-m0" }, "Liest Gruppenadressen, Namen und Datentypen. Bestehende Freigaben bleiben erhalten. Haustür, Garagentor und Alarm werden erkannt und fest auf „nur lesen“ gesetzt."),
          h("div", { class: "grid2" }, projIn, projPw),
          h("button", { class: "btn u-start", type: "button", onClick: async () => {
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
          h("button", { class: "btn u-start", type: "button", onClick: async () => { const r = await api("PUT", "/api/admin/knx/ga", { permissions: changes }); toast(`${r.changed} Freigaben gespeichert.`); rerender(); } }, "Freigaben speichern")] :
          h("p", { class: "small muted u-m0" }, "Noch keine Gruppenadressen. Importiere zuerst das ETS-Projekt.")));
      // Szenen und Fenster
      const scenes = h("textarea", { class: "inp", rows: 6, value: (val("knx.scenes") || []).map((s) => s.name + ": " + s.writes.map((w) => `${w.address}=${w.value}`).join(", ")).join("\n") });
      c.append(h("section", { class: "panel" }, h("h3", null, "Schnellsteuerung"),
        h("label", { class: "f" }, "Szenen, eine pro Zeile: Name: Adresse=Wert, Adresse=Wert (nur Administratoren können sie auslösen)", scenes),
        h("p", { class: "tiny muted u-m0" }, "Beispiel: Filmabend: 1/1/5=false, 2/1/3=80, 1/1/9=true"),
        h("button", { class: "btn u-start", type: "button", onClick: async () => {
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
        h("p", { class: "tiny muted u-m0" }, "Benutzer werden über die Objekt-ID ihres Entra-Kontos zugeordnet, nicht über die E-Mail.")),
        form("Verbindung", [["ms.enabled", "Microsoft 365 verwenden (Anmeldung und Datenquelle)", "toggle"], ["ms.tenant_id", "Verzeichnis-ID (Tenant)", "text"], ["ms.client_id", "Anwendungs-ID (Client)", "text"], ["ms.client_secret", "Geheimer Clientschlüssel", "text"]], { test: "ms" }),
        form("Berechtigungen", [["ms.mail", "Outlook lesen (Mail.Read)", "toggle"], ["ms.mail_drafts", "Entwürfe speichern (Mail.ReadWrite)", "toggle"], ["ms.calendar", "Kalender lesen (Calendars.Read)", "toggle"],
          ["ms.files", "OneDrive und SharePoint (Files.Read.All, Sites.Read.All)", "toggle"], ["ms.todo", "To Do: Aufgaben und Einkaufslisten (Tasks.ReadWrite)", "toggle"],
          ["ms.cal_check", "Familienkalender-Abgleich (Calendars.Read.Shared)", "toggle", "Prüft jeden Morgen die nächsten 7 Tage. Aus persönlichen Kalendern nur „belegt“, Titel nur aus dem gemeinsamen Kalender."],
          ["ms.family_calendar_owner", "Wem gehört der gemeinsame Kalender (E-Mail)", "text"], ["ms.family_calendar_name", "Name des gemeinsamen Kalenders", "text"], ["ms.todo_list", "To-Do-Liste für Einkaufslisten", "text"]],
          { intro: "Geänderte Berechtigungen gelten nach der nächsten Anmeldung jeder Person." }));
    },
  });
})();
