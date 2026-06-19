"""24-type classification: extreme=prev splits into a/b by wick ratio.

LONG  (extreme=prev): ratio = prev_wick_down / cur_wick_down
SHORT (extreme=prev): ratio = prev_wick_up   / cur_wick_up
  ≥ 2.0 → suffix 'a' (strong)
  <  2.0 → suffix 'b' (weak)

Outcomes per T-ID with fixed TP1R.
"""
import sys, pathlib, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

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


# 24 T-IDs: 16 extreme=prev split a/b + 8 extreme=cur
T_NAMES = {}
prev_types = [
    ("long",  True,  "≥2"),  # parent T1
    ("long",  True,  "1"),   # T3
    ("long",  False, "≥2"),  # T5
    ("long",  False, "1"),   # T7
    ("short", True,  "≥2"),  # T9
    ("short", True,  "1"),   # T11
    ("short", False, "≥2"),  # T13
    ("short", False, "1"),   # T15
]
cur_types = [
    ("long",  True,  "≥2"),  # T2
    ("long",  True,  "1"),   # T4
    ("long",  False, "≥2"),  # T6
    ("long",  False, "1"),   # T8
    ("short", True,  "≥2"),  # T10
    ("short", True,  "1"),   # T12
    ("short", False, "≥2"),  # T14
    ("short", False, "1"),   # T16
]
# Map (dir, swept, n_class, extreme, strong) → T-ID
T_MAPPING = {}
# Original IDs: T1..T16 by order from earlier
ORIG_PREV = {0:"T1", 1:"T3", 2:"T5", 3:"T7", 4:"T9", 5:"T11", 6:"T13", 7:"T15"}
ORIG_CUR  = {0:"T2", 1:"T4", 2:"T6", 3:"T8", 4:"T10", 5:"T12", 6:"T14", 7:"T16"}
for i, (d, sw, n) in enumerate(prev_types):
    base = ORIG_PREV[i]
    T_MAPPING[(d, sw, n, "prev", True)]  = base + "a"
    T_MAPPING[(d, sw, n, "prev", False)] = base + "b"
for i, (d, sw, n) in enumerate(cur_types):
    T_MAPPING[(d, sw, n, "cur", None)] = ORIG_CUR[i]


HORIZON_MS = 14 * 24 * 3600 * 1000


def wick_ratio(direction, prev, cur, EPS=0.01):
    if direction == "long":
        prev_wick = min(prev.open, prev.close) - prev.low
        cur_wick  = min(cur.open, cur.close) - cur.low
    else:
        prev_wick = prev.high - max(prev.open, prev.close)
        cur_wick  = cur.high - max(cur.open, cur.close)
    if cur_wick < EPS:
        return float("inf")
    return prev_wick / cur_wick


def tbm_one(direction, fvg_lo, fvg_hi, drop_lo, drop_hi, n_comp, born_ms):
    if direction == "long":
        deep = 0.8 if n_comp >= 2 else 0.2
        entry = fvg_hi - deep * (fvg_hi - fvg_lo)
        sl = drop_lo
        if entry <= sl: return {"touched": False}
        R = entry - sl
        i_start = int(np.searchsorted(ts_1m, born_ms))
        if i_start >= len(ts_1m): return {"touched": False}
        i_end = min(len(ts_1m) - 1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS)))
        slice_l = l_1m[i_start:i_end+1]
        touch_rel = int(np.argmax(slice_l <= entry)) if (slice_l <= entry).any() else -1
        if touch_rel == -1: return {"touched": False}
        touch_idx = i_start + touch_rel
        post_h = h_1m[touch_idx:i_end+1]
        post_l = l_1m[touch_idx:i_end+1]
        TP1 = entry + R
        tp1_rel = int(np.argmax(post_h >= TP1)) if (post_h >= TP1).any() else -1
        sl_rel = int(np.argmax(post_l <= sl)) if (post_l <= sl).any() else -1
        if tp1_rel != -1 and (sl_rel == -1 or tp1_rel <= sl_rel):
            return {"touched": True, "outcome": "win"}
        elif sl_rel != -1:
            return {"touched": True, "outcome": "loss"}
        return {"touched": True, "outcome": "timeout"}
    else:
        deep = 0.8 if n_comp >= 2 else 0.2
        entry = fvg_lo + deep * (fvg_hi - fvg_lo)
        sl = drop_hi
        if entry >= sl: return {"touched": False}
        R = sl - entry
        i_start = int(np.searchsorted(ts_1m, born_ms))
        if i_start >= len(ts_1m): return {"touched": False}
        i_end = min(len(ts_1m) - 1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS)))
        slice_h = h_1m[i_start:i_end+1]
        touch_rel = int(np.argmax(slice_h >= entry)) if (slice_h >= entry).any() else -1
        if touch_rel == -1: return {"touched": False}
        touch_idx = i_start + touch_rel
        post_h = h_1m[touch_idx:i_end+1]
        post_l = l_1m[touch_idx:i_end+1]
        TP1 = entry - R
        tp1_rel = int(np.argmax(post_l <= TP1)) if (post_l <= TP1).any() else -1
        sl_rel = int(np.argmax(post_h >= sl)) if (post_h >= sl).any() else -1
        if tp1_rel != -1 and (sl_rel == -1 or tp1_rel <= sl_rel):
            return {"touched": True, "outcome": "win"}
        elif sl_rel != -1:
            return {"touched": True, "outcome": "loss"}
        return {"touched": True, "outcome": "timeout"}


