"""Realtime features ТОЛЬКО на момент close pivot-свечи (i.close = i.open + 12h).

Доступно:
  - i, i-1, i-2 (3 свечи, последняя только что закрылась)
  - всё past history до i для ATR, EMA, SMA volume
  - confirmed HTF fractals если confirm_ts ≤ i.close

Williams condition требует i+1, i+2 в будущем — не используем. Но мы know что
наши 56 фракталов в итоге Williams-валидны. Вопрос: при i.close, можем ли
угадать "важный" or нет.

Features:

A) Pivot bar i anatomy:
   - wick_pct (relevant side)
   - body_pct
   - range_atr (range / ATR20)
   - vol_rel (vol / SMA20)
   - close_position: (c-l)/range — для FH хотим close в нижней половине (rejection)

B) i-1 anatomy:
   - i-1.range_atr
   - i-1.color (bull/bear)

C) i-2 anatomy:
   - аналогично

D) 3-bar approach pattern:
   - 3-bar momentum: (i.close - i-2.close) / ATR — для FH большое positive = impulse up
   - relative_pivot_extension: (i.high − i-1.high) / ATR для FH
   - approach_run_count: сколько подряд same-color баров включая i (для FH — bull bars)

E) Volume:
   - vol_climax: vol_i > 1.5 × max(vol_i-1, vol_i-2)
   - vol_avg_recent: vol_i / SMA20

F) Left extension (deeper past): обозначаем БЕЗ +sides
   - left_ext_5: i.high > max(highs [-5, -1]) для FH
   - left_ext_10: то же на 10
   - left_ext_20: 20

G) HTF context (confirmed at i.close):
   - d_conf_strict: D fractal same dir, confirm_ts ≤ i.close
                    AND |level diff| ≤ 0.5%
   - w_conf_strict: W fractal same dir, confirm_ts ≤ i.close

H) Trend context:
   - ema20_dir: i.close > EMA20 (bull) / < EMA20 (bear)
   - pivot_vs_ema20_atr: (i.close - EMA20) / ATR — degree of extension
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


# ATR, SMA vol, EMA20 на 12h
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
# EMA20
ema20 = np.zeros_like(cl12)
alpha = 2 / 21
ema20[0] = cl12[0]
for i in range(1, len(cl12)):
    ema20[i] = alpha * cl12[i] + (1 - alpha) * ema20[i-1]


# All D and W fractals (with confirm_ts)
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
        # decision moment = i.close = i.open + 12h
        "decision_ts": can12[i].open_time + TF12_MS,
    })


# === Compute features at i.close ===
for n_idx, f in enumerate(fractals, 1):
    f["num"] = n_idx
    bidx = f["idx"]
    pb = bars12[bidx]
    o, h_, l_, c_, v = pb[1], pb[2], pb[3], pb[4], pb[5]
    rng = h_ - l_ if h_ > l_ else 1e-9

    # A) Pivot bar i anatomy
    body = abs(c_ - o)
    f["wick_pct"] = ((h_ - max(o, c_)) if f["dir"] == "high" else (min(o, c_) - l_)) / rng
    f["body_pct"] = body / rng
    f["range_atr"] = rng / max(atr20[bidx], 1e-9)
    f["vol_rel"] = v / max(vol_sma20[bidx], 1e-9)
    # close_position: для FH хотим close ниже (отвергнут вверх)
    if f["dir"] == "high":
        f["close_pos"] = (c_ - l_) / rng  # ↓ хорошо для FH (close внизу = rejection)
    else:
        f["close_pos"] = (h_ - c_) / rng  # ↓ хорошо для FL (close вверху = rejection)
    f["pivot_color"] = "bull" if c_ > o else ("bear" if c_ < o else "doji")

    # B) i-1 anatomy
    pb1 = bars12[bidx-1]
    rng1 = pb1[2] - pb1[3] if pb1[2] > pb1[3] else 1e-9
    f["im1_range_atr"] = rng1 / max(atr20[bidx-1], 1e-9)
    f["im1_color"] = "bull" if pb1[4] > pb1[1] else ("bear" if pb1[4] < pb1[1] else "doji")

    # C) i-2 anatomy
    pb2 = bars12[bidx-2]
    rng2 = pb2[2] - pb2[3] if pb2[2] > pb2[3] else 1e-9
    f["im2_range_atr"] = rng2 / max(atr20[bidx-2], 1e-9)
    f["im2_color"] = "bull" if pb2[4] > pb2[1] else ("bear" if pb2[4] < pb2[1] else "doji")

    # D) 3-bar approach
    f["mom_3bar_R"] = abs(c_ - pb2[4]) / max(atr20[bidx], 1e-9)
    # signed direction: для FH хотим mom_3bar positive (импульс вверх)
    f["mom_3bar_signed_match"] = (
        (f["dir"] == "high" and c_ > pb2[4]) or (f["dir"] == "low" and c_ < pb2[4])
    )
    # extension over prev bar
    if f["dir"] == "high":
        f["ext_vs_im1_R"] = (h_ - pb1[2]) / max(atr20[bidx], 1e-9)
    else:
        f["ext_vs_im1_R"] = (pb1[3] - l_) / max(atr20[bidx], 1e-9)
    # approach run: 3 bars all same-color matching expected direction
    def is_bull(b): return b[4] > b[1]
    def is_bear(b): return b[4] < b[1]
    if f["dir"] == "high":
        f["approach_run3"] = is_bull(pb2) and is_bull(pb1) and is_bull(pb)
        f["approach_run2"] = is_bull(pb1) and is_bull(pb)
    else:
        f["approach_run3"] = is_bear(pb2) and is_bear(pb1) and is_bear(pb)
        f["approach_run2"] = is_bear(pb1) and is_bear(pb)

    # E) Volume
    f["vol_climax"] = v > 1.5 * max(pb1[5], pb2[5])
    f["vol_relative_3"] = v / max(np.mean([pb1[5], pb2[5]]), 1e-9)

    # F) Left extension (без правой стороны)
    def left_ext_check(N_back):
        # check i.high/low vs [i-N_back, i-1]
        win_lo = max(0, bidx - N_back); win_hi = bidx  # exclude i itself
        if win_lo >= win_hi: return True
        slice_ = bars12[win_lo:win_hi]
        if f["dir"] == "high":
            return h_ > max(b[2] for b in slice_)
        else:
            return l_ < min(b[3] for b in slice_)

    f["left_ext_3"] = left_ext_check(3)   # vs i-3, i-2, i-1
    f["left_ext_5"] = left_ext_check(5)
    f["left_ext_10"] = left_ext_check(10)
    f["left_ext_20"] = left_ext_check(20)

    # G) HTF confluence (strict causal at decision_ts)
    dec_ts = f["decision_ts"]
    d_conf = False
    d_level_diff = None
    for fd in fr_D:
        if fd["dir"] != f["dir"]: continue
        if fd["confirm_ts"] > dec_ts: continue
        # increased tolerance
        if abs(fd["level"] - f["level"]) / f["level"] > 0.005: continue
        if abs(fd["center_ts"] - f["center_ts"]) > 4 * TF_D_MS: continue
        d_conf = True; d_level_diff = (fd["level"] - f["level"]) / f["level"]; break
    f["d_conf"] = d_conf

    w_conf = False
    for fw in fr_W:
        if fw["dir"] != f["dir"]: continue
        if fw["confirm_ts"] > dec_ts: continue
        if abs(fw["level"] - f["level"]) / f["level"] > 0.01: continue
        if abs(fw["center_ts"] - f["center_ts"]) > 14 * TF_D_MS: continue
        w_conf = True; break
    f["w_conf"] = w_conf

    # H) Trend / EMA
    f["ema20"] = float(ema20[bidx])
    f["above_ema20"] = c_ > ema20[bidx]
    f["ext_ema20_R"] = (c_ - ema20[bidx]) / max(atr20[bidx], 1e-9)
    # trend match: FH хочется когда trend up (= top формируется в uptrend = real top)
    if f["dir"] == "high":
        f["trend_match"] = c_ > ema20[bidx]
    else:
        f["trend_match"] = c_ < ema20[bidx]

    f["is_important"] = (n_idx in IMPORTANT)


# === Print table ===
print(f"\n{'='*160}")
print(f" CAUSAL-ONLY features at i.close moment — 56 fractals (★ = important)")
print(f"{'='*160}")
print(f"{'#':>3} {'★':>1} {'tp':>3} {'center':<14} {'level':>6} "
      f"{'wk%':>4} {'bd%':>4} {'r/a':>4} {'vol':>4} {'cp':>4} "
      f"{'m3R':>4} {'ex/1':>4} {'r3':>2} {'vc':>2} "
      f"{'L3':>2} {'L5':>2} {'L10':>3} {'L20':>3} "
      f"{'D':>2} {'W':>2} {'tEMA':>4} {'em+':>4}")
print("-" * 160)
for f in fractals:
    star = "★" if f["is_important"] else " "
    glyph = "FH" if f["dir"] == "high" else "FL"
    print(f"{f['num']:>3} {star:>1} {glyph:>3} {fmt(f['center_ts']):<14} {f['level']:>6.0f} "
          f"{f['wick_pct']*100:>3.0f}% {f['body_pct']*100:>3.0f}% "
          f"{f['range_atr']:>3.1f}x {f['vol_rel']:>3.1f}x "
          f"{f['close_pos']:>3.2f} "
          f"{f['mom_3bar_R']:>3.1f}x {f['ext_vs_im1_R']:>3.1f}x "
          f"{'Y' if f['approach_run3'] else '·':>2} "
          f"{'Y' if f['vol_climax'] else '·':>2} "
          f"{'Y' if f['left_ext_3'] else '·':>2} "
          f"{'Y' if f['left_ext_5'] else '·':>2} "
          f"{'Y' if f['left_ext_10'] else '·':>3} "
          f"{'Y' if f['left_ext_20'] else '·':>3} "
          f"{'Y' if f['d_conf'] else '·':>2} "
          f"{'Y' if f['w_conf'] else '·':>2} "
          f"{'Y' if f['trend_match'] else '·':>4} "
          f"{f['ext_ema20_R']:>+3.1f}x")


# === Eval rules ===
def eval_rule(name, pred):
    kept = [f for f in fractals if pred(f)]
    imp_kept = sum(1 for f in kept if f["is_important"])
    imp_lost = 18 - imp_kept
    noise_kept = len(kept) - imp_kept
    recall = imp_kept / 18 * 100
    prec = imp_kept / len(kept) * 100 if kept else 0
    f1 = 2 * recall * prec / (recall + prec) if (recall + prec) > 0 else 0
    print(f"  {name:<60} keep={len(kept):>3}  imp={imp_kept:>2}/18  "
          f"lost={imp_lost:>2}  noise={noise_kept:>3}  "
          f"recall={recall:>5.1f}%  prec={prec:>5.1f}%  F1={f1:>5.1f}")
    if imp_lost > 0 and imp_lost <= 6:
        lost_ids = [f["num"] for f in fractals if f["is_important"] and not pred(f)]
        print(f"      lost: {lost_ids}")


print(f"\n{'='*120}")
print(f" Single features")
print(f"{'='*120}")
eval_rule("left_ext_3 (i strict extreme vs [-3,-1])", lambda f: f["left_ext_3"])
eval_rule("left_ext_5", lambda f: f["left_ext_5"])
eval_rule("left_ext_10", lambda f: f["left_ext_10"])
eval_rule("left_ext_20", lambda f: f["left_ext_20"])
print()
eval_rule("approach_run3 (3 bars same color)", lambda f: f["approach_run3"])
eval_rule("approach_run2 (last 2 same color)", lambda f: f["approach_run2"])
print()
for thr in [0.3, 0.5, 0.8, 1.0]:
    eval_rule(f"mom_3bar_R ≥ {thr}", lambda f, t=thr: f["mom_3bar_R"] >= t)
print()
eval_rule("mom_3bar in expected direction", lambda f: f["mom_3bar_signed_match"])
for thr in [0.0, 0.2, 0.5]:
    eval_rule(f"ext_vs_im1_R ≥ {thr}", lambda f, t=thr: f["ext_vs_im1_R"] >= t)
print()
eval_rule("vol_climax (i > 1.5×max(i-1,i-2))", lambda f: f["vol_climax"])
print()
eval_rule("trend_match (FH in uptrend / FL in downtrend)", lambda f: f["trend_match"])
print()
eval_rule("d_conf strict (confirmed D fractal nearby)", lambda f: f["d_conf"])
eval_rule("w_conf strict", lambda f: f["w_conf"])
eval_rule("d_conf OR w_conf", lambda f: f["d_conf"] or f["w_conf"])
print()
# close pos
for thr in [0.3, 0.5, 0.7]:
    eval_rule(f"close_pos ≤ {thr} (rejection wick)", lambda f, t=thr: f["close_pos"] <= t)


print(f"\n{'='*120}")
print(f" Combos")
print(f"{'='*120}")
eval_rule("left_ext_5 AND trend_match",
          lambda f: f["left_ext_5"] and f["trend_match"])
eval_rule("left_ext_5 AND approach_run3",
          lambda f: f["left_ext_5"] and f["approach_run3"])
eval_rule("left_ext_5 AND mom_3bar_R ≥ 0.5",
          lambda f: f["left_ext_5"] and f["mom_3bar_R"] >= 0.5)
eval_rule("left_ext_5 AND mom_3bar_signed_match",
          lambda f: f["left_ext_5"] and f["mom_3bar_signed_match"])
eval_rule("left_ext_5 OR d_conf",
          lambda f: f["left_ext_5"] or f["d_conf"])
eval_rule("left_ext_10 OR d_conf OR w_conf",
          lambda f: f["left_ext_10"] or f["d_conf"] or f["w_conf"])
eval_rule("left_ext_5 AND (d_conf OR mom_3bar_signed_match)",
          lambda f: f["left_ext_5"] and (f["d_conf"] or f["mom_3bar_signed_match"]))
eval_rule("(left_ext_5 AND mom_3bar_signed_match) OR d_conf",
          lambda f: (f["left_ext_5"] and f["mom_3bar_signed_match"]) or f["d_conf"])
eval_rule("approach_run2 AND left_ext_5",
          lambda f: f["approach_run2"] and f["left_ext_5"])
eval_rule("approach_run2 AND left_ext_10",
          lambda f: f["approach_run2"] and f["left_ext_10"])
eval_rule("(approach_run2 AND left_ext_5) OR d_conf",
          lambda f: (f["approach_run2"] and f["left_ext_5"]) or f["d_conf"])
eval_rule("left_ext_5 AND ext_vs_im1_R ≥ 0.2",
          lambda f: f["left_ext_5"] and f["ext_vs_im1_R"] >= 0.2)
eval_rule("left_ext_5 AND ext_vs_im1_R ≥ 0",
          lambda f: f["left_ext_5"] and f["ext_vs_im1_R"] >= 0)
