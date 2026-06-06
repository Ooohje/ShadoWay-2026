// 간단한 앱 셸 캐시 (오프라인 기본 동작). 지도 타일/ API 는 캐시하지 않음.
const CACHE = "shadoway-v1";
const SHELL = ["./", "index.html", "style.css", "app.js", "config.js",
  "manifest.webmanifest", "icon-192.png", "icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
  ).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/")) return; // API 패스스루
  if (url.origin !== location.origin) return; // 외부(타일) 패스스루
  e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
});
