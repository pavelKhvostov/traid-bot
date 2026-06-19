"""Triple-Barrier на 2h ob_vc, по T1-T16.

Entry rules:
  - n_FVG ≥2: 0.8 deep in top FVG (LONG) / bottom FVG (SHORT) — patient
  - n_FVG = 1: 0.2 deep in the only FVG — aggressive

SL = low_ob_vc (LONG) / high_ob_vc (SHORT) — no buffer.
R = |entry - SL|.
TPs: 1.0R / 1.5R / 2.0R / 2.5R / 3.0R.

Horizon: 14 days from touch (cap).

Outcomes per trade:
  - NO_TRADE   : entry not filled within OB lifetime + horizon
  - L          : SL hit first
  - W_1R / 1.5 / 2 / 2.5 / 3 : highest TP hit before SL

Result: per-type table {N, N_touched, WR_1R..WR_3R, avg_R, EV_R}.
"""
import sys, pathlib, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from bisect import bisect_left

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import load_1m, aggregate_all_tfs, to_candles, detect_williams_n2

MSK = timezone(timedelta(hours=3))
T0 = time.time()

# ─── Load 2h bars, FVGs from parquet ─────────────────────────
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = df[df.htf == "2h"].copy()

# Dedup 15m > 20m
g2h["has_15m"] = g2h.groupby(["direction", "ob_cur_open_ms"])["ltf"].transform(
    lambda x: "15m" in set(x))
mask = ((g2h.has_15m & (g2h.ltf == "15m")) | (~g2h.has_15m & (g2h.ltf == "20m")))
g2h_dedup = g2h[mask].copy()
print(f"Phase 1.5 rows: {len(g2h):,}  after 15m>20m dedup: {len(g2h_dedup):,}")

# Load TFs
print("Loading 1m & aggregating...")
rows = load_1m()
bars_all = aggregate_all_tfs(rows)
cans2h = to_candles(bars_all["2h"])
fhs2h, fls2h = detect_williams_n2(cans2h, n=2)
fls_ts = np.array([x[2] for x in fls2h]); fls_lvl = np.array([x[1] for x in fls2h])
fhs_ts = np.array([x[2] for x in fhs2h]); fhs_lvl = np.array([x[1] for x in fhs2h])
bar_idx = {c.open_time: i for i, c in enumerate(cans2h)}

# 1m as numpy arrays (precomputed for speed)
ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
h_1m = np.array([r[2] for r in rows], dtype=np.float64)
l_1m = np.array([r[3] for r in rows], dtype=np.float64)
print(f"1m bars: {len(ts_1m):,}")


def classify(direction, cur_open_ms, n_comp):
    idx = bar_idx.get(cur_open_ms)
    if idx is None or idx == 0:
        return None
    cur = cans2h[idx]; prev = cans2h[idx-1]
    # Extreme
    if direction == "long":
        extreme = "prev" if prev.low < cur.low else "cur"
    else:
        extreme = "prev" if prev.high > cur.high else "cur"
    # Sweep
    if direction == "long":
        i_lo = bisect_left(fls_ts, cur_open_ms)
        recent = fls_lvl[max(0, i_lo-5):i_lo]
        min_low = min(prev.low, cur.low)
        swept = bool((recent > min_low).any()) if len(recent) else False
    else:
        i_lo = bisect_left(fhs_ts, cur_open_ms)
        recent = fhs_lvl[max(0, i_lo-5):i_lo]
        max_high = max(prev.high, cur.high)
        swept = bool((recent < max_high).any()) if len(recent) else False
    n_class = "≥2" if n_comp >= 2 else "1"
    return (direction, swept, n_class, extreme), prev, cur


# T-ID mapping
TYPE_IDS = {
    ("long",  True,  "≥2", "prev"): "T1",
    ("long",  True,  "≥2", "cur"):  "T2",
    ("long",  True,  "1",  "prev"): "T3",
    ("long",  True,  "1",  "cur"):  "T4",
    ("long",  False, "≥2", "prev"): "T5",
    ("long",  False, "≥2", "cur"):  "T6",
    ("long",  False, "1",  "prev"): "T7",
    ("long",  False, "1",  "cur"):  "T8",
    ("short", True,  "≥2", "prev"): "T9",
    ("short", True,  "≥2", "cur"):  "T10",
    ("short", True,  "1",  "prev"): "T11",
    ("short", True,  "1",  "cur"):  "T12",
    ("short", False, "≥2", "prev"): "T13",
    ("short", False, "≥2", "cur"):  "T14",
    ("short", False, "1",  "prev"): "T15",
    ("short", False, "1",  "cur"):  "T16",
}

