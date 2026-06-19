"""TBM на a-suffix с фиксированным SL = 0.5% от entry.

Default:
  LONG:  Entry = cur.low,   SL = entry × 0.995  (R% = 0.5% всегда)
  SHORT: Entry = cur.high,  SL = entry × 1.005

Это значит:
  - prev.low не используется как SL (только как Williams-фрактал для swept check)
  - R фиксирован: 0.5% от entry для всех setups
  - При 200× leverage trade risk = constant (без variability)
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

R_PCT_FIXED = 0.005  # 0.5%

ORIG_PREV = {0:"T1", 1:"T3", 2:"T5", 3:"T7", 4:"T9", 5:"T11", 6:"T13", 7:"T15"}
prev_types_idx = [
    ("long", True, "≥2"), ("long", True, "1"),
    ("long", False, "≥2"), ("long", False, "1"),
    ("short", True, "≥2"), ("short", True, "1"),
    ("short", False, "≥2"), ("short", False, "1"),
]


def wick_ratio(direction, prev, cur, EPS=0.01):
    if direction == "long":
        pw = min(prev.open, prev.close) - prev.low
        cw = min(cur.open, cur.close) - cur.low
    else:
        pw = prev.high - max(prev.open, prev.close)
        cw = cur.high - max(cur.open, cur.close)
    return float("inf") if cw < EPS else pw / cw


def tbm(entry, sl, direction, born_ms):
    if direction == "long" and entry <= sl: return None
    if direction == "short" and entry >= sl: return None
    R = abs(entry - sl)
    TP1 = entry + R if direction == "long" else entry - R
    i_start = int(np.searchsorted(ts_1m, born_ms))
    if i_start >= len(ts_1m): return None
    i_end = min(len(ts_1m)-1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS)))
    if direction == "long":
        slice_l = l_1m[i_start:i_end+1]
        touch_rel = int(np.argmax(slice_l <= entry)) if (slice_l <= entry).any() else -1
    else:
        slice_h = h_1m[i_start:i_end+1]
        touch_rel = int(np.argmax(slice_h >= entry)) if (slice_h >= entry).any() else -1
    if touch_rel == -1: return {"touched": False}
    ti = i_start + touch_rel
    post_h = h_1m[ti:i_end+1]; post_l = l_1m[ti:i_end+1]
    if direction == "long":
        tp1_rel = int(np.argmax(post_h >= TP1)) if (post_h >= TP1).any() else -1
        sl_rel = int(np.argmax(post_l <= sl)) if (post_l <= sl).any() else -1
    else:
        tp1_rel = int(np.argmax(post_l <= TP1)) if (post_l <= TP1).any() else -1
        sl_rel = int(np.argmax(post_h >= sl)) if (post_h >= sl).any() else -1
    if tp1_rel != -1 and (sl_rel == -1 or tp1_rel <= sl_rel):
        return {"touched": True, "outcome": "win"}
    elif sl_rel != -1:
        return {"touched": True, "outcome": "loss"}
    return {"touched": True, "outcome": "timeout"}


records = []
for k, (key, sub) in enumerate(g2h.groupby(["direction", "ob_cur_open_ms"])):
    direction, cur_open = key
    cur_open = int(cur_open)
    idx = bar_idx.get(cur_open)
    if idx is None or idx < 3: continue
    n2c=cans[idx-3]; n1c=cans[idx-2]; prev=cans[idx-1]; cur=cans[idx]
    if direction == "long":
        if not (prev.low < cur.low): continue   # extreme=prev only
        swept = min(prev.low,cur.low) < min(n1c.low,n2c.low)
    else:
        if not (prev.high > cur.high): continue
        swept = max(prev.high,cur.high) > max(n1c.high,n2c.high)
    r = wick_ratio(direction, prev, cur)
    if r < 2.0: continue   # a-suffix only

    n_comp = len(sub); n_class = "≥2" if n_comp >= 2 else "1"
    found_idx = None
    for i, (d, sw, nc) in enumerate(prev_types_idx):
        if d == direction and nc == n_class and sw == swept:
            found_idx = i; break
    t_id = ORIG_PREV[found_idx] + "a" if found_idx is not None else "?a"

    # FIXED SL = 0.5% от entry
    if direction == "long":
        entry = cur.low
        sl = entry * (1 - R_PCT_FIXED)
    else:
        entry = cur.high
        sl = entry * (1 + R_PCT_FIXED)

    chosen = sub.iloc[0]; born = int(chosen.born_ms)
    out = tbm(entry, sl, direction, born)
    if out is None: continue
    r_val = None
    if out.get("touched", False):
        r_val = 1 if out["outcome"] == "win" else (-1 if out["outcome"] == "loss" else 0)

    # Also compute natural raw R% (cur.low - prev.low) для сравнения
    if direction == "long":
        raw_rpct = (cur.low - prev.low) / cur.low * 100
    else:
        raw_rpct = (prev.high - cur.high) / cur.high * 100

    records.append({
        "t_id": t_id, "direction": direction,
        "raw_R_pct": raw_rpct,
        "touched": out.get("touched", False),
        "R": r_val,
    })

rdf = pd.DataFrame(records)
print(f"a-suffix setups processed: {len(rdf):,} (LONG {(rdf.direction=='long').sum()} + SHORT {(rdf.direction=='short').sum()})")
print(f"\nFixed SL = 0.5% от entry (cur.low/high)")
print(f"R% = 0.5% всегда — leverage @ 200× = 100% риск ≈ нужен margin buffer\n")

# Per-type stats
print(f"{'T':<5} {'N':>5} {'touch':>6} {'WR%':>6} {'EV':>9} {'Σ R':>7}")
print("-" * 50)
total_sum = 0
for t in [f"T{i}a" for i in (1,3,5,7,9,11,13,15)]:
    g = rdf[rdf.t_id == t]
    n = len(g)
    if n == 0: print(f"{t:<5} 0"); continue
    nt = g.touched.sum()
    wins = (g.R == 1).sum(); losses = (g.R == -1).sum()
    wr = wins/nt*100 if nt else 0
    ev = (2*wr/100) - 1
    sigR = wins - losses
    total_sum += sigR
    print(f"{t:<5} {n:>5} {nt:>6} {wr:>5.1f}% {ev:>+8.3f}R {sigR:>+6}R")
print(f"\nΣ всех a-suffix: {total_sum:+}R / 6y")

# Comparison vs Hybrid v2 baseline
print(f"\n{'='*60}")
print(f"Сравнение с Hybrid v2 (SL = prev.low/high)")
print(f"{'='*60}")
print(f"{'T':<5} {'Fixed SL Σ':>12} {'Hybrid v2 Σ':>14} {'Δ':>8}")
HYBRID_V2 = {
    "T1a": 54, "T3a": 86, "T5a": 39, "T7a": 121,
    "T9a": 28, "T11a": 38, "T13a": 25, "T15a": 89,
}
for t in [f"T{i}a" for i in (1,3,5,7,9,11,13,15)]:
    g = rdf[rdf.t_id == t]
    sigR = (g.R == 1).sum() - (g.R == -1).sum()
    delta = sigR - HYBRID_V2[t]
    print(f"{t:<5} {sigR:>+11}R {HYBRID_V2[t]:>+13}R {delta:>+7}R")

print(f"\nElapsed: {time.time()-t0:.1f}s")
