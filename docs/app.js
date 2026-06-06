// docs/app.js
const KNU = [35.8890, 128.6110]; // 기본 중심 (경북대)

// 백엔드 주소: config.js의 window.SHADOWAY_API 사용. 비어있으면 같은 출처.
const API_BASE = (window.SHADOWAY_API || "").replace(/\/$/, "");

const map = L.map("map", { zoomControl: false, attributionControl: false }).setView(KNU, 16);
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  maxZoom: 20, subdomains: "abcd",
}).addTo(map);
L.control.attribution({ position: "bottomleft", prefix: false })
  .addAttribution("© OpenStreetMap, CARTO · 건물: VWorld").addTo(map);

const $ = (id) => document.getElementById(id);

// ===== 상태 =====
let start = null, end = null;             // [lat, lng]
let startMarker = null, endMarker = null;
let routeLayer = null, shadowLayer = null, snapLayer = null;
let activeField = "start";                // 지도 클릭이 채울 대상

const toast = $("toast");
function showToast(html) { toast.innerHTML = html; toast.classList.remove("hide"); }
function hideToast() { toast.classList.add("hide"); }

function pinIcon(emoji) {
  return L.divIcon({ className: "", html: `<div class="pin">${emoji}</div>`,
    iconSize: [30, 30], iconAnchor: [15, 28] });
}

// ===== 출발/도착 설정 =====
function setPoint(which, latlng, label) {
  if (which === "start") {
    start = latlng;
    if (startMarker) map.removeLayer(startMarker);
    startMarker = L.marker(latlng, { icon: pinIcon("🟢") }).addTo(map);
    setFieldValue("start", label);
    activeField = "end";
  } else {
    end = latlng;
    if (endMarker) map.removeLayer(endMarker);
    endMarker = L.marker(latlng, { icon: pinIcon("🔴") }).addTo(map);
    setFieldValue("end", label);
    activeField = "start";
  }
  $("calcBtn").disabled = !(start && end);
  if (start && end) {
    showToast("‘경로 찾기’를 눌러보세요 🌿");
    setTimeout(hideToast, 2000);
  } else {
    showToast(which === "start"
      ? "이제 <b>도착지</b>를 검색하거나 지도를 누르세요"
      : "출발지·도착지를 지정하세요");
  }
}

function setFieldValue(which, label) {
  const input = $(which + "Input");
  input.value = label || "";
  input.closest(".search-field").classList.toggle("has-value", !!label);
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

function geoIconFor(item) {
  const c = item.class;
  if (c === "amenity" || c === "shop") return "📍";
  if (c === "building" || c === "office") return "🏢";
  if (c === "highway" || c === "place") return "🛣️";
  if (c === "leisure" || c === "natural") return "🌳";
  return "📌";
}

async function searchPlaces(q) {
  const params = new URLSearchParams({
    format: "jsonv2", countrycodes: "kr", limit: "6",
    "accept-language": "ko", addressdetails: "1", q,
  });
  const res = await fetch(`${GEO_URL}?${params}`, { headers: { "Accept": "application/json" } });
  if (!res.ok) throw new Error("검색 실패");
  return res.json();
}

function renderSuggest(which, items) {
  const ul = $(which + "Suggest");
  ul.innerHTML = "";
  if (!items || items.length === 0) {
    ul.innerHTML = `<li class="s-empty">검색 결과가 없어요. 지도를 직접 눌러도 됩니다.</li>`;
    ul.classList.add("open");
    return;
  }
  items.forEach((it) => {
    const li = document.createElement("li");
    const main = (it.name || it.display_name.split(",")[0] || "").trim();
    const sub = it.display_name;
    li.innerHTML = `<span class="s-ic">${geoIconFor(it)}</span>
      <span><span class="s-main">${escapeHtml(main)}</span>
      <span class="s-sub">${escapeHtml(sub)}</span></span>`;
    li.onclick = () => {
      const latlng = [parseFloat(it.lat), parseFloat(it.lon)];
      closeSuggest(which);
      map.flyTo(latlng, 17, { duration: 0.6 });
      setPoint(which, latlng, main);
    };
    ul.appendChild(li);
  });
  ul.classList.add("open");
}

function closeSuggest(which) { $(which + "Suggest").classList.remove("open"); }

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function wireSearchField(which) {
  const input = $(which + "Input");
  input.addEventListener("focus", () => { activeField = which; });
  input.addEventListener("input", () => {
    const q = input.value.trim();
    input.closest(".search-field").classList.toggle("has-value", !!q);
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
      const first = $(which + "Suggest").querySelector("li:not(.s-empty)");
      if (first) first.click();
    } else if (e.key === "Escape") { closeSuggest(which); }
  });
}
wireSearchField("start");
wireSearchField("end");

