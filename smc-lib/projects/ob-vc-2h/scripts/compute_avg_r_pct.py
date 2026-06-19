"""Compute average R% (= R / entry × 100) per type for OLD and NEW rules.
R% важна для leverage math: SL = R% × leverage от капитала.
"""
import sys, pathlib
import pandas as pd
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import load_1m, aggregate_all_tfs, to_candles

df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction", "ob_cur_open_ms"])["ltf"].transform(
    lambda x: "15m" in set(x))
mask = ((g2h.has_15m & (g2h.ltf == "15m")) | (~g2h.has_15m & (g2h.ltf == "20m")))
g2h = g2h[mask].copy()

cans = to_candles(aggregate_all_tfs(load_1m())["2h"])
bar_idx = {c.open_time: i for i, c in enumerate(cans)}
from bisect import bisect_left

# Williams N=2 for swept
def detect_williams(cans, n=2):
    fhs = []; fls = []
    for i in range(n, len(cans) - n):
        ch, cl = cans[i].high, cans[i].low
        if all(ch > cans[i-k].high and ch > cans[i+k].high for k in range(1, n+1)):
            fhs.append((cans[i].open_time, ch))
        if all(cl < cans[i-k].low and cl < cans[i+k].low for k in range(1, n+1)):
            fls.append((cans[i].open_time, cl))
    return fhs, fls

ORIG_PREV = {0:"T1", 1:"T3", 2:"T5", 3:"T7", 4:"T9", 5:"T11", 6:"T13", 7:"T15"}
ORIG_CUR  = {0:"T2", 1:"T4", 2:"T6", 3:"T8", 4:"T10", 5:"T12", 6:"T14", 7:"T16"}
prev_types_idx = [
    ("long",  True,  "≥2"), ("long",  True,  "1"),
    ("long",  False, "≥2"), ("long",  False, "1"),
    ("short", True,  "≥2"), ("short", True,  "1"),
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


# Aggregate R% per type
r_old = {}; r_new = {}

groups = g2h.groupby(["direction", "ob_cur_open_ms"])
for k, (key, sub) in enumerate(groups):
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

    # T-ID
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

    # OLD rule R% (using top FVG entry)
    if direction == "long":
        chosen = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
        deep = 0.8 if n_comp >= 2 else 0.2
        entry_old = chosen.fvg_zone_hi - deep * (chosen.fvg_zone_hi - chosen.fvg_zone_lo)
        sl_old = chosen.drop_lo
        R_old = entry_old - sl_old
    else:
        chosen = sub.sort_values("fvg_zone_lo", ascending=True).iloc[0]
        deep = 0.8 if n_comp >= 2 else 0.2
        entry_old = chosen.fvg_zone_lo + deep * (chosen.fvg_zone_hi - chosen.fvg_zone_lo)
        sl_old = chosen.drop_hi
        R_old = sl_old - entry_old

    if R_old > 0:
        r_pct_old = R_old / entry_old * 100
        r_old.setdefault(t_id, []).append(r_pct_old)

    # NEW rule R% (non-extreme entry)
    if direction == "long":
        if prev.low < cur.low:
            entry_new = cur.low; sl_new = prev.low
        else:
            entry_new = prev.low; sl_new = cur.low
        R_new = entry_new - sl_new
    else:
        if prev.high > cur.high:
            entry_new = cur.high; sl_new = prev.high
        else:
            entry_new = prev.high; sl_new = cur.high
        R_new = sl_new - entry_new

    if R_new > 0:
        r_pct_new = R_new / entry_new * 100
        r_new.setdefault(t_id, []).append(r_pct_new)


T_ORDER = [
    "T1a","T1b","T2","T3a","T3b","T4","T5a","T5b","T6","T7a","T7b","T8",
    "T9a","T9b","T10","T11a","T11b","T12","T13a","T13b","T14","T15a","T15b","T16",
]
PREV_TYPES = {"T1a","T1b","T3a","T3b","T5a","T5b","T7a","T7b",
              "T9a","T9b","T11a","T11b","T13a","T13b","T15a","T15b"}

print(f"{'T':<6}  {'avg R% OLD':>11}  {'avg R% NEW':>11}  {'avg R% HYBRID':>13}")
print("-" * 50)
for t in T_ORDER:
    old_vals = r_old.get(t, [])
    new_vals = r_new.get(t, [])
    mean_old = np.mean(old_vals) if old_vals else 0
    mean_new = np.mean(new_vals) if new_vals else 0
    mean_hyb = mean_new if t in PREV_TYPES else mean_old
    print(f"{t:<6}  {mean_old:>10.2f}%  {mean_new:>10.2f}%  {mean_hyb:>12.2f}%")
