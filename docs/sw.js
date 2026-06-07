// 킬 스위치 서비스워커.
// 개발 중 예전(cache-first) 서비스워커가 옛 화면을 계속 보여주는 문제를 끝내기 위해,
// 모든 캐시를 비우고 자기 자신을 등록 해제한 뒤, 열린 탭을 한 번 새로고침한다.
// 그 이후로는 서비스워커가 없어 항상 네트워크에서 최신본을 받는다.
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    try {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
    } catch (_) {}
    try { await self.registration.unregister(); } catch (_) {}
    const clients = await self.clients.matchAll({ type: "window" });
    clients.forEach((c) => { try { c.navigate(c.url); } catch (_) {} });
  })());
});