HORIZON_MS = 14 * 24 * 3600 * 1000  # 14 days


def tbm_one(direction, fvg_lo, fvg_hi, drop_lo, drop_hi, n_comp, born_ms):
    """Run TBM for single OB. Returns dict with outcome."""
    if direction == "long":
        # entry: 0.8 deep if n≥2, 0.2 deep if n=1
        deep = 0.8 if n_comp >= 2 else 0.2
        entry = fvg_hi - deep * (fvg_hi - fvg_lo)
        sl = drop_lo
        if entry <= sl: return {"touched": False, "reason": "entry_below_sl"}
        R = entry - sl
        tps = [(rr, entry + rr * R) for rr in (1.0, 1.5, 2.0, 2.5, 3.0)]

        # Touch: bar.low <= entry (LONG limit fill when price comes down)
        i_start = int(np.searchsorted(ts_1m, born_ms))
        if i_start >= len(ts_1m): return {"touched": False, "reason": "no_data"}
        i_end = int(np.searchsorted(ts_1m, born_ms + HORIZON_MS))
        i_end = min(i_end, len(ts_1m) - 1)

        # Vectorized: find first i where l_1m[i] <= entry in [i_start, i_end]
        slice_l = l_1m[i_start:i_end+1]
        touch_rel = np.argmax(slice_l <= entry) if (slice_l <= entry).any() else -1
        if touch_rel == -1:
            return {"touched": False, "reason": "no_touch"}
        touch_idx = i_start + touch_rel

        # After touch: scan forward to find SL or TPs
        post_h = h_1m[touch_idx:i_end+1]
        post_l = l_1m[touch_idx:i_end+1]
        # first SL hit
        sl_rel = np.argmax(post_l <= sl) if (post_l <= sl).any() else -1
        tp_rels = []
        for rr, lvl in tps:
            r = np.argmax(post_h >= lvl) if (post_h >= lvl).any() else -1
            tp_rels.append(r)
        # determine outcome: highest TP hit BEFORE SL
        highest_tp = None
        for (rr, lvl), tp_rel in zip(tps, tp_rels):
            if tp_rel == -1: continue
            if sl_rel == -1 or tp_rel <= sl_rel:
                highest_tp = rr
        if highest_tp is not None:
            return {"touched": True, "outcome": "win", "best_tp": highest_tp, "R": R}
        elif sl_rel != -1:
            return {"touched": True, "outcome": "loss", "best_tp": 0, "R": R}
        else:
            return {"touched": True, "outcome": "timeout", "best_tp": 0, "R": R}
    else:
        # SHORT — mirror
        deep = 0.8 if n_comp >= 2 else 0.2
        # For SHORT, FVG zone retest from below; entry = zone_lo + deep × width
        entry = fvg_lo + deep * (fvg_hi - fvg_lo)
        sl = drop_hi
        if entry >= sl: return {"touched": False, "reason": "entry_above_sl"}
        R = sl - entry
        tps = [(rr, entry - rr * R) for rr in (1.0, 1.5, 2.0, 2.5, 3.0)]

        i_start = int(np.searchsorted(ts_1m, born_ms))
        if i_start >= len(ts_1m): return {"touched": False, "reason": "no_data"}
        i_end = int(np.searchsorted(ts_1m, born_ms + HORIZON_MS))
        i_end = min(i_end, len(ts_1m) - 1)
        slice_h = h_1m[i_start:i_end+1]
        touch_rel = np.argmax(slice_h >= entry) if (slice_h >= entry).any() else -1
        if touch_rel == -1:
            return {"touched": False, "reason": "no_touch"}
        touch_idx = i_start + touch_rel
        post_h = h_1m[touch_idx:i_end+1]
        post_l = l_1m[touch_idx:i_end+1]
        sl_rel = np.argmax(post_h >= sl) if (post_h >= sl).any() else -1
        tp_rels = []
        for rr, lvl in tps:
            r = np.argmax(post_l <= lvl) if (post_l <= lvl).any() else -1
            tp_rels.append(r)
        highest_tp = None
        for (rr, lvl), tp_rel in zip(tps, tp_rels):
            if tp_rel == -1: continue
            if sl_rel == -1 or tp_rel <= sl_rel:
                highest_tp = rr
        if highest_tp is not None:
            return {"touched": True, "outcome": "win", "best_tp": highest_tp, "R": R}
        elif sl_rel != -1:
            return {"touched": True, "outcome": "loss", "best_tp": 0, "R": R}
        else:
            return {"touched": True, "outcome": "timeout", "best_tp": 0, "R": R}


