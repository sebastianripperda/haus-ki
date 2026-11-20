/* Haus-KI – Administration: Gerüst, Navigation und gemeinsame Formular-Helfer */
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
    const panel = h("section", { class: "panel" }, title ? h("h3", null, title) : null, opts.intro ? h("p", { class: "small muted u-m0" }, opts.intro) : null);
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
    const row = h("div", { class: "u-row u-wrap u-center" },
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

  // Die Bereiche liegen in admin-ki.js, admin-quellen.js, admin-system.js und admin-menschen.js
  // und tragen sich hier ein. index.html lädt sie nach dieser Datei.
  const SECTIONS = {};

  window.HKAdmin = { render, sections: SECTIONS, kit: { A, form, saveFields, rerender, val, isSecret } };
})();