records = []
groups = g2h.groupby(["direction", "ob_cur_open_ms"])
print(f"Processing {len(groups):,} ob_vc with 24-type classification (wick ratio)...")
for k, (key, sub) in enumerate(groups):
    if k % 500 == 0 and k > 0:
        print(f"  {k:,} / {len(groups):,}")
    direction, cur_open = key
    cur_open = int(cur_open)
    idx = bar_idx.get(cur_open)
    if idx is None or idx < 3: continue
    n2 = cans[idx-3]; n1 = cans[idx-2]; prev = cans[idx-1]; cur = cans[idx]

    if direction == "long":
        swept = min(prev.low, cur.low) < min(n1.low, n2.low)
        extreme = "prev" if prev.low < cur.low else "cur"
    else:
        swept = max(prev.high, cur.high) > max(n1.high, n2.high)
        extreme = "prev" if prev.high > cur.high else "cur"

    n_comp = len(sub)
    n_class = "≥2" if n_comp >= 2 else "1"

    # Wick ratio (only if extreme=prev)
    if extreme == "prev":
        r = wick_ratio(direction, prev, cur)
        strong = (r >= 2.0)
        t_id = T_MAPPING.get((direction, swept, n_class, "prev", strong))
        ratio_val = r if r != float("inf") else 999
    else:
        t_id = T_MAPPING.get((direction, swept, n_class, "cur", None))
        strong = None
        ratio_val = None

    if t_id is None: continue

    if direction == "long":
        chosen = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
    else:
        chosen = sub.sort_values("fvg_zone_lo", ascending=True).iloc[0]

    out = tbm_one(direction, chosen.fvg_zone_lo, chosen.fvg_zone_hi,
                   chosen.drop_lo, chosen.drop_hi, n_comp, int(chosen.born_ms))
    out.update({"t_id": t_id, "direction": direction, "extreme": extreme,
                "strong": strong, "wick_ratio": ratio_val})
    records.append(out)

rdf = pd.DataFrame(records)
print(f"  {len(rdf):,} / {len(groups):,}  ✓\n")
rdf.to_parquet(pathlib.Path(__file__).parent.parent / "data/tbm_2h_24types.parquet", index=False)

# Order T-IDs (24 total)
T_ORDER = [
    "T1a","T1b","T2","T3a","T3b","T4","T5a","T5b","T6","T7a","T7b","T8",
    "T9a","T9b","T10","T11a","T11b","T12","T13a","T13b","T14","T15a","T15b","T16",
]

print(f"{'='*85}")
print(f"  {'T':<6} {'N':>5} {'touch':>6} {'WR%':>6} {'EV/trade':>10} {'Σ R / 6y':>10} {'note':>15}")
print(f"{'='*85}")
total_sum = 0
for t in T_ORDER:
    g = rdf[rdf.t_id == t]
    n = len(g)
    if n == 0:
        print(f"  {t:<6} {0:>5}")
        continue
    n_t = g["touched"].sum()
    tg = g[g.touched]
    wins = (tg.outcome == "win").sum()
    losses = (tg.outcome == "loss").sum()
    wr = wins / n_t * 100 if n_t else 0
    ev = (2 * wr / 100) - 1
    total = wins - losses
    total_sum += total
    note = ""
    if ev > 0.15: note = "🟢🟢"
    elif ev > 0.10: note = "🟢"
    elif ev < 0: note = "🔴"
    print(f"  {t:<6} {n:>5,} {n_t:>6,} {wr:>5.1f}% {ev:>+8.3f}R {total:>+7}R   {note}")

print(f"\n  Σ all 24:  {total_sum:+}R за 6y")
print(f"\nElapsed: {time.time() - t0:.1f}s")
