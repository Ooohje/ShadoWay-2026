# poc/osm_loader.py
"""
임의 지역(bbox)을 받아 OpenStreetMap(Overpass)에서
- 보행 가능 도로망  -> networkx 그래프 (core.py가 기대하는 노드 스키마: x,y,lat,lng)
- 건물 footprint    -> buildings DataFrame (core.py 스키마: x,y,lat,lng,height,radius)
로 변환한다.

핵심: 출력 스키마를 기존 streamlit_app/core.py 가 이미 쓰는 형태와 동일하게 맞춰
그림자/경로 로직을 수정 없이 재사용할 수 있게 한다.

건물 높이(height)는 그림자 계산의 핵심 입력인데 OSM 한국 데이터는 누락이 잦다.
누락 시 building:levels*층고 -> 그래도 없으면 DEFAULT_HEIGHT_M 로 가정한다.
(정확도가 필요하면 이 부분을 VWorld GIS건물통합정보 WFS 로 교체)
"""
from __future__ import annotations
import math
import time
from dataclasses import dataclass
from typing import Optional

import requests
import numpy as np
import pandas as pd
import networkx as nx

# ENU 평면 근사 (좁은 지역에서만 유효 — PoC는 도시 일부라 OK)
R_EARTH = 6371000.0

# 보행 경로에 포함할 highway 종류
WALKABLE_HIGHWAYS = {
    "footway", "path", "pedestrian", "living_street", "residential",
    "service", "unclassified", "tertiary", "secondary", "primary",
    "steps", "track", "cycleway", "road",
}

DEFAULT_HEIGHT_M = 12.0   # 높이 정보가 전혀 없을 때 가정 (≈4층)
LEVEL_HEIGHT_M = 3.3      # building:levels 1개층당 높이

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


# ---------- 좌표 변환 (core.py 와 동일한 ENU) ----------
def latlng_to_xy(lat: float, lng: float, lat0: float, lng0: float):
    dlat = math.radians(lat - lat0)
    dlng = math.radians(lng - lng0)
    x = R_EARTH * dlng * math.cos(math.radians(lat0))
    y = R_EARTH * dlat
    return x, y


def haversine_m(lat1, lng1, lat2, lng2):
    p = math.pi / 180.0
    a = (0.5 - math.cos((lat2 - lat1) * p) / 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lng2 - lng1) * p)) / 2)
    return 2 * R_EARTH * math.asin(math.sqrt(a))


# ---------- Overpass 호출 ----------
def fetch_overpass(south: float, west: float, north: float, east: float,
                   timeout: int = 40, rounds: int = 2) -> dict:
    q = f"""
    [out:json][timeout:{timeout}];
    (
      way["highway"]({south},{west},{north},{east});
      way["building"]({south},{west},{north},{east});
    );
    out geom tags;
    """
    last_err = None
    for rnd in range(rounds):
        for url in OVERPASS_URLS:
            try:
                r = requests.post(url, data={"data": q}, timeout=timeout + 20)
                r.raise_for_status()
                return r.json()
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
        time.sleep(1.5)
    raise RuntimeError(f"Overpass 요청 실패(모든 미러): {last_err}")


# ---------- 높이 파싱 ----------
def _parse_height(tags: dict) -> float:
    h = tags.get("height")
    if h:
        try:
            return float(str(h).lower().replace("m", "").strip())
        except ValueError:
            pass
    lv = tags.get("building:levels")
    if lv:
        try:
            return float(str(lv).split(";")[0]) * LEVEL_HEIGHT_M
        except ValueError:
            pass
    return DEFAULT_HEIGHT_M


# ---------- 도로 -> 그래프 ----------
def _node_key(lat: float, lng: float):
    # Overpass 'out geom' 은 node id를 안 주므로 좌표를 양자화해 노드 식별자로 사용.
    # 같은 교차점 좌표는 동일 키가 되어 도로들이 연결된다. (~1e-7도 ≈ 1cm)
    return (round(lat, 7), round(lng, 7))


def build_graph(elements: list, lat0: float, lng0: float) -> nx.Graph:
    G = nx.Graph()
    for el in elements:
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {})
        if tags.get("highway") not in WALKABLE_HIGHWAYS:
            continue
        geom = el.get("geometry", [])
        if len(geom) < 2:
            continue
        keys = []
        for pt in geom:
            k = _node_key(pt["lat"], pt["lon"])
            if k not in G:
                x, y = latlng_to_xy(pt["lat"], pt["lon"], lat0, lng0)
                G.add_node(k, lat=pt["lat"], lng=pt["lon"], x=x, y=y)
            keys.append(k)
        for (a, pa), (b, pb) in zip(zip(keys, geom), zip(keys[1:], geom[1:])):
            if a == b:
                continue
            d = haversine_m(pa["lat"], pa["lon"], pb["lat"], pb["lon"])
            if d > 0:
                G.add_edge(a, b, length_m=d)
    # 최대 연결 요소만 남김 (고립된 도로 조각 제거)
    if G.number_of_nodes() == 0:
        return G
    largest = max(nx.connected_components(G), key=len)
    return G.subgraph(largest).copy()


# ---------- 건물 -> DataFrame ----------
def build_buildings(elements: list, lat0: float, lng0: float) -> pd.DataFrame:
    rows = []
    for el in elements:
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {})
        if "building" not in tags:
            continue
        geom = el.get("geometry", [])
        if len(geom) < 3:
            continue
        xs, ys, lats, lngs = [], [], [], []
        for pt in geom:
            x, y = latlng_to_xy(pt["lat"], pt["lon"], lat0, lng0)
            xs.append(x); ys.append(y); lats.append(pt["lat"]); lngs.append(pt["lon"])
        cx, cy = float(np.mean(xs)), float(np.mean(ys))
        clat, clng = float(np.mean(lats)), float(np.mean(lngs))
        # 외접원 반경 = 중심에서 꼭짓점까지 최대 거리 (구형 원형 모델 호환용, 더 이상 그림자엔 안 씀)
        radius = float(max(math.hypot(x - cx, y - cy) for x, y in zip(xs, ys)))
        rows.append({
            "lat": clat, "lng": clng, "x": cx, "y": cy,
            "height": _parse_height(tags), "radius": radius,
            "poly_ll": list(zip(lats, lngs)),  # 실제 footprint 꼭짓점 (lat,lng)
            "has_height": bool(tags.get("height") or tags.get("building:levels")),
        })
    return pd.DataFrame(rows)


@dataclass
class OSMArea:
    G: nx.Graph
    buildings: pd.DataFrame
    lat0: float
    lng0: float


def load_osm_area(south: float, west: float, north: float, east: float) -> OSMArea:
    lat0 = (south + north) / 2.0
    lng0 = (west + east) / 2.0
    data = fetch_overpass(south, west, north, east)
    elements = data.get("elements", [])
    G = build_graph(elements, lat0, lng0)
    buildings = build_buildings(elements, lat0, lng0)
    return OSMArea(G=G, buildings=buildings, lat0=lat0, lng0=lng0)
