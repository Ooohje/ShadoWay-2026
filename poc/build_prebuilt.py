# poc/build_prebuilt.py — 경북대 사전구축 데이터(그래프+건물)를 단일 pickle 로 묶는다.
# 백엔드가 Overpass 없이 이 지역을 즉시 처리하도록 한다. (parquet 엔진 불필요)
import pickle, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"

G = pickle.load(open(ART / "graph_xy.pkl", "rb"))
b = pd.read_parquet(ART / "buildings_xy.parquet", engine="fastparquet")

# 숫자 정리
for c in ["lat", "lng", "height", "radius", "x", "y"]:
    b[c] = pd.to_numeric(b[c], errors="coerce")
b = b.dropna(subset=["lat", "lng", "height", "radius", "x", "y"]).reset_index(drop=True)
b = b[["lat", "lng", "height", "radius", "x", "y"]].copy()

lats = [G.nodes[n]["lat"] for n in G.nodes]
lngs = [G.nodes[n]["lng"] for n in G.nodes]
lat0, lng0 = float(np.mean(lats)), float(np.mean(lngs))
bbox = (min(lats), min(lngs), max(lats), max(lngs))  # south,west,north,east

bundle = {"G": G, "buildings": b, "lat0": lat0, "lng0": lng0, "bbox": bbox,
          "name": "경북대학교(KNU)"}
out = ART / "knu_prebuilt.pkl"
pickle.dump(bundle, open(out, "wb"), protocol=4)
print(f"saved {out}")
print(f"nodes={G.number_of_nodes()} edges={G.number_of_edges()} buildings={len(b)}")
print(f"bbox={bbox}")
print(f"lat0,lng0={lat0:.6f},{lng0:.6f}")
