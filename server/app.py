# server/app.py
"""
ShadoWay 백엔드 (FastAPI).

- POST /api/route : 출발/도착 좌표 + 시각 + 가중치를 받아
  주변 도로(OSM) + 건물(VWorld/OSM)을 즉석에서 불러와
  실제 모양 그림자 기반 그늘 우선 경로를 계산해 반환.
- GET / : PWA 프론트(static) 서빙.

기존 poc/ 모듈(osm_loader, vworld_loader, shadow_poly)과
streamlit_app/core.py 의 로직을 그대로 재사용한다.

VWorld WFS 키는 환경변수 VWORLD_WFS_KEY 또는 server/.env 파일에서 읽는다.
(키는 절대 코드/깃에 넣지 않는다)
"""
from __future__ import annotations
import os
import sys
import math
import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "poc"))

# ---- server/.env 간단 로더 (python-dotenv 없이) ----
_env_file = Path(__file__).resolve().parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import core  # noqa: E402
import osm_loader  # noqa: E402
import shadow_poly  # noqa: E402
import pickle  # noqa: E402

app = FastAPI(title="ShadoWay API")

# ---- 사전구축(prebuilt) 지역: 경북대 (Overpass 없이 즉시 처리) ----
_PREBUILT = None
def _load_prebuilt():
    global _PREBUILT
    if _PREBUILT is None:
        p = ROOT / "artifacts" / "knu_prebuilt.pkl"
        try:
            _PREBUILT = pickle.load(open(p, "rb")) if p.exists() else {}
        except Exception:  # noqa: BLE001
            _PREBUILT = {}
    return _PREBUILT or None

def _within(bbox, pt):
    s, w, n, e = bbox
    return (s <= pt[0] <= n) and (w <= pt[1] <= e)

