"""Анализ фичей для 56 12h-фракталов; 18 помечены как важные (ground truth).

Цель: найти правила/комбинации, которые сохраняют ≥17/18 важных и режут
максимум из 38 неважных.

Фичи на каждый fractal:
  1. survive_h          — часов от confirm до first_touch (∞ если untouched)
  2. wick_pct           — relevant wick (upper для FH, lower для FL) / range pivot
  3. body_pct           — |close-open| / range
  4. range_atr_ratio    — range pivot / ATR(20, 12h)
  5. vol_relative       — pivot volume / SMA(20, 12h)
  6. hh_or_ll           — HH (FH выше prev FH) / LH; LL (FL ниже prev FL) / HL
  7. dist_to_prev_same_bars  — кол-во 12h баров до прошлого same-type fractal
  8. dist_to_prev_same_pct   — |level - prev_same_level| / level (%)
  9. d_confluence       — пересекается ли с D-fractal (±0.3% level, ±2 days center)
 10. w_confluence       — то же с W-fractal
 11. extreme_in_N_bars  — был ли level экстремум в окне ±N bars (=5 → ±2.5 дн)
                          для FH: level = strict max в [-N, +N] окне
                          для FL: level = strict min

Затем: для каждого правила (single feature threshold + комбо)
считаем recall (от 18 важных) и precision (важных в выбранном subset).
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
    mon_anchor = 1483315200000  # Monday
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
print(f"  12h={len(bars12)} D={len(barsD)} W={len(barsW)}")


def to_candles(bars):
    return [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]


can12 = to_candles(bars12); canD = to_candles(barsD); canW = to_candles(barsW)


# numpy 1m for first_touch
ts_arr = np.array([r[0] for r in data], dtype=np.int64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)


def first_touch(level, after_ts, kind):
    i0 = int(np.searchsorted(ts_arr, after_ts, side='left'))
    if i0 >= len(ts_arr): return None
    mask = hi_arr[i0:] >= level if kind == "high" else lo_arr[i0:] <= level
    nz = int(np.argmax(mask))
    if not mask[nz]: return None
    return int(ts_arr[i0 + nz])


# ATR(20) на 12h
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


# Detect ALL fractals on D and W (for confluence check) — даже до START_MS, чтобы доступны были
def all_fractals(candles, n=2):
    out = []
    for i in range(n, len(candles) - n):
        f = detect_fractal(candles[i-n:i+n+1], n=n)
        if f is None: continue
        out.append({"dir": f.direction, "level": f.level,
                    "center_ts": candles[i].open_time})
    return out


fr_D = all_fractals(canD, n=2)
fr_W = all_fractals(canW, n=2)
print(f"  D fractals={len(fr_D)} W fractals={len(fr_W)}")


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

# first_touch
for f in fractals:
    ft = first_touch(f["level"], f["confirm_ts"], f["dir"])
    f["first_touch"] = ft
    f["survive_h"] = ((ft - f["confirm_ts"]) / MS_HOUR) if ft else 10_000  # ∞ proxy


# === Compute features ===
for n_idx, f in enumerate(fractals, 1):
    f["num"] = n_idx
    bidx = f["idx"]
    o, h_, l_, c_, v = bars12[bidx][1], bars12[bidx][2], bars12[bidx][3], bars12[bidx][4], bars12[bidx][5]
    rng = h_ - l_
    if rng <= 0: rng = 1e-9

    # wick / body / range_atr
    body = abs(c_ - o)
    if f["dir"] == "high":
        rel_wick = h_ - max(o, c_)
    else:
        rel_wick = min(o, c_) - l_
    f["wick_pct"] = rel_wick / rng
    f["body_pct"] = body / rng
    f["range_atr_ratio"] = rng / max(atr20[bidx], 1e-9)
    f["vol_rel"] = v / max(vol_sma20[bidx], 1e-9)

    # HH/LL vs prev same-type (within fractals window from index 1)
    prev_same = None
    for p in reversed(fractals[:n_idx - 1]):
        if p["dir"] == f["dir"]:
            prev_same = p; break
    if prev_same is None:
        f["hh_or_ll"] = "N/A"
        f["dist_prev_bars"] = 0
        f["dist_prev_pct"] = 0.0
    else:
        if f["dir"] == "high":
            f["hh_or_ll"] = "HH" if f["level"] > prev_same["level"] else "LH"
        else:
            f["hh_or_ll"] = "LL" if f["level"] < prev_same["level"] else "HL"
        f["dist_prev_bars"] = (f["center_ts"] - prev_same["center_ts"]) // TF12_MS
        f["dist_prev_pct"] = abs(f["level"] - prev_same["level"]) / f["level"] * 100

    # D confluence: D fractal same direction within ±0.3% level и ±2 days center
    d_conf = False
    for fd in fr_D:
        if fd["dir"] != f["dir"]: continue
        if abs(fd["level"] - f["level"]) / f["level"] > 0.003: continue
        if abs(fd["center_ts"] - f["center_ts"]) > 2 * TF_D_MS: continue
        d_conf = True; break
    f["d_conf"] = d_conf

    # W confluence: ±0.5% level и ±1 week center
    w_conf = False
    for fw in fr_W:
        if fw["dir"] != f["dir"]: continue
        if abs(fw["level"] - f["level"]) / f["level"] > 0.005: continue
        if abs(fw["center_ts"] - f["center_ts"]) > 7 * TF_D_MS: continue
        w_conf = True; break
    f["w_conf"] = w_conf

    # extreme в окне ±N 12h bars: для FH максимум high в окне (исключая центр)
    N = 5  # 60h либо ~2.5 дня
    win_lo = max(0, bidx - N); win_hi = min(len(bars12), bidx + N + 1)
    other_highs = [bars12[k][2] for k in range(win_lo, win_hi) if k != bidx]
    other_lows = [bars12[k][3] for k in range(win_lo, win_hi) if k != bidx]
    if f["dir"] == "high":
        f["extreme_5"] = (h_ > max(other_highs))
    else:
        f["extreme_5"] = (l_ < min(other_lows))

    # И ±10 баров (5 дней)
    N = 10
    win_lo = max(0, bidx - N); win_hi = min(len(bars12), bidx + N + 1)
    other_highs = [bars12[k][2] for k in range(win_lo, win_hi) if k != bidx]
    other_lows = [bars12[k][3] for k in range(win_lo, win_hi) if k != bidx]
    if f["dir"] == "high":
        f["extreme_10"] = (h_ > max(other_highs))
    else:
        f["extreme_10"] = (l_ < min(other_lows))

    f["is_important"] = (n_idx in IMPORTANT)


# === Print feature table ===
print(f"\n{'='*128}")
print(f" 56 fractals × features (★ = ground truth important)")
print(f"{'='*128}")
print(f"{'#':>3} {'★':>1} {'type':>4} {'center':<16} {'level':>8} "
      f"{'srvH':>6} {'wick%':>6} {'body%':>6} {'rng/atr':>7} {'vol_rel':>7} "
      f"{'rel':>5} {'dPrev':>5} {'pctP':>5} {'D':>2} {'W':>2} {'e5':>3} {'e10':>3}")
print("-" * 128)
for f in fractals:
    star = "★" if f["is_important"] else " "
    glyph = "FH" if f["dir"] == "high" else "FL"
    srv = "∞" if f["survive_h"] > 9000 else f"{f['survive_h']:.0f}"
    print(f"{f['num']:>3} {star:>1} {glyph:>4} {fmt(f['center_ts']):<16} "
          f"{f['level']:>8.0f} {srv:>6} "
          f"{f['wick_pct']*100:>5.0f}% {f['body_pct']*100:>5.0f}% "
          f"{f['range_atr_ratio']:>6.2f}x {f['vol_rel']:>6.2f}x "
          f"{f['hh_or_ll']:>5} {f['dist_prev_bars']:>5} {f['dist_prev_pct']:>4.1f}% "
          f"{'Y' if f['d_conf'] else '·':>2} "
          f"{'Y' if f['w_conf'] else '·':>2} "
          f"{'Y' if f['extreme_5'] else '·':>3} "
          f"{'Y' if f['extreme_10'] else '·':>3}")


# === Rule evaluation ===
print(f"\n{'='*128}")
print(f" Single-feature filters — precision/recall vs 18 ground truth important")
print(f"{'='*128}")
print(f"  Goal: keep as many of 18 important, throw out as many of 38 noise.")
print()


def eval_rule(name, pred):
    kept = [f for f in fractals if pred(f)]
    important_kept = sum(1 for f in kept if f["is_important"])
    important_lost = 18 - important_kept
    noise_kept = len(kept) - important_kept
    recall = important_kept / 18 * 100
    precision = important_kept / len(kept) * 100 if kept else 0
    f1 = 2 * recall * precision / (recall + precision) if (recall + precision) > 0 else 0
    print(f"  {name:<58} keep={len(kept):>3}  imp_kept={important_kept:>2}/18  "
          f"imp_lost={important_lost:>2}  noise_kept={noise_kept:>3}  "
          f"recall={recall:>5.1f}%  prec={precision:>5.1f}%  F1={f1:>5.1f}")
    if important_lost > 0:
        lost_ids = [f["num"] for f in fractals if f["is_important"] and not pred(f)]
        print(f"      lost: {lost_ids}")


# Singles
for thr in [12, 24, 48, 72, 100, 150, 250]:
    eval_rule(f"survive_h ≥ {thr}", lambda f, t=thr: f["survive_h"] >= t)
print()
for thr in [0.3, 0.5, 0.7]:
    eval_rule(f"wick_pct ≥ {thr}", lambda f, t=thr: f["wick_pct"] >= t)
print()
for thr in [0.4, 0.5, 0.7]:
    eval_rule(f"body_pct ≤ {thr}", lambda f, t=thr: f["body_pct"] <= t)
print()
for thr in [0.8, 1.0, 1.3, 1.6, 2.0]:
    eval_rule(f"range_atr_ratio ≥ {thr}", lambda f, t=thr: f["range_atr_ratio"] >= t)
print()
for thr in [0.8, 1.0, 1.3, 1.6, 2.0]:
    eval_rule(f"vol_rel ≥ {thr}", lambda f, t=thr: f["vol_rel"] >= t)
print()
eval_rule("HH or LL (extreme rank)", lambda f: f["hh_or_ll"] in ("HH", "LL"))
eval_rule("LH or HL (counter-trend)", lambda f: f["hh_or_ll"] in ("LH", "HL"))
print()
for thr in [3, 5, 7, 10]:
    eval_rule(f"dist_prev_bars ≥ {thr}", lambda f, t=thr: f["dist_prev_bars"] >= t)
print()
for thr in [1.5, 2.5, 3.5, 5.0]:
    eval_rule(f"dist_prev_pct ≥ {thr}%", lambda f, t=thr: f["dist_prev_pct"] >= t)
print()
eval_rule("D confluence", lambda f: f["d_conf"])
eval_rule("W confluence", lambda f: f["w_conf"])
eval_rule("D OR W confluence", lambda f: f["d_conf"] or f["w_conf"])
print()
eval_rule("extreme in ±5 bars (=2.5d)", lambda f: f["extreme_5"])
eval_rule("extreme in ±10 bars (=5d)", lambda f: f["extreme_10"])


# === Combined rules ===
print(f"\n{'='*128}")
print(f" Combo rules")
print(f"{'='*128}")
eval_rule("extreme_10 OR survive_h ≥ 70", lambda f: f["extreme_10"] or f["survive_h"] >= 70)
eval_rule("extreme_10 AND survive_h ≥ 50", lambda f: f["extreme_10"] and f["survive_h"] >= 50)
eval_rule("extreme_5 AND survive_h ≥ 70", lambda f: f["extreme_5"] and f["survive_h"] >= 70)
eval_rule("(D or W conf) OR extreme_10", lambda f: f["d_conf"] or f["w_conf"] or f["extreme_10"])
eval_rule("extreme_10 AND range_atr ≥ 1.0", lambda f: f["extreme_10"] and f["range_atr_ratio"] >= 1.0)
eval_rule("extreme_10 AND wick_pct ≥ 0.3", lambda f: f["extreme_10"] and f["wick_pct"] >= 0.3)
eval_rule("survive_h ≥ 70 AND (HH/LL or D_conf)",
          lambda f: f["survive_h"] >= 70 and (f["hh_or_ll"] in ("HH", "LL") or f["d_conf"]))
eval_rule("survive_h ≥ 70 AND dist_prev_pct ≥ 2.5",
          lambda f: f["survive_h"] >= 70 and f["dist_prev_pct"] >= 2.5)
eval_rule("extreme_5 OR (D_conf OR W_conf)",
          lambda f: f["extreme_5"] or f["d_conf"] or f["w_conf"])
eval_rule("extreme_10 OR D_conf OR W_conf",
          lambda f: f["extreme_10"] or f["d_conf"] or f["w_conf"])
