# streamlit_app/core.py
import math
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple
from pathlib import Path
import datetime, pytz
import pickle

import numpy as np
import pandas as pd
import networkx as nx

# ========= 전역 경로 / 상수 =========
BASE_DIR = Path(__file__).resolve().parent
ARTIFACTS_DIR = BASE_DIR.parent / "artifacts"
KST = pytz.timezone("Asia/Seoul")
R = 6371000.0  # 지구 반지름 (m)

# ========= 시간 유틸 =========
def now_kst() -> datetime.datetime:
    return datetime.datetime.now(KST)

def ensure_kst(dt: datetime.datetime) -> datetime.datetime:
    if dt.tzinfo is None:
        return KST.localize(dt)
    return dt.astimezone(KST)

def to_utc(dt_local: datetime.datetime) -> datetime.datetime:
    return ensure_kst(dt_local).astimezone(pytz.UTC)

# ========= 좌표 변환 =========
def xy_to_ll(x: float, y: float, lat0: float, lng0: float):
    dlat = y / R
    dlng = x / (R * math.cos(math.radians(lat0)))
    return (math.degrees(dlat) + lat0, math.degrees(dlng) + lng0)

def latlng_to_xy(lat, lng, lat0, lng0):
    dlat = math.radians(lat - lat0)
    dlng = math.radians(lng - lng0)
    x = R * dlng * math.cos(math.radians(lat0))
    y = R * dlat
    return x, y

# ========= 태양 방위/고도 =========
from pysolar.solar import get_altitude, get_azimuth

def azimuth_deg_to_unit_xy(az_deg: float) -> Tuple[float, float]:
    th = math.radians(az_deg)
    ux = math.sin(th)  # East
    uy = math.cos(th)  # North
    return ux, uy

# ========= 그림자 직사각형 =========
@dataclass
class ShadowRect:
    cx: float; cy: float
    length: float; width: float
    dx: float; dy: float
    meta: Dict[str, Any]
    def corners(self) -> List[Tuple[float, float]]:
        hx = 0.5 * self.length * self.dx
        hy = 0.5 * self.length * self.dy
        nx, ny = -self.dy, self.dx
        half_w = 0.5 * self.width
        c1x, c1y = self.cx - hx, self.cy - hy
        c2x, c2y = self.cx + hx, self.cy + hy
        p1 = (c1x - half_w*nx, c1y - half_w*ny)
        p2 = (c1x + half_w*nx, c1y + half_w*ny)
        p3 = (c2x + half_w*nx, c2y + half_w*ny)
        p4 = (c2x - half_w*nx, c2y - half_w*ny)
        return [p1, p2, p3, p4]

# ========= 데이터 로드 =========
import streamlit as st

@st.cache_resource(show_spinner=False)
def load_graph_and_buildings():
    with open(ARTIFACTS_DIR / "graph_xy.pkl", "rb") as f:
        G = pickle.load(f)
    buildings = pd.read_parquet(ARTIFACTS_DIR / "buildings_xy.parquet").copy()
    for col in ["lat","lng","height","radius","x","y"]:
        if col in buildings.columns:
            buildings[col] = pd.to_numeric(buildings[col], errors="coerce")
    buildings = buildings.dropna(subset=["lat","lng","height","radius","x","y"]).reset_index(drop=True)
    lat_center = float(np.mean([G.nodes[n]["lat"] for n in G.nodes]))
    lng_center = float(np.mean([G.nodes[n]["lng"] for n in G.nodes]))
    return G, buildings, lat_center, lng_center

# ========= 시각→그림자 =========
def build_shadow_rects(buildings_df: pd.DataFrame, dt_local: datetime.datetime):
    dt_utc = to_utc(dt_local)
    rects: List[ShadowRect] = []
    for _, row in buildings_df.iterrows():
        lat = float(row["lat"]); lng = float(row["lng"])
        alt = get_altitude(lat, lng, dt_utc)
        if alt <= 0:  # 태양 고도 0 이하면 그림자 없음
            continue
        az  = get_azimuth(lat, lng, dt_utc)
        L = float(row["height"]) / math.tan(math.radians(alt))
        ux, uy = azimuth_deg_to_unit_xy(az)
        dx, dy = -ux, -uy
        nrm = math.hypot(dx, dy)
        if nrm == 0: continue
        dx, dy = dx/nrm, dy/nrm
        cx0, cy0 = float(row["x"]), float(row["y"])
        cx = cx0 + 0.5 * L * dx
        cy = cy0 + 0.5 * L * dy
        width = 2.0 * float(row["radius"])
        rects.append(ShadowRect(cx=cx, cy=cy, length=L, width=width, dx=dx, dy=dy,
                                meta={"latlng": (lat, lng), "alt_deg": alt, "az_deg": az}))
    return rects

