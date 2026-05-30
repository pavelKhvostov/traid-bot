"""Бэктест "1h close < VWAP" exit (без intra-bar trail).

Правила:
- Detection и entry как baseline: 0.5 RDRB block, limit, fill бессрочно.
- Hard SL = pattern_extreme (intra-bar, для защиты от газовых сценариев).
- Exit signal: на каждом 1h close проверяем close vs VWAP:
  - LONG: 1h_close < VWAP → exit at close
  - SHORT: 1h_close > VWAP → exit at close
- Нет фиксированного TP. Без trailing intra-bar — только на закрытии часа.

Это "regime change" exit — мы выходим когда тренд официально сломан (close ниже VWAP).
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
MS_5M = 5 * 60_000
MAX_HOLD_MIN = 30 * 24 * 60


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate_1h(d):
    out = []; cb = None; o = h = l = c = 0
    for ts, oo, hh, ll, cc, _ in d:
        b = ts - (ts % MS_HOUR)
        if b != cb:
            if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
    return out


print("Loading 1m..."); data = load_1m(); ts_arr = [r[0] for r in data]
candles_1h = aggregate_1h(data); print(f"{len(data):,} 1m → {len(candles_1h):,} 1h\n")


def idx_at(ms):
    lo, hi = 0, len(ts_arr)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_arr[m] < ms: lo = m + 1
        else: hi = m
    return lo


def find_extreme_1m(s, e, side, val):
    for k in range(idx_at(s), idx_at(e)):
        if side == "long" and data[k][3] == val: return k
        if side == "short" and data[k][2] == val: return k
    return None


patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    patterns.append((ir, c5))
print(f"{len(patterns)} patterns\n")


stats = {"long": {"win": 0, "partial": 0, "loss_sl": 0, "loss_close": 0, "open": 0, "no_setup": 0},
         "short": {"win": 0, "partial": 0, "loss_sl": 0, "loss_close": 0, "open": 0, "no_setup": 0}}
sum_r = 0.0; sum_r_long = 0.0; sum_r_short = 0.0
r_values = []
hold_minutes = []

for ir, c5 in patterns:
    side = ir.direction
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    if side == "long":
        pattern_extreme = min(c.low for c in all5)
    else:
        pattern_extreme = max(c.high for c in all5)
    r_unit = (entry - pattern_extreme) if side == "long" else (pattern_extreme - entry)
    if r_unit <= 0:
        stats[side]["no_setup"] += 1; continue

    anchor_k = find_extreme_1m(ir.rdrb.c1.open_time, c5.open_time + MS_HOUR, side, pattern_extreme)
    if anchor_k is None:
        stats[side]["no_setup"] += 1; continue
    anchor_ms = data[anchor_k][0]
    anchor_5m = anchor_ms - (anchor_ms % MS_5M)
    anchor_idx = idx_at(anchor_5m)
    c5_close_ms = c5.open_time + MS_HOUR

    # Накапливаем VWAP до C5 close
    cum_pv = 0.0; cum_vol = 0.0
    for k in range(anchor_idx, idx_at(c5_close_ms)):
        _, _, _, _, c_, v_ = data[k]
        cum_pv += v_ * c_; cum_vol += v_

    in_trade = False
    outcome = "open"
    exit_price = None
    fill_ms = None; exit_ms = None
    sl = pattern_extreme
    trend_confirmed = False  # стало True после первого 1h close выше/ниже VWAP

    start_k = idx_at(c5_close_ms)
    end_k = min(start_k + MAX_HOLD_MIN, len(data))

    for k in range(start_k, end_k):
        ts, o_, h_, l_, c_, v_ = data[k]
        cum_pv += v_ * c_; cum_vol += v_
        vwap = cum_pv / cum_vol if cum_vol else 0
        is_hour_close = (ts + 60_000) % MS_HOUR == 0

        if not in_trade:
            if side == "long" and l_ <= entry:
                in_trade = True; fill_ms = ts
                if l_ <= sl:
                    outcome = "loss_sl"; exit_price = sl; exit_ms = ts; break
            elif side == "short" and h_ >= entry:
                in_trade = True; fill_ms = ts
                if h_ >= sl:
                    outcome = "loss_sl"; exit_price = sl; exit_ms = ts; break
            else:
                continue
        else:
            # Hard SL
            if side == "long":
                if l_ <= sl:
                    outcome = "loss_sl"; exit_price = sl; exit_ms = ts; break
            else:
                if h_ >= sl:
                    outcome = "loss_sl"; exit_price = sl; exit_ms = ts; break
            # 1h close: либо подтверждаем тренд, либо выходим
            if is_hour_close:
                if side == "long":
                    if not trend_confirmed:
                        if c_ > vwap:
                            trend_confirmed = True
                    else:
                        if c_ < vwap:
                            outcome = "exit"; exit_price = c_; exit_ms = ts; break
                else:
                    if not trend_confirmed:
                        if c_ < vwap:
                            trend_confirmed = True
                    else:
                        if c_ > vwap:
                            outcome = "exit"; exit_price = c_; exit_ms = ts; break

    if outcome == "open":
        if in_trade:
            stats[side]["open"] += 1
        else:
            stats[side]["no_setup"] += 1
        continue

    if side == "long":
        delta = exit_price - entry
    else:
        delta = entry - exit_price
    r_val = delta / r_unit
    sum_r += r_val
    if side == "long": sum_r_long += r_val
    else: sum_r_short += r_val
    r_values.append(r_val)

    if outcome == "loss_sl":
        stats[side]["loss_sl"] += 1
    elif outcome == "loss_close":
        stats[side]["loss_close"] += 1
    elif r_val > 0.05:
        stats[side]["win"] += 1
    elif r_val < -0.05:
        stats[side]["partial"] += 1  # exit close с отриц R, но не SL
    else:
        stats[side]["partial"] += 1

    if fill_ms and exit_ms:
        hold_minutes.append((exit_ms - fill_ms) / 60_000)


# Сводка
print(f"{'Outcome':<14} {'LONG':>8} {'SHORT':>8} {'Total':>8}")
print("-" * 44)
for k in ("win", "partial", "loss_close", "loss_sl", "open", "no_setup"):
    l, s = stats["long"][k], stats["short"][k]
    print(f"{k:<14} {l:>8} {s:>8} {l+s:>8}")
tot_l = sum(stats["long"].values()); tot_s = sum(stats["short"].values())
print(f"{'Total':<14} {tot_l:>8} {tot_s:>8} {tot_l+tot_s:>8}")

n_filled = len(r_values)
pos = sum(1 for r in r_values if r > 0)
print()
print(f"WR (positive R / filled): {pos/n_filled*100:.2f}% ({pos}/{n_filled})")
print(f"Total R: {sum_r:+.1f}R")
print(f"  LONG:   {sum_r_long:+.1f}R")
print(f"  SHORT:  {sum_r_short:+.1f}R")
print(f"Expectancy: {sum_r/n_filled:+.3f}R per trade")
print(f"\nR distribution:")
print(f"  max R: {max(r_values):+.2f}")
print(f"  min R: {min(r_values):+.2f}")
print(f"  median R: {sorted(r_values)[len(r_values)//2]:+.2f}")
avg_pos = sum(r for r in r_values if r > 0) / pos if pos else 0
avg_neg = sum(r for r in r_values if r <= 0) / (n_filled - pos) if (n_filled - pos) else 0
print(f"  avg win:  {avg_pos:+.3f}R")
print(f"  avg loss: {avg_neg:+.3f}R")
print(f"  R/W vs R/L ratio: {abs(avg_pos/avg_neg):.2f}")
print(f"\nMedian hold: {sorted(hold_minutes)[len(hold_minutes)//2]:.0f}min ({sorted(hold_minutes)[len(hold_minutes)//2]/60:.1f}h)")
