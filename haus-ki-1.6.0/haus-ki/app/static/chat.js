/* Haus-KI – Unterhaltung, Senden und Empfangen. Teil der Oberfläche, die Dateien werden in fester Reihenfolge geladen (siehe index.html). */
"use strict";

// ------------------------------------------------------------------ Unterhaltung
async function openChat(id) {
  S.live = null;
  try {
    S.chat = await api("GET", "/api/chats/" + id);
  } catch (e) { toast(e.message, true); S.chat = null; go("#start"); return; }
  const last = [...S.chat.messages].reverse().find((m) => m.role === "assistant");
  S.ctx = last && last.meta.stats && last.meta.stats.num_ctx ? { used: (last.meta.stats.prompt_tokens || 0) + (last.meta.stats.tokens || 0), max: last.meta.stats.num_ctx } : null;
  S.stick = true;
  renderAll();
  const running = S.chat.jobs && S.chat.jobs[0];
  if (running) attachJob(running.id, id);
}
function newChat() {
  S.chat = null; S.live = null; S.ctx = null; S.editing = null;
  setDraft(""); S.attachments = []; S.tpl = null;
  go("#start");
}
function renderChat(wrap) {
  const c = S.chat;
  if (!c) { wrap.appendChild(h("p", { class: "muted" }, "Lädt …")); return; }
  if (c.readonly) {
    const owner = S.me.family.find((u) => u.id === c.chat.user_id);
    wrap.appendChild(h("div", { class: "banner note warn" }, h("span", { class: "grow" }, `Du liest den Chat von ${owner ? owner.name : "jemand anderem"}. Nur lesen, die Einsicht steht im Protokoll.`),
      h("button", { class: "btn sec", type: "button", onClick: async () => { S.viewAs = null; await loadChats(); go("#start"); } }, "Zurück zu meinen Chats")));
  }
  if (S.status && S.status.ollama && S.status.ollama.ok === false) wrap.appendChild(stateBanner());
  if (S.ctx && S.ctx.max && S.ctx.used / S.ctx.max >= 0.8) wrap.appendChild(h("div", { class: "banner note warn" },
    h("span", { class: "grow" }, `Dieser Chat ist zu ${Math.round((S.ctx.used / S.ctx.max) * 100)} % voll. Ältere Teile werden bald nicht mehr berücksichtigt.`),
    h("button", { class: "btn sec", type: "button", onClick: async () => { const r = await api("POST", `/api/chats/${c.chat.id}/summarize`); await loadChats(); go("#chat/" + r.chat_id); } }, "Zusammenfassen und neu beginnen")));
  const box = h("div", { class: "msgs" });
  wrap.appendChild(box);
  const msgs = c.messages;
  const lastAssistant = [...msgs].reverse().find((m) => m.role === "assistant");
  for (let i = 0; i < msgs.length; i++) {
    const m = msgs[i];
    if (m.role === "user") { box.appendChild(userMsg(m, i)); continue; }
    if (m.meta.variant === "b") continue;
    const b = msgs[i + 1] && msgs[i + 1].role === "assistant" && msgs[i + 1].meta.variant === "b" ? msgs[i + 1] : null;
    const isLast = m === lastAssistant || (b && b === lastAssistant);
    if (b) box.appendChild(h("div", { class: "cmp" }, answerView(m, isLast, true), answerView(b, isLast, true)));
    else box.appendChild(answerView(m, isLast));
  }
  if (S.live && S.live.chatId === c.chat.id) box.appendChild(liveView());
}
function userMsg(m, idx) {
  const atts = (m.meta.attachments || []).map((a) => h("span", { class: "att" }, icon("file", 14), a.label || a.name));
  const canEdit = !S.chat.readonly && !S.live;
  return h("div", { class: "u" }, atts.length ? h("div", { style: { display: "flex", gap: "6px", flexWrap: "wrap", justifyContent: "flex-end" } }, atts) : null,
    h("div", { class: "bubble" }, m.content),
    h("div", { style: { display: "flex", gap: "2px" } },
      canEdit ? h("button", { class: "act", type: "button", "aria-label": "Nachricht bearbeiten", title: "Bearbeiten", onClick: () => { S.editing = m.id; setDraft(m.content); renderComposer(); R.ta.focus(); } }, icon("edit", 15)) : null,
      h("button", { class: "act", type: "button", "aria-label": "Nachricht kopieren", title: "Kopieren", onClick: () => { navigator.clipboard.writeText(m.content); toast("Kopiert"); } }, icon("copy", 15))));
}
function stepsView(steps, running) {
  if (!steps || !steps.length) return null;
  return h("div", { class: "steps" }, steps.map((s, i) => h("div", { class: "step" + (s.state === "err" ? " err" : running && i === steps.length - 1 && s.state === "run" ? " run" : "") },
    h("span", { class: "dot", "aria-hidden": "true" }, s.state === "err" ? "✕" : s.state === "run" ? "" : "✓"), h("span", null, s.text))));
}
function citesView(cites, key) {
  if (!cites || !cites.length) return null;
  return h("div", { class: "cites" }, cites.map((c) => h(c.url ? "a" : "div", { class: "cite", id: `cite-${key}-${c.nr}`, href: c.url || null, target: c.url ? "_blank" : null, rel: c.url ? "noopener noreferrer" : null },
    h("span", null, h("span", { class: "src" }, c.source), h("span", { class: "tiny muted" }, ` [${c.nr}]`)), h("b", null, c.title), c.meta ? h("span", { class: "tiny muted" }, c.meta) : null,
    c.url && c.open ? h("span", { class: "tiny", style: { color: "var(--accent)", marginTop: "4px" } }, c.open) : null)));
}
function mdView(text, cursor) {
  const d = h("div", { class: "md" + (cursor ? " cursor" : ""), html: MD.render(text || "") });
  return d;
}
function memoryView(items) {
  if (!items || !items.length) return null;
  return h("details", { class: "small muted" }, h("summary", { style: { cursor: "pointer" } }, `Gedächtnis berücksichtigt (${items.length})`),
    h("ul", { style: { margin: "6px 0 0", paddingLeft: "20px" } }, items.map((t) => h("li", null, t))));
}
function actionCard(a) {
  const pending = a.status === "pending";
  const resText = { done: a.result, failed: a.result, rejected: "Abgebrochen, es wurde nichts geändert.", expired: "Abgelaufen, bitte noch einmal fragen." }[a.status];
  return h("div", { class: "confirm" }, h("b", null, a.summary),
    pending && !S.chat.readonly ? h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" } },
      h("button", { class: "btn", type: "button", onClick: () => decideAction(a, true) }, "Ausführen"),
      h("button", { class: "btn sec", type: "button", onClick: () => decideAction(a, false) }, "Abbrechen")) :
      h("span", { class: "small", style: { color: a.status === "done" ? "var(--ok)" : a.status === "failed" ? "var(--err)" : "var(--muted)" } }, resText || "",
        (a.auto || a.via === "ohne Rückfrage") ? h("span", { class: "muted" }, " Ohne Rückfrage, wie in deinen Einstellungen festgelegt. ",
          h("a", { href: "#", onClick: (e) => { e.preventDefault(); S.modal = "prefs"; renderAll(); } }, "Ändern")) : null));
}
async function decideAction(a, approve) {
  try { const r = await api("POST", "/api/actions/" + a.id, { approve }); a.status = r.status; a.result = r.result; if (r.status === "failed") toast(r.result, true); }
  catch (e) { toast(e.message, true); }
  renderBody();
}
function paperlessCard(m) {
  const pl = m.meta.paperless, p = pl.proposal || {};
  const title = h("input", { class: "inp", value: p.title || "", id: "pl" + m.id });
  const tags = new Set(p.tags || []);
  const tagBox = h("div", { style: { display: "flex", flexWrap: "wrap", gap: "6px" } });
  const drawTags = () => { tagBox.innerHTML = ""; for (const t of p.tags || []) tagBox.appendChild(h("button", { type: "button", class: "chip", "aria-pressed": tags.has(t) ? "true" : "false", style: tags.has(t) ? { background: "var(--okbg)", color: "var(--ok)", borderColor: "var(--okbd)" } : null, onClick: () => { tags.has(t) ? tags.delete(t) : tags.add(t); drawTags(); } }, t)); };
  drawTags();
  const field = (l, v) => v ? h("div", null, h("div", { class: "tiny muted" }, l), h("div", null, v)) : null;
  const decide = async (approve) => {
    try { const r = await api("POST", "/api/paperless/decide/" + m.id, { approve, title: title.value, tags: [...tags] }); m.meta.paperless = r; renderBody(); toast(approve ? "In Paperless abgelegt." : "Verworfen."); }
    catch (e) { toast(e.message, true); }
  };
  return h("div", { class: "confirm" }, h("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, h("span", { class: "logo", style: { background: "var(--okbg)", color: "var(--ok)" } }, "P"), h("b", null, "Vorschlag für Paperless")),
    pl.state === "pending" ? [h("label", { class: "f", for: "pl" + m.id }, "Titel", title),
      h("div", { class: "grid2", style: { gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))" } }, field("Korrespondent", p.correspondent), field("Dokumenttyp", p.document_type), field("Datum", p.date), field("Betrag", p.amount)),
      p.tags && p.tags.length ? h("div", null, h("div", { class: "tiny muted", style: { marginBottom: "4px" } }, "Tags"), tagBox) : null,
      p.deadline ? h("div", { class: "note warn" }, `Erkannte Frist: ${p.deadline}. Der Fristen-Wächter merkt sie nach dem Ablegen vor.`) : null,
      h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" } }, h("button", { class: "btn", type: "button", onClick: () => decide(true) }, "In Paperless ablegen"), h("button", { class: "btn sec", type: "button", onClick: () => decide(false) }, "Verwerfen"))] :
      h("span", { class: "small", style: { color: pl.state === "saved" ? "var(--ok)" : "var(--muted)" } }, pl.state === "saved" ? h("span", null, `Abgelegt als Dokument ${pl.doc_id}. `, h("a", { href: pl.url, target: "_blank", rel: "noopener" }, "In Paperless öffnen")) : "Verworfen. Das Dokument wurde aus Paperless entfernt."));
}
function answerView(m, isLast, compact) {
  const meta = m.meta, st = meta.stats || {};
  const el = h("div", { class: "a" }, h("span", { class: "model" }, simple() ? "Haus-KI" : meta.model || ""), stepsView(meta.steps));
  el.appendChild(mdView(m.content));
  if (meta.partial) el.appendChild(h("div", { class: "note err" }, "Antwort abgebrochen: " + (meta.error || "Verbindung unterbrochen") + ". Der Anfang bleibt stehen, ist aber unvollständig."));
  el.append(memoryView(meta.memory) || "", ...(meta.actions || []).map(actionCard));
  if (meta.paperless) el.appendChild(paperlessCard(m));
  const cv = citesView(meta.cites, m.id);
  if (cv) el.appendChild(cv);
  if (!S.chat.readonly) {
    const shareOpen = S.menuFor === "s" + m.id;
    el.appendChild(h("div", { class: "acts" },
      window.HKVoice ? window.HKVoice.speakButton(m) : null,
      h("button", { class: "act", type: "button", "aria-label": "Kopieren", title: "Kopieren", onClick: () => { navigator.clipboard.writeText(m.content); toast("Kopiert"); } }, icon("copy", 16)),
      isLast && !S.live ? h("button", { class: "act", type: "button", "aria-label": "Neu erzeugen", title: "Neu erzeugen", onClick: regenerate }, icon("refresh", 16)) : null,
      simple() ? null : h("button", { class: "act", type: "button", "aria-label": "Als Vorlage speichern", title: "Als Vorlage speichern", onClick: () => { const q = previousUser(m); S.modal = { kind: "template", t: null, prompt: q ? q.content : "" }; renderModal(); } }, icon("bookmark", 16)),
      h("span", { class: "rel", "data-pop": "1" }, h("button", { class: "act", type: "button", "aria-label": "Teilen", title: "Teilen", "aria-expanded": shareOpen ? "true" : "false", onClick: () => { S.menuFor = shareOpen ? null : "s" + m.id; S.pop = S.menuFor ? "share" : null; renderBody(); } }, icon("share", 16)),
        shareOpen ? h("div", { class: "pop", style: { bottom: "40px", left: 0 } }, h("div", { class: "tiny muted", style: { padding: "6px 10px" } }, "Antwort senden an"),
          S.me.family.filter((u) => u.id !== S.me.id).map((u) => h("button", { class: "menu-row", type: "button", onClick: async () => { S.menuFor = null; S.pop = null; await api("POST", `/api/messages/${m.id}/share`, { to: u.id }); toast(`An ${u.name} geteilt.`); renderBody(); } }, av(u), u.name))) : null),
      h("button", { class: "act", type: "button", "aria-label": "Gute Antwort", "aria-pressed": meta.feedback > 0 ? "true" : "false", style: { color: meta.feedback > 0 ? "var(--ok)" : null }, onClick: () => feedback(m, meta.feedback > 0 ? 0 : 1) }, icon("up", 16)),
      h("button", { class: "act", type: "button", "aria-label": "Schlechte Antwort", "aria-pressed": meta.feedback < 0 ? "true" : "false", style: { color: meta.feedback < 0 ? "var(--err)" : null }, onClick: () => feedback(m, meta.feedback < 0 ? 0 : -1) }, icon("down", 16)),
      st.tokens && !compact && !simple() ? h("span", { class: "tiny muted hide-sm", style: { marginLeft: "auto", fontVariantNumeric: "tabular-nums", fontFamily: "var(--mono)" } }, `${fmtN(st.tokens)} Token, ${fmtN(st.tps, 1)} Token/s, ${st.seconds} s`) : null));
  }
  if (isLast && meta.followups && meta.followups.length && !S.live && !S.chat.readonly) el.appendChild(h("div", { class: "follow" }, meta.followups.map((f) => h("button", { class: "chip", type: "button", onClick: () => { setDraft(f); send(); } }, f))));
  return el;
}
function previousUser(m) { const i = S.chat.messages.indexOf(m); for (let j = i - 1; j >= 0; j--) if (S.chat.messages[j].role === "user") return S.chat.messages[j]; return null; }
async function feedback(m, v) {
  m.meta.feedback = v;
  renderBody();
  let comment = "";
  if (v < 0) comment = (await promptDialog("Was war falsch?", "Optional, hilft beim Verbessern. Zum Beispiel: falsche Zahl, falsches Dokument, zu lang.", "")) || "";
  await api("POST", `/api/messages/${m.id}/feedback`, { value: v, comment });
  if (v < 0) toast("Danke. Die Antwort erscheint in der Administration unter Antwortqualität.");
}

function liveView() {
  const L = S.live;
  const one = (k) => {
    const a = L.answers[k] || { text: "", steps: [], cites: [], actions: [] };
    const el = h("div", { class: "a" }, h("span", { class: "model" }, simple() ? "Haus-KI" : a.model || L.model));
    if (L.queue && k === "a" && !L.started) {
      el.appendChild(h("div", { class: "confirm" },
        h("b", null, L.queue.ahead ? `Du bist an Position ${L.queue.position}. Vor dir: ${L.queue.ahead}` : "Gleich geht es los"),
        L.queue.eta ? h("span", { class: "small muted" }, `Geschätzt noch etwa ${L.queue.eta < 90 ? L.queue.eta + " Sekunden" : Math.round(L.queue.eta / 60) + " Minuten"}. Du kannst die Seite schließen, die Antwort erscheint trotzdem in diesem Chat.`) : null,
        h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" } },
          toggle("Benachrichtigen, wenn fertig", S.me.prefs.notify_done, async (v) => { S.me.prefs = await api("PUT", "/api/me/prefs", { notify_done: v }); askNotifyPermission(); renderBody(); }),
          h("button", { class: "btn sec", type: "button", onClick: stop }, "Anfrage zurückziehen"))));
      return el;
    }
    const steps = [...a.steps];
    if (!a.text && !a.done) steps.push({ text: a.steps.length ? "Antwort wird formuliert" : "Liest die Frage", state: "run" });
    el.append(stepsView(steps, true) || "", mdView(a.text, !a.done), memoryView(a.memory) || "", ...a.actions.map(actionCard));
    if (a.error) el.appendChild(h("div", { class: "note err" }, a.error));
    const cv = citesView(a.cites, "live");
    if (cv) el.appendChild(cv);
    return el;
  };
  return L.answers.b ? h("div", { class: "cmp" }, one("a"), one("b")) : one("a");
}

// ------------------------------------------------------------------ Senden und Empfangen
function requestBody(text) {
  const b = { text, model: S.model, sources: [...S.sources], style: S.style, think: S.think, attachments: S.attachments.map(({ name, text, image, data }) => ({ name, text, image, data })) };
  if (isAdmin()) { b.advanced = S.advanced; if (S.compare) b.compare_model = S.compare; }
  if (S.tpl) b.template_id = S.tpl.id;
  if (S.route.name === "project") b.project_id = S.route.id;
  return b;
}
async function send() {
  let text = S.draft.trim();
  if (S.tpl) text = fillTemplate(S.tpl.prompt, S.tplVars).trim();
  if ((!text && !S.attachments.length) || S.live) return;
  const body = requestBody(text);
  let r;
  try {
    if (S.editing) r = await api("POST", `/api/messages/${S.editing}/edit`, body);
    else if (S.route.name === "chat" && S.chat && !S.chat.readonly) r = await api("POST", `/api/chats/${S.chat.chat.id}/messages`, body);
    else r = await api("POST", "/api/chats", body);
  } catch (e) { toast(e.message, true); return; }
  setDraft(""); S.attachments = []; S.tpl = null; S.tplVars = {}; S.editing = null;
  if (!S.chat || S.chat.chat.id !== r.chat_id) {
    await loadChats();
    location.hash = "#chat/" + r.chat_id; // lädt den Chat und hängt sich an die laufende Antwort
    return;
  }
  const m = await api("GET", "/api/chats/" + r.chat_id);
  S.chat = m;
  attachJob(r.job_id, r.chat_id);
}
async function regenerate() {
  try { const r = await api("POST", `/api/chats/${S.chat.chat.id}/regenerate`, requestBody("")); S.chat = await api("GET", "/api/chats/" + r.chat_id); attachJob(r.job_id, r.chat_id); }
  catch (e) { toast(e.message, true); }
}
async function stop() {
  if (S.live) await api("POST", `/api/jobs/${S.live.jobId}/cancel`);
}
let paintQueued = false;
function paint() { if (paintQueued) return; paintQueued = true; requestAnimationFrame(() => { paintQueued = false; renderBody(); renderComposer(); }); }
function attachJob(jobId, chatId) {
  if (S.es) S.es.close();
  S.live = { jobId, chatId, model: S.model, answers: { a: { text: "", steps: [], cites: [], actions: [] } }, queue: null, started: false };
  S.stick = true;
  paint();
  const es = new EventSource(`/api/jobs/${jobId}/events`);
  S.es = es;
  es.onmessage = async (ev) => {
    const e = JSON.parse(ev.data), L = S.live;
    if (!L || L.jobId !== jobId) return;
    const k = e.key || "a";
    const a = L.answers[k] || (L.answers[k] = { text: "", steps: [], cites: [], actions: [] });
    switch (e.type) {
      case "queue": L.queue = e; break;
      case "start": L.started = true; break;
      case "variant": a.model = e.model; break;
      case "step": a.steps.push({ text: e.text, state: e.state }); break;
      case "delta": a.text += e.text; break;
      case "reset": a.text = ""; break;
      case "cites": a.cites = e.items; break;
      case "memory": a.memory = e.items; break;
      case "action": a.actions.push({ id: e.id, summary: e.summary, status: "pending" }); break;
      case "paperless": break;
      case "done": a.done = true; if (e.context) S.ctx = e.context; break;
      case "error": a.error = "Antwort abgebrochen: " + e.text; a.done = true; break;
      case "followups": break;
      case "cancelled": a.error = "Abgebrochen."; a.done = true; break;
      case "end":
        es.close(); S.es = null;
        if (e.status !== "done" && !Object.values(L.answers).some((x) => x.text)) { S.live = null; toast(a.error || "Die Antwort ist fehlgeschlagen.", true); }
        S.live = null;
        if (S.route.name === "chat" && S.route.id === chatId) S.chat = await api("GET", "/api/chats/" + chatId);
        loadChats().then(renderSide);
        break;
    }
    paint();
  };
  es.onerror = () => { es.close(); if (S.live && S.live.jobId === jobId) { S.live = null; openChat(chatId); } };
}
function listenEvents() {
  const es = new EventSource("/api/events");
  es.onmessage = (ev) => {
    const e = JSON.parse(ev.data);
    if (e.type === "notification") {
      toast(e.text, e.level === "error");
      systemNotify("Haus-KI", e.text, e.link);
      pollStatus();
    } else if (e.type === "answer_ready") {
      const viewing = S.route.name === "chat" && S.route.id === e.chat_id && !document.hidden;
      if (!viewing) systemNotify("Antwort ist fertig", e.text, "#chat/" + e.chat_id);
    }
  };
}
function askNotifyPermission() { if ("Notification" in window && Notification.permission === "default") Notification.requestPermission(); }
function systemNotify(title, body, link) {
  if (!("Notification" in window) || Notification.permission !== "granted" || !document.hidden) return;
  const n = new Notification(title, { body, tag: link || title });
  n.onclick = () => { window.focus(); if (link) location.hash = link.replace(/^#/, "#"); n.close(); };
}
async function pollStatus() {
  try { S.status = await api("GET", "/api/status"); } catch (e) { return; }
  if (!S.pop) renderHead();
  if (S.me.features.knx && (!S.tripAt || Date.now() - S.tripAt > 120000)) { S.tripAt = Date.now(); loadTrip(); }
}
