"""F2 alternative candidates — без zone interaction.

Кандидаты (все causal at i.close):
  A. D_trend_match (FH в D-uptrend / FL в D-downtrend по EMA20)
  B. D_left_ext_3 (pivot.level extreme на 3 D-bars влево)
  C. D_left_ext_5
  D. Pivot wick rejection (relevant wick ≥ 40% от range)
  E. Pivot body large (body ≥ 50% range = decisive momentum bar)
  F. Vol spike (pivot.vol > 1.3× SMA20)
  G. Range expansion (pivot.range > 1.3× ATR20)
  H. Approach run 3 (3 same-color bars before pivot ending at i)
  I. Sweep of prior HTF fractal level on pivot bar
  J. Distance from prev same-type fractal > N bars OR > X%
  K. Pivot.level совпадает с HTF FH/FL ±X% (confluence)
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.fractal.code import detect_fractal

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_HOUR = 3600_000
TF12_MS = 12 * MS_HOUR
TF_D_MS = 24 * MS_HOUR
TF_2D_MS = 48 * MS_HOUR
TF_3D_MS = 72 * MS_HOUR
TF_W_MS = 7 * 24 * MS_HOUR
START_MS = int(datetime(2026, 2, 4, 0, 0, tzinfo=MSK).timestamp() * 1000)
IMPORTANT = {1, 3, 4, 5, 9, 10, 11, 14, 15, 20, 23, 26, 29, 40, 41, 42, 47, 48}


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000),
                         float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate(d, tf_ms):
    out = []; cb = None; o = h = l = c = v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


def aggregate_weekly_mon(d):
    week_ms = 7 * 24 * 3600 * 1000
    mon_anchor = 1483315200000
    out = []; cb = None; o = h = l = c = v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        offset = (ts - mon_anchor) % week_ms
        b = ts - offset
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


print("Loading...")
data = load_1m()
bars12 = aggregate(data, TF12_MS)
barsD = aggregate(data, TF_D_MS)
bars2D = aggregate(data, TF_2D_MS)
bars3D = aggregate(data, TF_3D_MS)
barsW = aggregate_weekly_mon(data)

# 12h arrays
hi12 = np.array([b[2] for b in bars12])
lo12 = np.array([b[3] for b in bars12])
cl12 = np.array([b[4] for b in bars12])
vol12 = np.array([b[5] for b in bars12])
prev_cl = np.concatenate([[cl12[0]], cl12[:-1]])
tr12 = np.maximum.reduce([hi12 - lo12, np.abs(hi12 - prev_cl), np.abs(lo12 - prev_cl)])
atr20 = np.zeros_like(tr12)
for i in range(len(tr12)):
    atr20[i] = tr12[:i+1].mean() if i < 19 else tr12[i-19:i+1].mean()
volsma20 = np.zeros_like(vol12)
for i in range(len(vol12)):
    volsma20[i] = vol12[:i+1].mean() if i < 19 else vol12[i-19:i+1].mean()

# D arrays + EMA20
clD = np.array([b[4] for b in barsD])
emaD20 = np.zeros_like(clD)
alpha = 2 / 21
emaD20[0] = clD[0]
for i in range(1, len(clD)):
    emaD20[i] = alpha * clD[i] + (1 - alpha) * emaD20[i-1]


# Detect 12h fractals
candles12 = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars12]
fractals = []
for i in range(2, len(candles12) - 2):
    f = detect_fractal(candles12[i-2:i+3], n=2)
    if f is None: continue
    if candles12[i].open_time < START_MS: continue
    fractals.append({"dir": f.direction, "level": f.level, "idx": i,
                     "center_ts": candles12[i].open_time})


def left_ext_5(f):
    bidx = f["idx"]
    win_lo = max(0, bidx - 5); win_hi = bidx
    slice_ = bars12[win_lo:win_hi]
    if not slice_: return True
    if f["dir"] == "high":
        return f["level"] > max(b[2] for b in slice_)
    else:
        return f["level"] < min(b[3] for b in slice_)


for n, f in enumerate(fractals, 1):
    f["num"] = n
    f["is_important"] = (n in IMPORTANT)
    f["F1_pass"] = left_ext_5(f)


# === Compute alternative features ===
for f in fractals:
    bidx = f["idx"]
    b = bars12[bidx]
    o, h_, l_, c_, v = b[1], b[2], b[3], b[4], b[5]
    rng = h_ - l_ if h_ > l_ else 1e-9

    # Anatomy
    if f["dir"] == "high":
        rel_wick = h_ - max(o, c_)
    else:
        rel_wick = min(o, c_) - l_
    body = abs(c_ - o)
    f["wick_pct"] = rel_wick / rng
    f["body_pct"] = body / rng
    f["range_atr"] = rng / max(atr20[bidx], 1e-9)
    f["vol_rel"] = v / max(volsma20[bidx], 1e-9)

    # D trend
    di = next((j for j, bd in enumerate(barsD) if bd[0] + TF_D_MS > f["center_ts"]), len(barsD)) - 1
    if di >= 0 and di < len(emaD20):
        f["d_close"] = clD[di]
        f["d_ema"] = emaD20[di]
        f["d_above_ema"] = clD[di] > emaD20[di]
        if f["dir"] == "high":
            f["d_trend_match"] = clD[di] > emaD20[di]  # FH в uptrend
        else:
            f["d_trend_match"] = clD[di] < emaD20[di]  # FL в downtrend
    else:
        f["d_trend_match"] = False; f["d_close"] = 0; f["d_ema"] = 0; f["d_above_ema"] = False

    # D left_ext_N
    def d_left_ext(N):
        if di < N: return True
        sub = barsD[di - N:di]
        if f["dir"] == "high":
            return f["level"] >= max(bd[2] for bd in sub)  # pivot.level >= max high in N days
        else:
            return f["level"] <= min(bd[3] for bd in sub)

    f["d_lext_3"] = d_left_ext(3)
    f["d_lext_5"] = d_left_ext(5)
    f["d_lext_10"] = d_left_ext(10)

    # Approach run 3 same-color
    if bidx >= 2:
        b1 = bars12[bidx - 1]; b2 = bars12[bidx - 2]
        if f["dir"] == "high":
            f["approach_run3"] = (b2[4] > b2[1]) and (b1[4] > b1[1]) and (c_ > o)
        else:
            f["approach_run3"] = (b2[4] < b2[1]) and (b1[4] < b1[1]) and (c_ < o)
    else:
        f["approach_run3"] = False

    # Distance from prev same-type fractal (in bars)
    prev_same = None
    for p in reversed(fractals[:f["num"] - 1]):
        if p["dir"] == f["dir"]: prev_same = p; break
    if prev_same:
        f["dist_same_bars"] = (f["center_ts"] - prev_same["center_ts"]) // TF12_MS
        f["dist_same_pct"] = abs(f["level"] - prev_same["level"]) / f["level"] * 100
    else:
        f["dist_same_bars"] = 999; f["dist_same_pct"] = 999


post_F1 = [f for f in fractals if f["F1_pass"]]
print(f"post_F1: {len(post_F1)} (18 imp + 23 noise)")


def eval_filter(name, pred):
    kept = [f for f in post_F1 if pred(f)]
    imp = sum(1 for f in kept if f["is_important"])
    noise = len(kept) - imp
    lost = 18 - imp
    recall = imp / 18 * 100
    prec = imp / len(kept) * 100 if kept else 0
    f1 = 2 * recall * prec / (recall + prec) if (recall + prec) > 0 else 0
    print(f"  {name:<60} keep={len(kept):>3}  imp={imp:>2}/18  lost={lost:>2}  "
          f"noise={noise:>3}  recall={recall:>5.1f}%  prec={prec:>5.1f}%  F1={f1:>5.1f}")
    if lost > 0 and lost <= 6:
        lost_ids = [f["num"] for f in post_F1 if f["is_important"] and not pred(f)]
        print(f"      lost: {lost_ids}")


print(f"\n{'='*120}")
print(f" Single features as F2 (each AND-ed with F1)")
print(f"{'='*120}")
eval_filter("d_trend_match (FH up / FL down on D EMA20)", lambda f: f["d_trend_match"])
print()
eval_filter("d_left_ext_3 (pivot extreme vs last 3 D-bars)", lambda f: f["d_lext_3"])
eval_filter("d_left_ext_5", lambda f: f["d_lext_5"])
eval_filter("d_left_ext_10", lambda f: f["d_lext_10"])
print()
eval_filter("range_atr ≥ 1.0", lambda f: f["range_atr"] >= 1.0)
eval_filter("range_atr ≥ 1.3", lambda f: f["range_atr"] >= 1.3)
print()
eval_filter("vol_rel ≥ 1.0", lambda f: f["vol_rel"] >= 1.0)
eval_filter("vol_rel ≥ 1.3", lambda f: f["vol_rel"] >= 1.3)
print()
eval_filter("wick_pct ≥ 0.30 (rejection)", lambda f: f["wick_pct"] >= 0.30)
eval_filter("body_pct ≥ 0.50 (big body)", lambda f: f["body_pct"] >= 0.50)
print()
eval_filter("approach_run3 (3 same-color bars)", lambda f: f["approach_run3"])
print()
eval_filter("dist_same_bars ≥ 4", lambda f: f["dist_same_bars"] >= 4)
eval_filter("dist_same_bars ≥ 6", lambda f: f["dist_same_bars"] >= 6)
eval_filter("dist_same_pct ≥ 1.5", lambda f: f["dist_same_pct"] >= 1.5)
eval_filter("dist_same_pct ≥ 2.5", lambda f: f["dist_same_pct"] >= 2.5)

print(f"\n{'='*120}")
print(f" Combo F2 candidates")
print(f"{'='*120}")
eval_filter("d_trend_match OR d_lext_5",
            lambda f: f["d_trend_match"] or f["d_lext_5"])
eval_filter("d_trend_match AND range_atr ≥ 1.0",
            lambda f: f["d_trend_match"] and f["range_atr"] >= 1.0)
eval_filter("(d_lext_3 OR dist_same_pct ≥ 2.5)",
            lambda f: f["d_lext_3"] or f["dist_same_pct"] >= 2.5)
eval_filter("(d_trend_match OR d_lext_3) AND dist_same_bars ≥ 4",
            lambda f: (f["d_trend_match"] or f["d_lext_3"]) and f["dist_same_bars"] >= 4)
eval_filter("d_lext_3 OR (range_atr ≥ 1.3 AND vol_rel ≥ 1.0)",
            lambda f: f["d_lext_3"] or (f["range_atr"] >= 1.3 and f["vol_rel"] >= 1.0))


# Detail: which important are sensitive?
print(f"\n{'='*120}")
print(f" Important fractals × features")
print(f"{'='*120}")
print(f"  {'#':>3} {'tp':>3} {'level':>6} {'dTr':>3} {'dL3':>3} {'dL5':>3} {'r/a':>4} {'vol':>4} {'wk%':>4} {'bd%':>4} {'r3':>2} {'dB':>3} {'dP%':>4}")
for f in post_F1:
    if not f["is_important"]: continue
    glyph = "FH" if f["dir"] == "high" else "FL"
    print(f"  {f['num']:>3} {glyph:>3} {f['level']:>6.0f} "
          f"{'Y' if f['d_trend_match'] else '·':>3} "
          f"{'Y' if f['d_lext_3'] else '·':>3} "
          f"{'Y' if f['d_lext_5'] else '·':>3} "
          f"{f['range_atr']:>3.1f}x "
          f"{f['vol_rel']:>3.1f}x "
          f"{f['wick_pct']*100:>3.0f}% "
          f"{f['body_pct']*100:>3.0f}% "
          f"{'Y' if f['approach_run3'] else '·':>2} "
          f"{f['dist_same_bars']:>3} "
          f"{f['dist_same_pct']:>3.1f}")
