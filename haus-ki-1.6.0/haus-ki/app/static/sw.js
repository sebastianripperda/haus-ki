/* Haus-KI Service Worker: schnelles Laden, Push-Benachrichtigungen, „Teilen an Haus-KI“.
   Daten aus /api werden nie zwischengespeichert. */
const SHELL = "hk-shell-v2";
const SHARE = "hk-share";
const ASSETS = ["/", "/static/app.css", "/static/md.js", "/static/theme.js", "/static/core.js", "/static/login.js", "/static/shell.js",
  "/static/knx.js", "/static/pages.js", "/static/chat.js", "/static/composer.js", "/static/commands.js", "/static/dialogs.js", "/static/voice.js",
  "/static/admin.js", "/static/icons/icon-192.png", "/static/fonts/inter-latin-400-normal.woff2", "/static/fonts/inter-latin-700-normal.woff2"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(ASSETS).catch(() => {})).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== SHELL && k !== SHARE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  if (e.request.method === "POST" && url.pathname === "/share") { e.respondWith(receiveShare(e.request)); return; }
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/")) return;
  // Netz zuerst, damit Updates sofort ankommen; ohne Netz die gespeicherte Fassung
  e.respondWith(fetch(e.request).then((res) => {
    if (res.ok && (url.pathname === "/" || url.pathname.startsWith("/static/"))) {
      const copy = res.clone();
      caches.open(SHELL).then((c) => c.put(e.request, copy));
    }
    return res;
  }).catch(() => caches.match(e.request).then((r) => r || caches.match("/"))));
});

async function receiveShare(request) {
  // Geteilte Dateien nur auf dem Gerät ablegen; hochgeladen werden sie erst von der angemeldeten App
  const form = await request.formData();
  const cache = await caches.open(SHARE);
  const stamp = Date.now();
  let i = 0;
  for (const f of form.getAll("files")) {
    if (!(f instanceof File) || !f.size) continue;
    await cache.put(`/share-inbox/${stamp}-${i++}`, new Response(f, { headers: { "Content-Type": f.type || "application/octet-stream", "X-Name": encodeURIComponent(f.name || "datei") } }));
  }
  const text = [form.get("title"), form.get("text"), form.get("url")].filter(Boolean).join("\n").trim();
  if (text) await cache.put(`/share-inbox/${stamp}-text`, new Response(text, { headers: { "Content-Type": "text/plain; charset=utf-8", "X-Name": "text" } }));
  return Response.redirect("/#share", 303);
}

self.addEventListener("push", (e) => {
  let d = { title: "Haus-KI", body: "", link: "/" };
  try { d = Object.assign(d, e.data.json()); } catch (err) { if (e.data) d.body = e.data.text(); }
  e.waitUntil(self.registration.showNotification(d.title, { body: d.body, icon: "/static/icons/icon-192.png",
    badge: "/static/icons/badge-96.png", tag: d.link, data: { link: d.link } }));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const link = (e.notification.data && e.notification.data.link) || "/";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    for (const c of list) { if ("focus" in c) { c.navigate(link).catch(() => {}); return c.focus(); } }
    return self.clients.openWindow(link);
  }));
});
