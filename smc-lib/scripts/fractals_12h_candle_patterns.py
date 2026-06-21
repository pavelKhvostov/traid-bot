"""Анализ candle anatomy и multi-bar relationships
для 41 post-F1 fractals (18 imp + 23 noise).

Цель: найти паттерны по типу/размеру свечи и их relationships
которые разделяют important vs noise.

Features (causal at i.close — доступно [i-2, i-1, i]):

A) Pivot i anatomy:
   - type: bull/bear/doji
   - range_atr
   - body_pct, wick_pct (relevant side), opp_wick_pct
   - close_pos_in_range (0=low, 1=high)
   - marubozu_like (open at extreme on side opposite the wick)

B) i-1 anatomy (same fields)

C) i-2 anatomy (same fields)

D) Multi-bar relations (i vs i-1):
   - i_engulfs_im1_body (i.body covers i-1.body)
   - i_range_vs_im1 (ratio)
   - i_body_vs_im1
   - i_extends_im1_extreme (i.high > i-1.high для FH / i.low < i-1.low для FL)
   - i_closes_inside_im1 (i.close in i-1.range)
   - opposite_colors (i bull while i-1 bear — reversal candle)

E) 3-bar patterns (i-2, i-1, i):
   - 3_same_color (continuation)
   - V_shape (i-2 same color as i, i-1 opposite)
   - hammer_setup для FL: i-2 bear, i-1 bear (or small), i big bear with long lower wick
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
START_MS = int(datetime(2026, 2, 4, 0, 0, tzinfo=MSK).timestamp() * 1000)
IMPORTANT = {1, 3, 4, 5, 9, 10, 11, 14, 15, 20, 23, 26, 29, 40, 41, 42, 47, 48}


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000),
                         float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def aggregate(d, tf_ms):
    out = []; cb = None; o = h = l = c = 0.0
    for ts, oo, hh, ll, cc in d:
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append((cb, o, h, l, c))
    return out


print("Loading...")
data = load_1m()
bars12 = aggregate(data, TF12_MS)

# ATR(20) на 12h
hi12 = np.array([b[2] for b in bars12])
lo12 = np.array([b[3] for b in bars12])
cl12 = np.array([b[4] for b in bars12])
prev_cl = np.concatenate([[cl12[0]], cl12[:-1]])
tr12 = np.maximum.reduce([hi12 - lo12, np.abs(hi12 - prev_cl), np.abs(lo12 - prev_cl)])
atr20 = np.zeros_like(tr12)
for i in range(len(tr12)):
    atr20[i] = tr12[:i+1].mean() if i < 19 else tr12[i-19:i+1].mean()


# Detect 12h fractals
candles = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars12]
fractals = []
for i in range(2, len(candles) - 2):
    f = detect_fractal(candles[i-2:i+3], n=2)
    if f is None: continue
    if candles[i].open_time < START_MS: continue
    fractals.append({"dir": f.direction, "level": f.level, "idx": i,
                     "center_ts": candles[i].open_time})


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


# === Анатомия и связи ===
def bar_features(b, atr):
    o, h_, l_, c_ = b[1], b[2], b[3], b[4]
    rng = h_ - l_ if h_ > l_ else 1e-9
    body = abs(c_ - o)
    upper = h_ - max(o, c_)
    lower = min(o, c_) - l_
    color = "bull" if c_ > o else ("bear" if c_ < o else "doji")
    return {
        "o": o, "h": h_, "l": l_, "c": c_, "range": rng,
        "body": body, "upper": upper, "lower": lower,
        "color": color,
        "range_atr": rng / max(atr, 1e-9),
        "body_pct": body / rng,
        "upper_pct": upper / rng,
        "lower_pct": lower / rng,
        "close_pos": (c_ - l_) / rng,  # 0 = closed at low, 1 = closed at high
    }


for f in fractals:
    bidx = f["idx"]
    f["i"] = bar_features(bars12[bidx], atr20[bidx])
    f["i_1"] = bar_features(bars12[bidx - 1], atr20[bidx - 1])
    f["i_2"] = bar_features(bars12[bidx - 2], atr20[bidx - 2])

    # Multi-bar
    i = f["i"]; im1 = f["i_1"]; im2 = f["i_2"]

    # engulf check
    f["i_engulfs_im1_body"] = (min(i["o"], i["c"]) <= min(im1["o"], im1["c"])
                                and max(i["o"], i["c"]) >= max(im1["o"], im1["c"]))
    f["i_range_vs_im1"] = i["range"] / max(im1["range"], 1e-9)
    f["i_body_vs_im1"] = i["body"] / max(im1["body"], 1e-9)
    f["i_extends_im1"] = (i["h"] > im1["h"]) if f["dir"] == "high" else (i["l"] < im1["l"])
    f["i_closes_inside_im1"] = (im1["l"] <= i["c"] <= im1["h"])
    f["opposite_colors"] = (i["color"] != im1["color"]) and "doji" not in (i["color"], im1["color"])

    # 3-bar patterns
    f["three_same_color"] = (i["color"] == im1["color"] == im2["color"]
                              and i["color"] != "doji")
    f["v_shape"] = (i["color"] == im2["color"] and im1["color"] != i["color"]
                    and i["color"] != "doji")


post_F1 = [f for f in fractals if f["F1_pass"]]
print(f"post_F1: {len(post_F1)} fractals")


def eval_filter(name, pred):
    kept = [f for f in post_F1 if pred(f)]
    imp = sum(1 for f in kept if f["is_important"])
    noise = len(kept) - imp
    lost = 18 - imp
    print(f"  {name:<60} keep={len(kept):>3}  imp={imp:>2}/18  lost={lost:>2}  noise={noise:>3}")
    if lost > 0 and lost <= 5:
        lost_ids = [f["num"] for f in post_F1 if f["is_important"] and not pred(f)]
        print(f"      lost: {lost_ids}")


# Detail table
print(f"\n{'='*180}")
print(f" Anatomy table (post-F1)")
print(f"{'='*180}")
print(f"  {'#':>3} {'★':>1} {'tp':>3} {'level':>6}  "
      f"{'i col':>5} {'i r/a':>5} {'i bd%':>5} {'i wk%':>5} {'i cp':>4}  "
      f"{'i-1 col':>7} {'i-1 r/a':>7} {'i-1 bd%':>7}  "
      f"{'i-2 col':>7}  "
      f"{'eng':>3} {'ext':>3} {'in':>2} {'opp':>3} {'3sm':>3} {'V':>2}")
print("-" * 180)
for f in post_F1:
    star = "★" if f["is_important"] else " "
    glyph = "FH" if f["dir"] == "high" else "FL"
    i = f["i"]; im1 = f["i_1"]; im2 = f["i_2"]
    wk = i["upper_pct"] if f["dir"] == "high" else i["lower_pct"]
    print(f"  {f['num']:>3} {star:>1} {glyph:>3} {f['level']:>6.0f}  "
          f"{i['color']:>5} {i['range_atr']:>4.1f}x {i['body_pct']*100:>4.0f}% {wk*100:>4.0f}% {i['close_pos']:>3.2f}  "
          f"{im1['color']:>7} {im1['range_atr']:>5.1f}x {im1['body_pct']*100:>5.0f}%  "
          f"{im2['color']:>7}  "
          f"{'Y' if f['i_engulfs_im1_body'] else '·':>3} "
          f"{'Y' if f['i_extends_im1'] else '·':>3} "
          f"{'Y' if f['i_closes_inside_im1'] else '·':>2} "
          f"{'Y' if f['opposite_colors'] else '·':>3} "
          f"{'Y' if f['three_same_color'] else '·':>3} "
          f"{'Y' if f['v_shape'] else '·':>2}")


# Aggregate stats per feature
print(f"\n{'='*120}")
print(f" Feature aggregate stats — important (n=18) vs noise (n=23)")
print(f"{'='*120}")


def stat_pair(name, fn):
    imps = [fn(f) for f in post_F1 if f["is_important"]]
    nois = [fn(f) for f in post_F1 if not f["is_important"]]

    if all(isinstance(x, (int, bool, float)) for x in imps + nois):
        imp_avg = sum(imps) / len(imps)
        noi_avg = sum(nois) / len(nois)
        print(f"  {name:<46} imp_mean={imp_avg:>6.2f}  noise_mean={noi_avg:>6.2f}  "
              f"Δ={imp_avg-noi_avg:>+6.2f}")


stat_pair("i.range_atr", lambda f: f["i"]["range_atr"])
stat_pair("i.body_pct", lambda f: f["i"]["body_pct"])
stat_pair("i.relevant_wick_pct (rejection)",
          lambda f: f["i"]["upper_pct"] if f["dir"] == "high" else f["i"]["lower_pct"])
stat_pair("i.opposite_wick_pct",
          lambda f: f["i"]["lower_pct"] if f["dir"] == "high" else f["i"]["upper_pct"])
stat_pair("i.close_pos", lambda f: f["i"]["close_pos"])
stat_pair("im1.range_atr", lambda f: f["i_1"]["range_atr"])
stat_pair("im1.body_pct", lambda f: f["i_1"]["body_pct"])
stat_pair("i_range_vs_im1", lambda f: f["i_range_vs_im1"])
stat_pair("i_body_vs_im1", lambda f: f["i_body_vs_im1"])
stat_pair("i_engulfs_im1_body", lambda f: int(f["i_engulfs_im1_body"]))
stat_pair("i_extends_im1", lambda f: int(f["i_extends_im1"]))
stat_pair("i_closes_inside_im1", lambda f: int(f["i_closes_inside_im1"]))
stat_pair("opposite_colors", lambda f: int(f["opposite_colors"]))
stat_pair("three_same_color", lambda f: int(f["three_same_color"]))
stat_pair("v_shape", lambda f: int(f["v_shape"]))


# Color breakdown
print(f"\n--- Pivot bar color (i) ---")
for color in ("bull", "bear", "doji"):
    imps = [f for f in post_F1 if f["is_important"] and f["i"]["color"] == color]
    nois = [f for f in post_F1 if not f["is_important"] and f["i"]["color"] == color]
    print(f"  i={color}: imp={len(imps)}/18  noise={len(nois)}/23")

print(f"\n--- For FH only: i color × i-1 color ---")
fh_imps = [f for f in post_F1 if f["is_important"] and f["dir"] == "high"]
fh_nois = [f for f in post_F1 if not f["is_important"] and f["dir"] == "high"]
print(f"  FH important n={len(fh_imps)}, FH noise n={len(fh_nois)}")
for color_i in ("bull", "bear", "doji"):
    for color_im1 in ("bull", "bear", "doji"):
        imp_n = sum(1 for f in fh_imps if f["i"]["color"] == color_i and f["i_1"]["color"] == color_im1)
        noi_n = sum(1 for f in fh_nois if f["i"]["color"] == color_i and f["i_1"]["color"] == color_im1)
        if imp_n + noi_n > 0:
            print(f"    i={color_i}, i-1={color_im1}: imp={imp_n}  noise={noi_n}")

print(f"\n--- For FL only: i color × i-1 color ---")
fl_imps = [f for f in post_F1 if f["is_important"] and f["dir"] == "low"]
fl_nois = [f for f in post_F1 if not f["is_important"] and f["dir"] == "low"]
print(f"  FL important n={len(fl_imps)}, FL noise n={len(fl_nois)}")
for color_i in ("bull", "bear", "doji"):
    for color_im1 in ("bull", "bear", "doji"):
        imp_n = sum(1 for f in fl_imps if f["i"]["color"] == color_i and f["i_1"]["color"] == color_im1)
        noi_n = sum(1 for f in fl_nois if f["i"]["color"] == color_i and f["i_1"]["color"] == color_im1)
        if imp_n + noi_n > 0:
            print(f"    i={color_i}, i-1={color_im1}: imp={imp_n}  noise={noi_n}")


# Filter candidates
print(f"\n{'='*120}")
print(f" Top candidate filters")
print(f"{'='*120}")

# для FH (top) опасные паттерны i bear, i-1 bull (reversal candle = sign of top)
# для FL — i bull, i-1 bear

eval_filter("FH: i bear AND i-1 bull (top reversal candle setup)",
            lambda f: f["dir"] == "high" and f["i"]["color"] == "bear" and f["i_1"]["color"] == "bull")
eval_filter("FL: i bull AND i-1 bear (bottom reversal setup)",
            lambda f: f["dir"] == "low" and f["i"]["color"] == "bull" and f["i_1"]["color"] == "bear")
eval_filter("ABOVE both = full reversal pattern",
            lambda f: (f["dir"] == "high" and f["i"]["color"] == "bear" and f["i_1"]["color"] == "bull")
                   or (f["dir"] == "low" and f["i"]["color"] == "bull" and f["i_1"]["color"] == "bear"))

print()
eval_filter("opposite_colors (i vs i-1)", lambda f: f["opposite_colors"])
eval_filter("i_extends_im1 (i пробивает extremum i-1)", lambda f: f["i_extends_im1"])
eval_filter("i closes inside i-1 range", lambda f: f["i_closes_inside_im1"])
eval_filter("i_range_vs_im1 ≥ 1.0 (i bigger)", lambda f: f["i_range_vs_im1"] >= 1.0)
eval_filter("i_body_vs_im1 ≥ 1.0 (i body bigger)", lambda f: f["i_body_vs_im1"] >= 1.0)
eval_filter("NOT three_same_color (no continuation)", lambda f: not f["three_same_color"])
eval_filter("v_shape (i-2 same color as i, i-1 opposite)", lambda f: f["v_shape"])
