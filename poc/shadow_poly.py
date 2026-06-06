# poc/shadow_poly.py
"""
건물 footprint(실제 다각형)를 태양 반대 방향으로 밀어내(sweep) 만든
'진짜 모양' 그림자 폴리곤. 원/직사각형 근사를 대체한다.

원리:
  지면에 드리우는 건물 그림자 = footprint 다각형을
  태양 반대 방향 단위벡터 (dx,dy) 로 길이 L = height / tan(고도) 만큼
  쓸고 지나간 영역.
  = footprint 와 평행이동한 footprint, 그리고 그 사이를 잇는 옆면(quad)들의 합집합
  (다각형과 선분의 민코프스키 합).

shapely 로 합집합/교차를 계산하므로:
  - 여러 건물 그림자의 겹침은 unary_union 으로 자동 1회 계산(중복 그늘 방지)
  - 도로 간선의 그늘 길이 = 간선 LineString ∩ 그림자합집합 의 길이
"""
from __future__ import annotations
import math
import datetime
from typing import List

import pandas as pd
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union
from shapely.affinity import translate

# core.py 의 태양각/좌표 유틸 재사용 (run_poc 에서 sys.path 설정됨)
from core import sun_angles_deg, unit_vec_from_azimuth, latlng_to_xy, xy_to_ll


def _building_shadow(poly_xy: Polygon, dx: float, dy: float, L: float) -> Polygon:
    """footprint(local xy) 를 (dx,dy)*L 만큼 쓸어낸 그림자 폴리곤."""
    moved = translate(poly_xy, xoff=dx * L, yoff=dy * L)
    parts = [poly_xy, moved]
    # 외곽선 각 변을 (변, 변+이동벡터) 평행사변형으로 → 옆면 채우기
    coords = list(poly_xy.exterior.coords)
    for (x0, y0), (x1, y1) in zip(coords[:-1], coords[1:]):
        quad = Polygon([
            (x0, y0), (x1, y1),
            (x1 + dx * L, y1 + dy * L), (x0 + dx * L, y0 + dy * L),
        ])
        if quad.is_valid and quad.area > 0:
            parts.append(quad)
    return unary_union(parts)


def build_shadow_union(buildings: pd.DataFrame, dt_local: datetime.datetime,
                       lat0: float, lng0: float):
    """모든 건물의 그림자 합집합(shapely geometry)과 개별 폴리곤 리스트를 반환."""
    alt, az = sun_angles_deg(dt_local, lat0, lng0)
    if alt <= 0:
        return None, [], (alt, az)
    dx, dy = unit_vec_from_azimuth(az)
    tan_alt = math.tan(math.radians(alt))
    shadows: List[Polygon] = []
    for r in buildings.itertuples(index=False):
        poly_ll = getattr(r, "poly_ll", None)
        if not poly_ll or len(poly_ll) < 3:
            continue
        xy = [latlng_to_xy(lat, lng, lat0, lng0) for (lat, lng) in poly_ll]
        foot = Polygon(xy)
        if not foot.is_valid:
            foot = foot.buffer(0)
        if foot.is_empty or foot.area <= 0:
            continue
        L = float(r.height) / tan_alt
        sh = _building_shadow(foot, dx, dy, L)
        if sh and not sh.is_empty:
            shadows.append(sh)
    if not shadows:
        return None, [], (alt, az)
    union = unary_union(shadows)
    return union, shadows, (alt, az)


def edge_shade_length(p0, p1, shadow_union) -> float:
    """간선(p0->p1, local xy) 이 그림자합집합과 겹치는 실제 길이(m)."""
    if shadow_union is None:
        return 0.0
    seg = LineString([p0, p1])
    inter = seg.intersection(shadow_union)
    if inter.is_empty:
        return 0.0
    return float(inter.length)


def shadow_to_latlng_polys(shadow_union, lat0: float, lng0: float):
    """그림자 geometry 를 folium 용 [(lat,lng),...] 폴리곤 리스트로 변환."""
    if shadow_union is None or shadow_union.is_empty:
        return []
    geoms = getattr(shadow_union, "geoms", [shadow_union])
    out = []
    for g in geoms:
        if g.geom_type != "Polygon":
            continue
        out.append([xy_to_ll(x, y, lat0, lng0) for (x, y) in g.exterior.coords])
    return out
