// アプリ本体はキャッシュ、データは常にネット優先（オフライン時のみキャッシュ）
const CACHE = "sfcw-v2";
const SHELL = ["./", "index.html", "style.css", "app.js", "icon.svg", "manifest.webmanifest"];

self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  e.respondWith(
    fetch(e.request).then((r) => {
      const copy = r.clone();
      caches.open(CACHE).then((c) => c.put(url.pathname.endsWith("data.enc.json") ? "data.enc.json" : e.request, copy));
      return r;
    }).catch(() => caches.match(url.pathname.endsWith("data.enc.json") ? "data.enc.json" : e.request))
  );
});
