"""Полное 2D исследование a-suffix (LONG + SHORT) с R% ≥ 0.5%.

Default rules:
  LONG:  SL = prev.low,  Entry = cur.low
  SHORT: SL = prev.high, Entry = cur.high

Filter:
  prev_wick ≥ 2× cur_wick (a-suffix)
  |cur edge − prev edge| / cur edge ≥ 0.5%

Features:
  F1 = prev_wick / prev_body
  F3 = prev_wick / cur edge × 100  (% от цены)

Outputs:
  1) 2D quartile matrix per direction (WR, Σ R)
  2) Filter rule test: «tight clean» OR «deep sweep»
  3) Per-type breakdown
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

ORIG_PREV = {0:"T1", 1:"T3", 2:"T5", 3:"T7", 4:"T9", 5:"T11", 6:"T13", 7:"T15"}
prev_types_idx = [
    ("long", True, "≥2"), ("long", True, "1"),
    ("long", False, "≥2"), ("long", False, "1"),
    ("short", True, "≥2"), ("short", True, "1"),
    ("short", False, "≥2"), ("short", False, "1"),
]


def tbm(entry, sl, born_ms, direction):
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
        if not (prev.low < cur.low): continue
        if not (min(prev.low,cur.low) < min(n1c.low,n2c.low)): continue
        pw = min(prev.open, prev.close) - prev.low
        cw = min(cur.open, cur.close) - cur.low
        ref_price = cur.low
        sl = prev.low; entry = cur.low
        raw_R_pct = (entry - sl) / entry * 100
    else:
        if not (prev.high > cur.high): continue
        if not (max(prev.high,cur.high) > max(n1c.high,n2c.high)): continue
        pw = prev.high - max(prev.open, prev.close)
        cw = cur.high - max(cur.open, cur.close)
        ref_price = cur.high
        sl = prev.high; entry = cur.high
        raw_R_pct = (sl - entry) / entry * 100

    if cw < 0.01: continue
    if pw / cw < 2.0: continue
    if raw_R_pct < 0.5: continue

    prev_body = abs(prev.close - prev.open)
    F1 = pw / prev_body if prev_body > 0.01 else 999
    F3 = pw / ref_price * 100

    n_comp = len(sub); n_class = "≥2" if n_comp >= 2 else "1"
    swept_long = direction == "long"
    found_idx = None
    for i, (d, sw, nc) in enumerate(prev_types_idx):
        if d == direction and nc == n_class:
            # also check swept
            if direction == "long":
                if sw == (min(prev.low,cur.low) < min(n1c.low,n2c.low)):
                    found_idx = i; break
            else:
                if sw == (max(prev.high,cur.high) > max(n1c.high,n2c.high)):
                    found_idx = i; break
    t_id = ORIG_PREV[found_idx] + "a" if found_idx is not None else "?a"

    chosen = sub.iloc[0]; born = int(chosen.born_ms)
    out = tbm(entry, sl, born, direction)
    if out is None: continue
    r_out = None
    if out.get("touched", False):
        r_out = 1 if out["outcome"] == "win" else (-1 if out["outcome"] == "loss" else 0)

    records.append({
        "t_id": t_id, "direction": direction,
        "F1": F1, "F3": F3, "R_pct": raw_R_pct,
        "touched": out.get("touched", False),
        "R": r_out,
    })

rdf = pd.DataFrame(records)
print(f"a-suffix setups с R% ≥ 0.5%: {len(rdf):,}  (LONG {(rdf.direction=='long').sum()} + SHORT {(rdf.direction=='short').sum()})")
print(f"\nBaseline NEW rule (all 175 = no filter):")
nt = rdf.touched.sum()
wins = (rdf.R == 1).sum(); losses = (rdf.R == -1).sum()
wr = wins/nt*100 if nt else 0
print(f"  N={len(rdf)}  touch={nt}  WR={wr:.1f}%  Σ={wins-losses:+}R")
rdf.to_parquet(pathlib.Path(__file__).parent.parent / "data/research_2d_final.parquet", index=False)

# ─── 2D quartile matrix per direction ───
for d in ["long", "short"]:
    sub = rdf[rdf.direction == d]
    if len(sub) < 30: continue
    f1q = sub.F1.quantile([0.25, 0.5, 0.75]).values
    f3q = sub.F3.quantile([0.25, 0.5, 0.75]).values
    print(f"\n{'='*78}")
    print(f"{d.upper()} 2D matrix  (N={len(sub)})")
    print(f"  F1 bins: ≤{f1q[0]:.2f} | {f1q[0]:.2f}-{f1q[1]:.2f} | {f1q[1]:.2f}-{f1q[2]:.2f} | >{f1q[2]:.2f}")
    print(f"  F3 bins: ≤{f3q[0]:.2f}% | {f3q[0]:.2f}-{f3q[1]:.2f}% | {f3q[1]:.2f}-{f3q[2]:.2f}% | >{f3q[2]:.2f}%")
    print(f"{'='*78}")
    sub = sub.copy()
    sub["F1b"] = pd.cut(sub.F1, [-np.inf, f1q[0], f1q[1], f1q[2], np.inf], labels=["F1_low","F1_q2","F1_q3","F1_hi"])
    sub["F3b"] = pd.cut(sub.F3, [-np.inf, f3q[0], f3q[1], f3q[2], np.inf], labels=["F3_low","F3_q2","F3_q3","F3_hi"])
    print(f"\n{'F1\\F3':<10} {'F3_low':>16} {'F3_q2':>16} {'F3_q3':>16} {'F3_hi':>16}")
    for f1b in ["F1_low","F1_q2","F1_q3","F1_hi"]:
        cells = []
        for f3b in ["F3_low","F3_q2","F3_q3","F3_hi"]:
            g = sub[(sub.F1b == f1b) & (sub.F3b == f3b)]
            if len(g) == 0: cells.append(f"{'-':>16}"); continue
            n = len(g); nt = g.touched.sum()
            w = (g.R == 1).sum(); l = (g.R == -1).sum()
            wr = w/nt*100 if nt else 0
            cells.append(f"N={n:>2} WR{wr:>4.0f}% Σ{w-l:>+3}")
        print(f"{f1b:<10} {cells[0]:>16} {cells[1]:>16} {cells[2]:>16} {cells[3]:>16}")

# ─── Proposed filter test ───
print(f"\n{'='*78}")
print(f"FILTER TEST: «tight clean» OR «deep sweep»")
print(f"{'='*78}")
# Use LONG quartiles as reference (similar for SHORT)
f1q = rdf[rdf.direction=='long'].F1.quantile([0.25]).values[0]
f3q_low = rdf[rdf.direction=='long'].F3.quantile([0.25]).values[0]
f3q_hi  = rdf[rdf.direction=='long'].F3.quantile([0.75]).values[0]

filtered = rdf[((rdf.F1 <= f1q) & (rdf.F3 <= f3q_low)) | (rdf.F3 > f3q_hi)]
nt = filtered.touched.sum()
wins = (filtered.R == 1).sum(); losses = (filtered.R == -1).sum()
wr = wins/nt*100 if nt else 0
print(f"Rule: (F1 ≤ {f1q:.2f} AND F3 ≤ {f3q_low:.2f}%)  OR  F3 > {f3q_hi:.2f}%")
print(f"Result: N={len(filtered)}  touch={nt}  WR={wr:.1f}%  Σ={wins-losses:+}R")

# Compare: raw vs filtered
raw_total = (rdf.R == 1).sum() - (rdf.R == -1).sum()
filt_total = (filtered.R == 1).sum() - (filtered.R == -1).sum()
print(f"\nComparison:")
print(f"  Raw (no filter): N={len(rdf)}  Σ={raw_total:+}R  WR={(rdf.R==1).sum()/rdf.touched.sum()*100:.1f}%")
print(f"  Filtered:        N={len(filtered)}  Σ={filt_total:+}R  WR={wr:.1f}%")
print(f"  Per-trade EV:")
print(f"    Raw:      {raw_total/len(rdf):.3f}R / trade")
print(f"    Filtered: {filt_total/len(filtered):.3f}R / trade  ({(filt_total/len(filtered))/(raw_total/len(rdf)):.1f}x density)")

# ─── Per-type ───
print(f"\nPer-type Σ R под NEW rule с R% ≥ 0.5%:")
print(f"{'T':<5} {'N':>4} {'touch':>5} {'WR':>6} {'Σ R':>6} {'F3_med':>8}")
for t in [f"T{i}a" for i in (1,3,5,7,9,11,13,15)]:
    g = rdf[rdf.t_id == t]
    if len(g) == 0: continue
    nt = g.touched.sum(); w = (g.R == 1).sum(); l = (g.R == -1).sum()
    wr = w/nt*100 if nt else 0
    print(f"{t:<5} {len(g):>4} {nt:>5} {wr:>5.1f}% {w-l:>+5}R {g.F3.median():>7.2f}%")

print(f"\nElapsed: {time.time()-t0:.1f}s")
