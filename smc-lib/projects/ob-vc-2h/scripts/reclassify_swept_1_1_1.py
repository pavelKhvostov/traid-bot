"""Reclassify 2h ob_vc using Strategy 1.1.1 swept canon (n-1, n-2 lookback).
Then re-run TBM per T1-T16 with new classification.
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

# Dedup 15m > 20m
g2h["has_15m"] = g2h.groupby(["direction", "ob_cur_open_ms"])["ltf"].transform(
    lambda x: "15m" in set(x))
mask = ((g2h.has_15m & (g2h.ltf == "15m")) | (~g2h.has_15m & (g2h.ltf == "20m")))
g2h = g2h[mask].copy()

cans = to_candles(aggregate_all_tfs(load_1m())["2h"])
bar_idx = {c.open_time: i for i, c in enumerate(cans)}

ts_1m_arr = np.array([r[0] for r in load_1m()], dtype=np.int64)
# need 1m arrays for TBM
_rows = load_1m()
ts_1m = np.array([r[0] for r in _rows], dtype=np.int64)
h_1m = np.array([r[2] for r in _rows], dtype=np.float64)
l_1m = np.array([r[3] for r in _rows], dtype=np.float64)


TYPE_IDS = {
    ("long",  True,  "≥2", "prev"): "T1",   ("long",  True,  "≥2", "cur"):  "T2",
    ("long",  True,  "1",  "prev"): "T3",   ("long",  True,  "1",  "cur"):  "T4",
    ("long",  False, "≥2", "prev"): "T5",   ("long",  False, "≥2", "cur"):  "T6",
    ("long",  False, "1",  "prev"): "T7",   ("long",  False, "1",  "cur"):  "T8",
    ("short", True,  "≥2", "prev"): "T9",   ("short", True,  "≥2", "cur"):  "T10",
    ("short", True,  "1",  "prev"): "T11",  ("short", True,  "1",  "cur"):  "T12",
    ("short", False, "≥2", "prev"): "T13",  ("short", False, "≥2", "cur"):  "T14",
    ("short", False, "1",  "prev"): "T15",  ("short", False, "1",  "cur"):  "T16",
}

HORIZON_MS = 14 * 24 * 3600 * 1000


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
        else:
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
        else:
            return {"touched": True, "outcome": "timeout"}


# Reclassify + TBM
ob_groups = g2h.groupby(["direction", "ob_cur_open_ms"])
print(f"Processing {len(ob_groups):,} unique 2h ob_vc with 1.1.1 swept canon...")

records = []
for k, (key, sub) in enumerate(ob_groups):
    if k % 500 == 0 and k > 0:
        print(f"  {k:,} / {len(ob_groups):,}")
    direction, cur_open = key
    cur_open = int(cur_open)
    idx = bar_idx.get(cur_open)
    if idx is None or idx < 3: continue
    n2 = cans[idx-3]; n1 = cans[idx-2]; prev = cans[idx-1]; cur = cans[idx]

    # 1.1.1 swept canon
    if direction == "long":
        swept = min(prev.low, cur.low) < min(n1.low, n2.low)
        extreme = "prev" if prev.low < cur.low else "cur"
    else:
        swept = max(prev.high, cur.high) > max(n1.high, n2.high)
        extreme = "prev" if prev.high > cur.high else "cur"

    n_comp = len(sub)
    n_class = "≥2" if n_comp >= 2 else "1"
    t_id = TYPE_IDS.get((direction, swept, n_class, extreme))
    if t_id is None: continue

    # FVG pick (top for LONG, bottom for SHORT)
    if direction == "long":
        chosen = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
    else:
        chosen = sub.sort_values("fvg_zone_lo", ascending=True).iloc[0]

    out = tbm_one(direction, chosen.fvg_zone_lo, chosen.fvg_zone_hi,
                   chosen.drop_lo, chosen.drop_hi, n_comp, int(chosen.born_ms))
    out.update({"t_id": t_id, "direction": direction, "swept": swept,
                "extreme": extreme, "n_comp": n_comp})
    records.append(out)

rdf = pd.DataFrame(records)
print(f"  {len(rdf):,} / {len(ob_groups):,}  ✓\n")
rdf.to_parquet(pathlib.Path(__file__).parent.parent / "data/tbm_2h_swept_111.parquet", index=False)


# Counts per T
print(f"{'='*70}")
print(f"COUNTS per T1-T16 (1.1.1 swept canon)")
print(f"{'='*70}\n")
counts = rdf["t_id"].value_counts().sort_index(key=lambda x: x.str[1:].astype(int))
for t in [f"T{i}" for i in range(1, 17)]:
    n = counts.get(t, 0)
    g = rdf[rdf.t_id == t]
    n_touched = g["touched"].sum() if "touched" in g.columns else 0
    if n_touched > 0:
        tg = g[g.touched]
        wins = (tg.outcome == "win").sum()
        losses = (tg.outcome == "loss").sum()
        wr = wins / n_touched * 100 if n_touched else 0
        ev = (2 * wr / 100) - 1
        total = wins - losses
        print(f"  {t:<4} N={n:>4}  touch={n_touched:>4}  WR={wr:>5.1f}%  EV={ev:+.3f}R  Σ={total:+}R")
    else:
        print(f"  {t:<4} N={n:>4}")

print(f"\nElapsed: {time.time() - t0:.1f}s")
