/* Haus-KI – Administration: Menschen und Protokoll (Benutzer, Protokoll). Wird nach admin.js geladen. */
"use strict";
(function () {
  const { h, api, toast, toggle, seg, fmtN, fmtDate, fmtGB, av, confirmDialog, go } = window.HK;
  const { A, form, saveFields, rerender, val, isSecret } = window.HKAdmin.kit;

  Object.assign(window.HKAdmin.sections, {
    // ------------------------------------------------------------ Benutzer
    async users(c) {
      const list = await api("GET", "/api/admin/users");
      const knx = await api("GET", "/api/admin/knx").catch(() => ({ rooms: [] }));
      A.cache.sel = A.cache.sel || (list[0] && list[0].id);
      const u = list.find((x) => x.id === A.cache.sel) || list[0];
      const pick = h("div", { class: "follow" }, list.map((x) => h("button", { class: "chip", type: "button", "aria-pressed": x.id === u.id ? "true" : "false", style: x.id === u.id ? { borderColor: "var(--primary)" } : null, onClick: () => { A.cache.sel = x.id; rerender(); } }, av(x), x.name, x.disabled ? " (gesperrt)" : "")),
        h("button", { class: "chip", type: "button", "aria-expanded": A.cache.newUser ? "true" : "false", onClick: () => { A.cache.newUser = !A.cache.newUser; rerender(); } }, "+ Benutzer"));
      const ssoOn = !!A.settings.values["ms.enabled"];
      const minLen = A.settings.values["login.local_min_length"] || 8;
      const LOGIN = [["m365", "Microsoft 365"], ["local", "Lokal"], ["both", "Beides"]];
      const LOGIN_HELP = {
        m365: "Anmeldung nur über das Microsoft-Konto. Die Rolle kommt bei jeder Anmeldung aus Entra.",
        local: "Anmeldung nur mit Haus-KI-Passwort, ohne Microsoft-Konto. Microsoft-365-Daten (Kalender, Outlook, OneDrive) stehen dann nicht zur Verfügung.",
        both: "Anmeldung über Microsoft oder mit Haus-KI-Passwort, zum Beispiel wenn Microsoft gerade nicht erreichbar ist.",
      };
      // ---- Neuen Benutzer anlegen (erscheint unter der Personenauswahl)
      let newPanel = null;
      if (A.cache.newUser) {
        const nu = A.cache.nu = A.cache.nu || { role: "member", login: ssoOn ? "m365" : "local" };
        const name = h("input", { class: "inp", id: "nu_name", value: nu.name || "", autocomplete: "off", onInput: (e) => { nu.name = e.target.value; } });
        const email = h("input", { class: "inp", id: "nu_mail", type: "email", value: nu.email || "", autocomplete: "off", onInput: (e) => { nu.email = e.target.value; } });
        const pw1 = h("input", { class: "inp", id: "nu_pw1", type: "password", autocomplete: "new-password" });
        const pw2 = h("input", { class: "inp", id: "nu_pw2", type: "password", autocomplete: "new-password" });
        const err = h("p", { class: "small", role: "alert", style: { color: "var(--err)", margin: 0 } });
        const needPw = nu.login !== "m365";
        newPanel = h("section", { class: "panel" }, h("h3", null, "Neuen Benutzer anlegen"),
          h("div", { class: "grid2" }, h("label", { class: "f", for: "nu_name" }, "Vorname", name),
            h("label", { class: "f", for: "nu_mail" }, nu.login === "local" ? "E-Mail (optional)" : "E-Mail des Microsoft-Kontos (zum Verknüpfen bei der ersten Anmeldung)", email)),
          h("div", { class: "small muted" }, "Rolle"), seg([["member", "Mitglied"], ["admin", "Administrator"]], nu.role, (v) => { nu.role = v; rerender(); }, "Rolle"),
          h("div", { class: "small muted" }, "Anmeldung"), seg(LOGIN, nu.login, (v) => { nu.login = v; rerender(); }, "Anmeldung"),
          h("div", { class: "tiny muted" }, LOGIN_HELP[nu.login]),
          nu.login !== "local" && !ssoOn ? h("div", { class: "note warn" }, "Die Microsoft-Anmeldung ist noch nicht eingerichtet (Administration › Microsoft 365).") : null,
          needPw ? h("div", { class: "grid2" }, h("label", { class: "f", for: "nu_pw1" }, `Passwort (mindestens ${minLen} Zeichen)`, pw1), h("label", { class: "f", for: "nu_pw2" }, "Passwort wiederholen", pw2)) : null,
          err,
          h("div", { class: "u-row" },
            h("button", { class: "btn", type: "button", onClick: async () => {
              err.textContent = "";
              if (!name.value.trim()) { err.textContent = "Bitte einen Vornamen angeben."; return; }
              if (needPw && pw1.value !== pw2.value) { err.textContent = "Die Passwörter stimmen nicht überein."; return; }
              try {
                const r = await api("POST", "/api/admin/users", { name: name.value.trim(), email: email.value.trim(), role: nu.role, login: nu.login, local_password: needPw ? pw1.value : "" });
                A.cache.newUser = false; A.cache.nu = null; A.cache.sel = r.id; toast("Benutzer angelegt."); rerender();
              } catch (e) { err.textContent = e.message; }
            } }, "Anlegen"),
            h("button", { class: "btn sec", type: "button", onClick: () => { A.cache.newUser = false; A.cache.nu = null; rerender(); } }, "Abbrechen")));
      }
      const p = u.perms;
      const save = async (body) => { try { await api("PUT", "/api/admin/users/" + u.id, body); toast("Gespeichert."); rerender(); } catch (e) { toast(e.message, true); } };
      const perm = (k, label, help) => toggle(label, !!p[k], (v) => save({ perms: { [k]: v } }), help);
      const jfUser = h("input", { class: "inp", value: p.jellyfin_user || "", placeholder: "Jellyfin-Benutzer-ID" });
      const plTok = h("input", { class: "inp", type: "password", placeholder: u.paperless_token ? "•••• gespeichert" : "nicht gesetzt" });
      const pw = h("input", { class: "inp", type: "password", autocomplete: "new-password", placeholder: u.has_password ? "•••• gesetzt" : "nicht gesetzt" });
      const rooms = new Set(p.knx_rooms || []);
      // ---- Anmeldung pro Person: Microsoft 365, lokal oder beides
      function loginPanel() {
        const st = A.cache.login && A.cache.login.id === u.id ? A.cache.login : (A.cache.login = { id: u.id, mode: u.login });
        const needPw = st.mode !== "m365";
        const lp1 = h("input", { class: "inp", id: "lp1", type: "password", autocomplete: "new-password", placeholder: u.has_local_password ? "•••• gesetzt, leer lassen = unverändert" : "noch nicht gesetzt" });
        const lp2 = h("input", { class: "inp", id: "lp2", type: "password", autocomplete: "new-password" });
        const err = h("p", { class: "small", role: "alert", style: { color: "var(--err)", margin: 0 } });
        const changed = st.mode !== u.login;
        return h("section", { class: "panel" }, h("h3", null, "Anmeldung"),
          h("div", { class: "small muted" }, "Wie meldet sich " + u.name + " an?"),
          seg(LOGIN, st.mode, (v) => { st.mode = v; rerender(); }, "Anmeldeart"),
          h("div", { class: "tiny muted" }, LOGIN_HELP[st.mode]),
          st.mode !== "local" && !ssoOn ? h("div", { class: "note warn" }, "Die Microsoft-Anmeldung ist noch nicht eingerichtet (Administration › Microsoft 365). Bis dahin kann sich " + u.name + " so nicht anmelden.") : null,
          changed && st.mode === "local" && u.ms_connected ? h("div", { class: "note warn" }, "Die Verbindung zu Microsoft 365 wird getrennt, laufende Microsoft-Sitzungen werden beendet.") : null,
          changed && st.mode === "m365" && u.has_local_password ? h("div", { class: "note warn" }, "Laufende lokale Sitzungen werden beendet. Das lokale Passwort bleibt gespeichert, bis du es entfernst.") : null,
          needPw ? h("div", { class: "grid2" }, h("label", { class: "f", for: "lp1" }, `${u.has_local_password ? "Neues " : ""}Passwort für die lokale Anmeldung (mindestens ${minLen} Zeichen)`, lp1),
            h("label", { class: "f", for: "lp2" }, "Passwort wiederholen", lp2)) : null,
          needPw && u.has_local_password && !changed ? h("div", { class: "tiny muted" }, u.name + " kann das Passwort auch selbst unter „Einstellungen für mich“ ändern.") : null,
          err,
          h("div", { class: "u-row u-wrap" },
            h("button", { class: "btn", type: "button", onClick: async () => {
              err.textContent = "";
              const b = {};
              if (changed) b.login = st.mode;
              if (needPw && (lp1.value || lp2.value)) {
                if (lp1.value !== lp2.value) { err.textContent = "Die Passwörter stimmen nicht überein."; return; }
                b.local_password = lp1.value;
              }
              if (!Object.keys(b).length) { toast("Nichts geändert."); return; }
              try { await api("PUT", "/api/admin/users/" + u.id, b); A.cache.login = null; toast("Anmeldung gespeichert."); rerender(); }
              catch (e) { err.textContent = e.message; }
            } }, "Anmeldung speichern"),
            !needPw && !changed && u.has_local_password ? h("button", { class: "btn sec", type: "button", onClick: () => save({ remove_local_password: true }) }, "Lokales Passwort entfernen") : null));
      }
      c.append(pick, newPanel,
        h("section", { class: "panel" }, h("div", { style: { display: "flex", gap: "12px", alignItems: "center" } }, av(u, "lg"), h("div", null, h("h3", null, u.name), h("div", { class: "tiny muted" }, `${u.role === "admin" ? "Administrator" : "Mitglied"} · Anmeldung: ${{ m365: "Microsoft 365", local: "Lokal", both: "Microsoft 365 und lokal" }[u.login]} · ${u.email || "keine E-Mail"} · ${u.login === "local" ? "" : u.ms_connected ? "Microsoft verbunden · " : "Microsoft nicht verbunden · "}zuletzt ${u.last_seen ? fmtDate(u.last_seen) : "nie"}`))),
          h("div", { class: "small muted" }, u.login === "local" ? "Rolle" : "Rolle (wird bei jeder Microsoft-Anmeldung aus Entra übernommen)"),
          seg([["admin", "Administrator"], ["member", "Mitglied"]], u.role, (v) => save({ role: v })),
          h("div", { class: "tiny muted" }, "Microsoft-Objekt-ID: " + (u.oid || "noch nicht verknüpft"))),
        loginPanel(),
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
          h("div", { class: "u-row u-wrap" },
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
          ["login.local_min_length", "Lokale Anmeldung: Mindestlänge für Passwörter", "number"],
          ["login.max_failed", "Lokale Anmeldung und Notfall-Zugang: Sperre nach Fehlversuchen", "number"], ["login.lock_minutes", "Sperrdauer in Minuten", "number"],
          ["schedules.max_per_user", "Geplante Prompts pro Person", "number"]]));
    },
    // ------------------------------------------------------------ Protokoll
    async audit(c) {
      A.cache.audit = A.cache.audit || { category: "", q: "", days: 30 };
      const f = A.cache.audit;
      const rows = await api("GET", `/api/admin/audit?category=${encodeURIComponent(f.category)}&q=${encodeURIComponent(f.q)}&days=${f.days}`);
      const q = h("input", { class: "inp", value: f.q, placeholder: "Suchen", "aria-label": "Protokoll durchsuchen", style: { maxWidth: "260px" } });
      q.addEventListener("change", () => { f.q = q.value; rerender(); });
      c.append(h("div", { class: "u-row u-wrap u-center" },
        seg([["", "Alles"], ["Aktion", "Aktionen"], ["Einstellung", "Einstellungen"], ["Anmeldung", "Anmeldungen"], ["Einsicht", "Einsicht"], ["System", "System"], ["Sicherung", "Sicherung"]], f.category, (v) => { f.category = v; rerender(); }, "Bereich"),
        q, h("a", { class: "btn sec", href: "/api/admin/audit.csv" }, "Als CSV exportieren")),
        h("p", { class: "tiny muted u-m0" }, "Einträge bleiben 365 Tage erhalten."),
        h("div", { class: "panel", style: { padding: "8px 12px" } }, h("div", { class: "tablewrap" }, h("table", { class: "t" }, h("thead", null, h("tr", null, ["Zeit", "Wer", "Bereich", "Was"].map((x) => h("th", null, x)))),
          h("tbody", null, rows.map((r) => h("tr", null, h("td", { style: { whiteSpace: "nowrap" } }, fmtDate(r.ts)), h("td", null, r.user), h("td", null, r.category), h("td", null, r.text))))))),
        !rows.length ? h("p", { class: "muted" }, "Keine Einträge.") : null);
    },
  });
})();
