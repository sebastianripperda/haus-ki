/* Haus-KI – Anmeldung und Ersteinrichtung. Teil der Oberfläche, die Dateien werden in fester Reihenfolge geladen (siehe index.html). */
"use strict";

// ------------------------------------------------------------------ Anmeldung
async function renderLogin() {
  const root = $("#root");
  root.innerHTML = "";
  let st = { needs_setup: false, sso: false, recent: [] };
  try { st = await api("GET", "/api/setup/status"); } catch (e) { /* weiter */ }
  const params = new URLSearchParams(location.search);
  const ERR = {
    sso: "Die Anmeldung über Microsoft ist noch nicht eingerichtet. Nutze die lokale Anmeldung oder als Administrator den Notfall-Zugang.",
    "nur-lokal": "Für dein Konto ist die Anmeldung über Microsoft nicht freigegeben. Melde dich bitte mit deinem Haus-KI-Passwort an.",
    "keine-rolle": `Dein Microsoft-Konto ${params.get("konto") || ""} ist für Haus-KI nicht freigegeben. Ein Administrator kann dir in Microsoft Entra die App-Rolle „HausKI.Member“ zuweisen.`,
    abgelaufen: "Die Anmeldung hat zu lange gedauert. Bitte noch einmal.", abgebrochen: "Die Anmeldung wurde abgebrochen.",
    microsoft: "Microsoft hat die Anmeldung abgelehnt. Versuche es noch einmal.", gesperrt: "Dein Konto ist in Haus-KI gesperrt.",
  };
  const card = h("div", { class: "card" });
  root.appendChild(h("main", { class: "login" }, card));
  const themeBox = h("div", { class: "login-theme" }, themeSwitch());
  root.appendChild(themeBox);
  if (window.HKTheme) window.HKTheme.onChange(() => { themeBox.innerHTML = ""; themeBox.appendChild(themeSwitch()); });
  card.appendChild(h("div", { class: "brand" }, h("span", { class: "logo" }, "HK"), "Haus-KI"));
  if (params.get("fehler")) card.appendChild(h("div", { class: "note warn", role: "alert" }, ERR[params.get("fehler")] || "Die Anmeldung hat nicht geklappt."));
  // Microsoft hat die Anmeldung bestätigt, aber wir sind trotzdem hier: das Anmelde-Cookie ist unterwegs verloren gegangen
  const okAt = +params.get("angemeldet");
  if (okAt && Math.abs(Date.now() / 1000 - okAt) < 600) {
    const standalone = window.navigator.standalone === true || (window.matchMedia && matchMedia("(display-mode: standalone)").matches);
    card.appendChild(h("div", { class: "note warn", role: "alert" }, standalone
      ? "Die Anmeldung bei Microsoft hat geklappt, ist aber nicht in der App angekommen. Das kommt auf manchen iPhones bei der App vom Home-Bildschirm vor. Öffne Haus-KI einmal in Safari und melde dich dort an, oder nutze die Anmeldung ohne Microsoft, falls sie für dich freigegeben ist."
      : "Die Anmeldung bei Microsoft hat geklappt, aber dein Browser hat sie nicht gespeichert. Prüfe, ob Cookies für Haus-KI erlaubt sind und dem Haus-KI-Zertifikat vertraut wird (siehe Installationsleitfaden)."));
    api("POST", "/auth/lost-session", { standalone: !!standalone }, { quiet401: true }).catch(() => {});
    history.replaceState(null, "", "/" + location.hash);
  }

  if (st.needs_setup) {
    const f = { code: h("input", { class: "inp", id: "code", autocomplete: "off" }), name: h("input", { class: "inp", id: "nm", value: "" }),
      pw: h("input", { class: "inp", id: "pw", type: "password", autocomplete: "new-password" }), pw2: h("input", { class: "inp", id: "pw2", type: "password", autocomplete: "new-password" }) };
    const err = h("p", { class: "small", style: { color: "var(--err)", margin: 0 }, role: "alert" });
    card.append(
      h("h1", { style: { fontSize: "28px", fontWeight: 800 } }, "Ersteinrichtung"),
      h("p", { class: "muted", style: { margin: 0 } }, "Lege den ersten Administrator mit Notfall-Passwort an. Die Anmeldung über Microsoft richtest du danach in der Administration ein."),
      h("label", { class: "f", for: "code" }, "Einrichtungscode aus dem Installationsskript", f.code),
      h("label", { class: "f", for: "nm" }, "Dein Vorname", f.name),
      h("label", { class: "f", for: "pw" }, "Notfall-Passwort (mindestens 12 Zeichen)", f.pw),
      h("label", { class: "f", for: "pw2" }, "Passwort wiederholen", f.pw2), err,
      h("button", { class: "btn", type: "button", onClick: async () => {
        err.textContent = "";
        if (f.pw.value !== f.pw2.value) { err.textContent = "Die Passwörter stimmen nicht überein."; return; }
        try { await api("POST", "/api/setup", { code: f.code.value, name: f.name.value, password: f.pw.value }); location.href = "/#admin/overview"; location.reload(); }
        catch (e) { err.textContent = e.message; }
      } }, "Einrichten"));
    return;
  }
  card.appendChild(h("h1", { style: { fontSize: "28px", fontWeight: 800 } }, "Willkommen zu Hause"));
  const local = st.local || [];
  const admins = st.emergency || st.recent.filter((u) => u.role === "admin" && u.emergency);

  // Passwort-Anmeldung (lokal oder Notfall): Person wählen, Passwort eingeben
  function passwordForm(path, people, pwLabel, idp) {
    let chosen = people.length === 1 ? people[0].id : null;
    const pw = h("input", { class: "inp", id: idp + "pw", type: "password", autocomplete: "current-password" });
    const err = h("p", { class: "small", style: { color: "var(--err)", margin: 0 }, role: "alert" });
    const btn = h("button", { class: "btn" + (path === "/auth/emergency" ? " sec" : ""), type: "button" }, "Anmelden");
    const login = async () => {
      err.textContent = "";
      if (!chosen) { err.textContent = "Bitte wähle zuerst aus, wer du bist."; return; }
      btn.disabled = true;
      try { await api("POST", path, { user_id: chosen, password: pw.value }, { quiet401: true }); location.href = "/"; }
      catch (e) { err.textContent = e.message; btn.disabled = false; pw.select(); }
    };
    btn.addEventListener("click", login);
    pw.addEventListener("keydown", (e) => { if (e.key === "Enter") login(); });
    const people_ = h("div", { class: "login-people", role: "radiogroup", "aria-label": "Wer bist du?" });
    const drawPeople = () => {
      people_.innerHTML = "";
      people_.append(people.map((u) => h("button", { type: "button", class: "login-person", role: "radio", "aria-checked": chosen === u.id ? "true" : "false",
        onClick: () => { chosen = u.id; drawPeople(); pw.focus(); } }, av(u, "lg"), h("span", null, u.name))));
    };
    drawPeople();
    return h("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } },
      h("div", { class: "small muted" }, "Wer bist du?"), people_,
      h("label", { class: "f", for: idp + "pw" }, pwLabel, pw), err, btn);
  }

  if (st.sso) card.appendChild(h("a", { class: "ms", href: "/auth/login" },
    h("svg", { width: 18, height: 18, viewBox: "0 0 21 21", "aria-hidden": "true" }, h("rect", { x: 1, y: 1, width: 9, height: 9, fill: "#f25022" }), h("rect", { x: 11, y: 1, width: 9, height: 9, fill: "#7fba00" }), h("rect", { x: 1, y: 11, width: 9, height: 9, fill: "#00a4ef" }), h("rect", { x: 11, y: 11, width: 9, height: 9, fill: "#ffb900" })),
    "Mit Microsoft anmelden"));
  if (st.sso && st.recent.length && !local.length) card.appendChild(h("div", { style: { display: "flex", gap: "12px", flexWrap: "wrap" } },
    st.recent.map((u) => h("a", { href: "/auth/login?prompt=select_account", style: { display: "flex", flexDirection: "column", alignItems: "center", gap: "4px", textDecoration: "none", color: "var(--text)", fontSize: "13px" } }, av(u, "lg"), u.name))));
  if (local.length) {
    if (st.sso) card.appendChild(h("div", { class: "login-or" }, h("span", null, "oder ohne Microsoft-Konto")));
    else card.appendChild(h("p", { class: "muted", style: { margin: 0 } }, "Melde dich mit deinem Haus-KI-Passwort an."));
    card.appendChild(passwordForm("/auth/local", local, "Passwort", "l"));
  }
  if (!st.sso && !local.length && !admins.length) card.appendChild(h("div", { class: "note warn" }, "Für niemanden ist eine Anmeldung eingerichtet. Ein Administrator kann das unter Administration › Benutzer ändern."));
  if (admins.length) card.appendChild(h("details", { open: !st.sso && !local.length ? true : null },
    h("summary", { style: { cursor: "pointer", minHeight: "40px", display: "flex", alignItems: "center" } }, "Notfall-Zugang für Administratoren"),
    h("div", { style: { display: "flex", flexDirection: "column", gap: "10px", paddingTop: "8px" } },
      h("p", { class: "small muted", style: { margin: 0 } }, "Für den Fall, dass Microsoft nicht erreichbar ist. Jede Anmeldung wird protokolliert."),
      passwordForm("/auth/emergency", admins, "Notfall-Passwort", "e"))));
  // Versionsnummer: zeigt auf iPhone und iPad, ob die aktuelle Oberfläche geladen ist
  if (st.version) card.appendChild(h("p", { class: "tiny muted", style: { margin: 0, textAlign: "center" } }, "Haus-KI " + st.version));
}
