"""Pred-12h fractal baseline: cascade F1 ∩ F2 ∩ F3.

Canon (per memory [[feedback-pred12h-window-and-noimp]]):
  - Window: 2020-01-01 → текущий момент (UTC)
  - Predict pivot bar i: будет ли Williams n=2 confirmation на right side
  - Strict causal: используем только {i-N..i, i+1, i+2} bars
  - Метрики: только n / conf / WR / Δ (без is_imp)

Pipeline:
  Pre-W : 3-bar local extreme (i.high > i-1.high, i-2.high)        for FH
          (mirror for FL)
  F1    : pivot.ext превосходит 5 левых баров (left_ext_5)
  F2    : (i.color ≠ i-1.color)  ∨  (i = i-1 = i-2 same color)     no doji
  F3    : body/range ≤ 0.80  ∧  relevant_wick/range ≥ 0.03

Output:
  - Console: n/conf/WR per stage
  - Parquet: ~/Desktop/pred12h_baseline_v2.parquet с колонками
    pivot_open_ts_ms, direction, confirmed, body_pct, wick_pct, color
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone
import numpy as np
import pandas as pd

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT = pathlib.Path.home() / "Desktop/pred12h_baseline_v2.parquet"

MS_M = 60_000
TF12 = 12 * 60 * MS_M
START = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

# Cascade parameters
LEFT_EXT_N = 5      # F1 window
SAME_COLOR_N = 3    # F2 second condition window
BODY_MAX = 0.80     # F3 body/range max
WICK_MIN = 0.03     # F3 relevant wick min
DOJI_EPS = 0.0      # color tie threshold (close == open)

# ─── Load 1m → 12h ─────────────────────────────────────────────
print(f"START:  2020-01-01 00:00 UTC")
print(f"END:    {datetime.fromtimestamp(END/1000, timezone.utc):%Y-%m-%d %H:%M UTC}")
print(f"Loading 1m: {CSV.name}")

ts1m, o1m, h1m, l1m, c1m = [], [], [], [], []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if t < START or t > END: continue
        ts1m.append(t); o1m.append(float(r[1])); h1m.append(float(r[2]))
        l1m.append(float(r[3])); c1m.append(float(r[4]))
print(f"  1m bars in window: {len(ts1m):,}")

# Aggregate to 12h (anchor at epoch — same as canon F1-F3)
def agg_12h(ts, o, h, l, c):
    bars = []
    cur_b = None; oo = hh = ll = cc = 0.0
    for i in range(len(ts)):
        b = ts[i] - (ts[i] % TF12)
        if b != cur_b:
            if cur_b is not None:
                bars.append((cur_b, oo, hh, ll, cc))
            cur_b = b; oo = o[i]; hh = h[i]; ll = l[i]; cc = c[i]
        else:
            hh = max(hh, h[i]); ll = min(ll, l[i]); cc = c[i]
    if cur_b is not None:
        bars.append((cur_b, oo, hh, ll, cc))
    return bars


bars = agg_12h(ts1m, o1m, h1m, l1m, c1m)
n = len(bars)
t12 = np.array([b[0] for b in bars], dtype=np.int64)
o12 = np.array([b[1] for b in bars])
h12 = np.array([b[2] for b in bars])
l12 = np.array([b[3] for b in bars])
c12 = np.array([b[4] for b in bars])
print(f"  12h bars: {n:,}")

# ─── Pre-computed derived arrays ──────────────────────────────
body = np.abs(c12 - o12)
rng  = h12 - l12
# Upper / lower wick
upper_wick = h12 - np.maximum(o12, c12)
lower_wick = np.minimum(o12, c12) - l12
# Color: +1 bullish, -1 bearish, 0 doji
color = np.where(c12 > o12, 1, np.where(c12 < o12, -1, 0))

# Williams n=2 confirmation flag (computable when i + 2 < n)
def williams_confirm(i, direction):
    """Has Williams n=2 right-side confirmation."""
    if i + 2 >= n: return False
    if direction == "high":
        return h12[i+1] < h12[i] and h12[i+2] < h12[i]
    return l12[i+1] > l12[i] and l12[i+2] > l12[i]


# ─── Pre-W: 3-bar local extreme ───────────────────────────────
# FH candidate: h[i] > h[i-1] AND h[i] > h[i-2]
# FL candidate: l[i] < l[i-1] AND l[i] < l[i-2]
fh_prew = np.zeros(n, dtype=bool)
fl_prew = np.zeros(n, dtype=bool)
fh_prew[2:] = (h12[2:] > h12[1:-1]) & (h12[2:] > h12[:-2])
fl_prew[2:] = (l12[2:] < l12[1:-1]) & (l12[2:] < l12[:-2])

# ─── F1: left_ext_N (vectorized) ──────────────────────────────
# For each i, check h[i] > max(h[i-1..i-N]) for FH; mirror for FL.
left_max_h = np.full(n, -np.inf)
left_min_l = np.full(n,  np.inf)
for i in range(LEFT_EXT_N, n):
    left_max_h[i] = h12[i - LEFT_EXT_N:i].max()
    left_min_l[i] = l12[i - LEFT_EXT_N:i].min()

fh_f1 = fh_prew & (h12 > left_max_h)
fl_f1 = fl_prew & (l12 < left_min_l)

# ─── F2: opp_colors  ∨  three_same  (no doji) ─────────────────
non_doji = (color != 0)

# A) opp_colors at i (vs i-1)
opp_colors = np.zeros(n, dtype=bool)
opp_colors[1:] = non_doji[1:] & non_doji[:-1] & (color[1:] != color[:-1])

# B) three_same: i = i-1 = i-2 same color (all non-doji)
three_same = np.zeros(n, dtype=bool)
three_same[2:] = (
    non_doji[2:] & non_doji[1:-1] & non_doji[:-2]
    & (color[2:] == color[1:-1]) & (color[1:-1] == color[:-2])
)

f2_pass = opp_colors | three_same
fh_f2 = fh_f1 & f2_pass
fl_f2 = fl_f1 & f2_pass

# ─── F3: body+wick form (per-direction wick) ──────────────────
# Avoid divide-by-zero
safe_rng = np.where(rng > 0, rng, 1.0)
body_pct = body / safe_rng
upper_wick_pct = upper_wick / safe_rng
lower_wick_pct = lower_wick / safe_rng

fh_f3 = fh_f2 & (rng > 0) & (body_pct <= BODY_MAX) & (upper_wick_pct >= WICK_MIN)
fl_f3 = fl_f2 & (rng > 0) & (body_pct <= BODY_MAX) & (lower_wick_pct >= WICK_MIN)

# ─── Confirmation (Williams n=2) — vectorized for ALL bars ────
# fh_conf[i] = h[i] > h[i+1] AND h[i] > h[i+2]
# fl_conf[i] = l[i] < l[i+1] AND l[i] < l[i+2]
fh_conf = np.zeros(n, dtype=bool)
fl_conf = np.zeros(n, dtype=bool)
fh_conf[:-2] = (h12[:-2] > h12[1:-1]) & (h12[:-2] > h12[2:])
fl_conf[:-2] = (l12[:-2] < l12[1:-1]) & (l12[:-2] < l12[2:])

# ─── Reporting ────────────────────────────────────────────────
def stats(mask_fh, mask_fl, mask_fh_conf=None, mask_fl_conf=None):
    n_fh = int(mask_fh.sum()); n_fl = int(mask_fl.sum())
    total_n = n_fh + n_fl
    if mask_fh_conf is None: return total_n, n_fh, n_fl, None, None, None
    c_fh = int((mask_fh & mask_fh_conf).sum())
    c_fl = int((mask_fl & mask_fl_conf).sum())
    total_c = c_fh + c_fl
    wr = 100 * total_c / total_n if total_n else 0
    return total_n, n_fh, n_fl, total_c, c_fh, c_fl, wr


print("\n" + "="*78)
print("F1 ∩ F2 ∩ F3 — Cascade results")
print("="*78)
print(f"  {'Stage':<10} {'n':>7} {'FH':>6} {'FL':>6}  {'conf':>5}  {'WR':>6}")
for name, mfh, mfl in [
    ("Pre-W",  fh_prew, fl_prew),
    ("F1",     fh_f1, fl_f1),
    ("F2",     fh_f2, fl_f2),
    ("F3",     fh_f3, fl_f3),
]:
    n_h = int(mfh.sum()); n_l = int(mfl.sum())
    n_total = n_h + n_l
    c_h = int((mfh & fh_conf).sum()); c_l = int((mfl & fl_conf).sum())
    c_total = c_h + c_l
    wr = 100 * c_total / n_total if n_total else 0
    print(f"  {name:<10} {n_total:>7,} {n_h:>6,} {n_l:>6,}  {c_total:>5,} {wr:>5.2f}%")

# Final baseline P(W)
n_baseline = int(fh_f3.sum() + fl_f3.sum())
c_fh = int((fh_f3 & fh_conf).sum()); c_fl = int((fl_f3 & fl_conf).sum())
c_baseline = c_fh + c_fl
wr_baseline = 100 * c_baseline / n_baseline if n_baseline else 0.0

# Also account for pivots without right confirmation window (last 2 bars):
# they cannot be confirmed. Report them separately so WR is on confirmable subset.
mask_confirmable = np.arange(n) < (n - 2)
n_confirmable_fh = int((fh_f3 & mask_confirmable).sum())
n_confirmable_fl = int((fl_f3 & mask_confirmable).sum())
n_confirmable = n_confirmable_fh + n_confirmable_fl
wr_confirmable = 100 * c_baseline / n_confirmable if n_confirmable else 0.0

print()
print("="*70)
print(f"BASELINE F1 ∩ F2 ∩ F3")
print("="*70)
print(f"  n total:           {n_baseline:>6,}   (FH {int(fh_f3.sum())}, FL {int(fl_f3.sum())})")
print(f"  n confirmable:     {n_confirmable:>6,}   (исключены последние 2 бара)")
print(f"  conf (Williams):   {c_baseline:>6,}   (FH {c_fh}, FL {c_fl})")
print(f"  WR / P(W):         {wr_confirmable:>6.2f}%  ← на confirmable")
print(f"  WR including right-edge: {wr_baseline:>6.2f}%")

# ─── Save parquet ─────────────────────────────────────────────
rows = []
for i in range(n):
    if fh_f3[i]:
        rows.append({
            "pivot_open_ts_ms": int(t12[i]),
            "direction": "high",
            "confirmable": bool(mask_confirmable[i]),
            "confirmed": bool(fh_conf[i]),
            "body_pct": float(body_pct[i]),
            "wick_pct": float(upper_wick_pct[i]),
            "color": int(color[i]),
        })
    if fl_f3[i]:
        rows.append({
            "pivot_open_ts_ms": int(t12[i]),
            "direction": "low",
            "confirmable": bool(mask_confirmable[i]),
            "confirmed": bool(fl_conf[i]),
            "body_pct": float(body_pct[i]),
            "wick_pct": float(lower_wick_pct[i]),
            "color": int(color[i]),
        })

df = pd.DataFrame(rows)
df.to_parquet(OUT, index=False)
print(f"\nSaved parquet: {OUT}  ({len(df):,} rows)")