# GitHub Pages(다른 도메인) 프론트에서 호출하므로 CORS 허용.
# ALLOW_ORIGINS 환경변수(쉼표구분)로 좁힐 수 있고, 없으면 전체 허용.
_origins = os.environ.get("ALLOW_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _origins.strip() == "*" else [o.strip() for o in _origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 지역 데이터 캐시 (bbox 반올림 키) ----
_area_cache: dict = {}


class RouteRequest(BaseModel):
    start: list[float]      # [lat, lng]
    end: list[float]        # [lat, lng]
    datetime: str | None = None   # ISO, KST. 없으면 현재
    w_dist: float = 8.0           # 거리 가중치 5~10
    bld_src: str = "osm"          # "osm"(빠름·기본) | "vworld"(정확하지만 호스트에서 느릴 수 있음)
    margin_m: float = 180.0       # 두 점 주변 여유 반경(m) — 작을수록 빠름


def _bbox_from_points(start, end, margin_m):
    lat_min, lat_max = min(start[0], end[0]), max(start[0], end[0])
    lng_min, lng_max = min(start[1], end[1]), max(start[1], end[1])
    latc = (lat_min + lat_max) / 2
    dlat = margin_m / 111000.0
    dlng = margin_m / (111000.0 * math.cos(math.radians(latc)))
    return (lat_min - dlat, lng_min - dlng, lat_max + dlat, lng_max + dlng)


def _load_area(bbox, bld_src):
    key = (bld_src, *[round(v, 4) for v in bbox])
    if key in _area_cache:
        return _area_cache[key]
    south, west, north, east = bbox
    area = osm_loader.load_osm_area(south, west, north, east)
    # area.buildings 는 이 시점에 이미 OSM 건물로 채워져 있다(폴백 기본값).
    area.bld_source = "osm"
    if bld_src == "vworld":
        # VWorld 건물(정확한 높이)을 시도하되, 실패(502 등)하면 OSM 건물로 폴백.
        try:
            from vworld_loader import load_buildings_vworld
            vb = load_buildings_vworld(south, west, north, east, area.lat0, area.lng0)
            if vb is not None and len(vb) > 0:
                area.buildings = vb
                area.bld_source = "vworld"
        except Exception as e:  # noqa: BLE001
            print(f"[warn] VWorld 실패 → OSM 건물로 폴백: {e}", flush=True)
    _area_cache[key] = area
    return area


def _route_prebuilt(pre, req, dt_local, w_dist, w_shade):
    """경북대 사전구축 그래프 + 직사각형 그림자(빠름)로 경로 계산. (Overpass 미사용)"""
    G = pre["G"].copy()
    lat0, lng0 = pre["lat0"], pre["lng0"]
    buildings = pre["buildings"]

    sx, sy = osm_loader.latlng_to_xy(req.start[0], req.start[1], lat0, lng0)
    ex, ey = osm_loader.latlng_to_xy(req.end[0], req.end[1], lat0, lng0)
    src = core.nearest_node_xy(G, sx, sy)
    dst = core.nearest_node_xy(G, ex, ey)
    if src == dst:
        raise HTTPException(400, "출발지와 도착지가 너무 가깝습니다.")

    alt, az = core.sun_angles_deg(dt_local, lat0, lng0)
    rects = core.build_shadow_rects(buildings, dt_local, lat0, lng0)  # alt<=0이면 []
    for u, v in G.edges:
        p0 = (G.nodes[u]["x"], G.nodes[u]["y"])
        p1 = (G.nodes[v]["x"], G.nodes[v]["y"])
        G[u][v]["shaded_len_m"] = core.compute_unique_shade_length_for_edge(p0, p1, rects)

    core.apply_edge_costs(G, w_dist, w_shade)
    try:
        path = nx.shortest_path(G, src, dst, weight="cost")
    except nx.NetworkXNoPath:
        raise HTTPException(404, "두 지점을 잇는 경로가 없습니다.")

    info = core.summarize_path(G, path)
    route_ll = [[G.nodes[n]["lat"], G.nodes[n]["lng"]] for n in path]
    shadows = []
    for r in rects:
        shadows.append([list(core.xy_to_ll(x, y, lat0, lng0)) for (x, y) in r.corners()])

    return {
        "stats": {
            "distance_m": round(info["total_len_m"], 1),
            "shade_m": round(info["total_shade_m"], 1),
            "shade_ratio": round(info["shade_ratio"], 4),
            "sun_alt": round(alt, 1),
            "sun_az": round(az, 1),
            "n_buildings": int(len(buildings)),
            "bld_source": "prebuilt-knu",
        },
        "route": route_ll,
        "start_snapped": [G.nodes[src]["lat"], G.nodes[src]["lng"]],
        "end_snapped": [G.nodes[dst]["lat"], G.nodes[dst]["lng"]],
        "shadows": shadows,
    }


@app.post("/api/route")
def compute_route(req: RouteRequest):
    if req.datetime:
        dt_local = core.ensure_kst(datetime.datetime.fromisoformat(req.datetime))
    else:
        dt_local = core.now_kst()

    w_dist = max(5.0, min(10.0, req.w_dist))
    w_shade = 10.0 - w_dist

    # 사전구축 지역(경북대) 안이면 Overpass 없이 즉시 처리
    pre = _load_prebuilt()
    if pre and _within(pre["bbox"], req.start) and _within(pre["bbox"], req.end):
        return _route_prebuilt(pre, req, dt_local, w_dist, w_shade)

    bbox = _bbox_from_points(req.start, req.end, req.margin_m)
    try:
        area = _load_area(bbox, req.bld_src)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"데이터 수집 실패: {e}")

    if area.G.number_of_nodes() == 0:
        raise HTTPException(404, "이 지역에서 도로망을 찾지 못했습니다.")

    G = area.G
    sx, sy = osm_loader.latlng_to_xy(req.start[0], req.start[1], area.lat0, area.lng0)
    ex, ey = osm_loader.latlng_to_xy(req.end[0], req.end[1], area.lat0, area.lng0)
    src = core.nearest_node_xy(G, sx, sy)
    dst = core.nearest_node_xy(G, ex, ey)
    if src == dst:
        raise HTTPException(400, "출발지와 도착지가 너무 가깝습니다.")

    shadow_union, shadows, (alt, az) = shadow_poly.build_shadow_union(
        area.buildings, dt_local, area.lat0, area.lng0
    )
    # STRtree 공간 인덱스로 간선마다 '근처' 그림자만 교차 → Render에서도 수초 내 계산
    tree, shadow_list = shadow_poly.build_shade_index(shadows)
    for u, v in G.edges:
        p0 = (G.nodes[u]["x"], G.nodes[u]["y"])
        p1 = (G.nodes[v]["x"], G.nodes[v]["y"])
        G[u][v]["shaded_len_m"] = shadow_poly.edge_shade_length_idx(p0, p1, tree, shadow_list)

    core.apply_edge_costs(G, w_dist, w_shade)
    try:
        path = nx.shortest_path(G, src, dst, weight="cost")
    except nx.NetworkXNoPath:
        raise HTTPException(404, "두 지점을 잇는 경로가 없습니다.")

    info = core.summarize_path(G, path)
    route_ll = [[G.nodes[n]["lat"], G.nodes[n]["lng"]] for n in path]
    shadow_polys = shadow_poly.shadow_to_latlng_polys(shadow_union, area.lat0, area.lng0)

    return {
        "stats": {
            "distance_m": round(info["total_len_m"], 1),
            "shade_m": round(info["total_shade_m"], 1),
            "shade_ratio": round(info["shade_ratio"], 4),
            "sun_alt": round(alt, 1),
            "sun_az": round(az, 1),
            "n_buildings": int(len(area.buildings)),
            "bld_source": getattr(area, "bld_source", "osm"),
        },
        "route": route_ll,
        "start_snapped": [G.nodes[src]["lat"], G.nodes[src]["lng"]],
        "end_snapped": [G.nodes[dst]["lat"], G.nodes[dst]["lng"]],
        "shadows": shadow_polys,
    }


@app.get("/api/health")
def health():
    return {"ok": True, "vworld_key": bool(os.environ.get("VWORLD_WFS_KEY"))}


# ---- 정적 PWA 서빙 (맨 마지막에 마운트) ----
# 프론트는 docs/ 에 둔다(=GitHub Pages 발행 폴더와 동일 소스).
STATIC_DIR = ROOT / "docs"


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


app.mount("/", StaticFiles(directory=str(STATIC_DIR)), name="static")
