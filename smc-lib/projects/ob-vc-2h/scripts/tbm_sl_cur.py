"""TBM с SL = cur.low (LONG) / cur.high (SHORT) для всех 24 типов.
Entry: OLD rule (0.8/0.2 deep top FVG).

Гипотеза: tighter SL → меньше R → выше WR на TP1R.
Риск: cur wick может зацепить SL.

Для extreme=cur SL и так = cur.low/cur.high → no change.
Для extreme=prev SL смещается с prev.low → cur.low (tighter).
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


ORIG_PREV = {0:"T1", 1:"T3", 2:"T5", 3:"T7", 4:"T9", 5:"T11", 6:"T13", 7:"T15"}
ORIG_CUR  = {0:"T2", 1:"T4", 2:"T6", 3:"T8", 4:"T10", 5:"T12", 6:"T14", 7:"T16"}
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


HORIZON_MS = 14 * 24 * 3600 * 1000


def tbm(direction, sub, prev, cur, born_ms):
    """OLD entry (0.8 deep top FVG), NEW SL = cur.low/cur.high."""
    n_comp = len(sub)
    if direction == "long":
        chosen = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
        deep = 0.8 if n_comp >= 2 else 0.2
        entry = chosen.fvg_zone_hi - deep * (chosen.fvg_zone_hi - chosen.fvg_zone_lo)
        sl = cur.low                    # NEW SL!
        if entry <= sl: return {"touched": False, "R_pct": 0}
        R = entry - sl
        TP1 = entry + R
        i_start = int(np.searchsorted(ts_1m, born_ms))
        if i_start >= len(ts_1m): return {"touched": False, "R_pct": 0}
        i_end = min(len(ts_1m) - 1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS)))
        slice_l = l_1m[i_start:i_end+1]
        touch_rel = int(np.argmax(slice_l <= entry)) if (slice_l <= entry).any() else -1
        if touch_rel == -1: return {"touched": False, "R_pct": R/entry*100}
        touch_idx = i_start + touch_rel
        post_h = h_1m[touch_idx:i_end+1]
        post_l = l_1m[touch_idx:i_end+1]
        tp1_rel = int(np.argmax(post_h >= TP1)) if (post_h >= TP1).any() else -1
        sl_rel = int(np.argmax(post_l <= sl)) if (post_l <= sl).any() else -1
        outcome = "timeout"
        if tp1_rel != -1 and (sl_rel == -1 or tp1_rel <= sl_rel):
            outcome = "win"
        elif sl_rel != -1:
            outcome = "loss"
        return {"touched": True, "outcome": outcome, "R_pct": R/entry*100}
    else:
        chosen = sub.sort_values("fvg_zone_lo", ascending=True).iloc[0]
        deep = 0.8 if n_comp >= 2 else 0.2
        entry = chosen.fvg_zone_lo + deep * (chosen.fvg_zone_hi - chosen.fvg_zone_lo)
        sl = cur.high                   # NEW SL!
        if entry >= sl: return {"touched": False, "R_pct": 0}
        R = sl - entry
        TP1 = entry - R
        i_start = int(np.searchsorted(ts_1m, born_ms))
        if i_start >= len(ts_1m): return {"touched": False, "R_pct": 0}
        i_end = min(len(ts_1m) - 1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS)))
        slice_h = h_1m[i_start:i_end+1]
        touch_rel = int(np.argmax(slice_h >= entry)) if (slice_h >= entry).any() else -1
        if touch_rel == -1: return {"touched": False, "R_pct": R/entry*100}
        touch_idx = i_start + touch_rel
        post_h = h_1m[touch_idx:i_end+1]
        post_l = l_1m[touch_idx:i_end+1]
        tp1_rel = int(np.argmax(post_l <= TP1)) if (post_l <= TP1).any() else -1
        sl_rel = int(np.argmax(post_h >= sl)) if (post_h >= sl).any() else -1
        outcome = "timeout"
        if tp1_rel != -1 and (sl_rel == -1 or tp1_rel <= sl_rel):
            outcome = "win"
        elif sl_rel != -1:
            outcome = "loss"
        return {"touched": True, "outcome": outcome, "R_pct": R/entry*100}


records = []
groups = g2h.groupby(["direction", "ob_cur_open_ms"])
for k, (key, sub) in enumerate(groups):
    if k % 500 == 0 and k > 0: print(f"  {k:,} / {len(groups):,}")
    direction, cur_open = key
    cur_open = int(cur_open)
    idx = bar_idx.get(cur_open)
    if idx is None or idx < 3: continue
    n2c=cans[idx-3]; n1c=cans[idx-2]; prev=cans[idx-1]; cur=cans[idx]
    if direction == "long":
        swept = min(prev.low,cur.low) < min(n1c.low,n2c.low)
        extreme = "prev" if prev.low < cur.low else "cur"
    else:
        swept = max(prev.high,cur.high) > max(n1c.high,n2c.high)
        extreme = "prev" if prev.high > cur.high else "cur"
    n_comp = len(sub); n_class = "≥2" if n_comp >= 2 else "1"
    found_idx = None
    for i, (d, sw, nc) in enumerate(prev_types_idx):
        if d == direction and sw == swept and nc == n_class:
            found_idx = i; break
    if found_idx is None: continue
    if extreme == "prev":
        r = wick_ratio(direction, prev, cur)
        suffix = "a" if r >= 2.0 else "b"
        t_id = ORIG_PREV[found_idx] + suffix
    else:
        t_id = ORIG_CUR[found_idx]

    chosen = sub.iloc[0]
    out = tbm(direction, sub, prev, cur, int(chosen.born_ms))
    out["t_id"] = t_id
    records.append(out)

rdf = pd.DataFrame(records)
print(f"\nProcessed: {len(rdf):,}\n")

T_ORDER = ["T1a","T1b","T2","T3a","T3b","T4","T5a","T5b","T6","T7a","T7b","T8",
           "T9a","T9b","T10","T11a","T11b","T12","T13a","T13b","T14","T15a","T15b","T16"]

print(f"{'T':<6} {'N':>5} {'touch':>6} {'WR%':>6} {'EV':>9} {'ΣR':>6} {'avgR%':>7}")
print("-" * 55)
total_sum = 0
for t in T_ORDER:
    g = rdf[rdf.t_id == t]
    n = len(g)
    if n == 0: print(f"{t:<6} 0"); continue
    n_t = g.touched.sum()
    tg = g[g.touched]
    wins = (tg.outcome == "win").sum()
    losses = (tg.outcome == "loss").sum()
    wr = wins / n_t * 100 if n_t else 0
    ev = (2 * wr / 100) - 1
    total = wins - losses
    total_sum += total
    avg_rpct = g.R_pct.mean()
    print(f"{t:<6} {n:>5} {n_t:>6} {wr:>5.1f}% {ev:>+8.3f}R {total:>+5}R {avg_rpct:>6.2f}%")
print(f"\nΣ всех: {total_sum:+}R / 6y")
print(f"Elapsed: {time.time()-t0:.1f}s")
