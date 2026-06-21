"""Pred-12h v2 — predictor по 3 свечам (i-2, i-1, i) что i+1, i+2 не нарушат Williams.

Baseline conversion: 38.9% (2892 candidates → 1124 confirmed).
Цель: features что повышают precision значительно выше 38.9% без сильной потери recall.

Все features — causal на i.close. Нет look-ahead.
"""
from __future__ import annotations
import csv
import pathlib
import sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
TF12_MS = 12 * 3600_000
TF_D_MS = 24 * 3600_000


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
last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
bars12 = [b for b in bars12 if b[0] >= window_start_ms]
print(f"  12h bars in 6y: {len(bars12)}")

# ATR(20)
hi12 = np.array([b[2] for b in bars12])
lo12 = np.array([b[3] for b in bars12])
cl12 = np.array([b[4] for b in bars12])
vol12 = np.array([b[5] for b in bars12])
prev_cl = np.concatenate([[cl12[0]], cl12[:-1]])
tr12 = np.maximum.reduce([hi12 - lo12, np.abs(hi12 - prev_cl), np.abs(lo12 - prev_cl)])
atr20 = np.zeros_like(tr12)
for i in range(len(tr12)):
    atr20[i] = tr12[:i+1].mean() if i < 19 else tr12[i-19:i+1].mean()
volsma = np.zeros_like(vol12)
for i in range(len(vol12)):
    volsma[i] = vol12[:i+1].mean() if i < 19 else vol12[i-19:i+1].mean()

# D EMA20
clD = np.array([b[4] for b in barsD])
emaD = np.zeros_like(clD)
alpha = 2/21
emaD[0] = clD[0]
for i in range(1, len(clD)):
    emaD[i] = alpha * clD[i] + (1 - alpha) * emaD[i-1]


def color(b):
    if b[4] > b[1]: return "bull"
    if b[4] < b[1]: return "bear"
    return "doji"


# Build candidates
print("\nBuilding 3-bar candidates...")
candidates = []  # (idx, direction, confirmed, features_dict)

for i in range(2, len(bars12) - 2):
    bi = bars12[i]; bi1 = bars12[i-1]; bi2 = bars12[i-2]
    bip1 = bars12[i+1]; bip2 = bars12[i+2]

    pre_fh = bi[2] > bi1[2] and bi[2] > bi2[2]
    pre_fl = bi[3] < bi1[3] and bi[3] < bi2[3]
    if not (pre_fh or pre_fl): continue

    for direction in (("high",) if pre_fh else ()) + (("low",) if pre_fl else ()):
        if direction == "high":
            confirmed = bi[2] > bip1[2] and bi[2] > bip2[2]
            level = bi[2]
            relevant_wick = bi[2] - max(bi[1], bi[4])
        else:
            confirmed = bi[3] < bip1[3] and bi[3] < bip2[3]
            level = bi[3]
            relevant_wick = min(bi[1], bi[4]) - bi[3]

        rng = bi[2] - bi[3] if bi[2] > bi[3] else 1e-9
        body = abs(bi[4] - bi[1])
        opp_wick = (min(bi[1], bi[4]) - bi[3]) if direction == "high" else (bi[2] - max(bi[1], bi[4]))

        # i-1, i-2 anatomy
        rng1 = bi1[2] - bi1[3] if bi1[2] > bi1[3] else 1e-9
        body1 = abs(bi1[4] - bi1[1])
        rng2 = bi2[2] - bi2[3] if bi2[2] > bi2[3] else 1e-9

        # excess over i-1 extremum
        if direction == "high":
            excess_R = (bi[2] - bi1[2]) / max(atr20[i], 1e-9)
        else:
            excess_R = (bi1[3] - bi[3]) / max(atr20[i], 1e-9)

        # left_ext_5
        left_lo = max(0, i - 5); left_hi = i
        if direction == "high":
            left_ext5 = bi[2] > max(b[2] for b in bars12[left_lo:left_hi]) if left_hi > left_lo else True
        else:
            left_ext5 = bi[3] < min(b[3] for b in bars12[left_lo:left_hi]) if left_hi > left_lo else True

        # colors
        c0 = color(bi); c1 = color(bi1); c2 = color(bi2)
        opp_colors = c0 != c1 and "doji" not in (c0, c1)
        three_same = c0 == c1 == c2 and c0 != "doji"

        # D trend
        d_idx = next((j for j, bd in enumerate(barsD) if bd[0] + TF_D_MS > bi[0]), len(barsD)) - 1
        if 0 <= d_idx < len(emaD):
            d_trend_match = (direction == "high" and clD[d_idx] > emaD[d_idx]) or \
                            (direction == "low" and clD[d_idx] < emaD[d_idx])
        else:
            d_trend_match = False

        # close_pos
        close_pos = (bi[4] - bi[3]) / rng
        if direction == "low":
            close_pos = 1 - close_pos  # for FL want higher close_pos meaning closed away from low

        # Approach 3-same color (for direction)
        if direction == "high":
            approach_run3 = (c2 == "bull" and c1 == "bull" and c0 == "bull")
        else:
            approach_run3 = (c2 == "bear" and c1 == "bear" and c0 == "bear")

        features = {
            "range_atr": rng / max(atr20[i], 1e-9),
            "body_pct": body / rng,
            "wick_pct": relevant_wick / rng,
            "opp_wick_pct": opp_wick / rng,
            "close_pos": close_pos,
            "excess_R": excess_R,
            "left_ext5": left_ext5,
            "opp_colors": opp_colors,
            "three_same": three_same,
            "approach_run3": approach_run3,
            "d_trend_match": d_trend_match,
            "i_range_vs_im1": rng / max(rng1, 1e-9),
            "vol_rel": bi[5] / max(volsma[i], 1e-9),
            "im1_range_atr": rng1 / max(atr20[i-1], 1e-9),
        }

        candidates.append({
            "idx": i, "direction": direction, "confirmed": confirmed,
            "level": level, "ts": bi[0],
            **features,
        })


