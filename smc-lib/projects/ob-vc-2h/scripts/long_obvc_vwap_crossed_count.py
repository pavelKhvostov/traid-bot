"""LONG ob_vc 2h since 2023-06-06 — count D-VWAPs (i+1 anchor) that:
   drop_lo < VWAP_value(born_ms)  AND  cur.close > VWAP_value(born_ms)
   = wick crossed VWAP, close recovered above.
ALL D fractals (FL + FH, ~646), no direction filter.
"""
import sys, pathlib, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles, detect_williams_n2

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
CUT = int(datetime(2023, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)
N_FRACTAL = 2

rows = []
with CSV_1M.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if t < START_MS: continue
        rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
c_1m = np.array([r[4] for r in rows], dtype=np.float64)
v_1m = np.array([r[5] for r in rows], dtype=np.float64)
cum_pv = np.concatenate(([0.0], np.cumsum(c_1m * v_1m)))
cum_v = np.concatenate(([0.0], np.cumsum(v_1m)))

rows_ohlc = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
cans_d = aggregate_all_tfs(rows_ohlc)
cans_2h = to_candles(cans_d["2h"])
cans_1d = to_candles(cans_d["1d"])
bar2h_idx = {c.open_time: i for i, c in enumerate(cans_2h)}

# All D fractals anchored at i+1
fhs, fls = detect_williams_n2(cans_1d, n=N_FRACTAL)
anchors = []
for (i, lvl, _) in fls:
    if i + 1 < len(cans_1d):
        anchors.append((int(cans_1d[i+1].open_time), float(lvl), "FL"))
for (i, lvl, _) in fhs:
    if i + 1 < len(cans_1d):
        anchors.append((int(cans_1d[i+1].open_time), float(lvl), "FH"))
anchors.sort(key=lambda x: x[0])
A_TS = np.array([a[0] for a in anchors], dtype=np.int64)
print(f"Total D VWAPs (FL+FH, i+1 anchor): {len(A_TS)}")


def vwap_batch(anchors_ts, target_ts):
    if len(anchors_ts) == 0: return np.array([])
    i_t = int(np.searchsorted(ts_1m, target_ts, side="right"))
    if i_t == 0: return np.full(len(anchors_ts), np.nan)
    i_as = np.searchsorted(ts_1m, anchors_ts, side="left")
    active = i_as < i_t
    out = np.full(len(anchors_ts), np.nan)
    if not active.any(): return out
    p = cum_pv[i_t] - cum_pv[i_as[active]]
    v = cum_v[i_t] - cum_v[i_as[active]]
    out[active] = np.where(v > 0, p / v, np.nan)
    return out


# Load LONG setups since 2023-06-06
src = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g = src[src.htf == "2h"].copy()
g["has_15m"] = g.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask = ((g.has_15m & (g.ltf=="15m")) | (~g.has_15m & (g.ltf=="20m")))
g = g[mask]
ob = g.groupby(["direction","ob_cur_open_ms"]).agg(
    drop_lo=("drop_lo","first"), born_ms=("born_ms","first")
).reset_index()
ob = ob[(ob.direction == "long") & (ob.born_ms >= CUT)].reset_index(drop=True)
print(f"LONG ob_vc 2h since 2023-06-06: {len(ob)}")

# Compute
counts = []
TF_2H = 2*3600*1000
for _, r in ob.iterrows():
    born = int(r.born_ms)
    cur_open_ms = int(r.ob_cur_open_ms)
    cur_idx = bar2h_idx.get(cur_open_ms)
    if cur_idx is None:
        counts.append(None); continue
    cur = cans_2h[cur_idx]
    drop_lo = float(r.drop_lo); cur_close = float(cur.close)
    vw = vwap_batch(A_TS, born)
    valid = ~np.isnan(vw)
    if not valid.any():
        counts.append(0); continue
    vv = vw[valid]
    # Crossed by wick + closed above: drop_lo < VWAP < cur.close
    crossed = (drop_lo < vv) & (vv < cur_close)
    counts.append(int(crossed.sum()))

ob["n_crossed"] = counts
print(f"\nDistribution of n_crossed VWAPs (LONG ob_vc, wick<VWAP<cur.close):")
print(f"  min: {min(c for c in counts if c is not None)}")
print(f"  max: {max(c for c in counts if c is not None)}")
print(f"  mean: {ob.n_crossed.mean():.2f}")
print(f"  median: {ob.n_crossed.median():.0f}")
print(f"\nBuckets:")
for lo, hi in [(0,0),(1,2),(3,5),(6,10),(11,20),(21,50),(51,100),(101,200),(201,9999)]:
    n = ((ob.n_crossed >= lo) & (ob.n_crossed <= hi)).sum()
    print(f"  n_crossed [{lo:>3}, {hi:>4}]:  {n:>4} setups  ({n/len(ob)*100:.1f}%)")

print(f"\nTop counts (10 highest):")
print(ob.nlargest(10, "n_crossed")[["ob_cur_open_ms","drop_lo","n_crossed"]])
