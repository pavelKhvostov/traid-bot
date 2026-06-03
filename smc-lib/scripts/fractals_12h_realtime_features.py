"""Realtime (anti-look-ahead) features для 12h-фракталов.

При моменте confirmation (= pivot_center + 3*12h) доступны только:
  - Pivot bar полностью (anatomy)
  - 2 LEFT neighbor bars (used in Williams detection)
  - 2 RIGHT neighbor bars (used in Williams detection)
  - 1 confirmation bar (3-й справа от pivot)
  - Все ранее CONFIRMED фракталы (D fractal confirmed if its center+72h ≤ now)

Фичи (все causal):

A) Pivot anatomy:
   - wick_pct, body_pct
   - range_atr (range / ATR(20))
   - vol_rel (vol / SMA(20))
   - pivot_color (bull/bear/doji)

B) Post-confirmation displacement (3 bars right):
   - post_drift_R: drift цены в направлении ОТ pivot за 3 bars / ATR
     для FH = (pivot.high − min(close bars+1..+3)) / ATR
     для FL = (max(close bars+1..+3) − pivot.low) / ATR
   - post_color_balance: сколько баров справа в направлении reversal
     FH: bear bars / 3; FL: bull bars / 3
   - first_bar_strong: первый бар справа сильно в направлении reversal
     (body_pct ≥ 0.5 AND правильный цвет)

C) Left extension (фрактал отдельно стоит):
   - left_extreme_5: pivot.high > all highs в [-5,-3]; pivot.low < all lows в [-5,-3]
   - left_extreme_10: то же в [-10,-3]

D) Structure context:
   - hh_or_ll vs предыдущий confirmed same-type
   - dist_prev_pct: |level - prev_same.level| / level
   - dist_prev_bars
   - dist_to_recent_opposite_bars: бары до ближайшего противоположного fractal

E) HTF confluence (только CONFIRMED HTF fractals):
   - d_conf_strict: D fractal same dir с center_ts ≤ our_pivot_center - 36h (D confirms +72h)
                   AND |level diff| ≤ 0.3%
   - w_conf_strict: W fractal same dir, confirmed by our confirm time
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
TF_W_MS = 7 * 24 * MS_HOUR

START_MSK = datetime(2026, 2, 4, 0, 0, tzinfo=MSK)
START_MS = int(START_MSK.timestamp() * 1000)

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


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H:%M')


print("Loading...")
data = load_1m()

bars12 = aggregate(data, TF12_MS)
barsD = aggregate(data, TF_D_MS)
barsW = aggregate_weekly_mon(data)


def to_candles(bars):
    return [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]


can12 = to_candles(bars12); canD = to_candles(barsD); canW = to_candles(barsW)


# ATR(20), SMA(20) для vol на 12h
hi12 = np.array([b[2] for b in bars12])
lo12 = np.array([b[3] for b in bars12])
cl12 = np.array([b[4] for b in bars12])
vol12 = np.array([b[5] for b in bars12])
prev_cl = np.concatenate([[cl12[0]], cl12[:-1]])
tr12 = np.maximum.reduce([hi12 - lo12, np.abs(hi12 - prev_cl), np.abs(lo12 - prev_cl)])
atr20 = np.zeros_like(tr12)
for i in range(len(tr12)):
    atr20[i] = tr12[:i+1].mean() if i < 19 else tr12[i-19:i+1].mean()
vol_sma20 = np.zeros_like(vol12)
for i in range(len(vol12)):
    vol_sma20[i] = vol12[:i+1].mean() if i < 19 else vol12[i-19:i+1].mean()


# All D and W fractals with confirm_ts
def all_fractals_with_confirm(candles, tf_ms, n=2):
    out = []
    for i in range(n, len(candles) - n):
        f = detect_fractal(candles[i-n:i+n+1], n=n)
        if f is None: continue
        out.append({"dir": f.direction, "level": f.level,
                    "center_ts": candles[i].open_time,
                    "confirm_ts": candles[i].open_time + (n+1) * tf_ms})
    return out


fr_D = all_fractals_with_confirm(canD, TF_D_MS, n=2)
fr_W = all_fractals_with_confirm(canW, TF_W_MS, n=2)


# Detect 12h fractals from START
fractals = []
for i in range(2, len(can12) - 2):
    f = detect_fractal(can12[i-2:i+3], n=2)
    if f is None: continue
    if can12[i].open_time < START_MS: continue
    fractals.append({
        "dir": f.direction, "level": f.level, "idx": i,
        "center_ts": can12[i].open_time,
        "confirm_ts": can12[i].open_time + 3 * TF12_MS,
        "pivot": bars12[i],
    })


# === Compute features ===
for n_idx, f in enumerate(fractals, 1):
    f["num"] = n_idx
    bidx = f["idx"]
    pb = bars12[bidx]
    o, h_, l_, c_, v = pb[1], pb[2], pb[3], pb[4], pb[5]
    rng = h_ - l_ if h_ > l_ else 1e-9

    # A) Pivot anatomy
    body = abs(c_ - o)
    f["wick_pct"] = ((h_ - max(o, c_)) if f["dir"] == "high" else (min(o, c_) - l_)) / rng
    f["body_pct"] = body / rng
    f["range_atr"] = rng / max(atr20[bidx], 1e-9)
    f["vol_rel"] = v / max(vol_sma20[bidx], 1e-9)
    f["pivot_color"] = "bull" if c_ > o else ("bear" if c_ < o else "doji")

    # B) Post-confirmation displacement (bars i+1, i+2, i+3)
    post_bars = bars12[bidx+1:bidx+4]  # 3 bars: i+1, i+2, i+3
    if len(post_bars) >= 3:
        if f["dir"] == "high":
            min_close_post = min(b[4] for b in post_bars)
            drift = h_ - min_close_post
            color_balance = sum(1 for b in post_bars if b[4] < b[1]) / 3.0
            first_bar = post_bars[0]
            first_body = abs(first_bar[4] - first_bar[1])
            first_range = first_bar[2] - first_bar[3] if first_bar[2] > first_bar[3] else 1e-9
            first_strong = (first_bar[4] < first_bar[1]) and (first_body / first_range >= 0.5)
        else:
            max_close_post = max(b[4] for b in post_bars)
            drift = max_close_post - l_
            color_balance = sum(1 for b in post_bars if b[4] > b[1]) / 3.0
            first_bar = post_bars[0]
            first_body = abs(first_bar[4] - first_bar[1])
            first_range = first_bar[2] - first_bar[3] if first_bar[2] > first_bar[3] else 1e-9
            first_strong = (first_bar[4] > first_bar[1]) and (first_body / first_range >= 0.5)
        f["post_drift_R"] = drift / max(atr20[bidx], 1e-9)
        f["post_color"] = color_balance  # 0..1
        f["first_strong"] = first_strong
    else:
        f["post_drift_R"] = 0; f["post_color"] = 0; f["first_strong"] = False

    # C) Left extension (avoid overlap с Williams окном [-2,+2])
    # left_extreme_5 means: pivot extremum in [-5, -3] left bars only
    def left_ext_check(N_back):
        win_lo = max(0, bidx - N_back); win_hi = bidx - 2  # exclude [-2,-1, pivot]
        if win_lo >= win_hi: return True  # no bars to compare → trivially true
        slice_ = bars12[win_lo:win_hi]
        if f["dir"] == "high":
            return h_ > max(b[2] for b in slice_)
        else:
            return l_ < min(b[3] for b in slice_)

    f["left_ext_5"] = left_ext_check(5)
    f["left_ext_10"] = left_ext_check(10)
    f["left_ext_20"] = left_ext_check(20)

    # D) Structure context
    prev_same = None
    prev_opposite = None
    for p in reversed(fractals[:n_idx - 1]):
        if p["dir"] == f["dir"] and prev_same is None:
            prev_same = p
        if p["dir"] != f["dir"] and prev_opposite is None:
            prev_opposite = p
        if prev_same and prev_opposite: break

    if prev_same is None:
        f["hh_or_ll"] = "N/A"; f["dist_same_bars"] = 0; f["dist_same_pct"] = 0
    else:
        if f["dir"] == "high":
            f["hh_or_ll"] = "HH" if f["level"] > prev_same["level"] else "LH"
        else:
            f["hh_or_ll"] = "LL" if f["level"] < prev_same["level"] else "HL"
        f["dist_same_bars"] = (f["center_ts"] - prev_same["center_ts"]) // TF12_MS
        f["dist_same_pct"] = abs(f["level"] - prev_same["level"]) / f["level"] * 100

    if prev_opposite:
        f["dist_opp_bars"] = (f["center_ts"] - prev_opposite["center_ts"]) // TF12_MS
    else:
        f["dist_opp_bars"] = 0

    # E) HTF confluence (strict causal)
    confirm_ts = f["confirm_ts"]
    d_conf = False
    for fd in fr_D:
        if fd["dir"] != f["dir"]: continue
        if fd["confirm_ts"] > confirm_ts: continue  # not yet confirmed at our moment
        if abs(fd["level"] - f["level"]) / f["level"] > 0.003: continue
        if abs(fd["center_ts"] - f["center_ts"]) > 2 * TF_D_MS: continue
        d_conf = True; break
    f["d_conf"] = d_conf

    w_conf = False
    for fw in fr_W:
        if fw["dir"] != f["dir"]: continue
        if fw["confirm_ts"] > confirm_ts: continue
        if abs(fw["level"] - f["level"]) / f["level"] > 0.005: continue
        if abs(fw["center_ts"] - f["center_ts"]) > 7 * TF_D_MS: continue
        w_conf = True; break
    f["w_conf"] = w_conf

    f["is_important"] = (n_idx in IMPORTANT)


# === Print table ===
print(f"\n{'='*144}")
print(f" REALTIME (anti-look-ahead) features — 56 fractals (★ = important)")
print(f"{'='*144}")
print(f"{'#':>3} {'★':>1} {'tp':>3} {'center':<14} {'level':>6} "
      f"{'wick%':>5} {'body%':>5} {'rng/atr':>6} {'vol':>5} "
      f"{'drft_R':>6} {'col':>4} {'1st':>3} {'L5':>2} {'L10':>3} {'L20':>3} "
      f"{'rel':>4} {'dB':>3} {'dP%':>4} {'D':>2} {'W':>2}")
print("-" * 144)
for f in fractals:
    star = "★" if f["is_important"] else " "
    glyph = "FH" if f["dir"] == "high" else "FL"
    print(f"{f['num']:>3} {star:>1} {glyph:>3} {fmt(f['center_ts']):<14} "
          f"{f['level']:>6.0f} "
          f"{f['wick_pct']*100:>4.0f}% {f['body_pct']*100:>4.0f}% "
          f"{f['range_atr']:>5.2f}x {f['vol_rel']:>4.2f}x "
          f"{f['post_drift_R']:>5.2f}x {f['post_color']:>4.2f} "
          f"{'Y' if f['first_strong'] else '·':>3} "
          f"{'Y' if f['left_ext_5'] else '·':>2} "
          f"{'Y' if f['left_ext_10'] else '·':>3} "
          f"{'Y' if f['left_ext_20'] else '·':>3} "
          f"{f['hh_or_ll']:>4} {f['dist_same_bars']:>3} {f['dist_same_pct']:>3.1f} "
          f"{'Y' if f['d_conf'] else '·':>2} "
          f"{'Y' if f['w_conf'] else '·':>2}")


def eval_rule(name, pred):
    kept = [f for f in fractals if pred(f)]
    imp_kept = sum(1 for f in kept if f["is_important"])
    imp_lost = 18 - imp_kept
    noise_kept = len(kept) - imp_kept
    recall = imp_kept / 18 * 100
    prec = imp_kept / len(kept) * 100 if kept else 0
    f1 = 2 * recall * prec / (recall + prec) if (recall + prec) > 0 else 0
    print(f"  {name:<58} keep={len(kept):>3}  imp={imp_kept:>2}/18  "
          f"lost={imp_lost:>2}  noise={noise_kept:>3}  "
          f"recall={recall:>5.1f}%  prec={prec:>5.1f}%  F1={f1:>5.1f}")
    if imp_lost > 0 and imp_lost <= 8:
        lost_ids = [f["num"] for f in fractals if f["is_important"] and not pred(f)]
        print(f"      lost: {lost_ids}")


print(f"\n{'='*120}")
print(f" REALTIME single-feature filters")
print(f"{'='*120}")

# post_drift_R
for thr in [0.3, 0.5, 0.7, 1.0, 1.3]:
    eval_rule(f"post_drift_R ≥ {thr}", lambda f, t=thr: f["post_drift_R"] >= t)
print()

# post_color
for thr in [0.34, 0.67, 1.0]:
    eval_rule(f"post_color ≥ {thr}", lambda f, t=thr: f["post_color"] >= t)
print()

# first_strong
eval_rule("first_strong", lambda f: f["first_strong"])
print()

# left_ext
eval_rule("left_ext_5", lambda f: f["left_ext_5"])
eval_rule("left_ext_10", lambda f: f["left_ext_10"])
eval_rule("left_ext_20", lambda f: f["left_ext_20"])
print()

# D conf strict
eval_rule("d_conf (strict causal)", lambda f: f["d_conf"])
eval_rule("w_conf (strict causal)", lambda f: f["w_conf"])
eval_rule("d_conf OR w_conf (strict)", lambda f: f["d_conf"] or f["w_conf"])
print()

# range, vol, body
for thr in [0.8, 1.0, 1.3]:
    eval_rule(f"range_atr ≥ {thr}", lambda f, t=thr: f["range_atr"] >= t)
print()

eval_rule("HH or LL", lambda f: f["hh_or_ll"] in ("HH", "LL"))
print()


print(f"\n{'='*120}")
print(f" REALTIME combo filters")
print(f"{'='*120}")
eval_rule("post_drift_R ≥ 0.5 OR d_conf", lambda f: f["post_drift_R"] >= 0.5 or f["d_conf"])
eval_rule("post_drift_R ≥ 0.5 OR left_ext_10", lambda f: f["post_drift_R"] >= 0.5 or f["left_ext_10"])
eval_rule("post_drift_R ≥ 0.3 OR left_ext_10 OR d_conf",
          lambda f: f["post_drift_R"] >= 0.3 or f["left_ext_10"] or f["d_conf"])
eval_rule("post_drift_R ≥ 0.5 AND post_color ≥ 0.67",
          lambda f: f["post_drift_R"] >= 0.5 and f["post_color"] >= 0.67)
eval_rule("left_ext_10 AND post_drift_R ≥ 0.3",
          lambda f: f["left_ext_10"] and f["post_drift_R"] >= 0.3)
eval_rule("d_conf AND post_drift_R ≥ 0.3",
          lambda f: f["d_conf"] and f["post_drift_R"] >= 0.3)
eval_rule("(d_conf or left_ext_10) AND post_drift_R ≥ 0.3",
          lambda f: (f["d_conf"] or f["left_ext_10"]) and f["post_drift_R"] >= 0.3)
eval_rule("(d_conf or left_ext_10) AND first_strong",
          lambda f: (f["d_conf"] or f["left_ext_10"]) and f["first_strong"])
eval_rule("d_conf AND (left_ext_10 OR post_drift_R ≥ 0.5)",
          lambda f: f["d_conf"] and (f["left_ext_10"] or f["post_drift_R"] >= 0.5))
eval_rule("d_conf AND first_strong",
          lambda f: f["d_conf"] and f["first_strong"])
eval_rule("(post_drift_R ≥ 0.5) AND (left_ext_5 OR d_conf)",
          lambda f: f["post_drift_R"] >= 0.5 and (f["left_ext_5"] or f["d_conf"]))
eval_rule("(post_drift_R ≥ 0.3) AND (left_ext_5)",
          lambda f: f["post_drift_R"] >= 0.3 and f["left_ext_5"])
