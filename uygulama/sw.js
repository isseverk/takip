// Takip Akışı — çevrimdışı çalışma katmanı
const SURUM = "takip-v2";
const KABUK = ["./", "./index.html", "./veri.json", "./manifest.webmanifest",
  "./ikon-192.png", "./ikon-512.png", "./ikon-maskable-512.png", "./ikon-96.png", "./rozet-96.png", "./apple-touch-icon.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(SURUM).then(c => Promise.all(KABUK.map(u => c.add(u).catch(() => null))))
    .then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== SURUM).map(x => caches.delete(x))))
    .then(() => self.clients.claim()));
});

async function agOnce(istek, anahtar) {
  const c = await caches.open(SURUM);
  try {
    const cevap = await fetch(istek, {cache: "no-store"});
    if (cevap.ok) c.put(anahtar || istek, cevap.clone());
    return cevap;
  } catch (e) {
    const eski = await c.match(anahtar || istek, {ignoreSearch: true});
    if (eski) return eski;
    throw e;
  }
}

self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;  // GitHub/ntfy istekleri doğrudan
  if (e.request.mode === "navigate") { e.respondWith(agOnce(e.request, "./index.html")); return; }
  if (u.pathname.endsWith("/veri.json")) { e.respondWith(agOnce(e.request, "./veri.json")); return; }
  e.respondWith(caches.match(e.request).then(x => x || agOnce(e.request)));
});

// ───── uygulama bildirimleri (Web Push)
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = {metin: e.data ? e.data.text() : ""}; }
  e.waitUntil(self.registration.showNotification(d.baslik || "Takip", {
    body: d.metin || "", icon: "ikon-192.png", badge: "rozet-96.png", lang: "tr",
    tag: d.etiket || "takip", renotify: true, data: {url: d.url || "./"}
  }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const hedef = new URL((e.notification.data && e.notification.data.url) || "./", self.registration.scope).href;
  const uygulamaIci = hedef.startsWith(self.registration.scope);
  e.waitUntil((async () => {
    if (uygulamaIci) {
      const acik = await clients.matchAll({type: "window", includeUncontrolled: true});
      for (const c of acik) {
        if (!c.url.startsWith(self.registration.scope)) continue;
        try { await c.focus(); await c.navigate(hedef); return; } catch (_) {}
      }
    }
    await clients.openWindow(hedef);
  })());
});
