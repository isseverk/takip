// Takip Akışı — çevrimdışı çalışma katmanı
const SURUM = "takip-v1";
const KABUK = ["./", "./index.html", "./veri.json", "./manifest.webmanifest",
  "./ikon-192.png", "./ikon-512.png", "./ikon-maskable-512.png", "./ikon-96.png", "./apple-touch-icon.png"];

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
