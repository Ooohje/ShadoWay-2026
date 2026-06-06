// docs/app.js — ShadoWay 프론트 로직 (Claude Design 스킨에 연결)
const KNU = [35.8890, 128.6110]; // 기본 중심 (경북대)

// 백엔드 주소: config.js의 window.SHADOWAY_API 사용. 비어있으면 같은 출처.
const API_BASE = (window.SHADOWAY_API || "").replace(/\/$/, "");

const $ = (id) => document.getElementById(id);

// ===== 지도 =====
const map = L.map("map", { zoomControl: false, attributionControl: false }).setView(KNU, 16);
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  maxZoom: 20, subdomains: "abcd",
}).addTo(map);
L.control.attribution({ position: "bottomleft", prefix: false })
  .addAttribution("© OpenStreetMap, CARTO · 건물: VWorld/OSM").addTo(map);

// ===== 상태 =====
let start = null, end = null;             // [lat, lng]
let startMarker = null, endMarker = null;
let routeLayer = null, shadowLayer = null, snapLayer = null;
let activeField = "start";

// ===== 토스트 =====
const toastEl = $("toast");
const toastMsg = toastEl.querySelector(".toast-msg");
let toastTimer = null;
function showToast(html, autoHideMs) {
  toastMsg.innerHTML = html;
  toastEl.classList.add("show");
  clearTimeout(toastTimer);
  // 안내 팝업은 항상 잠깐 떴다가 자동으로 사라진다.
  toastTimer = setTimeout(hideToast, autoHideMs || 2600);
}
function hideToast() { toastEl.classList.remove("show"); }

// ===== 마커 핀 (컬러 티어드롭) =====
function pinIcon(kind) {
  const color = kind === "start" ? "#16a34a" : "#ef4444";
  const svg = `<svg width="30" height="40" viewBox="0 0 30 40" xmlns="http://www.w3.org/2000/svg">
    <path d="M15 0C6.7 0 0 6.7 0 15c0 10.5 15 25 15 25s15-14.5 15-25C30 6.7 23.3 0 15 0z" fill="${color}"/>
    <circle cx="15" cy="15" r="6" fill="#fff"/></svg>`;
  return L.divIcon({ className: "pin-wrap", html: `<div class="pin">${svg}</div>`,
    iconSize: [30, 40], iconAnchor: [15, 39] });
}

// ===== 출발/도착 설정 =====
function setFieldValue(which, label) { $(which + "Input").value = label || ""; }

function setPoint(which, latlng, label) {
  if (which === "start") {
    start = latlng;
    if (startMarker) map.removeLayer(startMarker);
    startMarker = L.marker(latlng, { icon: pinIcon("start") }).addTo(map);
    setFieldValue("start", label);
    activeField = "end";
  } else {
    end = latlng;
    if (endMarker) map.removeLayer(endMarker);
    endMarker = L.marker(latlng, { icon: pinIcon("end") }).addTo(map);
    setFieldValue("end", label);
    activeField = "start";
  }
  $("calcBtn").disabled = !(start && end);
  if (start && end) showToast("‘그늘길 찾기’를 눌러보세요 🌿", 2200);
  else showToast(which === "start"
    ? "이제 <b>도착지</b>를 검색하거나 지도를 누르세요"
    : "출발지·도착지를 지정하세요", 0);
}

function clearPoint(which) {
  if (which === "start") { if (startMarker) map.removeLayer(startMarker); startMarker = null; start = null; }
  else { if (endMarker) map.removeLayer(endMarker); endMarker = null; end = null; }
  setFieldValue(which, "");
  activeField = which;
  $("calcBtn").disabled = !(start && end);
}

// ===== 지오코딩 (Nominatim / OSM, 키 불필요) =====
const GEO_URL = "https://nominatim.openstreetmap.org/search";
const debounceTimers = {};
const PIN_SVG = '<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="11" r="3.2" stroke="currentColor" stroke-width="1.8"/><path d="M12 21c4-4 6.5-7.2 6.5-10A6.5 6.5 0 1 0 5.5 11c0 2.8 2.5 6 6.5 10Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>';

