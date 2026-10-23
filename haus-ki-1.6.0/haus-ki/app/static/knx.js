/* Haus-KI – Haus-Schnellsteuerung (KNX). Teil der Oberfläche, die Dateien werden in fester Reihenfolge geladen (siehe index.html). */
"use strict";

// ------------------------------------------------------------------ Haus-Schnellsteuerung
async function loadKnx() {
  try { S.knx = await api("GET", "/api/knx"); } catch (e) { S.knx = { enabled: true, rooms: [], error: e.message }; }
  if (S.pop === "knx") renderHead();
}
async function loadTrip() {
  if (!S.me.features.knx) return;
  try { S.trip = await api("GET", "/api/knx/trip"); } catch (e) { S.trip = null; }
  renderHead();
}
function knxControl(it) {
  const main = (it.dpt || "").split(".")[0];
  const write = async (v) => {
    try { await api("POST", "/api/knx/write", { address: it.address, value: v }); it.value = v; toast(`${it.name}: gesetzt`); loadKnx(); }
    catch (e) { toast(e.message, true); }
  };
  if (!it.writable) return h("span", { class: "small muted", style: { display: "inline-flex", gap: "6px", alignItems: "center" } }, it.locked ? icon("lock", 14) : null, it.text);
  if (main === "1") return h("button", { type: "button", class: "tg", role: "switch", "aria-checked": it.value ? "true" : "false", "aria-label": it.name, style: { width: "auto", padding: 0 }, onClick: () => write(!it.value) }, h("span", { class: "track" }));
  if (main === "5") return h("input", { type: "range", min: 0, max: 100, step: 5, value: it.value || 0, "aria-label": it.name, style: { width: "120px" }, onChange: (e) => write(+e.target.value) });
  if (main === "9") return h("span", { style: { display: "inline-flex", alignItems: "center", gap: "4px" } },
    h("button", { class: "ib", type: "button", "aria-label": it.name + " niedriger", onClick: () => write(Math.round(((it.value || 20) - 0.5) * 2) / 2) }, "−"),
    h("span", { class: "small", style: { minWidth: "56px", textAlign: "center" } }, it.text),
    h("button", { class: "ib", type: "button", "aria-label": it.name + " höher", onClick: () => write(Math.round(((it.value || 20) + 0.5) * 2) / 2) }, "+"));
  return h("span", { class: "small muted" }, it.text);
}
function knxPopover() {
  const k = S.knx;
  return h("div", { class: "pop pad", style: { top: "48px", right: 0, width: "min(400px, calc(100vw - 24px))", maxHeight: "70vh", overflowY: "auto" } },
    h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px" } }, h("b", null, "Haus"),
      h("button", { class: "btn sec", type: "button", onClick: async () => { await loadTrip(); S.pop = "knx"; renderHead(); } }, "Bevor wir fahren")),
    S.trip ? h("div", { class: "note " + (S.trip.some((t) => t.open) ? "warn" : "ok") },
      S.trip.length ? (S.trip.some((t) => t.open) ? "Offen: " + S.trip.filter((t) => t.open).map((t) => `${t.name}${t.room ? " (" + t.room + ")" : ""}`).join(", ") : "Alle Fenster sind zu.") : "Keine Fensterkontakte freigegeben.") : null,
    !k ? h("p", { class: "small muted" }, "Lädt …") : k.error ? h("div", { class: "note err" }, "Die KNX-Schnittstelle antwortet nicht: " + k.error) : null,
    k && k.scenes && k.scenes.length ? h("div", null, h("div", { class: "tiny muted", style: { marginBottom: "6px" } }, "Szenen"),
      h("div", { class: "follow" }, k.scenes.map((s) => h("button", { class: "chip", type: "button", onClick: async () => {
        if (!(await confirmDialog("Szene ausführen?", `„${s}“ schaltet mehrere Geräte.`, "Ausführen"))) return;
        try { const r = await api("POST", "/api/knx/scene", { name: s }); toast(r.result); } catch (e) { toast(e.message, true); } } }, s)))) : null,
    k && k.rooms ? k.rooms.map((r) => h("div", null, h("div", { class: "over", style: { margin: "6px 0 2px" } }, r.name),
      r.items.map((it) => h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px", minHeight: "40px" } }, h("span", { class: "small" }, it.name), knxControl(it))))) : null,
    k && k.rooms && !k.rooms.length && !k.error ? h("p", { class: "small muted", style: { margin: 0 } }, isAdmin() ? "Noch keine Gruppenadressen freigegeben. Das geht unter Administration › Haus." : "Für dich sind noch keine Räume freigegeben.") : null);
}
