"""F3+ search — повышаем precision F1∩F2 при сохранении 18 important.

Стратегия:
  1. Compute extended features per pre-Williams candidate (6y)
  2. Identify which features are TRUE for all 18 important (must-keep)
  3. Find features with high precision lift over baseline 45.2%
  4. Combine F1+F2+F3 — must keep 18 imp + maximize precision
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
TF12_MS = 12 * 3600_000
TF_D_MS = 24 * 3600_000
START_MS = int(datetime(2026, 2, 4, 0, 0, tzinfo=timezone(timedelta(hours=3))).timestamp() * 1000)
IMPORTANT = {1, 3, 4, 5, 9, 10, 11, 14, 15, 20, 23, 26, 29, 40, 41, 42, 47, 48}


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
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
last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
bars12 = [b for b in bars12 if b[0] >= window_start_ms]
print(f"  12h bars in 6y: {len(bars12)}")

# ATR + EMA
hi12 = np.array([b[2] for b in bars12]); lo12 = np.array([b[3] for b in bars12])
cl12 = np.array([b[4] for b in bars12]); vol12 = np.array([b[5] for b in bars12])
prev_cl = np.concatenate([[cl12[0]], cl12[:-1]])
tr12 = np.maximum.reduce([hi12-lo12, np.abs(hi12-prev_cl), np.abs(lo12-prev_cl)])
atr20 = np.zeros_like(tr12)
for i in range(len(tr12)):
    atr20[i] = tr12[:i+1].mean() if i < 19 else tr12[i-19:i+1].mean()
volsma = np.zeros_like(vol12)
for i in range(len(vol12)):
    volsma[i] = vol12[:i+1].mean() if i < 19 else vol12[i-19:i+1].mean()

clD = np.array([b[4] for b in barsD])
emaD = np.zeros_like(clD); alpha = 2/21; emaD[0] = clD[0]
for i in range(1, len(clD)): emaD[i] = alpha * clD[i] + (1 - alpha) * emaD[i-1]


def color(b):
    if b[4] > b[1]: return "bull"
    if b[4] < b[1]: return "bear"
    return "doji"


# Detect for ground truth: 56 fractals from START_MS
cands_full = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars12]
gt_fractals = []
for i in range(2, len(cands_full) - 2):
    f = detect_fractal(cands_full[i-2:i+3], n=2)
    if f is None: continue
    if cands_full[i].open_time < START_MS: continue
    gt_fractals.append({"dir": f.direction, "level": f.level, "idx": i, "ts": cands_full[i].open_time})
imp_idx_set = {gt_fractals[n-1]["idx"] for n in IMPORTANT}
print(f"  Ground truth: {len(gt_fractals)} 12h fractals в 4mo окне, важных={len(imp_idx_set)}")

# Build pre-Williams candidates over 6y
print("Building 6y pre-Williams candidates with extended features...")
candidates = []
for i in range(2, len(bars12) - 2):
    bi = bars12[i]; bi1 = bars12[i-1]; bi2 = bars12[i-2]
    bip1 = bars12[i+1]; bip2 = bars12[i+2]
    pre_fh = bi[2] > bi1[2] and bi[2] > bi2[2]
    pre_fl = bi[3] < bi1[3] and bi[3] < bi2[3]
    if not (pre_fh or pre_fl): continue

    for direction in (("high",) if pre_fh else ()) + (("low",) if pre_fl else ()):
        if direction == "high":
            confirmed = bi[2] > bip1[2] and bi[2] > bip2[2]
            relevant_wick = bi[2] - max(bi[1], bi[4])
            level = bi[2]
        else:
            confirmed = bi[3] < bip1[3] and bi[3] < bip2[3]
            relevant_wick = min(bi[1], bi[4]) - bi[3]
            level = bi[3]
        rng = bi[2] - bi[3] if bi[2] > bi[3] else 1e-9
        body = abs(bi[4] - bi[1])
        rng1 = bi1[2] - bi1[3] if bi1[2] > bi1[3] else 1e-9
        body1 = abs(bi1[4] - bi1[1])
        rng2 = bi2[2] - bi2[3] if bi2[2] > bi2[3] else 1e-9
        body2 = abs(bi2[4] - bi2[1])

        c0, c1, c2 = color(bi), color(bi1), color(bi2)
        opp_colors = c0 != c1 and "doji" not in (c0, c1)
        three_same = c0 == c1 == c2 and c0 != "doji"

        # F1
        left_lo = max(0, i-5); left_hi = i
        if direction == "high":
            f1 = bi[2] > max(b[2] for b in bars12[left_lo:left_hi]) if left_hi > left_lo else True
        else:
            f1 = bi[3] < min(b[3] for b in bars12[left_lo:left_hi]) if left_hi > left_lo else True

        # D EMA trend
        d_idx = next((j for j, bd in enumerate(barsD) if bd[0] + TF_D_MS > bi[0]), len(barsD)) - 1
        if 0 <= d_idx < len(emaD):
            d_trend_match = (direction == "high" and clD[d_idx] > emaD[d_idx]) or \
                            (direction == "low" and clD[d_idx] < emaD[d_idx])
            d_ema_dist_pct = (bi[4] - emaD[d_idx]) / bi[4] * 100
        else:
            d_trend_match = False; d_ema_dist_pct = 0

        # close position in pivot bar
        close_pos = (bi[4] - bi[3]) / rng  # 0=low, 1=high
        if direction == "low": close_pos = 1 - close_pos  # for FL: 1=closed high (away from low)

        # i_extends_im1 always True by pre-Williams
        # i_engulfs_im1_body
        engulfs = (min(bi[1], bi[4]) <= min(bi1[1], bi1[4]) and max(bi[1], bi[4]) >= max(bi1[1], bi1[4]))

        # i_closes_inside_im1
        closes_inside = bi1[3] <= bi[4] <= bi1[2]

        # 3-bar drift R (in expected direction)
        if direction == "high":
            drift = bi[4] - bi2[4]
        else:
            drift = bi2[4] - bi[4]
        drift_R = drift / max(atr20[i], 1e-9)

        # excess over i-1 extremum in R
        if direction == "high":
            excess_R = (bi[2] - bi1[2]) / max(atr20[i], 1e-9)
        else:
            excess_R = (bi1[3] - bi[3]) / max(atr20[i], 1e-9)

        # i-1 large body? i-1 was strong move?
        body1_pct = body1 / rng1

        # Vol_rel
        vol_rel = bi[5] / max(volsma[i], 1e-9)

        candidates.append({
            "idx": i, "direction": direction, "confirmed": confirmed,
            "is_important": i in imp_idx_set and bi[0] >= START_MS,
            "level": level, "ts": bi[0],
            "f1": f1, "opp_colors": opp_colors, "three_same": three_same,
            "range_atr": rng / max(atr20[i], 1e-9),
            "body_pct": body / rng,
            "wick_pct": relevant_wick / rng,
            "close_pos": close_pos,
            "d_trend_match": d_trend_match,
            "d_ema_dist_pct": d_ema_dist_pct,
            "engulfs": engulfs,
            "closes_inside": closes_inside,
            "drift_R": drift_R,
            "excess_R": excess_R,
            "body1_pct": body1_pct,
            "vol_rel": vol_rel,
            "i_range_vs_im1": rng / max(rng1, 1e-9),
            "i_range_vs_im2": rng / max(rng2, 1e-9),
            "im1_color": c1,
        })


# Subset: F1 ∩ F2
post_F1F2 = [c for c in candidates if c["f1"] and (c["opp_colors"] or c["three_same"])]
total = len(post_F1F2)
confirmed = sum(1 for c in post_F1F2 if c["confirmed"])
imp_count = sum(1 for c in post_F1F2 if c["is_important"])
print(f"\nF1 ∩ F2 candidates: {total}")
print(f"  Williams confirmed: {confirmed} ({confirmed/total*100:.1f}%) — baseline precision")
print(f"  Important (4mo ground truth): {imp_count}/18")


def stat(name, pred):
    yes = [c for c in post_F1F2 if pred(c)]
    if not yes:
        print(f"  {name:<60} keep=  0 → empty")
        return
    conf_yes = sum(1 for c in yes if c["confirmed"])
    imp_yes = sum(1 for c in yes if c["is_important"])
    prec = conf_yes / len(yes) * 100
    print(f"  {name:<60} keep={len(yes):>4} conf={conf_yes:>3} ({prec:>5.1f}%)  imp_kept={imp_yes:>2}/18")


# Find features that are TRUE for all 18 imp
print(f"\n{'='*120}")
print(f" Features TRUE for all 18 imp (must-keep constraint)")
print(f"{'='*120}")

imp_only = [c for c in post_F1F2 if c["is_important"]]
print(f"  имп range_atr: min={min(c['range_atr'] for c in imp_only):.2f}, max={max(c['range_atr'] for c in imp_only):.2f}")
print(f"  имп body_pct:  min={min(c['body_pct'] for c in imp_only):.2f}, max={max(c['body_pct'] for c in imp_only):.2f}")
print(f"  имп wick_pct:  min={min(c['wick_pct'] for c in imp_only):.2f}, max={max(c['wick_pct'] for c in imp_only):.2f}")
print(f"  имп drift_R:   min={min(c['drift_R'] for c in imp_only):.2f}, max={max(c['drift_R'] for c in imp_only):.2f}")
print(f"  имп excess_R:  min={min(c['excess_R'] for c in imp_only):.2f}, max={max(c['excess_R'] for c in imp_only):.2f}")
print(f"  имп close_pos: min={min(c['close_pos'] for c in imp_only):.2f}, max={max(c['close_pos'] for c in imp_only):.2f}")
print(f"  имп d_trend_match: TRUE count = {sum(1 for c in imp_only if c['d_trend_match'])}/18")
print(f"  имп engulfs:   TRUE count = {sum(1 for c in imp_only if c['engulfs'])}/18")
print(f"  имп closes_inside: TRUE count = {sum(1 for c in imp_only if c['closes_inside'])}/18")
print(f"  имп vol_rel:   min={min(c['vol_rel'] for c in imp_only):.2f}, max={max(c['vol_rel'] for c in imp_only):.2f}")


print(f"\n{'='*120}")
print(f" Single-feature F3 candidates (precision lift при keeping 18)")
print(f"{'='*120}")
# Test with thresholds matching imp range
stat("baseline (F1∩F2 only)", lambda c: True)
print("\n--- Range/Body/Wick thresholds (preserving imp range) ---")
stat("range_atr ≥ 0.55", lambda c: c["range_atr"] >= 0.55)
stat("range_atr ≥ 0.60", lambda c: c["range_atr"] >= 0.60)
stat("range_atr ≥ 0.70", lambda c: c["range_atr"] >= 0.70)
stat("range_atr ≥ 0.80", lambda c: c["range_atr"] >= 0.80)
stat("body_pct ≤ 0.80", lambda c: c["body_pct"] <= 0.80)
stat("body_pct ≤ 0.85", lambda c: c["body_pct"] <= 0.85)
stat("wick_pct ≥ 0.03", lambda c: c["wick_pct"] >= 0.03)
stat("wick_pct ≥ 0.05", lambda c: c["wick_pct"] >= 0.05)

print("\n--- close_pos (для pivot bar) ---")
stat("close_pos ≤ 0.97", lambda c: c["close_pos"] <= 0.97)
stat("close_pos ≥ 0.05", lambda c: c["close_pos"] >= 0.05)
stat("close_pos in [0.05, 0.97]", lambda c: 0.05 <= c["close_pos"] <= 0.97)

print("\n--- D-EMA trend ---")
stat("d_trend_match", lambda c: c["d_trend_match"])

print("\n--- Drift / Excess ---")
stat("drift_R > -0.5 (not extreme counter-drift)", lambda c: c["drift_R"] > -0.5)
stat("drift_R > 0.0", lambda c: c["drift_R"] > 0.0)
stat("excess_R ≥ 0.00 (= must extend i-1)", lambda c: c["excess_R"] >= 0.0)
stat("excess_R ≥ 0.20", lambda c: c["excess_R"] >= 0.20)

print("\n--- Multi-bar relations ---")
stat("NOT closes_inside_im1", lambda c: not c["closes_inside"])
stat("engulfs i-1 body", lambda c: c["engulfs"])
stat("i_range_vs_im1 ≥ 1.0", lambda c: c["i_range_vs_im1"] >= 1.0)
stat("im1_body_pct < 0.85 (i-1 не marubozu)", lambda c: c["body1_pct"] < 0.85)

print("\n--- Volume ---")
stat("vol_rel ≥ 0.5", lambda c: c["vol_rel"] >= 0.5)
stat("vol_rel ≥ 0.7", lambda c: c["vol_rel"] >= 0.7)
stat("vol_rel ≥ 1.0", lambda c: c["vol_rel"] >= 1.0)

print("\n--- Combos preserving 18 imp ---")
stat("body_pct ≤ 0.85 AND range_atr ≥ 0.6", lambda c: c["body_pct"] <= 0.85 and c["range_atr"] >= 0.6)
stat("body_pct ≤ 0.85 AND vol_rel ≥ 0.5", lambda c: c["body_pct"] <= 0.85 and c["vol_rel"] >= 0.5)
stat("body_pct ≤ 0.85 AND range_atr ≥ 0.6 AND vol_rel ≥ 0.5",
     lambda c: c["body_pct"] <= 0.85 and c["range_atr"] >= 0.6 and c["vol_rel"] >= 0.5)
stat("body_pct ≤ 0.85 AND wick_pct ≥ 0.03",
     lambda c: c["body_pct"] <= 0.85 and c["wick_pct"] >= 0.03)
stat("body_pct ≤ 0.85 AND drift_R > -0.5",
     lambda c: c["body_pct"] <= 0.85 and c["drift_R"] > -0.5)

print("\n--- BEST combos preserving 18 imp ---")
stat("body ≤ 0.80 AND wick ≥ 0.03",
     lambda c: c["body_pct"] <= 0.80 and c["wick_pct"] >= 0.03)
stat("body ≤ 0.80 AND range_atr ≥ 0.55",
     lambda c: c["body_pct"] <= 0.80 and c["range_atr"] >= 0.55)
stat("body ≤ 0.80 AND close_pos ≤ 0.97",
     lambda c: c["body_pct"] <= 0.80 and c["close_pos"] <= 0.97)
stat("body ≤ 0.80 AND wick ≥ 0.03 AND range ≥ 0.55",
     lambda c: c["body_pct"] <= 0.80 and c["wick_pct"] >= 0.03 and c["range_atr"] >= 0.55)
stat("body ≤ 0.80 AND wick ≥ 0.03 AND close_pos ≤ 0.97",
     lambda c: c["body_pct"] <= 0.80 and c["wick_pct"] >= 0.03 and c["close_pos"] <= 0.97)
stat("body ≤ 0.78 AND wick ≥ 0.03",
     lambda c: c["body_pct"] <= 0.78 and c["wick_pct"] >= 0.03)
stat("body ≤ 0.77 AND wick ≥ 0.04",
     lambda c: c["body_pct"] <= 0.77 and c["wick_pct"] >= 0.04)
stat("body in [0.09, 0.80] AND wick ≥ 0.04",
     lambda c: 0.09 <= c["body_pct"] <= 0.80 and c["wick_pct"] >= 0.04)
stat("body in [0.09, 0.80] AND range ≥ 0.55",
     lambda c: 0.09 <= c["body_pct"] <= 0.80 and c["range_atr"] >= 0.55)
stat("ALL: body[0.09,0.80] AND wick≥0.04 AND range≥0.55",
     lambda c: 0.09 <= c["body_pct"] <= 0.80 and c["wick_pct"] >= 0.04 and c["range_atr"] >= 0.55)
