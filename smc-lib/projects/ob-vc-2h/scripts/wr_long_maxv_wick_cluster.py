"""Multi-bar maxV-in-wick cluster check for LONG 2h ob_vc.

Per memory [[feedback-vic-maxv-absolute-not-sided]]:
  maxV per 2h = close of 1m bar with ABSOLUTE max volume within 2h

For LONG: "maxV in lower wick" means maxV_close < min(bar.open, bar.close) = body_lo

Check for each LONG ob_vc:
  prev_wick_maxV       = maxV of prev 2h is in lower wick
  prev1_wick_maxV      = maxV of prev-1 (= 2h before prev) is in lower wick
  prev2_wick_maxV      = maxV of prev-2 is in lower wick

Cluster levels:
  n_wick_cluster = how many of (prev, prev-1, prev-2) have maxV in lower wick
                  = 0, 1, 2, 3
"""
import sys, pathlib, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
CUT = int(datetime(2023, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)
TF_2H = 2 * 3600 * 1000
HORIZON_MS = 14*24*3600*1000

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
h_1m = np.array([r[2] for r in rows], dtype=np.float64)
l_1m = np.array([r[3] for r in rows], dtype=np.float64)

rows_ohlc = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
cans_d = aggregate_all_tfs(rows_ohlc)
cans_2h = to_candles(cans_d["2h"])
bar2h_idx = {c.open_time: i for i, c in enumerate(cans_2h)}


def maxv_close_in_2h(open_time_ms):
    """Return close of 1m bar with absolute max volume within 2h bar."""
    i_lo = int(np.searchsorted(ts_1m, open_time_ms, side="left"))
    i_hi = int(np.searchsorted(ts_1m, open_time_ms + TF_2H, side="left"))
    if i_hi <= i_lo: return None
    vols = v_1m[i_lo:i_hi]
    closes = c_1m[i_lo:i_hi]
    if len(vols) == 0: return None
    j = int(np.argmax(vols))
    return float(closes[j])


def maxv_in_lower_wick(bar, max_v_close):
    """True if maxV close is in lower wick = below body_lo."""
    if max_v_close is None: return False
    body_lo = min(bar.open, bar.close)
    return max_v_close < body_lo


def maxv_in_upper_wick(bar, max_v_close):
    if max_v_close is None: return False
    body_hi = max(bar.open, bar.close)
    return max_v_close > body_hi


def tbm_long(entry, sl, born):
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


# Load LONG ob_vc
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt & (g2h.direction == "long")].copy()

records = []
for (d, co), sub in g2h.groupby(["direction","ob_cur_open_ms"]):
    co = int(co); born = int(sub.iloc[0].born_ms)
    idx2h = bar2h_idx.get(co)
    if idx2h is None or idx2h < 4: continue
    cur = cans_2h[idx2h]; prev = cans_2h[idx2h-1]
    prev1 = cans_2h[idx2h-2]; prev2 = cans_2h[idx2h-3]

    # Compute maxV for each bar
    mv_prev = maxv_close_in_2h(prev.open_time)
    mv_prev1 = maxv_close_in_2h(prev1.open_time)
    mv_prev2 = maxv_close_in_2h(prev2.open_time)
    mv_cur = maxv_close_in_2h(cur.open_time)

    # Check wick positions
    prev_lw = maxv_in_lower_wick(prev, mv_prev)
    prev1_lw = maxv_in_lower_wick(prev1, mv_prev1)
    prev2_lw = maxv_in_lower_wick(prev2, mv_prev2)
    cur_lw = maxv_in_lower_wick(cur, mv_cur)

    cluster = int(prev_lw) + int(prev1_lw) + int(prev2_lw)

    # Entry/SL
    nc = len(sub)
    cf = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
    drop_lo = float(cf.drop_lo); fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
    dp = 0.8 if nc >= 2 else 0.2
    entry = fvg_hi - dp * (fvg_hi - fvg_lo); sl = drop_lo

    out = tbm_long(entry, sl, born)
    if out is None: continue
    R = 0; touched = "out" in out
    if touched:
        if out["out"] == "win": R = 1
        elif out["out"] == "loss": R = -1
    records.append({
        "born_ms": born, "R": R, "touched": touched,
        "prev_lw_mv": prev_lw, "prev1_lw_mv": prev1_lw, "prev2_lw_mv": prev2_lw,
        "cur_lw_mv": cur_lw, "n_wick_cluster": cluster,
    })

