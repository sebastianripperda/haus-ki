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
    sso: "Die Anmeldung über Microsoft ist noch nicht eingerichtet. Administratoren nutzen den Notfall-Zugang.",
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
  if (st.sso) card.appendChild(h("a", { class: "ms", href: "/auth/login" },
    h("svg", { width: 18, height: 18, viewBox: "0 0 21 21", "aria-hidden": "true" }, h("rect", { x: 1, y: 1, width: 9, height: 9, fill: "#f25022" }), h("rect", { x: 11, y: 1, width: 9, height: 9, fill: "#7fba00" }), h("rect", { x: 1, y: 11, width: 9, height: 9, fill: "#00a4ef" }), h("rect", { x: 11, y: 11, width: 9, height: 9, fill: "#ffb900" })),
    "Mit Microsoft anmelden"));
  if (st.sso && st.recent.length) card.appendChild(h("div", { style: { display: "flex", gap: "12px", flexWrap: "wrap" } },
    st.recent.map((u) => h("a", { href: "/auth/login?prompt=select_account", style: { display: "flex", flexDirection: "column", alignItems: "center", gap: "4px", textDecoration: "none", color: "var(--text)", fontSize: "13px" } }, av(u, "lg"), u.name))));
  const admins = st.recent.filter((u) => u.role === "admin" && u.emergency);
  const sel = h("select", { class: "inp", id: "eu" }, admins.map((u) => h("option", { value: u.id }, u.name)));
  const pw = h("input", { class: "inp", id: "epw", type: "password", autocomplete: "current-password" });
  const err = h("p", { class: "small", style: { color: "var(--err)", margin: 0 }, role: "alert" });
  const login = async () => {
    try { await api("POST", "/auth/emergency", { user_id: +sel.value, password: pw.value }, { quiet401: true }); location.href = "/"; }
    catch (e) { err.textContent = e.message; }
  };
  pw.addEventListener("keydown", (e) => { if (e.key === "Enter") login(); });
  const details = h("details", { open: !st.sso ? true : null },
    h("summary", { style: { cursor: "pointer", minHeight: "40px", display: "flex", alignItems: "center" } }, "Notfall-Zugang für Administratoren"),
    h("div", { style: { display: "flex", flexDirection: "column", gap: "10px", paddingTop: "8px" } },
      h("p", { class: "small muted", style: { margin: 0 } }, "Für den Fall, dass Microsoft nicht erreichbar ist. Jede Anmeldung wird protokolliert."),
      h("label", { class: "f", for: "eu" }, "Wer", sel), h("label", { class: "f", for: "epw" }, "Notfall-Passwort", pw), err,
      h("button", { class: "btn sec", type: "button", onClick: login }, "Anmelden")));
  if (admins.length) card.appendChild(details);
}