# ========= 선분×회전사각형 =========
def _segment_rect_interval(p0, p1, rect) -> List[Tuple[float,float]]:
    d = np.array([rect.dx, rect.dy], dtype=float)
    n = np.array([-rect.dy, rect.dx], dtype=float)
    c = np.array([rect.cx, rect.cy], dtype=float)
    p0 = np.array(p0, dtype=float) - c
    p1 = np.array(p1, dtype=float) - c
    dp = p1 - p0
    u0, v0 = float(np.dot(p0, d)), float(np.dot(p0, n))
    du, dv = float(np.dot(dp, d)), float(np.dot(dp, n))
    umin, umax = -0.5*rect.length, 0.5*rect.length
    vmin, vmax = -0.5*rect.width,  0.5*rect.width
    t0, t1 = 0.0, 1.0
    def clip(p, q, t0, t1):
        if p == 0: return (t0, t1) if q <= 0 else (None, None)
        r = q / p
        if p > 0: t0 = max(t0, r)
        else:     t1 = min(t1, r)
        if t0 > t1: return (None, None)
        return (t0, t1)
    for (p, q) in [( du, umin - u0), (-du, umax - u0), ( dv, vmin - v0), (-dv, vmax - v0)]:
        t0, t1 = clip(p, q, t0, t1)
        if t0 is None: return []
    if t0 <= t1 and t1 >= 0 and t0 <= 1:
        return [(max(0.0, t0), min(1.0, t1))]
    return []

def _merge_intervals(intervals: List[Tuple[float,float]], eps: float=1e-12):
    if not intervals: return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [list(intervals[0])]
    for a,b in intervals[1:]:
        if a <= merged[-1][1] + eps: merged[-1][1] = max(merged[-1][1], b)
        else: merged.append([a,b])
    return [(a,b) for a,b in merged]

def compute_unique_shade_length_for_edge(p0, p1, rects) -> float:
    ex = p1[0] - p0[0]; ey = p1[1] - p0[1]
    edge_len = math.hypot(ex, ey)
    if edge_len == 0: return 0.0
    intervals = []
    ebox = (min(p0[0],p1[0]), min(p0[1],p1[1]), max(p0[0],p1[0]), max(p0[1],p1[1]))
    for r in rects:
        xs = [p[0] for p in r.corners()]; ys = [p[1] for p in r.corners()]
        rb = (min(xs), min(ys), max(xs), max(ys))
        if not (ebox[2] >= rb[0] and rb[2] >= ebox[0] and ebox[3] >= rb[1] and rb[3] >= ebox[1]):
            continue
        its = _segment_rect_interval(p0, p1, r)
        intervals.extend(its)
    merged = _merge_intervals(intervals)
    return sum((b-a) for a,b in merged) * edge_len

# ========= 비용/경로 =========
def apply_edge_costs(G: nx.Graph, w_dist: float, w_shade: float):
    if abs((w_dist + w_shade) - 10.0) > 1e-9:
        raise ValueError("w_dist + w_shade는 10이어야 합니다.")
    if not (5.0 <= w_dist <= 10.0 and 0.0 <= w_shade <= 5.0):
        raise ValueError("가중치 범위를 확인하세요.")
    for u, v, d in G.edges(data=True):
        base_len = float(d.get("length_m", d.get("length_xy_m", 0.0)))
        shade_len = float(d.get("shaded_len_m", 0.0))
        cost = (w_dist * base_len - w_shade * shade_len) / 10.0
        d["cost"] = max(cost, 1e-9)

def summarize_path(G: nx.Graph, path: list[int]) -> dict:
    total_len = total_shade = total_cost = 0.0
    for a, b in zip(path[:-1], path[1:]):
        d = G[a][b]
        total_len  += float(d.get("length_m", d.get("length_xy_m", 0.0)))
        total_shade+= float(d.get("shaded_len_m", 0.0))
        total_cost += float(d.get("cost", 0.0))
    ratio = (total_shade / total_len) if total_len > 0 else 0.0
    return {"n_edges": len(path)-1, "total_len_m": total_len,
            "total_shade_m": total_shade, "shade_ratio": ratio,
            "total_cost": total_cost}

# ========= 최근접 노드 =========
def nearest_node_xy(G: nx.Graph, x: float, y: float) -> int:
    nid, best = None, float("inf")
    for n in G.nodes:
        dx = x - G.nodes[n]["x"]; dy = y - G.nodes[n]["y"]
        d2 = dx*dx + dy*dy
        if d2 < best:
            best, nid = d2, n
    return nid

# ========= 캐시: 시간 → 그림자 → 간선 그늘 =========
@st.cache_data(show_spinner=True)
def compute_shades_for_time(dt_local_iso: str):
    G, buildings, lat0, lng0 = load_graph_and_buildings()
    dt_local = ensure_kst(datetime.datetime.fromisoformat(dt_local_iso))
    rects = build_shadow_rects(buildings, dt_local)
    shaded = {}
    for u, v in G.edges:
        p0 = (G.nodes[u]["x"], G.nodes[u]["y"])
        p1 = (G.nodes[v]["x"], G.nodes[v]["y"])
        shaded_len = compute_unique_shade_length_for_edge(p0, p1, rects)
        shaded[(u, v)] = shaded_len
        shaded[(v, u)] = shaded_len
    return rects, shaded
