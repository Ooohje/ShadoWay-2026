# streamlit_app/ui.py
import datetime
import folium
import streamlit as st
from streamlit_folium import st_folium
import networkx as nx
from pathlib import Path
import base64, mimetypes

from core import (
    now_kst, ensure_kst,
    load_graph_and_buildings, xy_to_ll, latlng_to_xy,
    compute_shades_for_time, apply_edge_costs, summarize_path, nearest_node_xy
)

# ---- 스타일 주입 ----
def inject_css():
    st.markdown("""
    <style>
    header {visibility: hidden;}
    footer {visibility: hidden;}
    div.block-container {padding-top: .5rem; padding-bottom: .5rem;}
    div.stButton > button {padding: .35rem .6rem; font-size: .9rem;}
    div[data-baseweb="slider"] {margin-top: .1rem; margin-bottom: .1rem;}
    div[data-testid="stMetricValue"] {font-size: 1.1rem;}
    h3.page-title { margin: .2rem 0 .5rem 0 !important; line-height: 1.15; }
    hr.hr-compact { border: none; height: 1px; background: rgba(127,127,127,.28); margin: .25rem 0 .45rem 0; }

    .comp-logo { display:flex; justify-content:flex-end; align-items:center; }
    .comp-logo img { height:36px; object-fit:contain; opacity:.95; }
    @media (max-width:1200px){ .comp-logo img{ height:32px; } }

    .sponsor-box{ border-radius:12px; padding:10px 12px; margin-top:.6rem; }
    .sponsor-grid{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
    @media (max-width:1280px){ .sponsor-grid{ grid-template-columns:repeat(2,1fr); } }
    @media (max-width:960px){  .sponsor-grid{ grid-template-columns:1fr; } }

    .sponsor-card{
      background:#FFFFFF !important;
      border:1px solid #e9e9e9 !important;
      border-radius:12px; padding:10px; height:110px;
      display:flex; align-items:center; justify-content:center; flex-direction:column;
      box-shadow:0 1px 2px rgba(0,0,0,.04);
    }
    .sponsor-img{ width:140px; height:60px; object-fit:contain; }
    .sponsor-cap{ color:#333; opacity:.85; margin-top:6px; font-size:.8rem; }

    .team-note{ text-align:center; font-size:.9rem; opacity:.85; margin-top:.5rem; }
    @media (max-width:960px){ .team-note{ text-align:left; } }

    @media (max-width: 820px){
      .comp-logo { justify-content: flex-start !important; margin-top: .35rem; }
      .comp-logo img { height: 44px; }
    }
    </style>
    """, unsafe_allow_html=True)

def render_competition_logo_topright(size_px: int = 56):
    root = Path(__file__).resolve().parent.parent
    src = _file_to_data_uri(root / "대회로고.png")
    if src:
        st.markdown(
            f'<div class="comp-logo"><img src="{src}" alt="대회 로고" style="height:{size_px}px"/></div>',
            unsafe_allow_html=True
        )

def _file_to_data_uri(p: Path) -> str:
    if not p.exists(): return ""
    mime, _ = mimetypes.guess_type(str(p))
    if mime is None: mime = "image/png"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"

def render_sponsor_strip(items=None, team_note: str | None = None):
    root = Path(__file__).resolve().parent.parent
    if items is None:
        items = [("주최", "주최로고.png"), ("주관", "주관로고.jpg")]

    normalized = []
    for label, p in items:
        path = (root / p) if isinstance(p, str) else p
        normalized.append((label, path))

    cards_html = []
    for label, path in normalized:
        src = _file_to_data_uri(path)
        if src:
            cards_html.append(
                f'<div class="sponsor-card">'
                f'  <img class="sponsor-img" src="{src}" alt="{label} 로고" />'
                f'  <div class="sponsor-cap">{label}</div>'
                f'</div>'
            )
        else:
            cards_html.append(
                f'<div class="sponsor-card"><div class="sponsor-cap">{label} 로고 없음</div></div>'
            )

    note_html = f'<div class="team-note">{team_note}</div>' if team_note else ""
    html_str = (
        '<div class="sponsor-box">'
        f'  <div class="sponsor-grid" style="grid-template-columns: repeat({len(normalized)}, 1fr);">'
        f'    {"".join(cards_html)}'
        '  </div>'
        f'{note_html}'
        '</div>'
    )
    st.markdown(html_str, unsafe_allow_html=True)

