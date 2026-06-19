"""Wick features research для 8 a-suffix типов.

Computes per setup:
  F1 = prev_wick / |prev.close - prev.open|    (prev wick-to-body)
  F2 = cur_wick  / |cur.close  - cur.open|     (cur wick-to-body)
  F3 = prev_wick / cur.low × 100               (prev wick as % of price)
  F4 = cur_wick  / cur.low × 100               (cur wick as % of price)

For each setup, runs TBM under 3 rules:
  R_NEW:  Entry = cur.low, SL = prev.low
  R_MOVE: as NEW but with R% floor at 0.5%
  R_OLD:  Entry = 0.8/0.2 deep top FVG, SL = drop_lo (= prev.low for extreme=prev)

Then bins by F3 quartiles and reports WR/EV/Σ R per bin per rule.
Цель: найти threshold за пределы которого one rule dominates.
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
prev_types_idx = [
    ("long", True, "≥2"), ("long", True, "1"),
    ("long", False, "≥2"), ("long", False, "1"),
    ("short", True, "≥2"), ("short", True, "1"),
    ("short", False, "≥2"), ("short", False, "1"),
]

HORIZON_MS = 14 * 24 * 3600 * 1000
R_PCT_MIN = 0.005


def wick_ratio(direction, prev, cur, EPS=0.01):
    if direction == "long":
        pw = min(prev.open, prev.close) - prev.low
        cw = min(cur.open, cur.close) - cur.low
    else:
        pw = prev.high - max(prev.open, prev.close)
        cw = cur.high - max(cur.open, cur.close)
    return (pw, cw, (float("inf") if cw < EPS else pw / cw))


def tbm_long(entry, sl, born_ms):
    if entry <= sl: return None
    R = entry - sl
    TP1 = entry + R
    i_start = int(np.searchsorted(ts_1m, born_ms))
    if i_start >= len(ts_1m): return None
    i_end = min(len(ts_1m)-1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS)))
    slice_l = l_1m[i_start:i_end+1]
    touch_rel = int(np.argmax(slice_l <= entry)) if (slice_l <= entry).any() else -1
    if touch_rel == -1: return {"touched": False, "R_pct": R/entry*100}
    ti = i_start + touch_rel
    post_h = h_1m[ti:i_end+1]; post_l = l_1m[ti:i_end+1]
    tp1_rel = int(np.argmax(post_h >= TP1)) if (post_h >= TP1).any() else -1
    sl_rel = int(np.argmax(post_l <= sl)) if (post_l <= sl).any() else -1
    if tp1_rel != -1 and (sl_rel == -1 or tp1_rel <= sl_rel):
        outcome = "win"
    elif sl_rel != -1:
        outcome = "loss"
    else:
        outcome = "timeout"
    return {"touched": True, "outcome": outcome, "R_pct": R/entry*100}


def tbm_short(entry, sl, born_ms):
    if entry >= sl: return None
    R = sl - entry
    TP1 = entry - R
    i_start = int(np.searchsorted(ts_1m, born_ms))
    if i_start >= len(ts_1m): return None
    i_end = min(len(ts_1m)-1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS)))
    slice_h = h_1m[i_start:i_end+1]
    touch_rel = int(np.argmax(slice_h >= entry)) if (slice_h >= entry).any() else -1
    if touch_rel == -1: return {"touched": False, "R_pct": R/entry*100}
    ti = i_start + touch_rel
    post_h = h_1m[ti:i_end+1]; post_l = l_1m[ti:i_end+1]
    tp1_rel = int(np.argmax(post_l <= TP1)) if (post_l <= TP1).any() else -1
    sl_rel = int(np.argmax(post_h >= sl)) if (post_h >= sl).any() else -1
    if tp1_rel != -1 and (sl_rel == -1 or tp1_rel <= sl_rel):
        outcome = "win"
    elif sl_rel != -1:
        outcome = "loss"
    else:
        outcome = "timeout"
    return {"touched": True, "outcome": outcome, "R_pct": R/entry*100}


records = []
for k, (key, sub) in enumerate(g2h.groupby(["direction", "ob_cur_open_ms"])):
    direction, cur_open = key
    cur_open = int(cur_open)
    idx = bar_idx.get(cur_open)
    if idx is None or idx < 3: continue
    n2c=cans[idx-3]; n1c=cans[idx-2]; prev=cans[idx-1]; cur=cans[idx]

    # SWEPT?
    if direction == "long":
        swept = min(prev.low,cur.low) < min(n1c.low,n2c.low)
        extreme = "prev" if prev.low < cur.low else "cur"
    else:
        swept = max(prev.high,cur.high) > max(n1c.high,n2c.high)
        extreme = "prev" if prev.high > cur.high else "cur"

    if extreme != "prev": continue   # only extreme=prev
    pw, cw, ratio = wick_ratio(direction, prev, cur)
    if ratio < 2.0: continue          # only a-suffix (ratio ≥ 2×)

    n_comp = len(sub); n_class = "≥2" if n_comp >= 2 else "1"
    found_idx = None
    for i, (d, sw, nc) in enumerate(prev_types_idx):
        if d == direction and sw == swept and nc == n_class:
            found_idx = i; break
    if found_idx is None: continue
    t_id = ORIG_PREV[found_idx] + "a"

    # Features
    prev_body = abs(prev.close - prev.open)
    cur_body = abs(cur.close - cur.open)
    F1 = pw / prev_body if prev_body > 0.01 else 10.0
    F2 = cw / cur_body if cur_body > 0.01 else 10.0
    ref_price = cur.low if direction == "long" else cur.high
    F3 = pw / ref_price * 100
    F4 = cw / ref_price * 100

    chosen = sub.iloc[0]; born = int(chosen.born_ms)

    # NEW rule
    if direction == "long":
        sl_new = prev.low; entry_new = cur.low
        out_new = tbm_long(entry_new, sl_new, born)
    else:
        sl_new = prev.high; entry_new = cur.high
        out_new = tbm_short(entry_new, sl_new, born)

    # MOVE rule
    raw_R_pct = abs(entry_new - sl_new) / entry_new
    if raw_R_pct >= R_PCT_MIN:
        entry_move = entry_new; sl_move = sl_new
    else:
        if direction == "long":
            sl_move = prev.low; entry_move = sl_move / (1 - R_PCT_MIN)
        else:
            sl_move = prev.high; entry_move = sl_move / (1 + R_PCT_MIN)
    if direction == "long":
        out_move = tbm_long(entry_move, sl_move, born)
    else:
        out_move = tbm_short(entry_move, sl_move, born)

    # OLD rule
    if direction == "long":
        chosen_f = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
        deep = 0.8 if n_comp >= 2 else 0.2
        entry_old = chosen_f.fvg_zone_hi - deep * (chosen_f.fvg_zone_hi - chosen_f.fvg_zone_lo)
        sl_old = chosen_f.drop_lo
        out_old = tbm_long(entry_old, sl_old, born)
    else:
        chosen_f = sub.sort_values("fvg_zone_lo", ascending=True).iloc[0]
        deep = 0.8 if n_comp >= 2 else 0.2
        entry_old = chosen_f.fvg_zone_lo + deep * (chosen_f.fvg_zone_hi - chosen_f.fvg_zone_lo)
        sl_old = chosen_f.drop_hi
        out_old = tbm_short(entry_old, sl_old, born)

    def outcome_R(o):
        if o is None: return None
        if not o.get("touched", False): return 0  # no_trade
        if o["outcome"] == "win": return 1
        if o["outcome"] == "loss": return -1
        return 0

    records.append({
        "t_id": t_id, "direction": direction,
        "F1_pw_body": F1, "F2_cw_body": F2,
        "F3_pw_pct": F3, "F4_cw_pct": F4,
        "ratio": ratio,
        "R_NEW": outcome_R(out_new), "Rpct_NEW": out_new.get("R_pct",0) if out_new else 0,
        "R_MOVE": outcome_R(out_move), "Rpct_MOVE": out_move.get("R_pct",0) if out_move else 0,
        "R_OLD": outcome_R(out_old), "Rpct_OLD": out_old.get("R_pct",0) if out_old else 0,
        "touched_NEW": out_new.get("touched", False) if out_new else False,
        "touched_MOVE": out_move.get("touched", False) if out_move else False,
        "touched_OLD": out_old.get("touched", False) if out_old else False,
    })

rdf = pd.DataFrame(records)
print(f"a-suffix setups processed: {len(rdf):,}\n")

# Save raw data
rdf.to_parquet(pathlib.Path(__file__).parent.parent / "data/wick_features_research.parquet", index=False)

# =========== Feature distributions ===========
print("="*78)
print("Feature distributions per type")
print("="*78)
for t in [f"T{i}a" for i in (1,3,5,7,9,11,13,15)]:
    g = rdf[rdf.t_id == t]
    if len(g) == 0: continue
    print(f"\n{t}:  N={len(g)}")
    print(f"  F1 prev_wick/body: median={g.F1_pw_body.median():.2f}, q25={g.F1_pw_body.quantile(0.25):.2f}, q75={g.F1_pw_body.quantile(0.75):.2f}")
    print(f"  F2 cur_wick/body : median={g.F2_cw_body.median():.2f}, q25={g.F2_cw_body.quantile(0.25):.2f}, q75={g.F2_cw_body.quantile(0.75):.2f}")
    print(f"  F3 prev_wick %   : median={g.F3_pw_pct.median():.2f}%, q25={g.F3_pw_pct.quantile(0.25):.2f}%, q75={g.F3_pw_pct.quantile(0.75):.2f}%")
    print(f"  F4 cur_wick  %   : median={g.F4_cw_pct.median():.2f}%, q25={g.F4_cw_pct.quantile(0.25):.2f}%, q75={g.F4_cw_pct.quantile(0.75):.2f}%")

# =========== F3 (absolute prev wick %) — key feature ===========
print("\n" + "="*78)
print("Binned by F3 (prev_wick as % of price) — quartile bins per type")
print("="*78)
for t in [f"T{i}a" for i in (1,3,5,7,9,11,13,15)]:
    g = rdf[rdf.t_id == t].copy()
    if len(g) < 20: continue
    qs = np.quantile(g.F3_pw_pct, [0.25, 0.5, 0.75])
    g["bin"] = pd.cut(g.F3_pw_pct, bins=[-np.inf, qs[0], qs[1], qs[2], np.inf],
                       labels=["Q1_low","Q2","Q3","Q4_high"])
    print(f"\n{t}  N={len(g)}  F3 quartiles: <{qs[0]:.2f}% | {qs[0]:.2f}-{qs[1]:.2f}% | {qs[1]:.2f}-{qs[2]:.2f}% | >{qs[2]:.2f}%")
    print(f"  {'Bin':<10} {'N':>4} {'NEW WR':>8} {'NEW ΣR':>8} {'MOVE WR':>9} {'MOVE ΣR':>9} {'OLD WR':>8} {'OLD ΣR':>8}")
    for bin_name in ["Q1_low","Q2","Q3","Q4_high"]:
        gb = g[g.bin == bin_name]
        n = len(gb)
        if n == 0: continue
        # NEW
        nt_new = gb.touched_NEW.sum()
        win_new = (gb.R_NEW == 1).sum(); loss_new = (gb.R_NEW == -1).sum()
        wr_new = win_new/nt_new*100 if nt_new else 0
        # MOVE
        nt_move = gb.touched_MOVE.sum()
        win_move = (gb.R_MOVE == 1).sum(); loss_move = (gb.R_MOVE == -1).sum()
        wr_move = win_move/nt_move*100 if nt_move else 0
        # OLD
        nt_old = gb.touched_OLD.sum()
        win_old = (gb.R_OLD == 1).sum(); loss_old = (gb.R_OLD == -1).sum()
        wr_old = win_old/nt_old*100 if nt_old else 0
        print(f"  {bin_name:<10} {n:>4} {wr_new:>7.1f}% {win_new-loss_new:>+7}R {wr_move:>8.1f}% {win_move-loss_move:>+8}R {wr_old:>7.1f}% {win_old-loss_old:>+7}R")

print(f"\nElapsed: {time.time()-t0:.1f}s")
print("Data saved → data/wick_features_research.parquet")
