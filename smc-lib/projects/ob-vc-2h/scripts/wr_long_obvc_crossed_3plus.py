"""WR for LONG ob_vc 2h since 2023-06-06 with n_crossed_VWAPs ≥ 3.

Canonical entry rule:
  - SL = drop_lo
  - Entry: 0.8 deep in TOP FVG (n_FVG≥2) or 0.2 deep (n_FVG=1)
  - LTF: 15m if exists, else 20m
  - TBM with fixed TP1R exit

Compute fresh — no A1, no Stage A drop. Raw all-LONG.
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
HORIZON_MS = 14*24*3600*1000

rows = []
with CSV_1M.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if t < START_MS: continue
        rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
h_1m = np.array([r[2] for r in rows], dtype=np.float64)
l_1m = np.array([r[3] for r in rows], dtype=np.float64)
c_1m = np.array([r[4] for r in rows], dtype=np.float64)
v_1m = np.array([r[5] for r in rows], dtype=np.float64)
cum_pv = np.concatenate(([0.0], np.cumsum(c_1m * v_1m)))
cum_v = np.concatenate(([0.0], np.cumsum(v_1m)))

rows_ohlc = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
cans_d = aggregate_all_tfs(rows_ohlc)
cans_2h = to_candles(cans_d["2h"])
cans_1d = to_candles(cans_d["1d"])
bar2h_idx = {c.open_time: i for i, c in enumerate(cans_2h)}

# All 646 D VWAPs (i+1 anchor)
fhs, fls = detect_williams_n2(cans_1d, n=N_FRACTAL)
anchors = []
for (i, lvl, _) in fls + fhs:
    if i + 1 < len(cans_1d):
        anchors.append(int(cans_1d[i+1].open_time))
A_TS = np.array(sorted(anchors), dtype=np.int64)


def vwap_batch(target_ts):
    i_t = int(np.searchsorted(ts_1m, target_ts, side="right"))
    if i_t == 0: return np.full(len(A_TS), np.nan)
    i_as = np.searchsorted(ts_1m, A_TS, side="left")
    active = i_as < i_t
    out = np.full(len(A_TS), np.nan)
    if not active.any(): return out
    p = cum_pv[i_t] - cum_pv[i_as[active]]
    v = cum_v[i_t] - cum_v[i_as[active]]
    out[active] = np.where(v > 0, p / v, np.nan)
    return out


def tbm(entry, sl, born):
    if entry <= sl: return None
    R = entry - sl; TP1 = entry + R
    iS = int(np.searchsorted(ts_1m, born))
    if iS >= len(ts_1m): return None
    iE = min(len(ts_1m)-1, int(np.searchsorted(ts_1m, born + HORIZON_MS)))
    s = l_1m[iS:iE+1]
    if not (s <= entry).any(): return {"touched": False}
    tr = int(np.argmax(s <= entry))
    ti = iS + tr
    ph = h_1m[ti:iE+1]; pl = l_1m[ti:iE+1]
    tp1r = int(np.argmax(ph >= TP1)) if (ph >= TP1).any() else -1
    slr = int(np.argmax(pl <= sl)) if (pl <= sl).any() else -1
    if tp1r != -1 and (slr == -1 or tp1r <= slr): return {"touched": True, "out": "win"}
    elif slr != -1: return {"touched": True, "out": "loss"}
    return {"touched": True, "out": "timeout"}


# Load raw LONG setups
src = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g = src[src.htf == "2h"].copy()
g["has_15m"] = g.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask = ((g.has_15m & (g.ltf=="15m")) | (~g.has_15m & (g.ltf=="20m")))
g = g[mask].copy()

records = []
for (d, co), sub in g.groupby(["direction","ob_cur_open_ms"]):
    if d != "long": continue
    born = int(sub.iloc[0].born_ms)
    if born < CUT: continue
    nc = len(sub)
    cf = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
    drop_lo = float(cf.drop_lo)
    fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
    dp = 0.8 if nc >= 2 else 0.2
    entry = fvg_hi - dp * (fvg_hi - fvg_lo)
    sl = drop_lo

    cur_idx = bar2h_idx.get(int(co))
    if cur_idx is None: continue
    cur = cans_2h[cur_idx]
    cur_close = float(cur.close)

    # Count crossed VWAPs
    vw = vwap_batch(born)
    valid = ~np.isnan(vw)
    n_crossed = int(((drop_lo < vw) & (vw < cur_close) & valid).sum()) if valid.any() else 0

    # TBM
    out = tbm(entry, sl, born)
    if out is None: continue
    R = 0
    touched = out.get("touched", False)
    if touched:
        if out["out"] == "win": R = 1
        elif out["out"] == "loss": R = -1
    records.append({
        "born_ms": born, "cur_open_ms": int(co),
        "drop_lo": drop_lo, "cur_close": cur_close,
        "n_FVG": nc, "n_crossed": n_crossed,
        "entry": entry, "sl": sl,
        "touched": touched, "R": R,
    })

rdf = pd.DataFrame(records)
print(f"\nLONG ob_vc 2h since 2023-06-06 with TBM computed: {len(rdf)}")

# All
all_w = (rdf.R==1).sum(); all_l = (rdf.R==-1).sum(); all_nt = rdf.touched.sum()
all_wr = all_w/all_nt*100 if all_nt else 0
print(f"\nALL LONG since 2023-06-06:")
print(f"  N={len(rdf)}  touched={all_nt}  W={all_w}  L={all_l}  WR={all_wr:.1f}%  Σ={all_w-all_l:+}R")

# Buckets
print(f"\nWR by n_crossed VWAPs:")
print(f"{'n_crossed':<12} {'N':>5} {'touched':>8} {'W':>4} {'L':>4} {'WR':>6} {'Σ':>5}")
print("-"*55)
for lo, hi in [(0,0),(1,2),(3,5),(6,10),(11,20),(21,9999)]:
    sub = rdf[(rdf.n_crossed >= lo) & (rdf.n_crossed <= hi)]
    nt=sub.touched.sum(); w=(sub.R==1).sum(); l=(sub.R==-1).sum()
    wr = w/nt*100 if nt else 0
    print(f"[{lo:>3}, {hi:>4}]  {len(sub):>5} {nt:>8} {w:>4} {l:>4} {wr:>5.1f}% {w-l:>+4}R")

# Cumulative ≥k
print(f"\nCumulative WR for n_crossed ≥ k:")
print(f"{'k':<3} {'N':>5} {'touched':>8} {'W':>4} {'L':>4} {'WR':>6} {'Σ':>5}")
print("-"*55)
for k in [1, 2, 3, 4, 5, 6, 8, 10, 15, 20]:
    sub = rdf[rdf.n_crossed >= k]
    if len(sub) < 5: continue
    nt=sub.touched.sum(); w=(sub.R==1).sum(); l=(sub.R==-1).sum()
    wr = w/nt*100 if nt else 0
    print(f"{k:<3} {len(sub):>5} {nt:>8} {w:>4} {l:>4} {wr:>5.1f}% {w-l:>+4}R")
