"""LONG 2h ob_vc parent HTF — FORMING bar canon (real-time, no-lookahead).

Canon for LONG:
  HTF bar B containing our cur 2h:
    B.open_time ≤ cur_2h.open_time < B.open_time + HTF_ms
  At born_ms (= cur_2h.close):
    partial_open  = B.open (= open of first 2h in B)
    partial_close = cur_2h.close (current price at born_ms)
    partial_low   = min of 2h.low for all 2h bars in B with open_time ≤ cur_2h.open_time
    partial_high  = max of 2h.high for same set
  PARENT FIRES if:
    partial_close > partial_open  (forming bullish)
    AND partial_low == drop_lo    (our 2h pair makes parent's low so far)
"""
import sys, pathlib, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
CUT_2023 = int(datetime(2023, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)
HORIZON_MS = 14*24*3600*1000
TF_2H = 2 * 3600 * 1000
TF_4H = 4 * 3600 * 1000
TF_6H = 6 * 3600 * 1000

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

rows_ohlc = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
cans_d = aggregate_all_tfs(rows_ohlc)
cans_2h = to_candles(cans_d["2h"])
bar2h_idx = {c.open_time: i for i, c in enumerate(cans_2h)}

# Pre-build 2h arrays for fast lookup
ts_2h = np.array([c.open_time for c in cans_2h], dtype=np.int64)
o_2h = np.array([c.open for c in cans_2h], dtype=np.float64)
h_2h = np.array([c.high for c in cans_2h], dtype=np.float64)
l_2h = np.array([c.low for c in cans_2h], dtype=np.float64)
c_2h = np.array([c.close for c in cans_2h], dtype=np.float64)


def forming_parent_long(cur_open_ms: int, drop_lo: float, htf_ms: int):
    """Check forming HTF parent at cur close time.
    Returns (fires, partial_open, partial_low, partial_close).
    """
    # HTF bar containing cur_2h
    htf_open = cur_open_ms - (cur_open_ms % htf_ms)
    # 2h bars within this HTF bar with open_time ≤ cur_open_ms
    i_lo = int(np.searchsorted(ts_2h, htf_open, side="left"))
    i_hi = int(np.searchsorted(ts_2h, cur_open_ms, side="right"))  # exclusive top
    # include cur_2h itself
    if i_hi == 0 or i_lo >= len(ts_2h):
        return False, None, None, None
    if ts_2h[i_hi - 1] != cur_open_ms:
        # cur not aligned
        return False, None, None, None
    # Range [i_lo, i_hi) covers 2h bars from htf_open through cur (inclusive)
    if i_hi <= i_lo:
        return False, None, None, None
    partial_open = float(o_2h[i_lo])
    partial_close = float(c_2h[i_hi - 1])  # = cur close
    partial_low = float(l_2h[i_lo:i_hi].min())
    partial_high = float(h_2h[i_lo:i_hi].max())
    bullish = partial_close > partial_open
    low_match = abs(partial_low - drop_lo) < 1e-6
    return bullish and low_match, partial_open, partial_low, partial_close


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


# Load LONG 2h ob_vc — ALL 2034
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt & (g2h.direction == "long")].copy()

records = []
for (d, co), sub in g2h.groupby(["direction","ob_cur_open_ms"]):
    co = int(co)
    born = int(sub.iloc[0].born_ms)
    nc = len(sub)
    cf = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
    drop_lo = float(cf.drop_lo)
    fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
    dp = 0.8 if nc >= 2 else 0.2
    entry = fvg_hi - dp * (fvg_hi - fvg_lo)
    sl = drop_lo

    p4, _, _, _ = forming_parent_long(co, drop_lo, TF_4H)
    p6, _, _, _ = forming_parent_long(co, drop_lo, TF_6H)

    out = tbm_long(entry, sl, born)
    if out is None: continue
    R = 0; touched = "out" in out
    if touched:
        if out["out"] == "win": R = 1
        elif out["out"] == "loss": R = -1
    records.append({
        "born_ms": born, "ob_cur_open_ms": co, "n_FVG": nc,
        "p4_form": p4, "p6_form": p6,
        "p_any": p4 or p6, "p_both": p4 and p6,
        "touched": touched, "R": R,
    })

