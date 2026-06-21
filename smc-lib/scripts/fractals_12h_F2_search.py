"""Поиск F2 — фильтра для 23 noise, оставшихся после F1 = left_ext_5.

Базис: 41 fractal (18 important + 23 noise) после F1.
Цель F2: 100% recall важных + максимум noise срезано.

Кандидаты F2 (все causal на момент i.close):
  A) dist_to_prev_opp_R     — |level - prev_opp.level| / ATR (impulse size)
  B) dist_to_prev_opp_pct   — % distance from prev opposite fractal
  C) dist_to_prev_same_bars — bars since last same-type
  D) dist_to_prev_same_pct  — % distance from prev same-type (cluster-dup detection)
  E) D-trend match          — close vs EMA20(D) at i.close
  F) D 5-bar extreme        — i's price extreme vs last 5 D-bars (analog F1 на D)
  G) 4h ASVK zone matches direction (optional)
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
TF12_MS = 12 * 3600_000
TF_D_MS = 24 * 3600_000
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


print("Loading...")
data = load_1m()

bars12 = aggregate(data, TF12_MS)
barsD = aggregate(data, TF_D_MS)


# ATR(20) на 12h, EMA20 на D
hi12 = np.array([b[2] for b in bars12])
lo12 = np.array([b[3] for b in bars12])
cl12 = np.array([b[4] for b in bars12])
prev_cl = np.concatenate([[cl12[0]], cl12[:-1]])
tr12 = np.maximum.reduce([hi12 - lo12, np.abs(hi12 - prev_cl), np.abs(lo12 - prev_cl)])
atr20 = np.zeros_like(tr12)
for i in range(len(tr12)):
    atr20[i] = tr12[:i+1].mean() if i < 19 else tr12[i-19:i+1].mean()

clD = np.array([b[4] for b in barsD])
emaD20 = np.zeros_like(clD)
alpha = 2 / 21
emaD20[0] = clD[0]
for i in range(1, len(clD)):
    emaD20[i] = alpha * clD[i] + (1 - alpha) * emaD20[i-1]


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H:%M')


candles12 = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars12]
fractals = []
for i in range(2, len(candles12) - 2):
    f = detect_fractal(candles12[i-2:i+3], n=2)
    if f is None: continue
    if candles12[i].open_time < START_MS: continue
    fractals.append({"dir": f.direction, "level": f.level, "idx": i,
                     "center_ts": candles12[i].open_time,
                     "decision_ts": candles12[i].open_time + TF12_MS})

# Compute F1
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


# Compute F2 candidates
for n, f in enumerate(fractals, 1):
    bidx = f["idx"]
    atr = atr20[bidx]

    # A,B) distance to prev opposite fractal (causal: prev_opp before our decision)
    prev_opp = None
    for p in reversed(fractals[:n-1]):
        if p["dir"] != f["dir"] and p["decision_ts"] <= f["decision_ts"]:
            prev_opp = p; break
    if prev_opp:
        diff = abs(f["level"] - prev_opp["level"])
        f["dist_opp_R"] = diff / max(atr, 1e-9)
        f["dist_opp_pct"] = diff / f["level"] * 100
        f["dist_opp_bars"] = (f["center_ts"] - prev_opp["center_ts"]) // TF12_MS
    else:
        f["dist_opp_R"] = 0; f["dist_opp_pct"] = 0; f["dist_opp_bars"] = 0

    # C,D) distance to prev same-type
    prev_same = None
    for p in reversed(fractals[:n-1]):
        if p["dir"] == f["dir"] and p["decision_ts"] <= f["decision_ts"]:
            prev_same = p; break
    if prev_same:
        f["dist_same_bars"] = (f["center_ts"] - prev_same["center_ts"]) // TF12_MS
        f["dist_same_pct"] = abs(f["level"] - prev_same["level"]) / f["level"] * 100
        f["dist_same_R"] = abs(f["level"] - prev_same["level"]) / max(atr, 1e-9)
    else:
        f["dist_same_bars"] = 999; f["dist_same_pct"] = 999; f["dist_same_R"] = 999

    # E) D-trend match
    d_idx = next((j for j, b in enumerate(barsD) if b[0] + TF_D_MS > f["decision_ts"]), len(barsD)) - 1
    if d_idx >= 0 and d_idx < len(emaD20):
        d_close = clD[d_idx]
        d_ema = emaD20[d_idx]
        f["d_ema_above"] = d_close > d_ema  # bull regime
        # For FH (top) — хотим bull regime (real top); для FL — bear regime
        if f["dir"] == "high":
            f["d_trend_match"] = d_close > d_ema
        else:
            f["d_trend_match"] = d_close < d_ema
    else:
        f["d_ema_above"] = False; f["d_trend_match"] = False

    # F) D 5-bar extreme (analog left_ext_5 на D)
    if d_idx >= 5:
        d_left = barsD[d_idx - 5:d_idx]
        if f["dir"] == "high":
            f["d_left_ext_5"] = f["level"] >= max(b[2] for b in d_left)
        else:
            f["d_left_ext_5"] = f["level"] <= min(b[3] for b in d_left)
    else:
        f["d_left_ext_5"] = True

    # G) D 3-bar extreme (more permissive)
    if d_idx >= 3:
        d_left = barsD[d_idx - 3:d_idx]
        if f["dir"] == "high":
            f["d_left_ext_3"] = f["level"] >= max(b[2] for b in d_left)
        else:
            f["d_left_ext_3"] = f["level"] <= min(b[3] for b in d_left)
    else:
        f["d_left_ext_3"] = True


# Print stats only for F1-passing fractals
post_F1 = [f for f in fractals if f["F1_pass"]]
print(f"\nFractals after F1: {len(post_F1)} (important={sum(1 for f in post_F1 if f['is_important'])}, "
      f"noise={sum(1 for f in post_F1 if not f['is_important'])})")


# Print table sorted by num
print(f"\n{'='*120}")
print(f" F2 features for fractals AFTER F1 (41 total)")
print(f"{'='*120}")
print(f"{'#':>3} {'★':>1} {'tp':>3} {'center':<14} {'level':>6} "
      f"{'opp_R':>5} {'opp%':>5} {'oppB':>4} "
      f"{'samB':>4} {'sam%':>4} "
      f"{'dEMA':>4} {'dTrM':>4} {'dE5':>3} {'dE3':>3}")
print("-" * 120)
for f in post_F1:
    star = "★" if f["is_important"] else " "
    glyph = "FH" if f["dir"] == "high" else "FL"
    print(f"{f['num']:>3} {star:>1} {glyph:>3} {fmt(f['center_ts']):<14} {f['level']:>6.0f} "
          f"{f['dist_opp_R']:>4.1f}x {f['dist_opp_pct']:>4.1f} {f['dist_opp_bars']:>4} "
          f"{f['dist_same_bars']:>4} {f['dist_same_pct']:>3.1f} "
          f"{'Y' if f['d_ema_above'] else '·':>4} "
          f"{'Y' if f['d_trend_match'] else '·':>4} "
          f"{'Y' if f['d_left_ext_5'] else '·':>3} "
          f"{'Y' if f['d_left_ext_3'] else '·':>3}")


def eval_F2(name, pred):
    """Только среди post_F1. F2 = AND с F1."""
    kept = [f for f in post_F1 if pred(f)]
    imp_kept = sum(1 for f in kept if f["is_important"])
    imp_lost = 18 - imp_kept
    noise_kept = len(kept) - imp_kept
    recall = imp_kept / 18 * 100
    prec = imp_kept / len(kept) * 100 if kept else 0
    f1 = 2 * recall * prec / (recall + prec) if (recall + prec) > 0 else 0
    print(f"  {name:<58} keep={len(kept):>3}  imp={imp_kept:>2}/18  "
          f"lost={imp_lost:>2}  noise={noise_kept:>3}  "
          f"recall={recall:>5.1f}%  prec={prec:>5.1f}%  F1={f1:>5.1f}")
    if imp_lost > 0 and imp_lost <= 6:
        lost_ids = [f["num"] for f in post_F1 if f["is_important"] and not pred(f)]
        print(f"      lost: {lost_ids}")


print(f"\n{'='*120}")
print(f" F2 single-feature candidates (после F1)")
print(f"{'='*120}")
for thr in [1.0, 2.0, 3.0, 4.0, 5.0, 7.0]:
    eval_F2(f"dist_opp_R ≥ {thr}", lambda f, t=thr: f["dist_opp_R"] >= t)
print()
for thr in [1.0, 2.0, 3.0, 5.0, 7.0]:
    eval_F2(f"dist_opp_pct ≥ {thr}%", lambda f, t=thr: f["dist_opp_pct"] >= t)
print()
for thr in [2, 3, 5, 7, 10]:
    eval_F2(f"dist_opp_bars ≥ {thr}", lambda f, t=thr: f["dist_opp_bars"] >= t)
print()
for thr in [2, 3, 5, 7, 10]:
    eval_F2(f"dist_same_bars ≥ {thr}", lambda f, t=thr: f["dist_same_bars"] >= t)
print()
for thr in [1.0, 2.0, 3.0]:
    eval_F2(f"dist_same_pct ≥ {thr}%", lambda f, t=thr: f["dist_same_pct"] >= t)
print()
eval_F2("d_trend_match (FH up / FL down)", lambda f: f["d_trend_match"])
eval_F2("d_left_ext_5 (D 5-bar extreme)", lambda f: f["d_left_ext_5"])
eval_F2("d_left_ext_3 (D 3-bar extreme)", lambda f: f["d_left_ext_3"])


print(f"\n{'='*120}")
print(f" F2 combos (после F1=left_ext_5)")
print(f"{'='*120}")
eval_F2("dist_opp_R ≥ 2 AND dist_opp_bars ≥ 3",
        lambda f: f["dist_opp_R"] >= 2 and f["dist_opp_bars"] >= 3)
eval_F2("dist_opp_R ≥ 3 OR d_trend_match",
        lambda f: f["dist_opp_R"] >= 3 or f["d_trend_match"])
eval_F2("d_left_ext_3 AND d_trend_match",
        lambda f: f["d_left_ext_3"] and f["d_trend_match"])
eval_F2("d_left_ext_3 OR dist_opp_R ≥ 2",
        lambda f: f["d_left_ext_3"] or f["dist_opp_R"] >= 2)
eval_F2("dist_opp_R ≥ 2 OR d_left_ext_5",
        lambda f: f["dist_opp_R"] >= 2 or f["d_left_ext_5"])
eval_F2("dist_opp_pct ≥ 2 AND dist_opp_bars ≥ 3",
        lambda f: f["dist_opp_pct"] >= 2 and f["dist_opp_bars"] >= 3)
eval_F2("dist_same_bars ≥ 3 AND dist_opp_R ≥ 2",
        lambda f: f["dist_same_bars"] >= 3 and f["dist_opp_R"] >= 2)
eval_F2("d_trend_match AND dist_opp_R ≥ 1",
        lambda f: f["d_trend_match"] and f["dist_opp_R"] >= 1)
