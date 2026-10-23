/* Haus-KI – Sprache: Aufnahme, Spracherkennung, Vorlesen, Gesprächsmodus.
   Erkennung (Whisper) und Stimme (Piper) laufen auf dem Haus-KI-Server. */
"use strict";
(function () {
  const HK = window.HK;
  const { S, h, api, toast, icon } = HK;
  const V = { phase: "idle", sec: 0, level: 0, rec: null, audio: null, speakKey: null, speakPos: 0, speakDur: 0, info: null };
  const T = { on: false, phase: "listen", paused: false, log: [], chatId: null, pending: null, hint: "", stopRequested: false };
  let talkEl = null;

  const enabled = () => !!(S.me && S.me.features && S.me.features.voice);
  const micPossible = () => !!(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  const fmtT = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const MIC = "M12 3a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3";
  const SPK = "M4 9v6h4l5 4V5L8 9zM16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11";
  const WAVE = "M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4";
  const svg = (d, size = 20, sw = 1.8) => h("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": sw, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" }, h("path", { d }));

  // ------------------------------------------------------------------ Aufnahme
  function pickMime() {
    for (const m of ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4", "audio/webm"]) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m)) return m;
    }
    return "";
  }
  /* Nimmt auf, bis stop() gerufen wird oder (mit vad) nach dem Sprechen eine Pause folgt.
     Liefert ein Steuerobjekt mit promise (Blob oder null, wenn nichts gesprochen wurde). */
  async function record({ vad = true, maxSec = 60, noSpeechMs = 15000, onTick } = {}) {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    const mime = pickMime();
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const chunks = [];
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const src = ctx.createMediaStreamSource(stream);
    const an = ctx.createAnalyser();
    an.fftSize = 1024;
    src.connect(an);
    const buf = new Float32Array(an.fftSize);
    let spoke = false, loudSince = 0, quietSince = 0, raf = 0, stopped = false;
    const started = performance.now();
    let resolveFn;
    const promise = new Promise((res) => { resolveFn = res; });
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      cancelAnimationFrame(raf);
      stream.getTracks().forEach((t) => t.stop());
      ctx.close().catch(() => {});
      resolveFn(spoke || !vad ? new Blob(chunks, { type: rec.mimeType || mime || "audio/webm" }) : null);
    };
    const stop = () => { if (!stopped) { stopped = true; if (rec.state !== "inactive") rec.stop(); } };
    const loop = () => {
      an.getFloatTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      const level = Math.min(1, Math.sqrt(sum / buf.length) * 6);
      const now = performance.now();
      if (level > 0.12) { if (!loudSince) loudSince = now; if (now - loudSince > 150) spoke = true; quietSince = 0; }
      else { loudSince = 0; if (spoke && !quietSince) quietSince = now; }
      if (onTick) onTick(level, (now - started) / 1000);
      if (vad && spoke && quietSince && now - quietSince > 1200) return stop();
      if (vad && !spoke && now - started > noSpeechMs) return stop();
      if ((now - started) / 1000 > maxSec) return stop();
      raf = requestAnimationFrame(loop);
    };
    rec.start(250);
    raf = requestAnimationFrame(loop);
    // finish(): bewusst beendet, Aufnahme immer zur Erkennung geben; cancel(): verwerfen
    return { stop, finish: () => { spoke = true; stop(); }, cancel: () => { spoke = false; stop(); }, promise, setSpoke: () => { spoke = true; } };
  }

  async function transcribe(blob) {
    const fd = new FormData();
    const ext = (blob.type || "").includes("mp4") ? "m4a" : (blob.type || "").includes("ogg") ? "ogg" : "webm";
    fd.append("file", blob, "aufnahme." + ext);
    const r = await api("POST", "/api/voice/stt", fd);
    return r.text;
  }

  function showMicHelp() {
    S.modal = "voice-help";
    HK.renderAll();
  }

  // ------------------------------------------------------------------ Eingabefeld
  async function composerToggle() {
    if (V.phase === "rec") { V.rec && V.rec.finish(); return; }
    if (V.phase !== "idle") return;
    if (!micPossible()) return showMicHelp();
    try {
      V.rec = await record({ vad: S.me.voice ? S.me.voice.vad : true, maxSec: 90, noSpeechMs: 20000,
        onTick: (lvl, sec) => { V.level = lvl; V.sec = Math.floor(sec); updateLive(); } });
    } catch (e) { return showMicHelp(); }
    V.phase = "rec"; V.sec = 0; paintComposer();
    const blob = await V.rec.promise;
    V.rec = null;
    if (!blob) { V.phase = "idle"; paintComposer(); if (!V.cancelled) toast("Ich habe nichts gehört. Sprich etwas näher am Gerät.", true); V.cancelled = false; return; }
    V.phase = "stt"; paintComposer();
    try {
      const text = await transcribe(blob);
      const cur = S.draft.trim();
      HK.setDraft(cur ? cur + " " + text : text);
      V.phase = "idle"; paintComposer();
      const ta = document.querySelector("#composer textarea");
      if (ta && innerWidth > 720 && !S.me.prefs.voice_auto_send) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
      if (S.me.prefs.voice_auto_send) HK.send();
    } catch (e) { V.phase = "idle"; paintComposer(); toast(e.message, true); }
  }
  function composerCancel() { V.cancelled = true; if (V.rec) V.rec.cancel(); }
  // Nur bei einem Wechsel der Phase neu zeichnen; Zeit und Pegel werden direkt aktualisiert,
  // damit die Knöpfe stehen bleiben und sich zuverlässig antippen lassen.
  function paintComposer() { HK.renderComposerVoice(); }
  const barH = (i, lv) => Math.round(6 + 18 * Math.min(1, lv * (0.6 + ((i * 37) % 10) / 12))) + "px";
  function bars(n, color, cls) {
    return h("span", { class: "hk-bars " + (cls || ""), "aria-hidden": "true" }, Array.from({ length: n }, (_, i) =>
      h("span", { style: { height: barH(i, V.level), background: color || "var(--accent)" } })));
  }
  function updateLive() {
    for (const box of document.querySelectorAll(".hk-bars.live")) {
      Array.from(box.children).forEach((el, i) => { el.style.height = barH(i, V.level); });
    }
    const t = document.getElementById("rec-time");
    if (t) t.textContent = fmtT(V.sec);
  }
  function composerBanner() {
    if (V.phase === "rec") return h("div", { class: "voice-row", role: "status" },
      h("span", { class: "rec-dot", "aria-hidden": "true" }), h("b", null, "Aufnahme läuft"), h("span", { class: "mono muted", id: "rec-time" }, fmtT(V.sec)), bars(12, null, "live"),
      h("span", { class: "grow" }),
      h("button", { class: "act", type: "button", onClick: composerCancel }, "Verwerfen"),
      h("button", { class: "btn", type: "button", onClick: () => V.rec && V.rec.finish() }, S.me.prefs.voice_auto_send ? "Fertig und senden" : "Fertig"));
    if (V.phase === "stt") return h("div", { class: "voice-row muted", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Erkenne Sprache …",
      h("span", { class: "tiny" }, `Whisper „${(S.me.voice && S.me.voice.model) || "small"}“, lokal auf dem Haus-KI-Server`));
    return null;
  }
  function micButton() {
    if (!enabled()) return null;
    const rec = V.phase === "rec";
    return h("button", { class: "mic" + (rec ? " on" : ""), type: "button", "aria-pressed": rec ? "true" : "false", disabled: V.phase === "stt",
      "aria-label": rec ? "Aufnahme beenden" : "Spracheingabe starten", title: rec ? "Aufnahme beenden" : "Spracheingabe", onClick: composerToggle }, svg(MIC));
  }

  // ------------------------------------------------------------------ Vorlesen
  async function speak(text, { raw = false, key = null, voice = "" } = {}) {
    stopSpeak();
    V.speakKey = key;
    const res = await fetch("/api/voice/tts", { method: "POST", headers: { "x-haus-ki": "1", "content-type": "application/json" },
      body: JSON.stringify({ text, raw, voice }) });
    if (!res.ok) { V.speakKey = null; let msg = "Vorlesen ist gerade nicht möglich."; try { msg = (await res.json()).detail || msg; } catch (e) { /* leer */ } throw new Error(msg); }
    const url = URL.createObjectURL(await res.blob());
    const audio = new Audio(url);
    V.audio = audio;
    return new Promise((resolve) => {
      const done = () => { URL.revokeObjectURL(url); if (V.audio === audio) { V.audio = null; V.speakKey = null; } HK.renderBody(); renderTalk(); resolve(); };
      audio.onended = done; audio.onerror = done; audio.onpause = () => { if (audio.currentTime < audio.duration) done(); };
      audio.ontimeupdate = () => { V.speakPos = audio.currentTime; V.speakDur = audio.duration || 0; const el = document.getElementById("speak-time"); if (el) el.textContent = `${fmtT(V.speakPos)} / ${fmtT(V.speakDur)}`; };
      audio.play().catch(() => done());
      HK.renderBody();
    });
  }
  function stopSpeak() { if (V.audio) { const a = V.audio; V.audio = null; V.speakKey = null; a.pause(); } }
  function speakButton(m) {
    if (!enabled()) return null;
    const on = V.speakKey === "m" + m.id;
    return h("button", { class: "act", type: "button", "aria-pressed": on ? "true" : "false", "aria-label": on ? "Vorlesen beenden" : "Vorlesen", title: on ? "Vorlesen beenden" : "Vorlesen",
      style: on ? { color: "var(--accent)" } : null,
      onClick: () => { if (on) { stopSpeak(); HK.renderBody(); } else speak(m.content, { key: "m" + m.id }).catch((e) => toast(e.message, true)); } },
      svg(SPK, 16), on ? h("span", { class: "tiny" }, "Liest vor ", h("span", { id: "speak-time", class: "mono" }, `${fmtT(V.speakPos)} / ${fmtT(V.speakDur)}`)) : null);
  }

  // ------------------------------------------------------------------ Satzweise vorlesen
  /* Zerlegt den bisher gestreamten Text in vorlesbare Sätze. Tabellen und Codeblöcke werden
     durch einen kurzen Hinweis ersetzt. Gibt nur vollständige Sätze zurück (außer final). */
  function speakableSentences(text, final) {
    const TABLE = "Es folgt eine Tabelle, die Details stehen im Chat.", CODE = "Ein Codebeispiel steht im Chat.";
    const lines = text.split("\n"), paras = [];
    let inCode = false, inTable = false, cur = "";
    const endPara = () => { if (cur.trim()) paras.push(cur.trim()); cur = ""; };
    lines.forEach((l, i) => {
      const last = i === lines.length - 1;
      if (/^\s*```/.test(l)) { endPara(); if (inCode) { inCode = false; paras.push(CODE); } else inCode = true; return; }
      if (inCode) return;
      if (/^\s*\|/.test(l)) { endPara(); inTable = true; return; }
      if (inTable) { if (last && !final && !l.trim()) return; inTable = false; paras.push(TABLE); }
      if (!l.trim()) { endPara(); return; }
      const item = l.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
      if (item) { endPara(); cur = item[1].trim(); return; }   // Listenpunkt = eigener Satz
      cur += (cur ? " " : "") + l.trim();
    });
    if (inTable && final) paras.push(TABLE);
    if (inCode && final) paras.push(CODE);
    // Satzende nur bei Satzzeichen + Leerzeichen + neuem Satzanfang, damit „1.184,20“ oder „z. B.“ nicht trennen
    const ABBR = /(?:\b(?:z|d|u|o|v|s|ca|bzw|usw|Nr|Dr|Str|ggf|evtl|inkl|zzgl|vgl|Mio|Mrd|Tel|St|Jh)\.)$/;
    const split = (p) => {
      const out = [];
      let start = 0;
      for (const m of p.matchAll(/[.!?:]\s+(?=[A-ZÄÖÜ„"(0-9])/g)) {
        const end = m.index + 1;
        if (ABBR.test(p.slice(Math.max(0, end - 5), end))) continue;
        out.push(p.slice(start, end).trim());
        start = m.index + m[0].length;
      }
      out.push(p.slice(start).trim());
      return out.filter(Boolean);
    };
    const out = [];
    paras.forEach((p) => out.push(...split(p)));
    if (cur.trim()) {
      const parts = split(cur);
      if (!final && !/[.!?:]$/.test(parts[parts.length - 1])) parts.pop(); // Satz noch im Entstehen
      out.push(...parts);
    }
    return out;
  }
  function makeSpeaker() {
    const queue = [];
    let playing = false, stopped = false, waiters = [];
    const fetchAudio = (text) => fetch("/api/voice/tts", { method: "POST", headers: { "x-haus-ki": "1", "content-type": "application/json" },
      body: JSON.stringify({ text }) }).then((r) => (r.ok ? r.blob() : null)).catch(() => null);
    async function run() {
      playing = true;
      while (queue.length && !stopped) {
        const blob = await queue.shift();
        if (!blob || stopped) continue;
        if (T.on && T.phase !== "speak") setPhase("speak");
        await new Promise((resolve) => {
          const url = URL.createObjectURL(blob), a = new Audio(url);
          V.audio = a; V.speakKey = "talk";
          const done = () => { URL.revokeObjectURL(url); if (V.audio === a) { V.audio = null; V.speakKey = null; } resolve(); };
          a.onended = done; a.onerror = done; a.onpause = () => { if (a.currentTime < a.duration) done(); };
          a.play().catch(done);
        });
      }
      playing = false;
      waiters.splice(0).forEach((w) => w());
    }
    return {
      push(text) { if (stopped) return; queue.push(fetchAudio(text)); if (!playing) run(); },
      done() { return playing || queue.length ? new Promise((r) => waiters.push(r)) : Promise.resolve(); },
      stop() { stopped = true; queue.length = 0; stopSpeak(); waiters.splice(0).forEach((w) => w()); },
      get stopped() { return stopped; },
    };
  }

  // ------------------------------------------------------------------ Gesprächsmodus
  async function askStreaming(text, speaker) {
    const body = HK.requestBody(text);
    const r = T.chatId ? await api("POST", `/api/chats/${T.chatId}/messages`, body) : await api("POST", "/api/chats", body);
    T.chatId = r.chat_id;
    let full = "", spoken = 0;
    const feed = (final) => {
      if (!speaker || speaker.stopped) return;
      const sents = speakableSentences(full, final);
      for (; spoken < sents.length; spoken++) speaker.push(sents[spoken]);
    };
    await new Promise((resolve) => {
      const es = new EventSource(`/api/jobs/${r.job_id}/events`);
      es.onmessage = (ev) => {
        const e = JSON.parse(ev.data);
        if (e.type === "delta" && (e.key || "a") === "a") { full += e.text; feed(false); }
        else if (e.type === "reset" && (e.key || "a") === "a") { full = ""; spoken = 0; }
        else if (e.type === "done" && (e.key || "a") === "a") feed(true);
        else if (e.type === "end") { es.close(); resolve(); }
      };
      es.onerror = () => { es.close(); resolve(); };
    });
    const chat = await api("GET", "/api/chats/" + T.chatId);
    const last = [...chat.messages].reverse().find((m) => m.role === "assistant");
    return last || { content: "Darauf habe ich gerade keine Antwort bekommen.", meta: { actions: [] } };
  }
  async function askAndWait(text) {
    const body = HK.requestBody(text);
    const r = T.chatId ? await api("POST", `/api/chats/${T.chatId}/messages`, body) : await api("POST", "/api/chats", body);
    T.chatId = r.chat_id;
    await new Promise((resolve) => {
      const es = new EventSource(`/api/jobs/${r.job_id}/events`);
      es.onmessage = (ev) => { const e = JSON.parse(ev.data); if (e.type === "end") { es.close(); resolve(); } };
      es.onerror = () => { es.close(); resolve(); };
    });
    const chat = await api("GET", "/api/chats/" + T.chatId);
    const last = [...chat.messages].reverse().find((m) => m.role === "assistant");
    return last || { content: "Darauf habe ich gerade keine Antwort bekommen.", meta: { actions: [] } };
  }
  function setPhase(p, hint) { T.phase = p; T.hint = hint || ""; renderTalk(); }
  async function talkLoop() {
    while (T.on) {
      if (T.paused) { await new Promise((r) => { T.resume = r; }); continue; }
      setPhase("listen");
      let blob = null;
      try {
        V.rec = await record({ vad: true, maxSec: 45, noSpeechMs: 15000, onTick: (lvl) => { V.level = lvl; updateLive(); } });
        blob = await V.rec.promise;
      } catch (e) { T.on = false; closeTalk(); return showMicHelp(); }
      V.rec = null;
      if (!T.on) return;
      if (!blob) { T.paused = true; setPhase("listen", "Ich habe eine Weile nichts gehört und mache Pause. Tippe auf „Weiter zuhören“."); continue; }
      setPhase("stt");
      let text = "";
      try { text = await transcribe(blob); } catch (e) {
        await say(e.message.startsWith("Ich habe") ? "Ich habe dich nicht verstanden. Bitte noch einmal." : e.message);
        continue;
      }
      T.log.push({ who: S.me.name, text });
      if (T.pending) { await confirmPending(text); continue; }
      setPhase("think");
      let ans;
      const reading = S.me.prefs.voice_read_talk !== false;
      T.speaker = reading ? makeSpeaker() : null;
      try { ans = await askStreaming(text, T.speaker); } catch (e) { await say("Das hat nicht geklappt: " + e.message); continue; }
      T.log.push({ who: "Haus-KI", text: ans.content });
      renderTalk();
      if (T.speaker) { await T.speaker.done(); T.speaker = null; }
      if (!T.on) return;
      const acts = (ans.meta.actions || []).filter((a) => a.status === "pending");
      if (acts.length) {
        T.pending = acts[0];
        const prompt = S.me.voice && S.me.voice.confirm ? `${acts[0].summary} Sag ja oder nein.` : `${acts[0].summary} Bitte bestätige auf dem Bildschirm.`;
        if (reading) await say(prompt); else renderTalk();
      }
      if (T.pending && !(S.me.voice && S.me.voice.confirm)) { T.paused = true; renderTalk(); }
    }
  }
  async function say(text, markdown) {
    if (!T.on) return;
    setPhase("speak");
    try { await speak(text, { raw: !markdown, key: "talk" }); } catch (e) { T.hint = e.message; }
  }
  async function confirmPending(text) {
    const a = T.pending;
    setPhase("think");
    try {
      const r = await api("POST", `/api/actions/${a.id}/voice`, { text });
      if (r.status === "unclear") { await say("Ich habe kein klares Ja verstanden. Bitte sag ja oder nein, oder tippe auf Ausführen."); return; }
      T.pending = null;
      const msg = r.status === "done" ? r.result : r.status === "rejected" ? "Gut, ich habe nichts geändert." : r.result;
      T.log.push({ who: "Haus-KI", text: msg });
      await say(msg);
    } catch (e) { T.pending = null; await say(e.message); }
  }
  async function confirmByButton(approve) {
    const a = T.pending;
    if (!a) return;
    stopSpeak();
    try {
      const r = await api("POST", "/api/actions/" + a.id, { approve });
      T.pending = null;
      T.log.push({ who: "Haus-KI", text: r.status === "rejected" ? "Abgebrochen, nichts geändert." : r.result });
      if (T.paused) { T.paused = false; if (T.resume) T.resume(); }
      renderTalk();
    } catch (e) { toast(e.message, true); }
  }
  function openTalk() {
    if (!micPossible()) return showMicHelp();
    if (S.live) return toast("Warte bitte, bis die laufende Antwort fertig ist.", true);
    Object.assign(T, { on: true, phase: "listen", paused: false, log: [], pending: null, hint: "",
      chatId: S.route.name === "chat" && S.chat && !S.chat.readonly ? S.chat.chat.id : null });
    if (!talkEl) { talkEl = h("div", { id: "talk" }); document.body.appendChild(talkEl); }
    renderTalk();
    talkLoop();
  }
  function closeTalk() {
    T.on = false;
    if (T.speaker) T.speaker.stop();
    if (V.rec) V.rec.cancel();
    stopSpeak();
    if (T.resume) T.resume();
    if (talkEl) talkEl.innerHTML = "";
    if (T.chatId) { HK.loadChats().then(() => HK.go("#chat/" + T.chatId)); }
  }
  function togglePause() {
    T.paused = !T.paused;
    if (T.paused) { if (V.rec) V.rec.cancel(); if (T.speaker) T.speaker.stop(); stopSpeak(); }
    else if (T.resume) { const r = T.resume; T.resume = null; r(); }
    renderTalk();
  }
  function mainButton() {
    if (T.phase === "speak") { if (T.speaker) T.speaker.stop(); stopSpeak(); return; } // unterbrechen
    if (T.phase === "listen" && V.rec && !T.paused) { V.rec.finish(); return; } // Frage beenden
    if (T.paused) togglePause();
  }
  function renderTalk() {
    if (!talkEl) return;
    talkEl.innerHTML = "";
    if (!T.on) return;
    const LABEL = { listen: "Hört zu", stt: "Erkennt Sprache", think: "Denkt nach", speak: "Spricht" };
    const HINT = { listen: "Sprich einfach. Eine kurze Pause beendet deine Frage.", stt: "Deine Frage wird auf dem Haus-KI-Server in Text umgewandelt.",
      think: "Haus-KI sucht in den eingeschalteten Quellen und formuliert die Antwort.", speak: "Tippe auf den Kreis, um Haus-KI zu unterbrechen." };
    const listening = T.phase === "listen" && !T.paused;
    const srcOn = [...S.sources].map((k) => ({ paperless: "Paperless", jellyfin: "Jellyfin", knx: "Haus", m365: "Microsoft 365", mail: "Postfächer", web: "Internet" }[k])).filter(Boolean);
    talkEl.appendChild(h("div", { class: "talk", role: "dialog", "aria-modal": "true", "aria-labelledby": "talk-title" },
      h("div", { class: "talk-head" }, h("h2", { id: "talk-title" }, "Gesprächsmodus"), h("span", { class: "badge" }, S.model),
        h("span", { class: "small muted" }, "Quellen: " + (srcOn.join(", ") || "keine, nur allgemeines Wissen")), h("span", { class: "grow" }),
        h("button", { class: "ib", type: "button", "aria-label": "Gesprächsmodus beenden", onClick: closeTalk }, icon("x"))),
      h("div", { class: "talk-body" },
        h("div", { class: "over", role: "status", "aria-live": "polite", style: { color: listening ? "var(--accent)" : "var(--muted)" } }, T.paused ? "Pausiert" : LABEL[T.phase]),
        h("button", { class: "talk-btn" + (listening ? " pulse" : ""), type: "button", style: { background: T.paused ? "var(--faint)" : listening ? "var(--accent)" : "var(--primary)" },
          "aria-label": T.phase === "speak" ? "Unterbrechen" : T.paused ? "Weiter zuhören" : "Frage beenden", onClick: mainButton },
          T.phase === "speak" && !T.paused ? bars(14, "currentColor") : listening ? h("span", { style: { display: "flex", flexDirection: "column", alignItems: "center", gap: "6px" } }, svg(MIC, 44, 1.6), bars(9, "currentColor", "live")) :
            (T.phase === "stt" || T.phase === "think") && !T.paused ? h("span", { class: "spinner big", "aria-hidden": "true" }) : svg(MIC, 48, 1.6)),
        h("p", { class: "muted small", style: { margin: 0, maxWidth: "46ch" } }, T.hint || (T.paused ? "Das Mikrofon ist aus. Tippe auf „Weiter zuhören“." : HINT[T.phase])),
        T.pending ? h("div", { class: "confirm", style: { maxWidth: "620px", width: "100%", textAlign: "left" } }, h("b", null, T.pending.summary),
          h("div", { style: { display: "flex", gap: "8px" } }, h("button", { class: "btn", type: "button", onClick: () => confirmByButton(true) }, "Ausführen"),
            h("button", { class: "btn sec", type: "button", onClick: () => confirmByButton(false) }, "Abbrechen"))) : null,
        h("div", { class: "talk-log" }, T.log.slice(-4).map((l) => h("div", { class: "talk-line" + (l.who === "Haus-KI" ? "" : " me") },
          h("span", { class: "tiny muted", style: { fontWeight: 700 } }, l.who),
          l.who === "Haus-KI" ? h("span", { class: "talk-bubble md", html: window.MD.render(l.text) }) : h("span", { class: "talk-bubble" }, l.text))))),
      h("div", { class: "talk-foot" },
        h("button", { class: "btn sec", type: "button", onClick: togglePause }, T.paused ? "Weiter zuhören" : "Pause"),
        h("button", { class: "btn", type: "button", onClick: closeTalk }, "Gespräch beenden")),
      h("p", { class: "tiny muted", style: { textAlign: "center", margin: "0 0 12px" } }, "Erkennung und Stimme laufen lokal. Aufnahmen werden nicht gespeichert, das Gespräch erscheint als normaler Chat.")));
  }

  // ------------------------------------------------------------------ Einstellungen und Hilfe
  async function settingsModal(frame) {
    if (!V.info) { try { V.info = await api("GET", "/api/voice/info"); } catch (e) { return frame("", "Sprache", [h("div", { class: "note err" }, e.message)]); } }
    const p = S.me.prefs, info = V.info;
    const mine = p.voice || info.default_voice;
    const save = async (k, v) => { S.me.prefs = await api("PUT", "/api/me/prefs", { [k]: v }); HK.renderAll(); };
    return frame("Nur für " + S.me.name, "Sprache", [
      h("div", null, h("div", { class: "small muted", style: { marginBottom: "6px" } }, "Stimme"),
        info.voices.map((v) => h("div", { class: "list-row", style: { borderTop: "1px solid var(--row)", flexWrap: "nowrap" } },
          h("button", { type: "button", class: "tg", style: { flex: "1 1 auto", width: "auto", minWidth: 0, padding: "6px 0" }, role: "radio", "aria-checked": v.id === mine ? "true" : "false", onClick: () => save("voice", v.id) },
            h("span", { class: "track", "aria-hidden": "true" }), h("span", { class: "tt" }, h("span", null, v.name), h("small", null, v.desc || v.id))),
          h("button", { class: "act", type: "button", style: { color: "var(--accent)" }, onClick: () => speak("Hallo, ich bin Haus-KI. So klinge ich mit dieser Stimme.", { raw: true, voice: v.id, key: "preview" }).catch((e) => toast(e.message, true)) }, "Probe hören")))),
      h("div", null, h("div", { class: "small muted", style: { marginBottom: "6px" } }, "Tempo"),
        HK.seg([["slow", "Langsamer"], ["normal", "Normal"], ["fast", "Schneller"]], p.voice_speed || "normal", (v) => save("voice_speed", v), "Tempo")),
      HK.toggle("Nach dem Sprechen sofort senden", !!p.voice_auto_send, (v) => save("voice_auto_send", v), "Sonst erscheint der erkannte Text erst im Eingabefeld, damit du ihn prüfen kannst."),
      HK.toggle("Im Gesprächsmodus Antworten vorlesen", p.voice_read_talk !== false, (v) => save("voice_read_talk", v), "Außerhalb des Gesprächsmodus liest Haus-KI nur vor, wenn du den Lautsprecher antippst."),
      h("p", { class: "tiny muted", style: { margin: 0 } }, "Sprache wird auf dem Haus-KI-Server erkannt und erzeugt. Aufnahmen werden nur im Arbeitsspeicher verarbeitet und nie gespeichert.")]);
  }
  function helpModal(frame) {
    const reason = !window.isSecureContext ? "Die Seite ist nicht über eine vertrauenswürdige HTTPS-Verbindung geöffnet." :
      !navigator.mediaDevices ? "Dieser Browser unterstützt keine Mikrofonaufnahmen." : "Der Zugriff auf das Mikrofon wurde nicht erlaubt.";
    return frame("", "Mikrofon nicht verfügbar", [
      h("div", { class: "note warn" }, reason),
      h("ol", { class: "small", style: { margin: 0, paddingLeft: "20px", display: "flex", flexDirection: "column", gap: "6px" } },
        h("li", null, "Haus-KI-Zertifikat einmalig auf diesem Gerät installieren: ", h("a", { href: "/ca.crt" }, "Zertifikat herunterladen"), ". Auf dem iPhone danach unter Einstellungen › Allgemein › Info › Zertifikatsvertrauen einschalten."),
        h("li", null, "Seite neu laden und den Mikrofon-Zugriff erlauben, wenn der Browser fragt."),
        h("li", null, "Wurde der Zugriff früher abgelehnt: in den Website-Einstellungen des Browsers das Mikrofon für Haus-KI erlauben.")),
      h("p", { class: "tiny muted", style: { margin: 0 } }, "Tippen funktioniert immer, auch ohne Mikrofon.")]);
  }

  window.HKVoice = { speakableSentences, speak, enabled, micButton, composerBanner, speakButton, openTalk, settingsModal, helpModal, stopSpeak, state: V, talk: T };
})();