rdf = pd.DataFrame(records)
print(f"LONG 2h ob_vc processed: {len(rdf)}")


def stats(df, mask, lbl, ref):
    s = df[mask]
    if len(s) < 10: print(f"  {lbl:<45} N={len(s)} (skip)"); return
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = wr - ref
    flag = "⭐" if lift >= 3 else ("✓" if lift >= 1 else "")
    print(f"  {lbl:<45} N={len(s):>4} touch={nt:>4} W={w:>3} L={l:>3} WR={wr:>5.1f}% Σ={w-l:>+4}R ({lift:+.1f}pp) {flag}")


# Full 6y
print(f"\n{'='*100}\nFULL 6y\n{'='*100}")
bw=(rdf.R==1).sum(); bl=(rdf.R==-1).sum(); bnt=rdf.touched.sum()
bwr = bw/bnt*100
print(f"BASELINE LONG: N={len(rdf)} WR={bwr:.1f}% Σ={bw-bl:+}R")

print(f"\n--- Cluster level (n of prev/prev-1/prev-2 with maxV in lower wick) ---")
for k in range(4):
    stats(rdf, rdf.n_wick_cluster == k, f"cluster = {k} bars wick-maxV", bwr)
print(f"\n--- Cumulative ≥k ---")
for k in [1, 2, 3]:
    stats(rdf, rdf.n_wick_cluster >= k, f"cluster ≥ {k}", bwr)

print(f"\n--- Individual position checks ---")
stats(rdf, rdf.prev_lw_mv, "prev wick-maxV (LONG)", bwr)
stats(rdf, rdf.prev_lw_mv & rdf.prev1_lw_mv, "prev + prev-1 wick-maxV", bwr)
stats(rdf, rdf.prev_lw_mv & rdf.prev1_lw_mv & rdf.prev2_lw_mv, "prev + prev-1 + prev-2 ALL wick-maxV", bwr)
stats(rdf, rdf.prev_lw_mv & ~rdf.prev1_lw_mv & ~rdf.prev2_lw_mv, "ONLY prev (no prev-1/-2)", bwr)

# Subset 2023+
print(f"\n{'='*100}\nSUBSET 2023-06-06+\n{'='*100}")
sub = rdf[rdf.born_ms >= CUT].copy()
bw=(sub.R==1).sum(); bl=(sub.R==-1).sum(); bnt=sub.touched.sum()
bwr_s = bw/bnt*100
print(f"BASELINE LONG subset: N={len(sub)} WR={bwr_s:.1f}% Σ={bw-bl:+}R")

print(f"\n--- Cluster levels ---")
for k in range(4):
    stats(sub, sub.n_wick_cluster == k, f"cluster = {k} bars", bwr_s)
print(f"\n--- Cumulative ≥k ---")
for k in [1, 2, 3]:
    stats(sub, sub.n_wick_cluster >= k, f"cluster ≥ {k}", bwr_s)

print(f"\n--- Patterns ---")
stats(sub, sub.prev_lw_mv, "prev wick-maxV", bwr_s)
stats(sub, sub.prev_lw_mv & sub.prev1_lw_mv, "prev + prev-1 wick-maxV (2-bar cluster)", bwr_s)
stats(sub, sub.prev_lw_mv & sub.prev1_lw_mv & sub.prev2_lw_mv, "ALL 3 wick-maxV (full cluster)", bwr_s)

# Verify T1a
TARGET = int(datetime(2026, 6, 5, 22, 0, tzinfo=timezone.utc).timestamp() * 1000)
t1a = rdf[rdf.born_ms == TARGET]
if len(t1a):
    r = t1a.iloc[0]
    print(f"\n=== T1a (2026-06-05 23:00 МСК cur, born 01:00 МСК) ===")
    print(f"  prev wick-maxV (LONG): {r.prev_lw_mv}")
    print(f"  prev-1 wick-maxV: {r.prev1_lw_mv}")
    print(f"  prev-2 wick-maxV: {r.prev2_lw_mv}")
    print(f"  cluster: {r.n_wick_cluster}")
    print(f"  Result: R={r.R}")

# Save
out_path = pathlib.Path(__file__).parent.parent / "data/maxv_wick_cluster.parquet"
rdf.to_parquet(out_path)
print(f"\nSaved: {out_path}")
