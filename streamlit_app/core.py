# streamlit_app/core.py
import math
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple
from pathlib import Path
import datetime, pytz
import pickle
from pyproj import Transformer

import numpy as np
import pandas as pd
import networkx as nx
import streamlit as st

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

# ========= 좌표 변환 (ENU) =========
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

# ========= 좌표 변환 (WGS84 ↔ UTM 52N) =========
EPSG_WGS84 = 4326
EPSG_UTM52 = 32652

_tf_wgs84_to_utm = Transformer.from_crs(EPSG_WGS84, EPSG_UTM52, always_xy=True)  # (lon,lat)->(E,N)
_tf_utm_to_wgs84 = Transformer.from_crs(EPSG_UTM52, EPSG_WGS84, always_xy=True)  # (E,N)->(lon,lat)

def ll_to_utm(lon: float, lat: float) -> tuple[float, float]:
    E, N = _tf_wgs84_to_utm.transform(lon, lat)
    return float(E), float(N)

def utm_to_ll(E: float, N: float) -> tuple[float, float]:
    lon, lat = _tf_utm_to_wgs84.transform(E, N)
    return float(lon), float(lat)

# ========= 태양 방위/고도 =========
from pysolar.solar import get_altitude, get_azimuth

def sun_angles_deg(dt_local: datetime.datetime, lat0: float, lng0: float) -> Tuple[float, float]:
    """그래프 중심(lat0,lng0) 기준으로 한 번만 계산."""
    dt_utc = to_utc(dt_local)
    alt = get_altitude(lat0, lng0, dt_utc)
    az  = get_azimuth(lat0, lng0, dt_utc)
    return alt, az

def unit_vec_from_azimuth(az_deg: float) -> Tuple[float, float]:
    th = math.radians(az_deg)
    ux = math.sin(th); uy = math.cos(th)  # 태양 방향(동,북)
    dx, dy = -ux, -uy                     # 태양 반대(그늘 방향)
    n = math.hypot(dx, dy)
    return (dx/n, dy/n) if n else (0.0, 0.0)

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

# ========= 교내 가로수 데이터 로드 =========
@st.cache_data(show_spinner="가로수 데이터 로딩 중...")
def load_and_merge_tree_data():
    # artifacts 폴더에 파일
    tree_loc_path = ARTIFACTS_DIR / "교내_가로수_정보.csv"
    tree_spec_path = ARTIFACTS_DIR / "수종_정보.csv"

    if not tree_loc_path.exists() or not tree_spec_path.exists():
        st.warning("가로수 정보 CSV 파일을 찾을 수 없습니다.")
        return pd.DataFrame()

    # 1. CSV 파일 불러오기
    trees_df = pd.read_csv(tree_loc_path)   # lat, lng, type
    species_df = pd.read_csv(tree_spec_path) # type, heit, radius 등

    # 2. 'type' 컬럼 기준으로 데이터 병합
    merged_df = pd.merge(trees_df, species_df, on='type', how='left')

    # 3. build_tree_shadow_rects 함수가 요구하는 컬럼명으로 변경
    merged_df.rename(columns={'heit': 'height', 'radius': 'crown_r'}, inplace=True)
    
    # 4. 필요한 컬럼만 남기고, 값이 없는 데이터 제거
    final_cols = ['lat', 'lng', 'height', 'crown_r']
    if all(col in merged_df.columns for col in final_cols):
        return merged_df[final_cols].dropna()
    else:
        st.error("가로수 데이터에 필요한 컬럼(lat, lng, heit, radius)이 부족합니다.")
        return pd.DataFrame()

# ========= 시각→그림자 (건물) =========
def build_shadow_rects(buildings_df: pd.DataFrame, dt_local: datetime.datetime,
                       lat0: float, lng0: float) -> List[ShadowRect]:
    alt, az = sun_angles_deg(dt_local, lat0, lng0)
    if alt <= 0:
        return []
    dx, dy = unit_vec_from_azimuth(az)
    tan_alt = math.tan(math.radians(alt))
    rects: List[ShadowRect] = []
    for _, row in buildings_df.iterrows():
        L = float(row["height"]) / tan_alt
        cx0, cy0 = float(row["x"]), float(row["y"])
        cx = cx0 + 0.5 * L * dx
        cy = cy0 + 0.5 * L * dy
        width = 2.0 * float(row["radius"])
        rects.append(ShadowRect(
            cx=cx, cy=cy, length=L, width=width, dx=dx, dy=dy,
            meta={"latlng": (row["lat"], row["lng"]), "alt_deg": alt, "az_deg": az}
        ))
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

