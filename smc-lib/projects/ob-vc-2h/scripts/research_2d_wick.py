"""2D исследование F1 × F3 на LONG a-suffix с R% ≥ 0.5%.

Filter:
  direction = long
  extreme = prev (prev.low < cur.low)
  swept (1.1.1 канон)
  prev_wick ≥ 2× cur_wick (a-suffix)
  (cur.low - prev.low) / cur.low ≥ 0.5%   ← новый фильтр

Rule: Entry = cur.low, SL = prev.low, TP1R, fixed exit.

Features:
  F1 = prev_wick / prev_body         (relative «фитильность» prev)
  F3 = prev_wick / cur.low × 100     (absolute размер фитиля в % цены)

Output: 2D bin matrix (F1 × F3) с N, WR, EV, Σ R.
"""
import sys, pathlib, time
import numpy as np
import pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import load_1m, aggregate_all_tfs, to_candles

t0 = time.time()
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction", "ob_cur_open_ms"])["ltf"].transform(
    lambda x: "15m" in set(x))
mask = ((g2h.has_15m & (g2h.ltf == "15m")) | (~g2h.has_15m & (g2h.ltf == "20m")))
g2h = g2h[mask].copy()

cans = to_candles(aggregate_all_tfs(load_1m())["2h"])
bar_idx = {c.open_time: i for i, c in enumerate(cans)}
_rows = load_1m()
ts_1m = np.array([r[0] for r in _rows], dtype=np.int64)
h_1m = np.array([r[2] for r in _rows], dtype=np.float64)
l_1m = np.array([r[3] for r in _rows], dtype=np.float64)
HORIZON_MS = 14*24*3600*1000


def tbm_long(entry, sl, born_ms):
    if entry <= sl: return None
    R = entry - sl
    TP1 = entry + R
    i_start = int(np.searchsorted(ts_1m, born_ms))
    if i_start >= len(ts_1m): return None
    i_end = min(len(ts_1m)-1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS)))
    slice_l = l_1m[i_start:i_end+1]
    touch_rel = int(np.argmax(slice_l <= entry)) if (slice_l <= entry).any() else -1
    if touch_rel == -1: return {"touched": False}
    ti = i_start + touch_rel
    post_h = h_1m[ti:i_end+1]; post_l = l_1m[ti:i_end+1]
    tp1_rel = int(np.argmax(post_h >= TP1)) if (post_h >= TP1).any() else -1
    sl_rel = int(np.argmax(post_l <= sl)) if (post_l <= sl).any() else -1
    if tp1_rel != -1 and (sl_rel == -1 or tp1_rel <= sl_rel):
        return {"touched": True, "outcome": "win"}
    elif sl_rel != -1:
        return {"touched": True, "outcome": "loss"}
    return {"touched": True, "outcome": "timeout"}


records = []
for k, (key, sub) in enumerate(g2h.groupby(["direction", "ob_cur_open_ms"])):
    direction, cur_open = key
    if direction != "long": continue
    cur_open = int(cur_open)
    idx = bar_idx.get(cur_open)
    if idx is None or idx < 3: continue
    n2c=cans[idx-3]; n1c=cans[idx-2]; prev=cans[idx-1]; cur=cans[idx]

    # extreme = prev
    if not (prev.low < cur.low): continue
    # swept
    if not (min(prev.low, cur.low) < min(n1c.low, n2c.low)): continue
    # wick ratio ≥ 2× (a-suffix)
    pw = min(prev.open, prev.close) - prev.low
    cw = min(cur.open, cur.close) - cur.low
    if cw < 0.01: continue
    if pw / cw < 2.0: continue
    # R% ≥ 0.5% filter
    raw_R_pct = (cur.low - prev.low) / cur.low * 100
    if raw_R_pct < 0.5: continue

    # Features
    prev_body = abs(prev.close - prev.open)
    F1 = pw / prev_body if prev_body > 0.01 else 999
    F3 = pw / cur.low * 100

    chosen = sub.iloc[0]; born = int(chosen.born_ms)

    # NEW rule TBM
    out = tbm_long(cur.low, prev.low, born)
    if out is None: continue
    if out.get("touched", False):
        r_out = 1 if out["outcome"] == "win" else (-1 if out["outcome"] == "loss" else 0)
    else:
        r_out = None  # NO_TRADE

    records.append({
        "F1": F1, "F3": F3,
        "R_pct": raw_R_pct,
        "touched": out.get("touched", False),
        "outcome": out.get("outcome", "no_touch"),
        "R": r_out,
    })

rdf = pd.DataFrame(records)
print(f"LONG a-suffix setups с R% ≥ 0.5%: {len(rdf):,}")
print(f"\nFeature stats:")
print(f"  F1 prev_wick/body: median={rdf.F1.median():.2f}, q25={rdf.F1.quantile(0.25):.2f}, q75={rdf.F1.quantile(0.75):.2f}, q90={rdf.F1.quantile(0.90):.2f}")
print(f"  F3 prev_wick %:    median={rdf.F3.median():.2f}%, q25={rdf.F3.quantile(0.25):.2f}%, q75={rdf.F3.quantile(0.75):.2f}%, q90={rdf.F3.quantile(0.90):.2f}%")