total = len(candidates)
confirmed = sum(1 for c in candidates if c["confirmed"])
print(f"  {total} candidates, {confirmed} confirmed ({confirmed/total*100:.1f}% baseline)")
fh_cand = [c for c in candidates if c["direction"] == "high"]
fl_cand = [c for c in candidates if c["direction"] == "low"]
print(f"  Pre-FH: {len(fh_cand)}  confirmed={sum(1 for c in fh_cand if c['confirmed'])} "
      f"({sum(1 for c in fh_cand if c['confirmed'])/len(fh_cand)*100:.1f}%)")
print(f"  Pre-FL: {len(fl_cand)}  confirmed={sum(1 for c in fl_cand if c['confirmed'])} "
      f"({sum(1 for c in fl_cand if c['confirmed'])/len(fl_cand)*100:.1f}%)")


# Univariate stats
def univariate_stats(name, pred):
    """For boolean predicate (or threshold), report confirmed conversion."""
    yes = [c for c in candidates if pred(c)]
    no = [c for c in candidates if not pred(c)]
    yes_conf = sum(1 for c in yes if c["confirmed"])
    no_conf = sum(1 for c in no if c["confirmed"])
    yes_p = yes_conf / len(yes) * 100 if yes else 0
    no_p = no_conf / len(no) * 100 if no else 0
    print(f"  {name:<55} N_yes={len(yes):>4} P(conf|yes)={yes_p:>5.1f}%  "
          f"N_no={len(no):>4} P(conf|no)={no_p:>5.1f}%  ΔP={yes_p-no_p:>+5.1f}pp")


print(f"\n{'='*120}")
print(f" Univariate feature analysis — baseline P=38.9%")
print(f"{'='*120}")

univariate_stats("left_ext_5", lambda c: c["left_ext5"])
univariate_stats("opp_colors", lambda c: c["opp_colors"])
univariate_stats("three_same", lambda c: c["three_same"])
univariate_stats("approach_run3", lambda c: c["approach_run3"])
univariate_stats("d_trend_match", lambda c: c["d_trend_match"])
print()

for thr in [0.5, 0.7, 1.0, 1.3]:
    univariate_stats(f"excess_R ≥ {thr}", lambda c, t=thr: c["excess_R"] >= t)
print()

for thr in [0.5, 0.8, 1.0, 1.3]:
    univariate_stats(f"range_atr ≥ {thr}", lambda c, t=thr: c["range_atr"] >= t)
print()

for thr in [0.3, 0.5, 0.7]:
    univariate_stats(f"body_pct ≥ {thr}", lambda c, t=thr: c["body_pct"] >= t)
print()

for thr in [0.3, 0.5, 0.7]:
    univariate_stats(f"wick_pct ≥ {thr}", lambda c, t=thr: c["wick_pct"] >= t)
print()

for thr in [1.0, 1.3, 1.7]:
    univariate_stats(f"i_range_vs_im1 ≥ {thr}", lambda c, t=thr: c["i_range_vs_im1"] >= t)
print()

univariate_stats("FH only (high direction)", lambda c: c["direction"] == "high")
univariate_stats("FL only (low direction)", lambda c: c["direction"] == "low")


# Combined predictors
print(f"\n{'='*120}")
print(f" Combined predictors")
print(f"{'='*120}")
univariate_stats("left_ext_5 AND opp_colors", lambda c: c["left_ext5"] and c["opp_colors"])
univariate_stats("left_ext_5 AND three_same", lambda c: c["left_ext5"] and c["three_same"])
univariate_stats("left_ext_5 AND (opp_colors OR three_same)",
                 lambda c: c["left_ext5"] and (c["opp_colors"] or c["three_same"]))
univariate_stats("excess_R ≥ 1.0 AND opp_colors",
                 lambda c: c["excess_R"] >= 1.0 and c["opp_colors"])
univariate_stats("range_atr ≥ 1.0 AND excess_R ≥ 0.5",
                 lambda c: c["range_atr"] >= 1.0 and c["excess_R"] >= 0.5)
