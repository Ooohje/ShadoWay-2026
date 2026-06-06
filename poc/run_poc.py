# poc/run_poc.py
"""
OSM 기반 ShadoWay PoC 실행기.

임의 지역(bbox)에서:
  1) OSM 도로/건물 가져오기 (osm_loader)
  2) 기존 streamlit_app/core.py 의 그림자·가중치 경로 로직을 '수정 없이' 재사용
  3) folium 지도(HTML)로 출력

목적: 경북대 전용 수작업 데이터 없이도 임의 지역에서 파이프라인이 끝까지 도는지 검증.

사용:
  venv\\Scripts\\python.exe poc\\run_poc.py
옵션(환경변수):
  POC_BBOX="south,west,north,east"   (기본: 대구 동성로 일대)
  POC_DT="2026-06-06T14:00"          (KST, 기본: 오늘 14시)
  POC_WDIST="8.0"                    (거리 가중치 5~10)
"""
from __future__ import annotations
import os
import sys
import math
import datetime
from pathlib import Path

import folium
import networkx as nx

# --- 기존 core.py 로직 재사용 ---
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "streamlit_app"))
import core  # noqa: E402  (sun_angles, ShadowRect, 그림자/경로 함수 재사용)

from osm_loader import load_osm_area, latlng_to_xy  # noqa: E402
import shadow_poly  # noqa: E402  (실제 모양 그림자)


# 기본 데모 지역: 대구 동성로 일대 (경북대가 아닌 신규 지역으로 검증)
DEFAULT_BBOX = (35.8680, 128.5900, 35.8730, 128.5980)


def pick_endpoints(area):
    """bbox 남서/북동 코너에 가장 가까운 노드를 출발/도착으로 선택."""
    s, w, n, e = area._bbox
    sx, sy = latlng_to_xy(s, w, area.lat0, area.lng0)
    ex, ey = latlng_to_xy(n, e, area.lat0, area.lng0)
    src = core.nearest_node_xy(area.G, sx, sy)
    dst = core.nearest_node_xy(area.G, ex, ey)
    return src, dst


def main():
    bbox = os.environ.get("POC_BBOX")
    if bbox:
        south, west, north, east = (float(v) for v in bbox.split(","))
    else:
        south, west, north, east = DEFAULT_BBOX

    dt_str = os.environ.get("POC_DT", "")
    if dt_str:
        dt_local = core.ensure_kst(datetime.datetime.fromisoformat(dt_str))
    else:
        dt_local = core.ensure_kst(
            datetime.datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)
        )

    w_dist = float(os.environ.get("POC_WDIST", "8.0"))
    w_shade = 10.0 - w_dist

    bld_src = os.environ.get("POC_BLD_SRC", "osm").lower()  # osm | vworld

    print(f"[1/4] OSM 도로망 수집: bbox=({south},{west},{north},{east})")
    area = load_osm_area(south, west, north, east)
    area._bbox = (south, west, north, east)

    if bld_src == "vworld":
        from vworld_loader import load_buildings_vworld
        print("      건물 소스: VWorld GIS건물통합정보 WFS (층수 기반 높이)")
        area.buildings = load_buildings_vworld(south, west, north, east,
                                               area.lat0, area.lng0)
    else:
        print("      건물 소스: OSM (height 태그, 누락 다수)")

    n_nodes = area.G.number_of_nodes()
    n_edges = area.G.number_of_edges()
    n_bld = len(area.buildings)
    if n_nodes == 0 or n_bld == 0:
        print(f"  ! 데이터 부족 (nodes={n_nodes}, buildings={n_bld}). bbox를 조정하세요.")
        return
    has_h = int(area.buildings["has_height"].sum())
    print(f"  도로 노드 {n_nodes} / 간선 {n_edges} / 건물 {n_bld} "
          f"(높이태그 보유 {has_h}, 나머지는 기본 {core.__dict__.get('DEFAULT', '')}가정)")

    print(f"[2/4] 실제 모양 그림자 계산: {dt_local.isoformat()}")
    shadow_union, shadows, (alt, az) = shadow_poly.build_shadow_union(
        area.buildings, dt_local, area.lat0, area.lng0
    )
    print(f"  태양 고도 {alt:.1f}°, 방위 {az:.1f}°")
    print(f"  건물 그림자 폴리곤 {len(shadows)}개 (footprint sweep)")

    print("[3/4] 간선별 그늘 길이(폴리곤 교차) + 가중치 경로(Dijkstra)")
    for u, v in area.G.edges:
        p0 = (area.G.nodes[u]["x"], area.G.nodes[u]["y"])
        p1 = (area.G.nodes[v]["x"], area.G.nodes[v]["y"])
        sl = shadow_poly.edge_shade_length(p0, p1, shadow_union)
        area.G[u][v]["shaded_len_m"] = sl

    core.apply_edge_costs(area.G, w_dist, w_shade)
    src, dst = pick_endpoints(area)
    path = nx.shortest_path(area.G, src, dst, weight="cost")
    info = core.summarize_path(area.G, path)
    print(f"  경로 간선 {info['n_edges']} / 거리 {info['total_len_m']:.0f}m / "
          f"그늘 {info['total_shade_m']:.0f}m ({info['shade_ratio']*100:.1f}%)")

    print("[4/4] 지도 렌더링 -> poc/poc_map.html")
    render_map(area, shadow_union, path, info)
    print("  완료. 브라우저로 poc/poc_map.html 를 여세요.")