# ---- 지도 그리기 ----
def build_map(G, rects_buildings, rects_campus_trees, rects_trees, path_ll, clicks, lat0, lng0, show_shadow: bool):
    m = folium.Map(
        location=[lat0, lng0],
        zoom_start=16,
        tiles=None,
        prefer_canvas=True  # Canvas 렌더링으로 성능/깜빡임 개선
    )

    # 베이스 타일 (Light / Dark)
    folium.TileLayer("cartodbpositron", name="Light", control=True, show=True).add_to(m)
    folium.TileLayer("cartodbdark_matter", name="Dark", control=True, show=False).add_to(m)

    # 전체 간선
    for u, v in G.edges:
        folium.PolyLine(
            [(G.nodes[u]["lat"], G.nodes[u]["lng"]),
             (G.nodes[v]["lat"], G.nodes[v]["lng"])],
            weight=2, opacity=0.35, color="#3388ff"
        ).add_to(m)

    # 그림자 레이어
    if show_shadow:
        if rects_buildings:
            fg_b = folium.FeatureGroup(name="Building Shadows", show=True)
            for r in rects_buildings:
                pts_ll = [xy_to_ll(x, y, lat0, lng0) for (x, y) in r.corners()]
                folium.Polygon(pts_ll, color="#000000", weight=1,
                               fill=True, fill_opacity=0.20).add_to(fg_b)
            fg_b.add_to(m)
        
        if rects_campus_trees:
            fg_t_campus = folium.FeatureGroup(name="Campus Tree Shadows", show=True)
            for r in rects_campus_trees:
                pts_ll = [xy_to_ll(x, y, lat0, lng0) for (x, y) in r.corners()]
                folium.Polygon(pts_ll, color="#2ca25f", weight=1.0,
                               fill=True, fill_opacity=0.22).add_to(fg_t_campus)
            fg_t_campus.add_to(m)


        if rects_trees:
            fg_t = folium.FeatureGroup(name="Tree Shadows (100m)", show=True)
            for r in rects_trees:
                pts_ll = [xy_to_ll(x, y, lat0, lng0) for (x, y) in r.corners()]
                folium.Polygon(pts_ll, color="#2ca29c", weight=1.0,
                               fill=True, fill_opacity=0.22).add_to(fg_t)
            fg_t.add_to(m)

    # 출발/도착 마커
    if len(clicks) >= 1:
        s_lat, s_lng = clicks[0]
        folium.Marker(
            (s_lat, s_lng), tooltip="출발지",
            icon=folium.Icon(color="green", icon="play", prefix="fa")
        ).add_to(m)
    if len(clicks) >= 2:
        e_lat, e_lng = clicks[1]
        folium.Marker(
            (e_lat, e_lng), tooltip="도착지",
            icon=folium.Icon(color="red", icon="flag-checkered", prefix="fa")
        ).add_to(m)

    # 경로
    if path_ll is not None:
        folium.PolyLine(path_ll, weight=7, color="#ff4d4f", opacity=0.95, tooltip="추천 경로").add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m

