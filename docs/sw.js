// 앱 셸 캐시. 전략: 네트워크 우선(network-first) — 항상 최신을 받아오고,
// 오프라인일 때만 캐시로 폴백한다. 그래서 배포 즉시 갱신이 반영된다.
// 지도 타일/API 는 캐시하지 않고 그대로 통과.
const CACHE = "shadoway-v2";
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
  if (e.request.method !== "GET") return;            // 변경요청 통과
  if (url.origin !== location.origin) return;         // 타일 등 외부 통과
  if (url.pathname.startsWith("/api/")) return;       // API 통과

  // network-first: 최신 우선, 성공 시 캐시 갱신, 실패(오프라인) 시 캐시 폴백
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request).then((hit) => hit || caches.match("./")))
  );
});