def render_map(area, shadow_union, path, info):
    G, lat0, lng0 = area.G, area.lat0, area.lng0
    m = folium.Map(location=[lat0, lng0], zoom_start=17, tiles="cartodbpositron",
                   prefer_canvas=True)
    # 도로
    fg_road = folium.FeatureGroup(name="도로", show=True)
    for u, v in G.edges:
        folium.PolyLine(
            [(G.nodes[u]["lat"], G.nodes[u]["lng"]), (G.nodes[v]["lat"], G.nodes[v]["lng"])],
            weight=2, opacity=0.3, color="#3388ff"
        ).add_to(fg_road)
    fg_road.add_to(m)
    # 건물 그림자 (실제 footprint sweep)
    fg_sh = folium.FeatureGroup(name="건물 그림자", show=True)
    for pts in shadow_poly.shadow_to_latlng_polys(shadow_union, lat0, lng0):
        folium.Polygon(pts, color="#222222", weight=0,
                       fill=True, fill_opacity=0.28).add_to(fg_sh)
    fg_sh.add_to(m)
    # 건물 footprint (참고용 윤곽)
    fg_bld = folium.FeatureGroup(name="건물", show=True)
    for r in area.buildings.itertuples(index=False):
        poly_ll = getattr(r, "poly_ll", None)
        if poly_ll and len(poly_ll) >= 3:
            folium.Polygon(poly_ll, color="#888", weight=1,
                           fill=True, fill_opacity=0.10).add_to(fg_bld)
    fg_bld.add_to(m)
    # 경로
    path_ll = [(G.nodes[n]["lat"], G.nodes[n]["lng"]) for n in path]
    folium.PolyLine(path_ll, weight=7, color="#ff4d4f", opacity=0.95,
                    tooltip="추천 경로").add_to(m)
    folium.Marker(path_ll[0], tooltip="출발",
                  icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(m)
    folium.Marker(path_ll[-1], tooltip="도착",
                  icon=folium.Icon(color="red", icon="flag-checkered", prefix="fa")).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    title = (f"거리 {info['total_len_m']:.0f}m · 그늘 {info['shade_ratio']*100:.1f}%")
    folium.map.Marker(
        [area._bbox[2], area._bbox[1]],
        icon=folium.DivIcon(html=f'<div style="font-size:13px;background:#fff;padding:4px 8px;'
                                 f'border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,.3)">'
                                 f'ShadoWay PoC — {title}</div>')
    ).add_to(m)
    m.save(str(Path(__file__).resolve().parent / "poc_map.html"))


if __name__ == "__main__":
    main()