# ---- 메인 렌더 ----
def render_app():
    inject_css()

    # 제목 + 로고
    hdr_l, hdr_r = st.columns([8, 4])
    with hdr_l:
        st.markdown('<h3 class="page-title">🌤️ ShadoWay</h3>', unsafe_allow_html=True)
    with hdr_r:
        render_competition_logo_topright(size_px=80)
    st.markdown('<hr class="hr-compact">', unsafe_allow_html=True)

    G, buildings, lat0, lng0 = load_graph_and_buildings()

    # 세션 상태
    if "clicks" not in st.session_state:
        st.session_state.clicks = []
    if "route" not in st.session_state:
        st.session_state.route = None

    # 레이아웃
    left, right = st.columns([8, 4], gap="small")

    # ===== 오른쪽 컨트롤 =====
    with right:
        _now_kst = now_kst().replace(second=0, microsecond=0)
        default_dt = _now_kst.replace(tzinfo=None)

        c_d, c_t = st.columns(2)
        with c_d:
            d_val = st.date_input("날짜(KST)", value=default_dt.date(), key="date_kst")
            if isinstance(d_val, tuple): d_val = d_val[0]
        with c_t:
            t_val = st.time_input("시간(KST)", value=default_dt.time(),
                                  step=datetime.timedelta(minutes=10), key="time_kst")
        dt_local = ensure_kst(datetime.datetime.combine(d_val, t_val))

        # ⏱️ 5분 단위 양자화 → 캐시 재사용률↑ & 깜빡임↓
        q = 5
        dt_local_q = dt_local.replace(second=0, microsecond=0)
        minute = (dt_local_q.minute // q) * q
        dt_local_q = dt_local_q.replace(minute=minute)

        c_w, c_opts = st.columns([3, 3])
        with c_w:
            w_dist = st.slider("거리 가중치", 5.0, 10.0, 8.0, 0.5, key="w_dist")
        with c_opts:
            show_shadow = st.checkbox("그림자 표시", value=True, key="show_shadow")
            use_trees  = st.checkbox("교외 가로수 그림자 포함", value=False, key="use_trees")
        w_shade = 10.0 - w_dist
        st.caption(f"그늘 가중치: **{w_shade:.1f}**  (거리+그늘=10)")

        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            do_calc = st.button("🧭 경로 계산", use_container_width=True,
                                disabled=len(st.session_state.clicks) < 2)
        with c_btn2:
            if st.button("🔁 초기화", use_container_width=True):
                st.session_state.clicks = []
                st.session_state.route = None
                st.rerun()

        # 시간 기반 그림자/그늘 (건물 + [옵션]가로수)
        with st.spinner("그림자 계산 중..."):
            rects_bld, rects_campus_tree, rects_tree, shaded_lookup = compute_shades_for_time(
                dt_local_q.replace(tzinfo=None).isoformat(), use_trees=use_trees
            )

        # 그래프에 그늘 길이 반영
        for u, v, d in G.edges(data=True):
            d["shaded_len_m"] = float(shaded_lookup.get((u, v), 0.0))

        # 출발/도착 최근접 노드
        src = dst = None
        if len(st.session_state.clicks) >= 1:
            x, y = latlng_to_xy(*st.session_state.clicks[0], lat0, lng0)
            src = nearest_node_xy(G, x, y)
        if len(st.session_state.clicks) >= 2:
            x, y = latlng_to_xy(*st.session_state.clicks[1], lat0, lng0)
            dst = nearest_node_xy(G, x, y)

        # 경로 계산
        if do_calc and (src is not None) and (dst is not None):
            apply_edge_costs(G, w_dist, w_shade)
            path_nodes = nx.shortest_path(G, source=src, target=dst, weight="cost")
            info = summarize_path(G, path_nodes)
            path_ll = [(G.nodes[n]["lat"], G.nodes[n]["lng"]) for n in path_nodes]
            st.session_state.route = {
                "nodes": path_nodes, "path_ll": path_ll, "info": info, "src": src, "dst": dst
            }

        # 선택/요약
        if st.session_state.route is not None:
            info = st.session_state.route["info"]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Edges", info['n_edges'])
            m2.metric("Distance (m)", f"{info['total_len_m']:.0f}")
            m3.metric("Shade (m)", f"{info['total_shade_m']:.0f}")
            m4.metric("Shade (%)", f"{info['shade_ratio']*100:.1f}")
        else:
            if len(st.session_state.clicks) < 2:
                st.info("지도를 **순서대로 2번 클릭**해 출발·도착을 지정하세요.")
            else:
                st.info("이제 **🧭 경로 계산**을 눌러 경로를 그려보세요.")

        # 주최/주관 로고 스트립
        render_sponsor_strip(
            [("주최", "주최로고.png"), ("주관", "주관로고.jpg")],
            team_note="팀명: 쉐도웨이(ShadoWay)<br>팀원: 오제석, 장지원, 안지호"
        )

    # ===== 왼쪽 지도 =====
    MAP_HEIGHT = 560
    MAP_TOP_OFFSET_PX = 8

    with left:
        st.markdown(f"<div style='height:{MAP_TOP_OFFSET_PX}px'></div>", unsafe_allow_html=True)
        path_ll = st.session_state.route["path_ll"] if st.session_state.route else None
        m = build_map(
            G=G,
            rects_buildings=rects_bld,
            rects_campus_trees=rects_campus_tree,
            rects_trees=rects_tree,
            path_ll=path_ll,
            clicks=st.session_state.clicks,
            lat0=lat0, lng0=lng0,
            show_shadow=st.session_state.get("show_shadow", True),
        )
        click_info = st_folium(m, height=MAP_HEIGHT, use_container_width=True, key="mainmap")

    # 클릭 수집
    if click_info and click_info.get("last_clicked"):
        lat = click_info["last_clicked"]["lat"]
        lng = click_info["last_clicked"]["lng"]
        st.session_state.clicks.append((lat, lng))
        if len(st.session_state.clicks) > 2:
            st.session_state.clicks = st.session_state.clicks[-2:]
        st.session_state.route = None
        st.rerun()
