# poc/vworld_loader.py
"""
VWorld GIS건물통합정보 WFS(getBldgisSpceWFS, typename=dt_d010) 에서
건물 footprint + 층수/높이를 가져와 osm_loader 와 동일한 건물 DataFrame 스키마
(lat,lng,x,y,height,radius,has_height) 로 변환한다.

OSM 대비 장점: 한국 전역 건물에 '지상층수(ground_floor_co)'가 채워져 있어
높이를 신뢰성 있게 추정할 수 있다 (그림자 정확도 ↑).

인증키는 환경변수 VWORLD_WFS_KEY 로 주입한다. (코드/깃에 하드코딩 금지)
"""
from __future__ import annotations
import os
import math
import time
import xml.etree.ElementTree as ET

import requests
import numpy as np
import pandas as pd

from osm_loader import latlng_to_xy

WFS_URL = "https://api.vworld.kr/ned/wfs/getBldgisSpceWFS"
TYPENAME = "dt_d010"
NS = {"sop": "https://www.vworld.kr", "gml": "http://www.opengis.net/gml"}

LEVEL_HEIGHT_M = 3.3
DEFAULT_HEIGHT_M = 9.0   # 층수·높이 모두 없을 때 (≈3층)


def _get_key() -> str:
    key = os.environ.get("VWORLD_WFS_KEY", "").strip()
    if not key:
        raise RuntimeError("환경변수 VWORLD_WFS_KEY 가 설정되지 않았습니다.")
    return key


def fetch_wfs(south: float, west: float, north: float, east: float,
              max_features: int = 1000, timeout: int = 12, attempts: int = 1) -> str:
    # bbox 축 순서: miny,minx,maxy,maxx = lat,lon,lat,lon (EPSG:4326)
    params = {
        "key": _get_key(),
        "typename": TYPENAME,
        "bbox": f"{south},{west},{north},{east}",
        "maxFeatures": str(max_features),
        "srsName": "EPSG:4326",
        "output": "GML2",
    }
    last_err = None
    for i in range(max(1, attempts)):
        try:
            r = requests.get(WFS_URL, params=params, timeout=timeout)
            r.raise_for_status()
            if "ServiceException" in r.text[:500]:
                raise RuntimeError(r.text[:300])
            return r.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            if i < attempts - 1:
                time.sleep(0.5)
    raise RuntimeError(f"VWorld WFS 요청 실패: {last_err}")


def _parse_height(member) -> tuple[float, bool]:
    """(height_m, has_real_source) 반환."""
    hg = member.findtext("sop:hg", default="0", namespaces=NS)
    floors = member.findtext("sop:ground_floor_co", default="0", namespaces=NS)
    try:
        hg = float(hg)
    except ValueError:
        hg = 0.0
    try:
        floors = int(float(floors))
    except ValueError:
        floors = 0
    if hg > 0:
        return hg, True
    if floors > 0:
        return floors * LEVEL_HEIGHT_M, True
    return DEFAULT_HEIGHT_M, False


def _polygon_coords(member):
    """ag_geom 의 첫 외곽 LinearRing 좌표 [(lon,lat), ...] 반환."""
    ring = member.find(".//gml:LinearRing/gml:coordinates", NS)
    if ring is None or not ring.text:
        return []
    pts = []
    for tok in ring.text.strip().split():
        lon_s, lat_s = tok.split(",")
        pts.append((float(lon_s), float(lat_s)))
    return pts


def load_buildings_vworld(south: float, west: float, north: float, east: float,
                          lat0: float, lng0: float) -> pd.DataFrame:
    xml = fetch_wfs(south, west, north, east)
    root = ET.fromstring(xml)
    rows = []
    for member in root.findall(".//sop:dt_d010", NS):
        coords = _polygon_coords(member)
        if len(coords) < 3:
            continue
        height, has_h = _parse_height(member)
        lats = [lat for _, lat in coords]
        lngs = [lon for lon, _ in coords]
        clat, clng = float(np.mean(lats)), float(np.mean(lngs))
        xs, ys = [], []
        for lon, lat in coords:
            x, y = latlng_to_xy(lat, lon, lat0, lng0)
            xs.append(x); ys.append(y)
        cx, cy = float(np.mean(xs)), float(np.mean(ys))
        radius = float(max(math.hypot(x - cx, y - cy) for x, y in zip(xs, ys)))
        if radius <= 0:
            continue
        rows.append({
            "lat": clat, "lng": clng, "x": cx, "y": cy,
            "height": height, "radius": radius, "has_height": has_h,
            "poly_ll": [(lat, lon) for lon, lat in coords],  # 실제 footprint (lat,lng)
        })
    return pd.DataFrame(rows)
