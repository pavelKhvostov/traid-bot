"""F3 — добавляем money_hands и trend_line_asvk на 12h.

Гипотезы:
  - money_hands color на pivot bar = bullish-weakening/bearish-strengthening etc.
  - trend_line_asvk color (up/down) — pivot на верном boundary?
  - bw2 value at pivot
  - MF (Money Flow) value
  - stochastics (rsiMod, stcRsiMod) extremes
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
from indicators.money_hands_asvk import money_hands
from indicators.trend_line_asvk import trend_line_asvk

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
TF12_MS = 12 * 3600_000
START_MS = int(datetime(2026, 2, 4, 0, 0, tzinfo=MSK).timestamp() * 1000)
IMPORTANT = {1, 3, 4, 5, 9, 10, 11, 14, 15, 20, 23, 26, 29, 40, 41, 42, 47, 48}
TO_REMOVE = {27, 53}


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
print(f"  {len(bars12)} 12h bars")


# money_hands и trend_line на 12h
# money_hands signature: bars = (o, h, l, c, v) BUT v unused. Wait — check
# actually from code: bars is (o, h, l, c, v). But h/l used.
# Let me adapt: pass (open, high, low, close, vol=0) per bar
mh_bars = [(b[1], b[2], b[3], b[4], 0.0) for b in bars12]
print("Computing money_hands on 12h...")
mh = money_hands(mh_bars)
# Returns dict with bw2, color, mf, rsi_mod, stc_rsi_mod

print("Computing trend_line_asvk on 12h...")
closes12 = [b[4] for b in bars12]
tl = trend_line_asvk(closes12)


# Fractals
candles12 = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars12]
fractals = []
for i in range(2, len(candles12) - 2):
    f = detect_fractal(candles12[i-2:i+3], n=2)
    if f is None: continue
    if candles12[i].open_time < START_MS: continue
    fractals.append({"dir": f.direction, "level": f.level, "idx": i,
                     "center_ts": candles12[i].open_time})


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

# Add indicator features per pivot
for f in post_F1F2:
    bidx = f["idx"]
    f["mh_bw2"] = mh["bw2"][bidx] if bidx < len(mh["bw2"]) else None
    f["mh_color"] = mh["color"][bidx] if bidx < len(mh["color"]) else None
    f["mh_mf"] = mh["mf"][bidx] if bidx < len(mh["mf"]) else None
    f["mh_rsi_mod"] = mh["rsi_mod"][bidx] if bidx < len(mh["rsi_mod"]) else None
    f["mh_stc_rsi_mod"] = mh["stc_rsi_mod"][bidx] if bidx < len(mh["stc_rsi_mod"]) else None
    f["tl_color"] = tl["color"][bidx] if bidx < len(tl["color"]) else None
    f["tl_hull"] = tl["mhull"][bidx] if bidx < len(tl["mhull"]) else None
    if f["tl_hull"] is not None:
        b = bars12[bidx]
        f["tl_close_vs_hull"] = (b[4] - f["tl_hull"]) / b[4] * 100  # % above hull


# Print table
print(f"\n{'='*180}")
print(f" Indicator state (12h indicators)")
print(f"{'='*180}")
print(f"  {'#':>3} {'★':>1} {'tag':>5} {'tp':>3} {'level':>6}  "
      f"{'bw2':>7} {'col':>4} {'MF':>6} {'rsi':>5} {'stcR':>5}  "
      f"{'TL_c':>5} {'TL_h':>8} {'cl-h%':>6}")
print("-" * 180)
for f in sorted(post_F1F2, key=lambda x: x["num"]):
    star = "★" if f["is_important"] else " "
    glyph = "FH" if f["dir"] == "high" else "FL"
    tag = "RMV" if f["num"] in TO_REMOVE else ("imp" if f["is_important"] else "nse")
    bw2 = f["mh_bw2"] if f["mh_bw2"] is not None else 0
    mf = f["mh_mf"] if f["mh_mf"] is not None else 0
    rsi = f["mh_rsi_mod"] if f["mh_rsi_mod"] is not None else 0
    stc = f["mh_stc_rsi_mod"] if f["mh_stc_rsi_mod"] is not None else 0
    cvh = f.get("tl_close_vs_hull", 0)
    print(f"  {f['num']:>3} {star:>1} {tag:>5} {glyph:>3} {f['level']:>6.0f}  "
          f"{bw2:>+6.2f} {(f['mh_color'] or '?'):>4} "
          f"{mf:>+5.2f} {rsi:>+4.1f} {stc:>+4.1f}  "
          f"{(f['tl_color'] or '?'):>5} {(f['tl_hull'] or 0):>7.0f} {cvh:>+5.2f}%")


def eval_filter(name, pred):
    kept = [f for f in post_F1F2 if pred(f)]
    imp = sum(1 for f in kept if f["is_important"])
    lost = 18 - imp
    noise = len(kept) - imp
    keeps_27 = any(f["num"] == 27 and pred(f) for f in post_F1F2)
    keeps_53 = any(f["num"] == 53 and pred(f) for f in post_F1F2)
    print(f"  {name:<60} keep={len(kept):>3}  imp={imp:>2}/18  noise={noise:>3}  "
          f"#27={'KEEP' if keeps_27 else 'CUT '}  #53={'KEEP' if keeps_53 else 'CUT '}")
    if lost > 0 and lost <= 5:
        lost_ids = [f["num"] for f in post_F1F2 if f["is_important"] and not pred(f)]
        print(f"      lost imp: {lost_ids}")


# Focus on important 3-same vs noise 3-same
print(f"\n{'='*120}")
print(f" Direct compare 3-same (5 imp + 7 noise)")
print(f"{'='*120}")
focus = {10, 11, 14, 21, 23, 27, 40, 50, 51, 53, 54, 56}
for f in sorted(post_F1F2, key=lambda x: x["num"]):
    if f["num"] not in focus: continue
    star = "★ IMP" if f["is_important"] else "✗ nse" + (" (TO RMV)" if f["num"] in TO_REMOVE else "")
    glyph = "FH" if f["dir"] == "high" else "FL"
    print(f"  {f['num']:>3} {star} {glyph}: "
          f"bw2={(f['mh_bw2'] or 0):+.2f} color={f['mh_color']} "
          f"MF={(f['mh_mf'] or 0):+.2f} rsiMod={(f['mh_rsi_mod'] or 0):+.1f} stc={(f['mh_stc_rsi_mod'] or 0):+.1f} "
          f"TL_color={f['tl_color']} close-hull={(f.get('tl_close_vs_hull') or 0):+.2f}%")


print(f"\n{'='*120}")
print(f" F3 candidate filters (must CUT #27 AND #53, KEEP 18 imp)")
print(f"{'='*120}")

# trend_line color
eval_filter("FH: TL_color='down'; FL: TL_color='up' (counter-trend pivot)",
            lambda f: (f["dir"]=="high" and f["tl_color"]=="down")
                   or (f["dir"]=="low" and f["tl_color"]=="up"))
eval_filter("FH: TL_color='up'; FL: TL_color='down' (with-trend pivot)",
            lambda f: (f["dir"]=="high" and f["tl_color"]=="up")
                   or (f["dir"]=="low" and f["tl_color"]=="down"))

# bw2 sign
eval_filter("FH: bw2 < 0; FL: bw2 > 0 (counter)",
            lambda f: (f["dir"]=="high" and (f["mh_bw2"] or 0) < 0)
                   or (f["dir"]=="low" and (f["mh_bw2"] or 0) > 0))
eval_filter("FH: bw2 > 0; FL: bw2 < 0 (with momentum)",
            lambda f: (f["dir"]=="high" and (f["mh_bw2"] or 0) > 0)
                   or (f["dir"]=="low" and (f["mh_bw2"] or 0) < 0))

# bw2 threshold
for thr in [20, 40, 60, 80]:
    eval_filter(f"FH: bw2 > {thr}; FL: bw2 < {-thr}",
                lambda f, t=thr: (f["dir"]=="high" and (f["mh_bw2"] or 0) > t)
                              or (f["dir"]=="low" and (f["mh_bw2"] or 0) < -t))

# rsi_mod (stoch fast)
for thr in [40, 60, 70, 80]:
    eval_filter(f"FH: rsiMod > {thr}; FL: rsiMod < {-thr}",
                lambda f, t=thr: (f["dir"]=="high" and (f["mh_rsi_mod"] or 0) > t)
                              or (f["dir"]=="low" and (f["mh_rsi_mod"] or 0) < -t))

# close vs hull distance
for thr in [0.5, 1.0, 2.0, 3.0]:
    eval_filter(f"FH: close above hull by >{thr}%; FL: close below hull by >{thr}%",
                lambda f, t=thr: (f["dir"]=="high" and f.get("tl_close_vs_hull", 0) > t)
                              or (f["dir"]=="low" and f.get("tl_close_vs_hull", 0) < -t))