# ========= 가로수(100m 격자) 유틸 =========
def _poisson_in_square(center_E: float, center_N: float, size_m: float, n: int,
                       seed: int = 42, max_tries: int = 5):
    import random
    rng = random.Random(seed)
    A = size_m * size_m
    alpha = 0.85
    r = alpha * math.sqrt(A / (max(n, 1) * math.pi))
    h = 0.5 * size_m

    for _ in range(max_tries):
        pts, active = [], []
        x0 = rng.uniform(-h, h); y0 = rng.uniform(-h, h)
        pts.append((x0, y0)); active.append((x0, y0))
        k, r2 = 30, r*r

        def in_sq(x, y): return (-h <= x <= h) and (-h <= y <= h)
        def far_enough(x, y):
            for (px, py) in pts:
                dx, dy = x - px, y - py
                if dx*dx + dy*dy < r2: return False
            return True

        while active and len(pts) < n:
            ax, ay = active[rng.randrange(len(active))]
            found = False
            for _ in range(k):
                rho = rng.uniform(r, 2*r); th = rng.uniform(0, 2*math.pi)
                nx_, ny_ = ax + rho*math.cos(th), ay + rho*math.sin(th)
                if in_sq(nx_, ny_) and far_enough(nx_, ny_):
                    pts.append((nx_, ny_)); active.append((nx_, ny_))
                    found = True
                    if len(pts) >= n: break
            if not found:
                active.remove((ax, ay))

        if len(pts) >= n:
            rng.shuffle(pts); pts = pts[:n]
            return [(center_E + x, center_N + y) for (x, y) in pts]

        r *= 0.85

    pts = [(rng.uniform(-h, h), rng.uniform(-h, h)) for _ in range(n)]
    return [(center_E + x, center_N + y) for (x, y) in pts]

def _sample_tree_params(n: int, rng=np.random.default_rng(0),
                        height_mean=8.0, height_std=2.0,
                        crown_r_min=2.0, crown_r_max=4.0):
    heights = np.clip(rng.normal(height_mean, height_std, size=n), 3.0, 20.0)
    crown_r = rng.uniform(crown_r_min, crown_r_max, size=n)
    return heights, crown_r

@st.cache_data(show_spinner=False)
def load_trees_grid_100m(trees_csv_path: Path) -> pd.DataFrame:
    if not trees_csv_path.exists():
        return pd.DataFrame()
    df = pd.read_csv(trees_csv_path)
    df["NUMPOINTS"]   = pd.to_numeric(df["NUMPOINTS"], errors="coerce").fillna(0).astype(int)
    df["grid_size_m"] = pd.to_numeric(df["grid_size_m"], errors="coerce")
    df = df[(df["grid_size_m"] == 100) & (df["NUMPOINTS"] > 0)].reset_index(drop=True)
    if df.empty:
        st.warning("trees_grid.csv에서 grid_size_m==100 & NUMPOINTS>0 레코드가 없습니다.", icon="⚠️")
        return df
    Es, Ns = zip(*[ll_to_utm(lon, lat) for lon, lat in zip(df["lon"], df["lat"])])
    df["E_center"], df["N_center"] = Es, Ns
    return df

