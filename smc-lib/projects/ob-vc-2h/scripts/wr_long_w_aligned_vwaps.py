"""WR for LONG ob_vc 2h since 2023-06-06, counting only D-VWAPs where the D fractal
is W-aligned (synchronized with W fractal, Mon-Mon anchor per canon).

Anchor: i+1 of D fractal.
"""
import sys, pathlib, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import agg, to_candles, aggregate_all_tfs, detect_williams_n2, MONDAY_USER_ANCHOR_MS

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
CUT = int(datetime(2023, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)
N_FRACTAL = 2
HORIZON_MS = 14*24*3600*1000
TF_W_MS = 7 * 24 * 3600 * 1000

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
# W with Monday anchor (canon per [[weekly-tf-anchor-monday]])
w_bars = agg(rows_ohlc, TF_W_MS, anchor=MONDAY_USER_ANCHOR_MS)
cans_w = to_candles(w_bars)
bar2h_idx = {c.open_time: i for i, c in enumerate(cans_2h)}

print(f"D bars: {len(cans_1d)}  W bars: {len(cans_w)}")

# Detect fractals
fhs_d, fls_d = detect_williams_n2(cans_1d, n=N_FRACTAL)
fhs_w, fls_w = detect_williams_n2(cans_w, n=N_FRACTAL)
print(f"D fractals: FL={len(fls_d)}  FH={len(fhs_d)}")
print(f"W fractals: FL={len(fls_w)}  FH={len(fhs_w)}")


def find_w_synced(d_frac, w_frac):
    """For each W fractal, find D fractal with matching level whose ts falls in W bar's range."""
    synced = []
    for (iw, lvl_w, _) in w_frac:
        ts_w = int(cans_w[iw].open_time)
        win_lo, win_hi = ts_w, ts_w + TF_W_MS
        for (id_, lvl_d, _) in d_frac:
            ts_d = int(cans_1d[id_].open_time)
            if win_lo <= ts_d < win_hi and abs(lvl_d - lvl_w) < 1e-6:
                synced.append((id_, lvl_d))
                break
    return synced


synced_FL = find_w_synced(fls_d, fls_w)
synced_FH = find_w_synced(fhs_d, fhs_w)
print(f"\nW-synced D fractals: FL={len(synced_FL)}  FH={len(synced_FH)}  total={len(synced_FL)+len(synced_FH)}")
print(f"  FL sync rate: {len(synced_FL)}/{len(fls_w)} = {len(synced_FL)/max(len(fls_w),1)*100:.0f}%")
print(f"  FH sync rate: {len(synced_FH)}/{len(fhs_w)} = {len(synced_FH)/max(len(fhs_w),1)*100:.0f}%")

# Build VWAP anchors (i+1) from synced D fractals
synced_anchors = []
for (i, lvl) in synced_FL + synced_FH:
    if i + 1 < len(cans_1d):
        synced_anchors.append(int(cans_1d[i+1].open_time))
A_TS = np.array(sorted(synced_anchors), dtype=np.int64)
print(f"\nW-synced D VWAPs (i+1 anchor): {len(A_TS)}")


def vwap_batch(target_ts):
    if len(A_TS) == 0: return np.array([])
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
    tr = int(np.argmax(s <= entry)); ti = iS + tr
    ph = h_1m[ti:iE+1]; pl = l_1m[ti:iE+1]
    tp1r = int(np.argmax(ph >= TP1)) if (ph >= TP1).any() else -1
    slr = int(np.argmax(pl <= sl)) if (pl <= sl).any() else -1
    if tp1r != -1 and (slr == -1 or tp1r <= slr): return {"out": "win"}
    elif slr != -1: return {"out": "loss"}
    return {"out": "timeout"}


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

    vw = vwap_batch(born)
    valid = ~np.isnan(vw)
    n_crossed = int(((drop_lo < vw) & (vw < cur_close) & valid).sum()) if valid.any() else 0
    n_active = int(valid.sum())

    out = tbm(entry, sl, born)
    if out is None: continue
    R = 0; touched = "out" in out
    if touched:
        if out["out"] == "win": R = 1
        elif out["out"] == "loss": R = -1
    records.append({
        "born_ms": born, "n_FVG": nc,
        "n_active_synced": n_active, "n_crossed": n_crossed,
        "touched": touched, "R": R,
    })

rdf = pd.DataFrame(records)
print(f"\nLONG ob_vc 2h since 2023-06-06: {len(rdf)}")
print(f"Mean active W-synced VWAPs: {rdf.n_active_synced.mean():.1f}")

nt=rdf.touched.sum(); w=(rdf.R==1).sum(); l=(rdf.R==-1).sum()
wr = w/nt*100 if nt else 0
print(f"\nBaseline (all 1017 LONG): N={len(rdf)} WR={wr:.1f}% Σ={w-l:+}R")

print(f"\nWR by n_crossed bucket (W-synced):")
for lo, hi in [(0,0),(1,1),(2,2),(3,4),(5,9),(10,9999)]:
    sub = rdf[(rdf.n_crossed >= lo) & (rdf.n_crossed <= hi)]
    if len(sub) == 0: continue
    nt=sub.touched.sum(); w=(sub.R==1).sum(); l=(sub.R==-1).sum()
    wr = w/nt*100 if nt else 0
    print(f"  [{lo:>3},{hi:>4}]: N={len(sub):>4} WR={wr:>5.1f}% Σ={w-l:+4}R")

print(f"\nCumulative n_crossed ≥ k:")
print(f"{'k':<3} {'N':>5} {'touched':>8} {'W':>4} {'L':>4} {'WR':>6} {'Σ':>5}")
for k in [1, 2, 3, 4, 5, 6, 8, 10]:
    sub = rdf[rdf.n_crossed >= k]
    if len(sub) < 5: continue
    nt=sub.touched.sum(); w=(sub.R==1).sum(); l=(sub.R==-1).sum()
    wr = w/nt*100 if nt else 0
    print(f"{k:<3} {len(sub):>5} {nt:>8} {w:>4} {l:>4} {wr:>5.1f}% {w-l:>+4}R")
