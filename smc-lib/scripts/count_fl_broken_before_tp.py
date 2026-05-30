"""Из 90 LONG winners с валидным FL-15m в зоне:
- 97 FL events суммарно
- Для каждого FL: опускалась ли цена ниже FL.low ПЕРЕД достижением TP?

Окно сканирования: от FL.confirm_ts до tp_hit_ts (момент пробития TP).
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


# Pattern detection
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None or ir.direction != "long": continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != "long": continue
    patterns.append((ir, c5))


total_fl_events = 0
broken_count = 0
patterns_with_any_broken = 0
patterns_total_with_fl = 0
broken_details = []  # для глубокого анализа

for ir, c5 in patterns:
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    sl = min(c.low for c in all5)
    r_unit = entry - sl
    if r_unit <= 0: continue
    tp = entry + r_unit
    c5_close_ms = c5.open_time + MS_HOUR
    pattern_start = ir.rdrb.c1.open_time

    # Backtest и найти tp_hit_ts
    start_k = idx_at(c5_close_ms)
    end_k = min(start_k + MAX_HOLD_MIN, len(data))
    in_trade = False; outcome = "no_fill"; tp_hit_ts = None
    for k in range(start_k, end_k):
        ts, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if l_ <= entry:
                in_trade = True
                if l_ <= sl: outcome = "loss"; break
                if h_ >= tp: outcome = "win"; tp_hit_ts = ts; break
        else:
            if l_ <= sl: outcome = "loss"; break
            if h_ >= tp: outcome = "win"; tp_hit_ts = ts; break
    if outcome != "win": continue

    # pattern_low_ts на 1m
    j0 = idx_at(pattern_start); j1 = idx_at(c5_close_ms)
    p_low_ts = None
    for k_ in range(j0, j1):
        if abs(data[k_][3] - sl) < 1e-6:
            p_low_ts = data[k_][0]; break
    if p_low_ts is None:
        bl = float("inf")
        for k_ in range(j0, j1):
            if data[k_][3] < bl: bl = data[k_][3]; p_low_ts = data[k_][0]

    # Валидные FL
    valid_fls = [f for f in fl_15m
                 if pattern_start <= f["open_ts"] <= c5_close_ms
                 and f["confirm_ts"] <= c5_close_ms
                 and f["open_ts"] > p_low_ts
                 and f["low_price"] > sl
                 and f["low_price"] <= block_b]
    if not valid_fls: continue
    patterns_total_with_fl += 1
    any_broken_in_pattern = False

    for fl in valid_fls:
        total_fl_events += 1
        # Scan от FL.confirm_ts до tp_hit_ts (inclusive)
        scan_start = idx_at(fl["confirm_ts"])
        scan_end = idx_at(tp_hit_ts) + 1
        broken = False
        for k in range(scan_start, scan_end):
            if data[k][3] < fl["low_price"]:
                broken = True
                break
        if broken:
            broken_count += 1
            any_broken_in_pattern = True
            broken_details.append({
                "fl_ts": fl["open_ts"], "fl_low": fl["low_price"],
                "pattern_c1_ts": pattern_start, "tp": tp,
            })

    if any_broken_in_pattern:
        patterns_with_any_broken += 1


print(f"=== Результаты ===\n")
print(f"Patterns LONG WIN с валидным 15m FL в зоне:  {patterns_total_with_fl}")
print(f"Total FL events:                              {total_fl_events}")
print(f"\nFL событий, где цена ОПУСКАЛАСЬ ниже FL.low до TP:  {broken_count}  ({broken_count/total_fl_events*100:.1f}%)")
print(f"FL событий, где цена НЕ опускалась до TP:           {total_fl_events - broken_count}  ({(total_fl_events-broken_count)/total_fl_events*100:.1f}%)")
print(f"\nPatterns где ≥1 FL был пробит до TP:                {patterns_with_any_broken}/{patterns_total_with_fl}  ({patterns_with_any_broken/patterns_total_with_fl*100:.1f}%)")
print(f"Patterns где ни один FL не пробит до TP:            {patterns_total_with_fl - patterns_with_any_broken}/{patterns_total_with_fl}  ({(patterns_total_with_fl - patterns_with_any_broken)/patterns_total_with_fl*100:.1f}%)")