univariate_stats("left_ext_5 AND range_atr ≥ 1.0",
                 lambda c: c["left_ext5"] and c["range_atr"] >= 1.0)
univariate_stats("left_ext_5 AND excess_R ≥ 0.5",
                 lambda c: c["left_ext5"] and c["excess_R"] >= 0.5)
univariate_stats("left_ext_5 AND excess_R ≥ 0.5 AND (opp_colors OR three_same)",
                 lambda c: c["left_ext5"] and c["excess_R"] >= 0.5 and (c["opp_colors"] or c["three_same"]))

print(f"\n{'='*120}")
print(f" Wick-based combos (most promising direction)")
print(f"{'='*120}")
univariate_stats("wick_pct ≥ 0.5 AND opp_colors",
                 lambda c: c["wick_pct"] >= 0.5 and c["opp_colors"])
univariate_stats("wick_pct ≥ 0.5 AND NOT three_same",
                 lambda c: c["wick_pct"] >= 0.5 and not c["three_same"])
univariate_stats("wick_pct ≥ 0.5 AND body_pct < 0.5",
                 lambda c: c["wick_pct"] >= 0.5 and c["body_pct"] < 0.5)
univariate_stats("wick_pct ≥ 0.3 AND body_pct < 0.5",
                 lambda c: c["wick_pct"] >= 0.3 and c["body_pct"] < 0.5)
univariate_stats("wick_pct ≥ 0.3 AND opp_colors",
                 lambda c: c["wick_pct"] >= 0.3 and c["opp_colors"])
univariate_stats("wick_pct ≥ 0.3 AND NOT three_same",
                 lambda c: c["wick_pct"] >= 0.3 and not c["three_same"])
univariate_stats("wick_pct ≥ 0.3 AND NOT approach_run3",
                 lambda c: c["wick_pct"] >= 0.3 and not c["approach_run3"])
univariate_stats("wick_pct ≥ 0.5 AND left_ext_5",
                 lambda c: c["wick_pct"] >= 0.5 and c["left_ext5"])
univariate_stats("wick_pct ≥ 0.7 AND opp_colors",
                 lambda c: c["wick_pct"] >= 0.7 and c["opp_colors"])

# Triple combos
print(f"\n--- triple ---")
univariate_stats("wick ≥ 0.5 AND opp_colors AND left_ext_5",
                 lambda c: c["wick_pct"] >= 0.5 and c["opp_colors"] and c["left_ext5"])
univariate_stats("wick ≥ 0.5 AND body < 0.5 AND NOT 3same",
                 lambda c: c["wick_pct"] >= 0.5 and c["body_pct"] < 0.5 and not c["three_same"])
univariate_stats("wick ≥ 0.3 AND body < 0.5 AND opp_colors",
                 lambda c: c["wick_pct"] >= 0.3 and c["body_pct"] < 0.5 and c["opp_colors"])
univariate_stats("wick ≥ 0.3 AND opp_colors AND left_ext_5",
                 lambda c: c["wick_pct"] >= 0.3 and c["opp_colors"] and c["left_ext5"])
univariate_stats("wick ≥ 0.3 AND NOT three_same AND NOT approach_run3",
                 lambda c: c["wick_pct"] >= 0.3 and not c["three_same"] and not c["approach_run3"])

print(f"\n{'='*120}")
print(f" RECALL-focused (preserve 18 important by structural similarity)")
print(f"{'='*120}")
# F1+F2 architecture: keep all important (by user-marked ground truth which used these rules)
univariate_stats("F1 (left_ext_5) alone",
                 lambda c: c["left_ext5"])
univariate_stats("F1 AND F2 (left_ext_5 AND (opp_colors OR three_same))",
                 lambda c: c["left_ext5"] and (c["opp_colors"] or c["three_same"]))
univariate_stats("F1 AND F2 AND range_atr ≥ 0.6 (tighten with range)",
                 lambda c: c["left_ext5"] and (c["opp_colors"] or c["three_same"]) and c["range_atr"] >= 0.6)
univariate_stats("F1 AND F2 AND range_atr ≥ 0.8",
                 lambda c: c["left_ext5"] and (c["opp_colors"] or c["three_same"]) and c["range_atr"] >= 0.8)
univariate_stats("F1 AND F2 AND NOT i_closes_inside_im1",
                 lambda c: c["left_ext5"] and (c["opp_colors"] or c["three_same"]) and not c.get("i_closes_inside_im1", False))
# Add a feature: pivot has minimum wick (anything > 0)
univariate_stats("F1 AND F2 AND wick_pct > 0.04 (all 18 imp wick ≥ 4%)",
                 lambda c: c["left_ext5"] and (c["opp_colors"] or c["three_same"]) and c["wick_pct"] > 0.04)
univariate_stats("F1 AND F2 AND body_pct < 0.85",
                 lambda c: c["left_ext5"] and (c["opp_colors"] or c["three_same"]) and c["body_pct"] < 0.85)