# Aggregate by OB
print("\nProcessing OBs...")
ob_groups = g2h_dedup.groupby(["direction", "ob_cur_open_ms"])
print(f"Unique 2h OBs: {len(ob_groups):,}")

results = []
for k, (key, sub) in enumerate(ob_groups):
    if k % 500 == 0 and k > 0:
        print(f"  {k:,} / {len(ob_groups):,}")
    direction, cur_open_ms = key
    n_comp = len(sub)
    cls = classify(direction, int(cur_open_ms), n_comp)
    if cls is None: continue
    cls_key, prev, cur = cls
    t_id = TYPE_IDS.get(cls_key)
    if t_id is None: continue

    # Pick FVG for entry:
    # n=1: only 1 FVG
    # n≥2: top FVG (LONG: max zone_hi; SHORT: min zone_lo)
    if direction == "long":
        sub_sorted = sub.sort_values("fvg_zone_hi", ascending=False)
    else:
        sub_sorted = sub.sort_values("fvg_zone_lo", ascending=True)
    chosen = sub_sorted.iloc[0]
    fvg_lo = chosen.fvg_zone_lo; fvg_hi = chosen.fvg_zone_hi
    drop_lo = chosen.drop_lo; drop_hi = chosen.drop_hi
    born_ms = int(chosen.born_ms)

    out = tbm_one(direction, fvg_lo, fvg_hi, drop_lo, drop_hi, n_comp, born_ms)
    out.update({"t_id": t_id, "direction": direction, "n_comp": n_comp,
                "cur_open_ms": int(cur_open_ms)})
    results.append(out)

print(f"  {len(results):,} / {len(ob_groups):,}  ✓")

rdf = pd.DataFrame(results)
print(f"\nDataFrame shape: {rdf.shape}")
print(f"Touched: {rdf['touched'].sum():,}")
print(f"  - win:     {(rdf.outcome == 'win').sum():,}")
print(f"  - loss:    {(rdf.outcome == 'loss').sum():,}")
print(f"  - timeout: {(rdf.outcome == 'timeout').sum():,}")

rdf.to_parquet(pathlib.Path(__file__).parent.parent / "data/tbm_2h_per_ob.parquet",
                index=False)

# ─── Aggregate per T-ID ──────────────────────────────────────
print(f"\n{'='*100}")
print(f"PER-TYPE TBM RESULTS")
print(f"{'='*100}\n")
print(f"{'T-ID':<5} {'N':>5} {'Touch%':>7} {'W_1R%':>7} {'W_1.5R%':>8} "
      f"{'W_2R%':>7} {'W_2.5R%':>8} {'W_3R%':>7} {'Loss%':>7} {'avg_TP':>7} {'EV_R':>7}")
print("-" * 100)

# Per T-ID stats
for t in [f"T{i}" for i in range(1, 17)]:
    g = rdf[rdf.t_id == t]
    n = len(g)
    if n == 0:
        print(f"{t:<5} {'-':>5}")
        continue
    n_touched = g.touched.sum()
    touch_pct = n_touched / n * 100
    tg = g[g.touched]
    if len(tg) == 0:
        print(f"{t:<5} {n:>5} {touch_pct:>6.1f}%")
        continue
    # WR per TP-level: trade reached at least that R
    wins = {rr: ((tg.outcome == "win") & (tg.best_tp >= rr)).sum() for rr in (1.0,1.5,2.0,2.5,3.0)}
    losses = (tg.outcome == "loss").sum()
    timeouts = (tg.outcome == "timeout").sum()
    win_1 = wins[1.0]/n_touched*100
    win_15 = wins[1.5]/n_touched*100
    win_2 = wins[2.0]/n_touched*100
    win_25 = wins[2.5]/n_touched*100
    win_3 = wins[3.0]/n_touched*100
    loss_pct = losses/n_touched*100
    # average best_tp (only winners)
    avg_tp = tg[tg.outcome == "win"]["best_tp"].mean() if wins[1.0] else 0.0
    # EV in R: WR_1R × avg_tp_when_win + (1-WR-timeout) × (-1)
    p_win = win_1/100
    p_loss = loss_pct/100
    ev = p_win * avg_tp - p_loss * 1.0
    print(f"{t:<5} {n:>5,} {touch_pct:>6.1f}% {win_1:>6.1f}% {win_15:>7.1f}% "
          f"{win_2:>6.1f}% {win_25:>7.1f}% {win_3:>6.1f}% {loss_pct:>6.1f}% "
          f"{avg_tp:>6.2f}R {ev:>+6.2f}R")

print(f"\nElapsed: {time.time() - T0:.1f}s")