@st.cache_data(show_spinner=True)
def build_trees_for_time_100m(dt_iso: str, df_grid_100: pd.DataFrame,
                              height_mean=8.0, height_std=2.0,
                              crown_r_min=2.0, crown_r_max=4.0,
                              seed_base: int = 12345) -> pd.DataFrame:
    if df_grid_100 is None or df_grid_100.empty:
        return pd.DataFrame()
    rows = []
    for i, row in df_grid_100.iterrows():
        n = int(row["NUMPOINTS"])
        pts_EN = _poisson_in_square(row["E_center"], row["N_center"], 100, n, seed=seed_base + i)
        heights, crown_r = _sample_tree_params(
            n, rng=np.random.default_rng(seed_base + i),
            height_mean=height_mean, height_std=height_std,
            crown_r_min=crown_r_min, crown_r_max=crown_r_max
        )
        for j, (E, N) in enumerate(pts_EN):
            lon, lat = utm_to_ll(E, N)
            rows.append({"lon": lon, "lat": lat,
                         "height": float(heights[j]), "crown_r": float(crown_r[j])})
    return pd.DataFrame(rows)

def build_tree_shadow_rects(df_trees: pd.DataFrame, dt_local: datetime.datetime,
                            lat0: float, lng0: float) -> List[ShadowRect]:
    alt, az = sun_angles_deg(dt_local, lat0, lng0)
    if alt <= 0:
        return []
    dx, dy = unit_vec_from_azimuth(az)
    tan_alt = math.tan(math.radians(alt))
    rects: List[ShadowRect] = []
    for r in df_trees.itertuples(index=False):
        L = float(r.height) / tan_alt
        x0, y0 = latlng_to_xy(r.lat, r.lng, lat0, lng0)
        cx = x0 + 0.5 * L * dx
        cy = y0 + 0.5 * L * dy
        rects.append(ShadowRect(
            cx=cx, cy=cy, length=L, width=2.0 * float(r.crown_r), dx=dx, dy=dy,
            meta={"type": "tree", "height": float(r.height),
                  "crown_r": float(r.crown_r), "alt_deg": alt, "az_deg": az}
        ))
    return rects

# ========= 캐시: 시간 → 그림자 → 간선 그늘 (건물 + [옵션]가로수) =========
@st.cache_data(show_spinner=True)
def compute_shades_for_time(dt_local_iso: str, use_trees: bool = False):
    """
    시간별 그림자 계산.
    - 건물 그림자: 항상 포함
    - 교내 가로수 그림자: 항상 포함
    - 교외 가로수 그림자: use_trees=True면 포함 (100m 격자만)
    리턴: (rects_buildings, rects_campus_trees, rects_trees, shaded_lookup)
    """
    G, buildings, lat0, lng0 = load_graph_and_buildings()
    dt_local = ensure_kst(datetime.datetime.fromisoformat(dt_local_iso))

    # (1) 건물 그림자
    rects_buildings = build_shadow_rects(buildings, dt_local, lat0, lng0)

    # (2) 교내 가로수 그림자

    df_campus_trees = load_and_merge_tree_data()
    rects_campus_trees = []
    if not df_campus_trees.empty:
        rects_campus_trees = build_tree_shadow_rects(df_campus_trees, dt_local, lat0, lng0)

    # (3) 선택: 가로수 그림자
    rects_trees: List[ShadowRect] = []
    if use_trees:
        trees_csv = ARTIFACTS_DIR / "경북대_가로수_위경도.csv"  # <-- 너가 쓰는 파일명에 맞춤
        df_grid_100 = load_trees_grid_100m(trees_csv)
        if not df_grid_100.empty:
            df_trees = build_trees_for_time_100m(dt_local.isoformat(), df_grid_100)
            #'lon' 열을 'lng'로 변경하여 데이터 형식 통일
            if 'lon' in df_trees.columns:
                df_trees.rename(columns={'lon':'lng'}, inplace=True)
            rects_trees = build_tree_shadow_rects(df_trees, dt_local, lat0, lng0)

    # (4) 간선 그늘 길이 (겹침 제거)
    rects_all = rects_buildings + rects_campus_trees + rects_trees
    shaded = {}
    for u, v in G.edges:
        p0 = (G.nodes[u]["x"], G.nodes[u]["y"])
        p1 = (G.nodes[v]["x"], G.nodes[v]["y"])
        shaded_len = compute_unique_shade_length_for_edge(p0, p1, rects_all)
        shaded[(u, v)] = shaded_len
        shaded[(v, u)] = shaded_len

    return rects_buildings, rects_campus_trees, rects_trees, shaded