# 2D BIN ANALYSIS
print(f"\n{'='*90}")
print(f"2D interaction matrix: F1 (rows) × F3 (cols)")
print(f"Bins (quartiles):")
f1_q = rdf.F1.quantile([0.25, 0.5, 0.75]).values
f3_q = rdf.F3.quantile([0.25, 0.5, 0.75]).values
print(f"  F1 thresholds: ≤{f1_q[0]:.2f} | {f1_q[0]:.2f}-{f1_q[1]:.2f} | {f1_q[1]:.2f}-{f1_q[2]:.2f} | >{f1_q[2]:.2f}")
print(f"  F3 thresholds: ≤{f3_q[0]:.2f}% | {f3_q[0]:.2f}-{f3_q[1]:.2f}% | {f3_q[1]:.2f}-{f3_q[2]:.2f}% | >{f3_q[2]:.2f}%")
print(f"{'='*90}\n")

rdf["F1_bin"] = pd.cut(rdf.F1, bins=[-np.inf, f1_q[0], f1_q[1], f1_q[2], np.inf],
                       labels=["F1_low","F1_q2","F1_q3","F1_high"])
rdf["F3_bin"] = pd.cut(rdf.F3, bins=[-np.inf, f3_q[0], f3_q[1], f3_q[2], np.inf],
                       labels=["F3_low","F3_q2","F3_q3","F3_high"])

# Matrix
print(f"{'F1\\F3':<10} {'F3_low':>15} {'F3_q2':>15} {'F3_q3':>15} {'F3_high':>15}")
print("-" * 75)
for f1b in ["F1_low","F1_q2","F1_q3","F1_high"]:
    cells = []
    for f3b in ["F3_low","F3_q2","F3_q3","F3_high"]:
        g = rdf[(rdf.F1_bin == f1b) & (rdf.F3_bin == f3b)]
        n = len(g)
        if n == 0:
            cells.append(f"{'-':>15}")
            continue
        n_t = g.touched.sum()
        wins = (g.R == 1).sum()
        losses = (g.R == -1).sum()
        wr = wins/n_t*100 if n_t else 0
        sigR = wins - losses
        cells.append(f"N={n:>3} WR{wr:>4.0f}% Σ{sigR:>+3}")
    print(f"{f1b:<10} {cells[0]:>15} {cells[1]:>15} {cells[2]:>15} {cells[3]:>15}")

# Σ R per cell (total contribution)
print(f"\nTotal Σ R per cell (= win × +1 + loss × -1):")
print(f"{'F1\\F3':<10} {'F3_low':>10} {'F3_q2':>10} {'F3_q3':>10} {'F3_high':>10}")
print("-" * 60)
for f1b in ["F1_low","F1_q2","F1_q3","F1_high"]:
    cells = []
    for f3b in ["F3_low","F3_q2","F3_q3","F3_high"]:
        g = rdf[(rdf.F1_bin == f1b) & (rdf.F3_bin == f3b)]
        wins = (g.R == 1).sum()
        losses = (g.R == -1).sum()
        cells.append(f"{wins-losses:>+5}R")
    print(f"{f1b:<10} {cells[0]:>10} {cells[1]:>10} {cells[2]:>10} {cells[3]:>10}")

# WR matrix only
print(f"\nWR % matrix (winners as % of touched):")
print(f"{'F1\\F3':<10} {'F3_low':>10} {'F3_q2':>10} {'F3_q3':>10} {'F3_high':>10}")
print("-" * 60)
for f1b in ["F1_low","F1_q2","F1_q3","F1_high"]:
    cells = []
    for f3b in ["F3_low","F3_q2","F3_q3","F3_high"]:
        g = rdf[(rdf.F1_bin == f1b) & (rdf.F3_bin == f3b)]
        n_t = g.touched.sum()
        wins = (g.R == 1).sum()
        wr = wins/n_t*100 if n_t else 0
        cells.append(f"{wr:>6.1f}%")
    print(f"{f1b:<10} {cells[0]:>10} {cells[1]:>10} {cells[2]:>10} {cells[3]:>10}")

# Marginal stats
print(f"\nMarginal stats:")
print(f"\n  По F1 (wick/body):")
for f1b in ["F1_low","F1_q2","F1_q3","F1_high"]:
    g = rdf[rdf.F1_bin == f1b]
    nt = g.touched.sum(); wins = (g.R == 1).sum(); losses = (g.R == -1).sum()
    wr = wins/nt*100 if nt else 0
    print(f"    {f1b:<10} N={len(g):>4} WR={wr:>5.1f}% Σ={wins-losses:>+4}R")
print(f"\n  По F3 (prev wick %):")
for f3b in ["F3_low","F3_q2","F3_q3","F3_high"]:
    g = rdf[rdf.F3_bin == f3b]
    nt = g.touched.sum(); wins = (g.R == 1).sum(); losses = (g.R == -1).sum()
    wr = wins/nt*100 if nt else 0
    print(f"    {f3b:<10} N={len(g):>4} WR={wr:>5.1f}% Σ={wins-losses:>+4}R")

print(f"\nElapsed: {time.time()-t0:.1f}s")