document.querySelectorAll(".field-clear").forEach((btn) => {
  btn.onclick = () => { const w = btn.dataset.clear; clearPoint(w); closeSuggest(w); $(w + "Input").focus(); };
});

// 바깥 클릭 시 자동완성 닫기
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
$("wDist").oninput = (e) => { $("prefLabel").textContent = prefText(parseFloat(e.target.value)); };

// ===== GPS 자동 위치 =====
function locateAsStart() {
  if (!navigator.geolocation) { showToast("출발지·도착지를 검색하거나 지도를 누르세요"); return; }
  showToast("📍 현재 위치를 찾는 중…");
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const p = [pos.coords.latitude, pos.coords.longitude];
      map.setView(p, 17);
      setPoint("start", p, "현재 위치");
    },
    () => { showToast("위치 권한이 없어요. 검색하거나 지도를 누르세요"); },
    { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 }
  );
}
locateAsStart();
$("locBtn").onclick = locateAsStart;

// ===== 지도 클릭 → 활성 필드 채우기 (이름은 역지오코딩) =====
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
  } catch { /* 이름 없으면 그대로 둠 */ }
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
  $("result").classList.add("hidden");
}
$("resetBtn").onclick = () => { resetRoute(); showToast("출발지·도착지를 검색하거나 지도를 누르세요"); };

// ===== 경로 계산 =====
$("calcBtn").onclick = async () => {
  if (!start || !end) return;
  $("loading").classList.remove("hidden");
  try {
    const body = {
      start, end,
      datetime: $("dt").value || null,
      w_dist: parseFloat($("wDist").value),
      bld_src: "vworld",
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
    showToast("⚠️ " + e.message);
    toast.classList.remove("hide");
  } finally {
    $("loading").classList.add("hidden");
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
    L.polyline(data.route, { color: "#ef4444", weight: 6, opacity: 0.98, lineCap: "round", lineJoin: "round" }),
  ]).addTo(map);
  const routeBounds = L.polyline(data.route).getBounds();
  snapLayer = L.layerGroup([
    L.circleMarker(data.start_snapped, { radius: 6, color: "#10b981", fillColor: "#10b981", fillOpacity: 1 }),
    L.circleMarker(data.end_snapped, { radius: 6, color: "#ef4444", fillColor: "#ef4444", fillOpacity: 1 }),
  ]).addTo(map);
  map.fitBounds(routeBounds, { padding: [80, 90] });

  const s = data.stats;
  $("mDist").textContent = (s.distance_m >= 1000)
    ? (s.distance_m / 1000).toFixed(2) + "km" : Math.round(s.distance_m) + "m";
  $("mShade").textContent = Math.round(s.shade_m) + "m";
  $("mRatio").textContent = (s.shade_ratio * 100).toFixed(0) + "%";
  $("mSun").textContent = s.sun_alt + "°";
  $("result").classList.remove("hidden");
  $("sheet").classList.remove("collapsed");
  hideToast();
}

// PWA service worker
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
