"""Подсчёт Williams FL на 15m в зоне [pattern_low, block.bottom 1h]
для 239 LONG WIN i-RDRB+FVG паттернов.

Условия:
- Williams FL N=2 на 15m TF
- Свеча FL образовалась внутри окна паттерна (C1.open → C5.close)
- Конфирмация FL (open_time + 2*15m) ≤ C5 close
- Цена FL.low ∈ [pattern_low, block.bottom]
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
    out = []; cb = None; o = h = l = c = 0; v_sum = 0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - (ts % bucket)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v_sum))
            cb = b; o, h, l, c = oo, hh, ll, cc; v_sum = vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v_sum += vv
    if cb is not None: out.append((cb, o, h, l, c, v_sum))
    return out


print("Loading..."); data = load_1m()
candles_15m = aggregate(data, 15)
candles_1h = [Candle(open=o, high=h, low=l, close=c, open_time=ts)
              for ts, o, h, l, c, _ in aggregate(data, 60)]
ts_1m = [r[0] for r in data]
print(f"{len(data):,} 1m → {len(candles_15m):,} 15m, {len(candles_1h):,} 1h")

# Detect Williams FL (N=2) on 15m
fl_15m = []  # (open_time, low_price, confirm_ts)
for i in range(N_FRACTAL, len(candles_15m) - N_FRACTAL):
    l_i = candles_15m[i][3]
    if all(l_i < candles_15m[j][3] for j in range(i - N_FRACTAL, i)) and \
       all(l_i < candles_15m[j][3] for j in range(i + 1, i + N_FRACTAL + 1)):
        fl_15m.append({
            "open_ts": candles_15m[i][0],
            "low_price": l_i,
            "confirm_ts": candles_15m[i + N_FRACTAL][0] + MS_15M,
        })
print(f"  15m FL count: {len(fl_15m):,}\n")


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
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    if ir.direction != "long": continue
    patterns.append((ir, c5))
print(f"{len(patterns)} LONG patterns\n")


# Backtest + count FL
results = []
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

    # Original backtest
    start_k = idx_at(c5_close_ms)
    end_k = min(start_k + MAX_HOLD_MIN, len(data))
    in_trade = False; outcome = "no_fill"
    for k in range(start_k, end_k):
        _, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if l_ <= entry:
                in_trade = True
                if l_ <= sl: outcome = "loss"; break
                if h_ >= tp: outcome = "win"; break
        else:
            if l_ <= sl: outcome = "loss"; break
            if h_ >= tp: outcome = "win"; break
    if outcome not in ("win", "loss"): continue

    # Найти 1m с pattern_low (для time constraint)
    p_low_ts = None
    j0 = idx_at(pattern_start); j1 = idx_at(c5_close_ms)
    for k in range(j0, j1):
        if abs(data[k][3] - sl) < 1e-6:
            p_low_ts = data[k][0]; break
    if p_low_ts is None:
        # ближайший минимум
        best_low = float("inf")
        for k in range(j0, j1):
            if data[k][3] < best_low:
                best_low = data[k][3]; p_low_ts = data[k][0]

    # Count 15m FL в зоне (с новыми constraints)
    fls = [f for f in fl_15m
           if pattern_start <= f["open_ts"] <= c5_close_ms
           and f["confirm_ts"] <= c5_close_ms
           and f["open_ts"] > p_low_ts            # строго ПОСЛЕ pattern_low по времени
           and f["low_price"] > sl                # строго ВЫШЕ pattern_low по цене
           and f["low_price"] <= block_b]
    results.append({"outcome": outcome, "n_fl": len(fls), "fl_lows": [f["low_price"] for f in fls]})


# Только WIN
wins = [r for r in results if r["outcome"] == "win"]
losses = [r for r in results if r["outcome"] == "loss"]
n_w = len(wins); n_l = len(losses)

print(f"=== ТОЛЬКО WIN ({n_w} паттернов) ===\n")
print("По наличию ≥1 15m FL в [pattern_low, block.bottom]:")
n_with = sum(1 for r in wins if r["n_fl"] >= 1)
n_without = n_w - n_with
print(f"  С FL:    {n_with} ({n_with/n_w*100:.1f}%)")
print(f"  Без FL:  {n_without} ({n_without/n_w*100:.1f}%)")

print("\nРаспределение по количеству FL:")
for n_target in (0, 1, 2, 3, 4):
    sub = [r for r in wins if r["n_fl"] == n_target]
    print(f"  {n_target} FL: {len(sub):>4} winners")
sub5 = [r for r in wins if r["n_fl"] >= 5]
if sub5:
    print(f"  ≥5 FL: {len(sub5):>4} winners")

total_fl = sum(r["n_fl"] for r in wins)
print(f"\nВсего FL в WIN-сделках: {total_fl}")
print(f"Среднее FL на winner: {total_fl/n_w:.2f}")

print(f"\n=== Сравнение WIN vs LOSS (контекст) ===\n")
print(f"WIN ({n_w}):    с FL: {n_with} ({n_with/n_w*100:.1f}%),  avg FL/trade: {total_fl/n_w:.2f}")
n_with_l = sum(1 for r in losses if r["n_fl"] >= 1)
total_fl_l = sum(r["n_fl"] for r in losses)
print(f"LOSS ({n_l}):   с FL: {n_with_l} ({n_with_l/n_l*100:.1f}%),  avg FL/trade: {total_fl_l/n_l:.2f}")

# WR по бакетам количества FL
print(f"\n=== WR по количеству FL (все 392 LONG) ===")
for n_target in (0, 1, 2):
    sub = [r for r in results if r["n_fl"] == n_target]
    if sub:
        w_sub = sum(1 for r in sub if r["outcome"] == "win")
        print(f"  {n_target} FL: n={len(sub):>4}  WR={w_sub/len(sub)*100:5.2f}%  (wins={w_sub})")
sub3plus = [r for r in results if r["n_fl"] >= 3]
if sub3plus:
    w_sub = sum(1 for r in sub3plus if r["outcome"] == "win")
    print(f"  ≥3 FL: n={len(sub3plus):>4}  WR={w_sub/len(sub3plus)*100:5.2f}%  (wins={w_sub})")
