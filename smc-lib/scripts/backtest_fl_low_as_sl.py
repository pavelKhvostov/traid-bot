"""Бэктест с SL = FL.low вместо pattern_low для LONG i-RDRB+FVG.

Гипотеза: FL над pattern_low может работать как tighter SL → больше RR при тех же TP.

Стратегии:
A) baseline (SL = pattern_low)
B) SL = highest FL.low (если есть валидный FL; иначе pattern_low) — самый тугой SL
C) SL = lowest FL.low (если есть; иначе pattern_low) — более консервативный

Метрика R считается в БAZE units (entry - pattern_low) для прямого сравнения с baseline.
TP всегда = entry + baseline_R_unit (фиксированный для всех вариантов).
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
MS_15M = 15 * 60_000
MAX_HOLD_MIN = 30 * 24 * 60
N_FRACTAL = 2


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate(d, tf_min):
    bucket = tf_min * 60_000
    out = []; cb = None; o = h = l = c = 0
    for ts, oo, hh, ll, cc, _ in d:
        b = ts - (ts % bucket)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append((cb, o, h, l, c))
    return out


print("Loading..."); data = load_1m()
candles_15m = aggregate(data, 15)
candles_1h = [Candle(open=o, high=h, low=l, close=c, open_time=ts)
              for ts, o, h, l, c in aggregate(data, 60)]
ts_1m = [r[0] for r in data]

fl_15m = []
for i in range(N_FRACTAL, len(candles_15m) - N_FRACTAL):
    l_i = candles_15m[i][3]
    if all(l_i < candles_15m[j][3] for j in range(i - N_FRACTAL, i)) and \
       all(l_i < candles_15m[j][3] for j in range(i + 1, i + N_FRACTAL + 1)):
        fl_15m.append({
            "open_ts": candles_15m[i][0],
            "low_price": l_i,
            "confirm_ts": candles_15m[i + N_FRACTAL][0] + MS_15M,
        })


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def simulate(entry, sl, tp, c5_close_ms, side="long"):
    """Возвращает (outcome, exit_price). Используется для long."""
    start_k = idx_at(c5_close_ms)
    end_k = min(start_k + MAX_HOLD_MIN, len(data))
    in_trade = False
    for k in range(start_k, end_k):
        _, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if l_ <= entry:
                in_trade = True
                if l_ <= sl: return "loss", sl
                if h_ >= tp: return "win", tp
        else:
            if l_ <= sl: return "loss", sl
            if h_ >= tp: return "win", tp
    return "no_fill", None


# Pattern detection
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None or ir.direction != "long": continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != "long": continue
    patterns.append((ir, c5))


stats = {"A_baseline": {"win": 0, "loss": 0, "total_r": 0.0, "n": 0},
         "B_highest_fl": {"win": 0, "loss": 0, "total_r": 0.0, "n": 0, "fl_used": 0},
         "C_lowest_fl": {"win": 0, "loss": 0, "total_r": 0.0, "n": 0, "fl_used": 0}}

per_pattern_results = []

for ir, c5 in patterns:
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    sl_base = min(c.low for c in all5)
    r_unit_base = entry - sl_base
    if r_unit_base <= 0: continue
    tp = entry + r_unit_base
    c5_close_ms = c5.open_time + MS_HOUR
    pattern_start = ir.rdrb.c1.open_time

    # pattern_low ts
    j0 = idx_at(pattern_start); j1 = idx_at(c5_close_ms)
    p_low_ts = None
    for k_ in range(j0, j1):
        if abs(data[k_][3] - sl_base) < 1e-6: p_low_ts = data[k_][0]; break
    if p_low_ts is None:
        bl = float("inf")
        for k_ in range(j0, j1):
            if data[k_][3] < bl: bl = data[k_][3]; p_low_ts = data[k_][0]

    # Valid FLs
    valid_fls = [f for f in fl_15m
                 if pattern_start <= f["open_ts"] <= c5_close_ms
                 and f["confirm_ts"] <= c5_close_ms
                 and f["open_ts"] > p_low_ts
                 and f["low_price"] > sl_base
                 and f["low_price"] <= block_b]

    # Strategy A: baseline
    out_a, exit_a = simulate(entry, sl_base, tp, c5_close_ms)
    if out_a not in ("win", "loss"): continue
    r_a = +1.0 if out_a == "win" else -1.0
    stats["A_baseline"]["n"] += 1
    stats["A_baseline"][out_a] += 1
    stats["A_baseline"]["total_r"] += r_a

    # Strategy B: highest FL.low (tightest)
    if valid_fls:
        sl_b = max(f["low_price"] for f in valid_fls)
        stats["B_highest_fl"]["fl_used"] += 1
    else:
        sl_b = sl_base
    out_b, exit_b = simulate(entry, sl_b, tp, c5_close_ms)
    if out_b in ("win", "loss"):
        if out_b == "win":
            r_b = +1.0
        else:
            r_b = (exit_b - entry) / r_unit_base
        stats["B_highest_fl"]["n"] += 1
        if r_b > 0:
            stats["B_highest_fl"]["win"] += 1
        else:
            stats["B_highest_fl"]["loss"] += 1
        stats["B_highest_fl"]["total_r"] += r_b

    # Strategy C: lowest FL.low
    if valid_fls:
        sl_c = min(f["low_price"] for f in valid_fls)
        stats["C_lowest_fl"]["fl_used"] += 1
    else:
        sl_c = sl_base
    out_c, exit_c = simulate(entry, sl_c, tp, c5_close_ms)
    if out_c in ("win", "loss"):
        if out_c == "win":
            r_c = +1.0
        else:
            r_c = (exit_c - entry) / r_unit_base
        stats["C_lowest_fl"]["n"] += 1
        if r_c > 0:
            stats["C_lowest_fl"]["win"] += 1
        else:
            stats["C_lowest_fl"]["loss"] += 1
        stats["C_lowest_fl"]["total_r"] += r_c


print(f"=== LONG i-RDRB+FVG: SL вариации ===\n")
print(f"{'Strategy':<18} {'n':<6} {'win':<6} {'loss':<6} {'WR%':<7} {'ΣR':<9} {'R/tr':<8} {'fl_used':<8}")
print("-" * 75)
for name, s in stats.items():
    wr = s["win"] / (s["win"] + s["loss"]) * 100 if (s["win"] + s["loss"]) else 0
    rtr = s["total_r"] / s["n"] if s["n"] else 0
    fl = s.get("fl_used", "—")
    print(f"{name:<18} {s['n']:<6} {s['win']:<6} {s['loss']:<6} {wr:<7.2f} {s['total_r']:<+9.1f} {rtr:<+8.3f} {fl:<8}")

print("\nЗначение:")
print("  - WIN — outcome > 0 (TP hit или partial exit > 0)")
print("  - LOSS — outcome ≤ 0 (R < 0)")
print("  - Для вариантов B/C: при LOSS R_realized в (-1, 0) — меньше -1R")