async function searchPlaces(q) {
  const params = new URLSearchParams({
    format: "jsonv2", countrycodes: "kr", limit: "6",
    "accept-language": "ko", addressdetails: "1", q,
  });
  const res = await fetch(`${GEO_URL}?${params}`, { headers: { "Accept": "application/json" } });
  if (!res.ok) throw new Error("검색 실패");
  return res.json();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderSuggest(which, items) {
  const ul = $(which + "Suggest");
  ul.innerHTML = "";
  if (!items || items.length === 0) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="sg-ico">${PIN_SVG}</span>
      <span class="sg-text"><span class="sg-title">검색 결과 없음</span>
      <span class="sg-sub">지도를 직접 눌러 선택할 수 있어요</span></span>`;
    ul.appendChild(li);
    return;
  }
  items.forEach((it) => {
    const li = document.createElement("li");
    const main = (it.name || it.display_name.split(",")[0] || "").trim();
    li.innerHTML = `<span class="sg-ico">${PIN_SVG}</span>
      <span class="sg-text"><span class="sg-title">${escapeHtml(main)}</span>
      <span class="sg-sub">${escapeHtml(it.display_name)}</span></span>`;
    li.onclick = () => {
      const latlng = [parseFloat(it.lat), parseFloat(it.lon)];
      closeSuggest(which);
      map.flyTo(latlng, 17, { duration: 0.6 });
      setPoint(which, latlng, main);
      $(which + "Input").blur();
    };
    ul.appendChild(li);
  });
}

function closeSuggest(which) { $(which + "Suggest").innerHTML = ""; } // :empty → 숨김

function wireSearchField(which) {
  const input = $(which + "Input");
  input.addEventListener("focus", () => { activeField = which; });
  input.addEventListener("input", () => {
    const q = input.value.trim();
    clearTimeout(debounceTimers[which]);
    if (q.length < 2) { closeSuggest(which); return; }
    debounceTimers[which] = setTimeout(async () => {
      try { renderSuggest(which, await searchPlaces(q)); }
      catch { closeSuggest(which); }
    }, 320);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const first = $(which + "Suggest").querySelector("li");
      if (first) first.click();
    } else if (e.key === "Escape") { closeSuggest(which); }
  });
}
wireSearchField("start");
wireSearchField("end");

document.querySelectorAll(".field-clear").forEach((btn) => {
  btn.onclick = () => { const w = btn.dataset.clear; clearPoint(w); closeSuggest(w); $(w + "Input").focus(); };
});

document.addEventListener("click", (e) => {
  if (!e.target.closest('.search-field[data-which="start"]')) closeSuggest("start");
  if (!e.target.closest('.search-field[data-which="end"]')) closeSuggest("end");
});

// 출발↔도착 교체
$("swapBtn").onclick = () => {
  const s = start, sLbl = $("startInput").value;
  const e = end, eLbl = $("endInput").value;
  clearPoint("start"); clearPoint("end");
  if (e) setPoint("start", e, eLbl);
  if (s) setPoint("end", s, sLbl);
};

// ===== 시각 / 우선순위 =====
function setNow() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  $("dt").value = d.toISOString().slice(0, 16);
}
setNow();
$("nowBtn").onclick = setNow;

function prefText(w) {
  if (w >= 9.5) return "최단거리";
  if (w >= 8.5) return "거리 우선";
  if (w >= 7) return "균형";
  if (w >= 6) return "그늘 우선";
  return "그늘 최우선";
}
$("prefLabel").textContent = prefText(parseFloat($("wDist").value));
$("wDist").oninput = (e) => { $("prefLabel").textContent = prefText(parseFloat(e.target.value)); };

// ===== GPS 현재 위치 =====
function locateAsStart() {
  if (!navigator.geolocation) { showToast("출발지·도착지를 검색하거나 지도를 누르세요", 0); return; }
  showToast("📍 현재 위치를 찾는 중…", 0);
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const p = [pos.coords.latitude, pos.coords.longitude];
      map.setView(p, 17);
      setPoint("start", p, "현재 위치");
    },
    () => { showToast("위치 권한이 없어요. 검색하거나 지도를 누르세요", 3500); },
    { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 }
  );
}
$("locBtn").onclick = locateAsStart;

// ===== 지도 클릭 → 활성 필드 채우기 (역지오코딩으로 이름) =====
map.on("click", async (e) => {
  const p = [e.latlng.lat, e.latlng.lng];
  const which = (!start) ? "start" : (!end ? "end" : activeField);
  setPoint(which, p, "지도에서 선택한 위치");
  try {
    const params = new URLSearchParams({
      format: "jsonv2", lat: p[0], lon: p[1], "accept-language": "ko", zoom: "18",
    });
    const r = await fetch(`https://nominatim.openstreetmap.org/reverse?${params}`);
    if (r.ok) {
      const j = await r.json();
      const name = (j.name || (j.display_name || "").split(",")[0] || "").trim();
      if (name) setFieldValue(which, name);
    }
  } catch { /* 이름 없으면 그대로 */ }
});

// ===== 바텀시트 접기/펼치기 =====
$("sheetHandle").onclick = () => $("sheet").classList.toggle("collapsed");

