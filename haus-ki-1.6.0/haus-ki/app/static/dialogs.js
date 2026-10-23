/* Haus-KI – Dialoge und Start der App. Teil der Oberfläche, die Dateien werden in fester Reihenfolge geladen (siehe index.html). */
"use strict";

// ------------------------------------------------------------------ Dialoge
let dialogResolve = null;
function promptDialog(title, label, value) {
  return new Promise((res) => { dialogResolve = res; S.modal = { kind: "prompt", title, label, value }; renderModal(); });
}
function confirmDialog(title, text, ok) {
  return new Promise((res) => { dialogResolve = res; S.modal = { kind: "confirm", title, text, ok }; renderModal(); });
}
function closeModal(result) { S.modal = null; renderModal(); if (dialogResolve) { const r = dialogResolve; dialogResolve = null; r(result); } }
function modalFrame(over, title, kids, width) {
  return h("div", { class: "modal-bg", onClick: (e) => { if (e.target === e.currentTarget) closeModal(null); } },
    h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": title, style: width ? { maxWidth: width } : null },
      h("div", { class: "head" }, h("div", null, over ? h("div", { class: "over" }, over) : null, h("h2", { style: { marginTop: over ? "6px" : 0 } }, title)),
        h("button", { class: "ib", type: "button", "aria-label": "Schließen", onClick: () => closeModal(null) }, icon("x"))), kids));
}
async function renderModal() {
  const el = R.modal;
  if (!el) return;
  el.innerHTML = "";
  const m = S.modal;
  if (!m) return;
  if (m.kind === "prompt") {
    const inp = h("input", { class: "inp", value: m.value || "", "aria-label": m.label });
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") closeModal(inp.value.trim()); });
    el.appendChild(modalFrame("", m.title, [h("label", { class: "f" }, m.label, inp),
      h("div", { style: { display: "flex", gap: "8px" } }, h("button", { class: "btn", type: "button", onClick: () => closeModal(inp.value.trim()) }, "Übernehmen"), h("button", { class: "btn sec", type: "button", onClick: () => closeModal(null) }, "Abbrechen"))], "460px"));
    setTimeout(() => inp.focus(), 0);
  } else if (m.kind === "confirm") {
    el.appendChild(modalFrame("", m.title, [h("p", { style: { margin: 0 } }, m.text),
      h("div", { style: { display: "flex", gap: "8px" } }, h("button", { class: "btn", type: "button", onClick: () => closeModal(true) }, m.ok || "Ja"), h("button", { class: "btn sec", type: "button", onClick: () => closeModal(false) }, "Abbrechen"))], "460px"));
  } else if (m.kind === "share") {
    el.appendChild(shareModal(m));
  } else if (m.kind === "template") {
    const t = m.t || { title: "", prompt: m.prompt || "", system: "", model: "" };
    const f = { title: h("input", { class: "inp", value: t.title }), prompt: h("textarea", { class: "inp", rows: 5, value: t.prompt }), system: h("textarea", { class: "inp", rows: 2, value: t.system || "" }) };
    let family = false;
    const famT = isAdmin() && !m.t ? h("div") : null;
    const drawFam = () => { if (famT) { famT.innerHTML = ""; famT.appendChild(toggle("Als Familienvorlage für alle", family, (v) => { family = v; drawFam(); })); } };
    drawFam();
    el.appendChild(modalFrame("", m.t ? "Vorlage bearbeiten" : "Als Vorlage speichern", [
      h("label", { class: "f" }, "Name", f.title), h("label", { class: "f" }, "Prompt. Platzhalter schreibst du als {{name}}, z. B. {{zeitraum}}.", f.prompt),
      h("label", { class: "f" }, "Zusätzliche Anweisung (optional)", f.system), famT,
      h("div", { style: { display: "flex", gap: "8px" } }, h("button", { class: "btn", type: "button", onClick: async () => {
        const body = { title: f.title.value, prompt: f.prompt.value, system: f.system.value, family };
        try { if (m.t) await api("PUT", "/api/templates/" + m.t.id, body); else await api("POST", "/api/templates", body); await loadTemplates(); closeModal(true); renderSide(); toast("Vorlage gespeichert."); }
        catch (e) { toast(e.message, true); } } }, "Speichern"), h("button", { class: "btn sec", type: "button", onClick: () => closeModal(null) }, "Abbrechen"))]));
  } else if (m === "memory") {
    const items = await api("GET", "/api/memory");
    const inp = h("input", { class: "inp", placeholder: "z. B. Ich esse vegetarisch", "aria-label": "Neuer Eintrag" });
    const add = async () => { if (!inp.value.trim()) return; await api("POST", "/api/memory", { text: inp.value }); renderModal(); };
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
    el.appendChild(modalFrame("Nur für " + S.me.name, "Gedächtnis", [
      h("p", { class: "small muted", style: { margin: 0 } }, "Diese Fakten fließen in deine Antworten ein. Niemand sonst sieht sie. Im Chat kannst du auch sagen: „Merke dir, …“"),
      h("div", { style: { display: "flex", gap: "8px" } }, inp, h("button", { class: "btn", type: "button", onClick: add }, "Hinzufügen")),
      h("div", null, items.length ? items.map((x) => h("div", { class: "list-row" },
        h("button", { type: "button", class: "tg", role: "switch", "aria-checked": x.enabled ? "true" : "false", "aria-label": (x.enabled ? "Ausschalten: " : "Einschalten: ") + x.text, style: { width: "auto", padding: 0 }, onClick: async () => { await api("PATCH", "/api/memory/" + x.id, { enabled: !x.enabled }); renderModal(); } }, h("span", { class: "track" })),
        h("span", { class: "grow", style: { opacity: x.enabled ? 1 : 0.55 } }, x.text),
        h("button", { class: "act", type: "button", style: { color: "var(--err)" }, onClick: async () => { await api("DELETE", "/api/memory/" + x.id); renderModal(); } }, "Löschen"))) :
        h("p", { class: "small muted" }, "Noch nichts gespeichert."))]));
  } else if (m === "accounts") {
    const d = await api("GET", "/api/accounts");
    const allowed = S.me.mail_allowed;
    const LABEL = { gmx: "GMX", gmail: "Gmail", outlookcom: "Outlook.com" };
    const kind = h("select", { class: "inp", "aria-label": "Anbieter" }, Object.keys(LABEL).filter((k) => allowed[k]).map((k) => h("option", { value: k }, LABEL[k])));
    const addr = h("input", { class: "inp", type: "email", placeholder: "Adresse", "aria-label": "E-Mail-Adresse" });
    const pw = h("input", { class: "inp", type: "password", placeholder: "App-Passwort", "aria-label": "App-Passwort" });
    const help = h("p", { class: "tiny muted", style: { margin: 0 } });
    const upd = () => { pw.classList.toggle("hidden", kind.value === "outlookcom"); help.textContent = { gmx: "Bei GMX unter Einstellungen › POP3/IMAP den IMAP-Zugriff einschalten. Mit Zwei-Faktor brauchst du ein App-Passwort.", gmail: "Bei Google unter Sicherheit › App-Passwörter ein Passwort für „Haus-KI“ erzeugen. Zwei-Faktor muss aktiv sein.", outlookcom: "Du wirst zu Microsoft weitergeleitet und meldest dich dort mit deinem privaten Konto an." }[kind.value] || ""; };
    kind.addEventListener("change", upd); upd();
    el.appendChild(modalFrame("Nur für " + S.me.name, "Meine Konten", [
      h("div", { class: "list-row", style: { borderTop: 0 } }, h("span", { class: "logo" }, "M"), h("span", { class: "grow" }, h("b", null, "Microsoft 365"), h("div", { class: "tiny muted" }, d.m365.connected ? `${d.m365.email}, automatisch über deine Anmeldung` : "Nicht verbunden. Melde dich einmal mit Microsoft an.")),
        d.m365.connected ? h("span", { class: "badge ok" }, "verbunden") : h("a", { class: "btn sec", href: "/auth/login" }, "Verbinden")),
      d.accounts.map((a) => h("div", { class: "list-row" }, h("span", { class: "logo" }, LABEL[a.kind][0]),
        h("span", { class: "grow" }, h("b", null, LABEL[a.kind]), h("div", { class: "tiny muted" }, a.address + (a.connected ? "" : " · Anmeldung nicht abgeschlossen"))),
        h("div", { style: { width: "220px" } }, toggle("Entwürfe erlauben", a.drafts, async (v) => { await api("PATCH", "/api/accounts/" + a.id, { drafts: v }); renderModal(); })),
        h("button", { class: "act", type: "button", style: { color: "var(--err)" }, onClick: async () => { if (await confirmDialog("Postfach entfernen?", a.address, "Entfernen")) { await api("DELETE", "/api/accounts/" + a.id); S.modal = "accounts"; renderModal(); } } }, "Entfernen"))),
      Object.values(allowed).some(Boolean) ? h("div", { class: "panel", style: { padding: "14px" } }, h("b", null, "Postfach hinzufügen"), h("div", { class: "grid2", style: { gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))" } }, kind, addr, pw), help,
        h("button", { class: "btn", type: "button", style: { alignSelf: "flex-start" }, onClick: async () => {
          try { const r = await api("POST", "/api/accounts", { kind: kind.value, address: addr.value, password: pw.value }); if (r.redirect) location.href = r.redirect; else { toast("Postfach verbunden."); renderModal(); } }
          catch (e) { toast(e.message, true); } } }, "Verbinden")) : null,
      h("p", { class: "tiny muted", style: { margin: 0 } }, "Haus-KI liest nur den Posteingang, nie den Spam-Ordner. Senden ist nicht möglich, höchstens Entwürfe.")]));
  } else if (m === "schedules") {
    const list = await api("GET", "/api/schedules");
    const DN = { Mo: "Montag", Di: "Dienstag", Mi: "Mittwoch", Do: "Donnerstag", Fr: "Freitag", Sa: "Samstag", So: "Sonntag" };
    el.appendChild(modalFrame("Nur für " + S.me.name, "Geplante Prompts", [
      h("p", { class: "small muted", style: { margin: 0 } }, "Haus-KI führt diese Prompts selbst aus und legt das Ergebnis als Chat ab. Neue planst du über ⋯ › Prompt planen im Eingabefeld."),
      list.length ? list.map((x) => h("div", { class: "list-row" },
        h("button", { type: "button", class: "tg", role: "switch", "aria-checked": x.enabled ? "true" : "false", "aria-label": (x.enabled ? "Pausieren: " : "Aktivieren: ") + x.name, style: { width: "auto", padding: 0 }, onClick: async () => { await api("PATCH", "/api/schedules/" + x.id, { enabled: !x.enabled }); renderModal(); } }, h("span", { class: "track" })),
        h("span", { class: "grow", style: { minWidth: "200px" } }, h("b", null, x.name), h("div", { class: "tiny muted" },
          ({ weekly: `Jeden ${DN[x.day]} um ${x.time}`, daily: `Täglich um ${x.time}`, monthly: `Monatlich am 1. um ${x.time}`, once: `Einmalig um ${x.time}` }[x.freq]) + (x.deliver === "notify" ? ", mit Benachrichtigung" : ", nur im Verlauf"))),
        h("span", { class: "tiny muted" }, x.next ? "nächster Lauf " + new Date(x.next).toLocaleString("de-DE", { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "pausiert"),
        h("button", { class: "act", type: "button", onClick: async () => { await api("POST", `/api/schedules/${x.id}/run`); closeModal(); toast(`„${x.name}“ wird ausgeführt. Das Ergebnis erscheint als Chat.`); setTimeout(() => loadChats().then(renderSide), 1500); } }, "Jetzt ausführen"),
        h("button", { class: "act", type: "button", style: { color: "var(--err)" }, onClick: async () => { await api("DELETE", "/api/schedules/" + x.id); renderModal(); } }, "Löschen"))) :
        h("p", { class: "small muted" }, "Noch nichts geplant.")]));
  } else if ((m === "voice" || m === "voice-help") && window.HKVoice) {
    const frame = (over, title, kids) => modalFrame(over, title, kids);
    el.appendChild(m === "voice" ? await window.HKVoice.settingsModal(frame) : window.HKVoice.helpModal(frame));
  } else if (m === "intro") {
    el.appendChild(introModal());
  } else if (m === "family") {
    const items = await api("GET", "/api/family");
    const inp = h("input", { class: "inp", placeholder: "z. B. Die Müllabfuhr kommt dienstags", "aria-label": "Neuer Eintrag" });
    const add = async () => { if (!inp.value.trim()) return; await api("POST", "/api/family", { text: inp.value }); renderModal(); };
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
    el.appendChild(modalFrame("Für alle in der Familie", "Familienwissen", [
      h("p", { class: "small muted", style: { margin: 0 } }, "Diese Fakten kennt Haus-KI bei allen Fragen von allen. Persönliches gehört ins eigene Gedächtnis. Im Chat geht auch: „Merke dir für alle, …“ oder /familie."),
      h("div", { style: { display: "flex", gap: "8px" } }, inp, h("button", { class: "btn", type: "button", onClick: add }, "Hinzufügen")),
      h("div", null, items.length ? items.map((x) => h("div", { class: "list-row" },
        x.can_edit ? h("button", { type: "button", class: "tg", role: "switch", "aria-checked": x.enabled ? "true" : "false", "aria-label": (x.enabled ? "Ausschalten: " : "Einschalten: ") + x.text, style: { width: "auto", padding: 0 },
          onClick: async () => { await api("PATCH", "/api/family/" + x.id, { enabled: !x.enabled }); renderModal(); } }, h("span", { class: "track" })) : null,
        h("span", { class: "grow", style: { opacity: x.enabled ? 1 : 0.55 } }, x.text, h("span", { class: "tiny muted" }, x.author ? " · " + x.author : "")),
        x.can_edit ? h("button", { class: "act", type: "button", style: { color: "var(--err)" }, onClick: async () => { await api("DELETE", "/api/family/" + x.id); renderModal(); } }, "Löschen") : null)) :
        h("p", { class: "small muted" }, "Noch nichts eingetragen."))]));
  } else if (m === "notifications") {
    const list = await api("GET", "/api/notifications");
    pollStatus();
    el.appendChild(modalFrame("", "Benachrichtigungen", [list.length ? list.map((n) => h("div", { class: "list-row" },
      h("span", { class: "status-dot" + (n.level === "error" ? " off" : n.level === "warn" ? " unk" : "") }), h("span", { class: "grow" }, n.text, h("div", { class: "tiny muted" }, fmtDate(n.created))),
      n.link ? h("a", { class: "act", href: n.link, onClick: () => closeModal() }, "Öffnen") : null)) : h("p", { class: "muted" }, "Keine Benachrichtigungen.")]));
  } else if (m === "prefs") {
    const p = S.me.prefs;
    const set = async (k, v) => { S.me.prefs = await api("PUT", "/api/me/prefs", { [k]: v }); if (v) askNotifyPermission(); renderModal(); };
    el.appendChild(modalFrame("Nur für " + S.me.name, "Einstellungen für mich", [
      h("div", null, h("b", null, "Benachrichtigungen"),
        toggle("Wenn eine Antwort fertig ist", p.notify_done, (v) => set("notify_done", v), "Auch wenn Haus-KI im Hintergrund ist."),
        toggle("Neue Fristen aus Paperless", p.notify_deadlines, (v) => set("notify_deadlines", v)),
        toggle("Überschneidungen im Familienkalender", p.notify_calendar, (v) => set("notify_calendar", v)),
        toggle("Geplante Prompts sind fertig", p.notify_schedules, (v) => set("notify_schedules", v))),
      h("div", null, h("b", null, "Ansicht"), toggle("Einfache Ansicht", !!p.simple_ui, async (v) => { S.me.prefs = await api("PUT", "/api/me/prefs", { simple_ui: v }); renderAll(); },
        "Weniger Knöpfe und Klartext statt Fachbegriffen. Alle Funktionen bleiben über / im Eingabefeld erreichbar.")),
      S.me.auto_allowed && S.me.auto_allowed.length ? h("div", null, h("b", null, "Ohne Rückfrage ausführen"),
        h("p", { class: "small muted", style: { margin: "4px 0 0" } }, "Haus-KI führt diese Aktionen direkt aus und sagt danach, was es getan hat. Haustür, Garage, Alarm, Mails und Dokumente fragen immer nach, und nach Webinhalten gibt es nie Aktionen."),
        S.me.auto_allowed.map((c) => toggle(c.label, (p.auto_actions || []).includes(c.id), async (v) => {
          const cur = new Set(S.me.prefs.auto_actions || []);
          if (v) cur.add(c.id); else cur.delete(c.id);
          S.me.prefs = await api("PUT", "/api/me/prefs", { auto_actions: [...cur] });
          renderModal();
        }))) : null,
      h("div", null, h("b", null, "Einführung"), h("div", null, h("button", { class: "act", type: "button", style: { color: "var(--accent)", paddingLeft: 0 }, onClick: () => { S.modal = "intro"; S.introStep = 0; renderAll(); } }, "Einführung noch einmal zeigen"))),
      pushBox(),
      h("div", null, h("b", null, "Vorschläge"), toggle("Vorschläge aus meinen Chats", p.suggestions, (v) => set("suggestions", v), "Nachts liest Haus-KI deine letzten Fragen und schlägt neue vor. Nur du siehst sie.")),
      "Notification" in window && Notification.permission !== "granted" ? h("button", { class: "btn sec", type: "button", style: { alignSelf: "flex-start" }, onClick: () => Notification.requestPermission().then(() => renderModal()) }, "Benachrichtigungen im Browser erlauben") : null,
      !S.me.features.admin_read ? null : h("p", { class: "tiny muted", style: { margin: 0 } }, isAdmin() ? "Administratoren können die Chats aller lesen. Jede Einsicht steht im Protokoll." : `${S.me.family.filter((u) => u.role === "admin").map((u) => u.name).join(" und ")} können deine Chats lesen. Jede Einsicht steht im Protokoll.`)]));
  }
}

// ------------------------------------------------------------------ Einführung beim ersten Anmelden
function introSteps() {
  const f = S.me.features, src = [];
  if (f.paperless) src.push("eure Dokumente in Paperless");
  if (f.knx) src.push("das Haus (Licht, Temperaturen, Fenster)");
  if (f.m365) src.push("Kalender, Mails und Aufgaben");
  if (f.jellyfin) src.push("Filme und Serien in Jellyfin");
  if (f.web) src.push("das Internet, wenn du es einschaltest");
  const voice = window.HKVoice && window.HKVoice.enabled();
  return [
    { over: "Willkommen, " + S.me.name, title: "So fragst du Haus-KI",
      body: [h("p", null, "Schreib einfach, was du wissen willst, wie in einer Nachricht. Zum Beispiel:"),
        h("div", { class: "follow" }, ["Was steht morgen an?", "Wie warm ist es im Kinderzimmer?", "Erklär mir die binomischen Formeln"].map((t) => h("span", { class: "chip" }, t))),
        voice ? h("p", null, "Lieber sprechen? Tippe auf das Mikrofon neben dem Senden-Knopf.") : null,
        h("p", null, "Ist eine Antwort falsch, tippe auf den Daumen nach unten. So wird Haus-KI besser.")] },
    { over: "Woher Haus-KI etwas weiß", title: "Quellen",
      body: [h("p", null, src.length ? "Wenn du sie unter „Quellen“ einschaltest, schaut Haus-KI hier nach: " + src.join(", ") + "." : "Haus-KI antwortet aus seinem allgemeinen Wissen. Weitere Quellen kann ein Administrator freigeben."),
        h("p", null, "Woher eine Antwort stammt, steht darunter mit kleinen Nummern wie [1]. Ein Klick darauf öffnet das Dokument, den Termin oder den Film."),
        f.knx ? h("p", null, "Haus-KI schaltet nichts heimlich: Vor jeder Aktion fragt es nach, außer bei dem, was du selbst unter „Einstellungen für mich“ freigibst.") : null] },
    { over: "Privat und einfach", title: "Das bleibt bei dir",
      body: [h("p", null, "Haus-KI läuft auf eurem eigenen Server. Deine Fragen gehen nicht an fremde Firmen."),
        h("p", null, S.me.role === "admin" ? "Deine Chats siehst nur du. Andere Administratoren können sie lesen, das wird aber protokolliert."
          : "Deine Chats siehst du. Die Administratoren eurer Familie können sie lesen, das wird aber jedes Mal protokolliert."),
        h("p", null, "Alle Funktionen findest du, wenn du im Eingabefeld „/“ tippst. Zum Beispiel ", h("code", null, "/merken"), " für Dinge, die Haus-KI sich merken soll.")] },
  ];
}
function introModal() {
  const steps = introSteps(), i = Math.min(S.introStep || 0, steps.length - 1), st = steps[i], last = i === steps.length - 1;
  const finish = async () => { S.me.prefs = await api("PUT", "/api/me/prefs", { onboarded: true }); closeModal(); };
  return modalFrame(st.over, st.title, [
    h("div", { class: "intro-body" }, st.body),
    h("div", { style: { display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" } },
      h("span", { class: "intro-dots", "aria-label": `Schritt ${i + 1} von ${steps.length}` }, steps.map((_, j) => h("span", { class: j === i ? "on" : "" }))),
      h("span", { class: "grow" }),
      !last ? h("button", { class: "act", type: "button", onClick: finish }, "Überspringen") : null,
      i > 0 ? h("button", { class: "btn sec", type: "button", onClick: () => { S.introStep = i - 1; renderModal(); } }, "Zurück") : null,
      h("button", { class: "btn", type: "button", onClick: () => { if (last) finish(); else { S.introStep = i + 1; renderModal(); } } }, last ? "Los geht’s" : "Weiter"))]);
}

// ------------------------------------------------------------------ Push-Benachrichtigungen
const PUSH = { state: "unknown", devices: 0 };
function b64ToBytes(b64) {
  const s = atob((b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}
async function pushRefresh() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !window.isSecureContext) { PUSH.state = "unsupported"; return; }
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  PUSH.state = sub ? "on" : "off";
  try { PUSH.devices = (await api("GET", "/api/push/key")).devices; } catch (e) { /* egal */ }
}
async function pushToggle(on) {
  try {
    const reg = await navigator.serviceWorker.ready;
    if (on) {
      if ((await Notification.requestPermission()) !== "granted") { toast("Benachrichtigungen wurden im Browser nicht erlaubt.", true); return; }
      const { key } = await api("GET", "/api/push/key");
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(key) });
      await api("POST", "/api/push/subscribe", sub.toJSON());
      toast("Auf diesem Gerät eingeschaltet.");
    } else {
      const sub = await reg.pushManager.getSubscription();
      if (sub) { await api("POST", "/api/push/unsubscribe", { endpoint: sub.endpoint }); await sub.unsubscribe(); }
    }
  } catch (e) { toast("Das hat nicht geklappt: " + e.message, true); }
  await pushRefresh();
  renderModal();
}
function pushBox() {
  const box = h("div");
  const draw = () => {
    box.innerHTML = "";
    if (PUSH.state === "unknown") { pushRefresh().then(draw); return; }
    box.append(h("b", null, "Auch bei geschlossener App"),
      PUSH.state === "unsupported" ? h("p", { class: "small muted", style: { margin: "6px 0 0" } }, "Dieser Browser kann keine Benachrichtigungen bei geschlossener App empfangen. Auf iPhone und iPad geht das, wenn Haus-KI über „Zum Home-Bildschirm“ installiert ist.") :
        [toggle("Benachrichtigungen auf diesem Gerät", PUSH.state === "on", (v) => pushToggle(v), `Kommen über den Push-Dienst des Geräteherstellers, nur ein kurzer Hinweistext, verschlüsselt. Eingeschaltet auf ${PUSH.devices} Gerät(en).`),
          PUSH.state === "on" ? h("button", { class: "act", type: "button", style: { color: "var(--accent)" }, onClick: async () => { try { await api("POST", "/api/push/test"); toast("Test gesendet."); } catch (e) { toast(e.message, true); } } }, "Test senden") : null]);
  };
  draw();
  return box;
}

// ------------------------------------------------------------------ Mit Haus-KI geteilt
async function openShareInbox() {
  if (!("caches" in window)) return;
  const cache = await caches.open("hk-share");
  const keys = await cache.keys();
  if (!keys.length) return;
  const items = [];
  for (const k of keys) {
    const r = await cache.match(k);
    const name = decodeURIComponent(r.headers.get("X-Name") || "datei");
    const blob = await r.blob();
    items.push({ key: k, name, blob, type: blob.type || r.headers.get("Content-Type") || "" });
  }
  const done = async (it) => { await cache.delete(it.key); items.splice(items.indexOf(it), 1); if (!items.length) closeModal(); else renderModal(); };
  S.modal = { kind: "share", items, done };
  renderModal();
}
function shareModal(m) {
  const f = S.me.features;
  return modalFrame("", "Mit Haus-KI geteilt", [
    h("p", { class: "small muted", style: { margin: 0 } }, "Was soll damit passieren? Die Dateien liegen bis dahin nur auf diesem Gerät."),
    m.items.map((it) => {
      const file = new File([it.blob], it.name, { type: it.type });
      const isText = it.name === "text";
      return h("div", { class: "list-row" }, icon("file"), h("span", { class: "grow", style: { minWidth: 0 } }, h("b", { class: "ell", style: { display: "block" } }, isText ? "Text oder Link" : it.name),
          h("span", { class: "tiny muted" }, isText ? "" : `${(it.blob.size / 1e6).toFixed(1).replace(".", ",")} MB`)),
        !isText && f.paperless_upload && /pdf|image/.test(it.type) ? h("button", { class: "btn", type: "button", onClick: async () => { await m.done(it); paperlessUpload(file); } }, "In Paperless ablegen") : null,
        h("button", { class: "btn sec", type: "button", onClick: async () => {
          if (isText) { setDraft((S.draft ? S.draft + "\n" : "") + (await it.blob.text())); }
          else addFile(file);
          await m.done(it); renderComposer(); } }, isText ? "Ins Eingabefeld" : "Im Chat anhängen"),
        h("button", { class: "act", type: "button", onClick: () => m.done(it) }, "Verwerfen"));
    })]);
}

window.HK = { S, h, api, toast, icon, toggle, seg, fmtN, fmtDate, fmtGB, av, debounce, confirmDialog, promptDialog, renderAll, renderBody, go, loadChats,
  send, setDraft, requestBody, renderComposerVoice };
window.addEventListener("resize", debounce(() => { if (S.me) renderHead(); }, 150));
if (window.HKTheme) window.HKTheme.onChange(() => { if (S.me) { renderHead(); } });
document.addEventListener("DOMContentLoaded", boot);
