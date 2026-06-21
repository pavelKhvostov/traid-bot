"""F3 поиск: что отличает #27, #53 (noise) от important 3-same continuation.

Кандидаты:
  - 3-bar cumulative drift in R units (i-2.close to i.close)
  - new_low_in_N: i.low < min(low) в окне [-N, -3] на 12h
  - prev_opposite_distance в R и barах
  - pivot extremum sequence: (i-2,i-1,i) monotonically extending?
  - i.range и body аномалии
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

# ATR(20)
hi12 = np.array([b[2] for b in bars12])
lo12 = np.array([b[3] for b in bars12])
cl12 = np.array([b[4] for b in bars12])
prev_cl = np.concatenate([[cl12[0]], cl12[:-1]])
tr12 = np.maximum.reduce([hi12 - lo12, np.abs(hi12 - prev_cl), np.abs(lo12 - prev_cl)])
atr20 = np.zeros_like(tr12)
for i in range(len(tr12)):
    atr20[i] = tr12[:i+1].mean() if i < 19 else tr12[i-19:i+1].mean()


candles = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars12]
fractals = []
for i in range(2, len(candles) - 2):
    f = detect_fractal(candles[i-2:i+3], n=2)
    if f is None: continue
    if candles[i].open_time < START_MS: continue
    fractals.append({"dir": f.direction, "level": f.level, "idx": i,
                     "center_ts": candles[i].open_time})


def color(b):
    if b[4] > b[1]: return "bull"
    if b[4] < b[1]: return "bear"
    return "doji"


def left_ext_5(f):
    bidx = f["idx"]
    win_lo = max(0, bidx - 5); win_hi = bidx
    slice_ = bars12[win_lo:win_hi]
    if not slice_: return True
    if f["dir"] == "high":
        return f["level"] > max(b[2] for b in slice_)
    else:
        return f["level"] < min(b[3] for b in slice_)


def f2_pass(f):
    bidx = f["idx"]
    c0, c1, c2 = color(bars12[bidx]), color(bars12[bidx-1]), color(bars12[bidx-2])
    opp = c0 != c1 and "doji" not in (c0, c1)
    three = c0 == c1 == c2 and c0 != "doji"
    return opp or three


for n, f in enumerate(fractals, 1):
    f["num"] = n
    f["is_important"] = (n in IMPORTANT)
    f["F1_pass"] = left_ext_5(f)
    f["F2_pass"] = f2_pass(f) if f["F1_pass"] else False


post_F1F2 = [f for f in fractals if f["F1_pass"] and f["F2_pass"]]

# Add features
def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H:%M')


for f in post_F1F2:
    bidx = f["idx"]
    b0 = bars12[bidx]; b1 = bars12[bidx-1]; b2 = bars12[bidx-2]
    atr = atr20[bidx]
    f["c0"], f["c1"], f["c2"] = color(b0), color(b1), color(b2)
    f["three_same"] = f["c0"] == f["c1"] == f["c2"] and f["c0"] != "doji"
    f["opp_colors"] = f["c0"] != f["c1"] and "doji" not in (f["c0"], f["c1"])

    # 3-bar cumulative drift R (signed: positive for FH expected drift up)
    if f["dir"] == "high":
        drift = b0[4] - b2[4]  # close to close — should be positive for top
        new_extreme = b0[2] > max(b1[2], b2[2])  # i.high above prior 2
        # new_high_in_N: i.high > max high in [-N, -3]
        def new_high_N(N):
            lo = max(0, bidx - N); hi = bidx - 2
            if lo >= hi: return True
            return b0[2] > max(bx[2] for bx in bars12[lo:hi])
        f["new_high_5"] = new_high_N(5)  # within left_ext_5 window — should already be Y by F1
        f["new_high_10"] = new_high_N(10)
        f["new_high_20"] = new_high_N(20)
    else:
        drift = b2[4] - b0[4]  # for FL: close at i should be below i-2 close
        new_extreme = b0[3] < min(b1[3], b2[3])
        def new_low_N(N):
            lo = max(0, bidx - N); hi = bidx - 2
            if lo >= hi: return True
            return b0[3] < min(bx[3] for bx in bars12[lo:hi])
        f["new_low_5"] = new_low_N(5)
        f["new_low_10"] = new_low_N(10)
        f["new_low_20"] = new_low_N(20)

    f["drift_3bar_R"] = drift / max(atr, 1e-9)
    f["i_monotonic_extreme"] = new_extreme

    # Pivot bar size
    rng = b0[2] - b0[3] if b0[2] > b0[3] else 1e-9
    body = abs(b0[4] - b0[1])
    f["range_atr"] = rng / max(atr, 1e-9)
    f["body_pct"] = body / rng

    # prev_opposite distance
    prev_opp = None
    for p in reversed(fractals[:f["num"] - 1]):
        if p["dir"] != f["dir"]:
            prev_opp = p; break
    if prev_opp:
        f["dist_opp_bars"] = (f["center_ts"] - prev_opp["center_ts"]) // TF12_MS
        f["dist_opp_pct"] = abs(f["level"] - prev_opp["level"]) / f["level"] * 100
        f["dist_opp_R"] = abs(f["level"] - prev_opp["level"]) / max(atr, 1e-9)
    else:
        f["dist_opp_bars"] = 999; f["dist_opp_pct"] = 999; f["dist_opp_R"] = 999

    # Also: distance to prev same-type
    prev_same = None
    for p in reversed(fractals[:f["num"] - 1]):
        if p["dir"] == f["dir"]:
            prev_same = p; break
    if prev_same:
        f["dist_same_bars"] = (f["center_ts"] - prev_same["center_ts"]) // TF12_MS
        f["dist_same_pct"] = abs(f["level"] - prev_same["level"]) / f["level"] * 100
    else:
        f["dist_same_bars"] = 999; f["dist_same_pct"] = 999


# Print focused comparison
print(f"\n{'='*150}")
print(f" Continuation 3-same fractals (post-F1∩F2)")
print(f"{'='*150}")
print(f"  {'#':>3} {'★':>1} {'tp':>3} {'level':>6}  {'pattern':>10} "
      f"{'drift_R':>7} {'r/a':>4} {'body%':>5} "
      f"{'nL5':>3} {'nL10':>4} {'nL20':>4} "
      f"{'dOPbar':>6} {'dOP%':>5} {'dOP_R':>5} "
      f"{'dSAMbar':>7} {'dSAM%':>5}")
print("-" * 150)
# Filter only 3-same fractals
three_same_set = [f for f in post_F1F2 if f["three_same"]]
print(f"  Total 3-same: {len(three_same_set)}")
for f in three_same_set:
    star = "★" if f["is_important"] else " "
    glyph = "FH" if f["dir"] == "high" else "FL"
    if f["dir"] == "high":
        nL5, nL10, nL20 = f["new_high_5"], f["new_high_10"], f["new_high_20"]
    else:
        nL5, nL10, nL20 = f["new_low_5"], f["new_low_10"], f["new_low_20"]
    print(f"  {f['num']:>3} {star:>1} {glyph:>3} {f['level']:>6.0f}  "
          f"{f['c2'][0]+f['c1'][0]+f['c0'][0]:>10} "
          f"{f['drift_3bar_R']:>+6.2f}x {f['range_atr']:>3.1f}x {f['body_pct']*100:>4.0f}% "
          f"{'Y' if nL5 else '·':>3} "
          f"{'Y' if nL10 else '·':>4} "
          f"{'Y' if nL20 else '·':>4} "
          f"{f['dist_opp_bars']:>6} {f['dist_opp_pct']:>4.1f} {f['dist_opp_R']:>4.1f}x "
          f"{f['dist_same_bars']:>7} {f['dist_same_pct']:>4.1f}")


# Now look at all post-F1F2 with same view
print(f"\n{'='*150}")
print(f" ALL post-F1∩F2 (35)")
print(f"{'='*150}")
print(f"  {'#':>3} {'★':>1} {'tp':>3} {'level':>6}  {'pattern':>10}  "
      f"{'drift_R':>7} {'r/a':>4} "
      f"{'nNew10':>6} {'nNew20':>6} "
      f"{'dSAM%':>5}  notes")
print("-" * 150)
for f in post_F1F2:
    star = "★" if f["is_important"] else " "
    glyph = "FH" if f["dir"] == "high" else "FL"
    if f["dir"] == "high":
        n10, n20 = f["new_high_10"], f["new_high_20"]
    else:
        n10, n20 = f["new_low_10"], f["new_low_20"]
    pattern = "3-same" if f["three_same"] else ("opp" if f["opp_colors"] else "?")
    note = ""
    if f["num"] in (27, 53): note = "← user-marked TO REMOVE"
    print(f"  {f['num']:>3} {star:>1} {glyph:>3} {f['level']:>6.0f}  {pattern:>10}  "
          f"{f['drift_3bar_R']:>+6.2f}x {f['range_atr']:>3.1f}x "
          f"{'Y' if n10 else '·':>6} "
          f"{'Y' if n20 else '·':>6} "
          f"{f['dist_same_pct']:>4.1f}  {note}")


# Test specific filters for #27 and #53
def eval_filter(name, pred):
    kept = [f for f in post_F1F2 if pred(f)]
    imp = sum(1 for f in kept if f["is_important"])
    lost = 18 - imp
    noise = len(kept) - imp
    keeps_27 = any(f["num"] == 27 and pred(f) for f in post_F1F2)
    keeps_53 = any(f["num"] == 53 and pred(f) for f in post_F1F2)
    print(f"  {name:<58} keep={len(kept):>3}  imp={imp:>2}/18  lost={lost:>2}  noise={noise:>3}  "
          f"#27={'KEEP' if keeps_27 else 'CUT '}  #53={'KEEP' if keeps_53 else 'CUT '}")
    if lost > 0 and lost <= 5:
        lost_ids = [f["num"] for f in post_F1F2 if f["is_important"] and not pred(f)]
        print(f"      lost imp: {lost_ids}")


print(f"\n{'='*120}")
print(f" F3 candidates (must CUT #27 AND #53, KEEP all 18 imp)")
print(f"{'='*120}")
# new_extreme on left in N bars
for N in [5, 7, 10, 15, 20]:
    eval_filter(f"new_extreme_in_{N} (i is strict ext vs [-{N},-3])",
                lambda f, N=N: (f["new_high_10"] if f["dir"]=="high" else f["new_low_10"])
                if N == 10 else (f["new_high_20"] if f["dir"]=="high" else f["new_low_20"]) if N == 20
                else (f["new_high_5"] if f["dir"]=="high" else f["new_low_5"]) if N == 5
                else True)

# Use new_low_N more directly
eval_filter("new_extreme_in_5 (strict)",
            lambda f: f["new_high_5"] if f["dir"]=="high" else f["new_low_5"])
eval_filter("new_extreme_in_10 (strict)",
            lambda f: f["new_high_10"] if f["dir"]=="high" else f["new_low_10"])
eval_filter("new_extreme_in_20 (strict)",
            lambda f: f["new_high_20"] if f["dir"]=="high" else f["new_low_20"])

print()
# drift threshold
for thr in [-0.5, -1.0, -1.5, -2.0]:
    eval_filter(f"drift_3bar_R ≥ {abs(thr)} in expected dir",
                lambda f, t=thr: f["drift_3bar_R"] >= abs(t))
print()
# Combinations
eval_filter("new_extreme_10 OR opp_colors",
            lambda f: f["opp_colors"] or (f["new_high_10"] if f["dir"]=="high" else f["new_low_10"]))
eval_filter("new_extreme_20 OR opp_colors",
            lambda f: f["opp_colors"] or (f["new_high_20"] if f["dir"]=="high" else f["new_low_20"]))
eval_filter("new_extreme_10 (3-same only) OR opp_colors",
            lambda f: f["opp_colors"] or (f["three_same"] and (f["new_high_10"] if f["dir"]=="high" else f["new_low_10"])))
eval_filter("new_extreme_20 (3-same only) OR opp_colors",
            lambda f: f["opp_colors"] or (f["three_same"] and (f["new_high_20"] if f["dir"]=="high" else f["new_low_20"])))

print()
# More combos
eval_filter("range_atr ≥ 1.0 OR opp_colors",
            lambda f: f["opp_colors"] or f["range_atr"] >= 1.0)
eval_filter("range_atr ≥ 1.0 (3-same only) OR opp_colors",
            lambda f: f["opp_colors"] or (f["three_same"] and f["range_atr"] >= 1.0))