// ===== 초기화 =====
function resetRoute() {
  [startMarker, endMarker, routeLayer, shadowLayer, snapLayer].forEach((l) => l && map.removeLayer(l));
  startMarker = endMarker = routeLayer = shadowLayer = snapLayer = null;
  start = end = null;
  setFieldValue("start", ""); setFieldValue("end", "");
  activeField = "start";
  $("calcBtn").disabled = true;
  $("result").hidden = true;
}
$("resetBtn").onclick = () => { resetRoute(); showToast("출발지·도착지를 검색하거나 지도를 누르세요", 2500); };

// ===== 경로 계산 =====
$("calcBtn").onclick = async () => {
  if (!start || !end) return;
  $("loading").hidden = false;
  try {
    const body = {
      start, end,
      datetime: $("dt").value || null,
      w_dist: parseFloat($("wDist").value),
      bld_src: "osm",
    };
    const res = await fetch(API_BASE + "/api/route", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "경로 계산 실패");
    }
    drawResult(await res.json());
  } catch (e) {
    showToast("⚠️ " + e.message, 5000);
  } finally {
    $("loading").hidden = true;
  }
};

function drawResult(data) {
  if (shadowLayer) map.removeLayer(shadowLayer);
  if (routeLayer) map.removeLayer(routeLayer);
  if (snapLayer) map.removeLayer(snapLayer);

  shadowLayer = L.layerGroup();
  (data.shadows || []).forEach((poly) => {
    L.polygon(poly, { color: "#222", weight: 0, fillColor: "#1f2937", fillOpacity: 0.25 }).addTo(shadowLayer);
  });
  shadowLayer.addTo(map);

  routeLayer = L.layerGroup([
    L.polyline(data.route, { color: "#ffffff", weight: 10, opacity: 0.9, lineCap: "round", lineJoin: "round" }),
    L.polyline(data.route, { color: "#0f766e", weight: 6, opacity: 0.98, lineCap: "round", lineJoin: "round" }),
  ]).addTo(map);
  const routeBounds = L.polyline(data.route).getBounds();
  snapLayer = L.layerGroup([
    L.circleMarker(data.start_snapped, { radius: 6, color: "#16a34a", fillColor: "#16a34a", fillOpacity: 1 }),
    L.circleMarker(data.end_snapped, { radius: 6, color: "#ef4444", fillColor: "#ef4444", fillOpacity: 1 }),
  ]).addTo(map);
  map.fitBounds(routeBounds, { padding: [90, 70] });

  // 통계 → 디자인 지표(숫자만, 단위는 별도 span)
  const s = data.stats;
  if (s.distance_m >= 1000) {
    $("mDist").textContent = (s.distance_m / 1000).toFixed(2);
    $("mDistUnit").textContent = "km";
  } else {
    $("mDist").textContent = Math.round(s.distance_m);
    $("mDistUnit").textContent = "m";
  }
  $("mShade").textContent = Math.round(s.shade_m);
  const ratioPct = Math.round((s.shade_ratio || 0) * 100);
  $("mRatio").textContent = ratioPct;
  $("mSun").textContent = s.sun_alt;

  // 도넛 링을 그늘 비율에 맞춰 채우기
  const ring = document.querySelector(".metric.feature .ring");
  if (ring) ring.style.background =
    `conic-gradient(rgba(255,255,255,.95) 0 ${ratioPct}%, rgba(255,255,255,.22) ${ratioPct}% 100%)`;

  $("result").hidden = false;
  $("sheet").classList.remove("collapsed");
  hideToast();
}

// ===== Render 백엔드 워밍업 + GPS 자동 시작 (온보딩 진입 시) =====
function warmBackend() {
  if (!API_BASE) return;
  fetch(API_BASE + "/api/health").catch(() => {});
}
let entered = false;
function onEnterApp() {
  if (entered) return; entered = true;
  map.invalidateSize();
  warmBackend();
  locateAsStart();
}
window.addEventListener("shadoway:enter", onEnterApp, { once: true });
// 온보딩 스크립트가 없거나 이벤트를 놓쳤을 때의 안전장치
setTimeout(() => { const i = $("intro"); if (!i || i.classList.contains("gone")) onEnterApp(); }, 1200);

// PWA service worker — 새 버전이 활성화되면 한 번 자동 새로고침해 최신 화면을 보여준다.
if ("serviceWorker" in navigator) {
  let refreshing = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (refreshing) return;
    refreshing = true;
    location.reload();
  });
  navigator.serviceWorker.register("sw.js")
    .then((reg) => { reg.update(); })
    .catch(() => {});
}