rdf = pd.DataFrame(records)
print(f"LONG 2h ob_vc processed: {len(rdf):,}")
print(f"  p4 (4h forming parent): {rdf.p4_form.sum()} ({rdf.p4_form.sum()/len(rdf)*100:.1f}%)")
print(f"  p6 (6h forming parent): {rdf.p6_form.sum()} ({rdf.p6_form.sum()/len(rdf)*100:.1f}%)")
print(f"  p_any (4h OR 6h):       {rdf.p_any.sum()} ({rdf.p_any.sum()/len(rdf)*100:.1f}%)")
print(f"  p_both (4h AND 6h):     {rdf.p_both.sum()} ({rdf.p_both.sum()/len(rdf)*100:.1f}%)")


def stat(rdf, mask, lbl, ref):
    s = rdf[mask]
    if len(s) < 10: print(f"  {lbl:<35} N={len(s)} (skip)"); return
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = wr - ref
    flag = "⭐" if lift >= 3 else ("✓" if lift >= 1 else "")
    print(f"  {lbl:<35} N={len(s):>4} touch={nt:>4} W={w:>4} L={l:>4} WR={wr:>5.1f}% Σ={w-l:>+4}R ({lift:+.1f}pp) {flag}")


# Full 6y
print(f"\n{'='*90}")
print(f"FULL 6y (LONG)")
print(f"{'='*90}")
bw=(rdf.R==1).sum(); bl=(rdf.R==-1).sum(); bnt=rdf.touched.sum()
bwr = bw/bnt*100 if bnt else 0
print(f"  BASELINE LONG               N={len(rdf):>4} WR={bwr:.1f}% Σ={bw-bl:+}R")
stat(rdf, rdf.p4_form, "Parent 4h forming", bwr)
stat(rdf, rdf.p6_form, "Parent 6h forming", bwr)
stat(rdf, rdf.p_any, "Parent 4h OR 6h", bwr)
stat(rdf, rdf.p_both, "Parent 4h AND 6h", bwr)
stat(rdf, ~rdf.p_any, "NO parent", bwr)

# Subset 2023+
sub = rdf[rdf.born_ms >= CUT_2023].reset_index(drop=True)
print(f"\n{'='*90}")
print(f"SUBSET 2023-06-06+ (LONG)")
print(f"{'='*90}")
bw=(sub.R==1).sum(); bl=(sub.R==-1).sum(); bnt=sub.touched.sum()
bwr = bw/bnt*100 if bnt else 0
print(f"  BASELINE LONG subset        N={len(sub):>4} WR={bwr:.1f}% Σ={bw-bl:+}R")
stat(sub, sub.p4_form, "Parent 4h forming", bwr)
stat(sub, sub.p6_form, "Parent 6h forming", bwr)
stat(sub, sub.p_any, "Parent 4h OR 6h", bwr)
stat(sub, sub.p_both, "Parent 4h AND 6h", bwr)
stat(sub, ~sub.p_any, "NO parent", bwr)

# Verify T1a
TARGET = int(datetime(2026, 6, 5, 20, 0, tzinfo=timezone.utc).timestamp() * 1000)
t1a = rdf[rdf.ob_cur_open_ms == TARGET]
print(f"\nT1a verification:")
if len(t1a):
    r = t1a.iloc[0]
    print(f"  p4={r.p4_form}  p6={r.p6_form}  p_any={r.p_any}  R={r.R}")
else:
    print(f"  T1a not found in processed records!")

# Save
out_path = pathlib.Path(__file__).parent.parent / "data/forming_parent_long.parquet"
rdf.to_parquet(out_path)
print(f"\nSaved: {out_path}")
