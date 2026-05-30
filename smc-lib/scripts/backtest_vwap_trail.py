"""Бэктест "Pure VWAP trail": SL трал по VWAP, нет фиксированного TP.

Правила:
- Detection: i-RDRB+FVG (1h, BTC, 6y).
- Anchor VWAP: 5m candle с pattern_low (LONG) / pattern_high (SHORT).
- Entry: 0.5 RDRB block (limit, ждёт fill бессрочно).
- Initial SL = pattern_low (LONG) / pattern_high (SHORT).
- После каждой 1m свечи: обновляем VWAP (cumulative); SL ratchets up (LONG) / down (SHORT)
  до max(pattern_low, vwap) — но никогда не "отвинчивается" обратно (monotonic).
- Exit: price intra-bar touches SL → выход по SL.
- Нет фиксированного TP. Trade едет пока SL не сработает (max hold 30 дней).

R-метрика: R_unit = entry − pattern_low (для long), pattern_high − entry (для short).
- При loss (SL=pattern_low): r = −1
- При profit (SL trailed выше entry): r = (exit_price − entry) / R_unit > 0
- При partial loss (SL trailed выше pattern_low, но ниже entry): r ∈ (−1, 0)
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


stats = {"long": {"win": 0, "loss": 0, "partial": 0, "open": 0, "no_setup": 0},
         "short": {"win": 0, "loss": 0, "partial": 0, "open": 0, "no_setup": 0}}
sum_r = 0.0; sum_r_long = 0.0; sum_r_short = 0.0
r_values: list[float] = []

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

    # 1. Накапливаем VWAP до C5 close (без торговли)
    cum_pv = 0.0; cum_vol = 0.0
    for k in range(anchor_idx, idx_at(c5_close_ms)):
        ts, _, _, _, c_, v_ = data[k]
        cum_pv += v_ * c_; cum_vol += v_

    # 2. После C5 close — ищем fill (0.5 block), потом trail SL
    in_trade = False
    outcome = "open"
    exit_price = None
    sl_current = pattern_extreme  # initial — never crosses entry

    start_k = idx_at(c5_close_ms)
    end_k = min(start_k + MAX_HOLD_MIN, len(data))

    for k in range(start_k, end_k):
        ts, o_, h_, l_, c_, v_ = data[k]

        if not in_trade:
            # Сначала проверка fill, потом обновим VWAP
            if side == "long":
                if l_ <= entry:
                    in_trade = True
                    sl_current = pattern_extreme  # initial trailing SL at worst case
                    # Hard SL within same bar
                    if l_ <= sl_current:
                        outcome = "exit"; exit_price = sl_current; break
            else:
                if h_ >= entry:
                    in_trade = True
                    sl_current = pattern_extreme
                    if h_ >= sl_current:
                        outcome = "exit"; exit_price = sl_current; break
            # Обновим VWAP даже если не fill (накапливается)
            cum_pv += v_ * c_; cum_vol += v_
        else:
            # 1) проверка exit по SL из конца предыдущего бара
            if side == "long":
                if l_ <= sl_current:
                    outcome = "exit"; exit_price = sl_current; break
            else:
                if h_ >= sl_current:
                    outcome = "exit"; exit_price = sl_current; break

            # 2) обновляем VWAP до текущего бара включительно
            cum_pv += v_ * c_; cum_vol += v_
            vwap = cum_pv / cum_vol if cum_vol else 0

            # 3) ratchet SL ВВЕРХ (long) / ВНИЗ (short), но не выше close (long) / не ниже close (short)
            if side == "long":
                proposed = max(pattern_extreme, vwap)
                # ограничиваем SL чтобы он не превышал текущий close (иначе сразу триггер)
                if proposed < c_:
                    sl_current = max(sl_current, proposed)
            else:
                proposed = min(pattern_extreme, vwap)
                if proposed > c_:
                    sl_current = min(sl_current, proposed)

    if outcome == "open":
        if in_trade:
            stats[side]["open"] += 1
        else:
            stats[side]["no_setup"] += 1
        continue

    # Classify outcome by exit_price vs entry
    if side == "long":
        delta = exit_price - entry
    else:
        delta = entry - exit_price
    r_val = delta / r_unit
    sum_r += r_val
    if side == "long": sum_r_long += r_val
    else: sum_r_short += r_val
    r_values.append(r_val)

    if r_val > 0.05:
        stats[side]["win"] += 1
    elif r_val < -0.95:
        stats[side]["loss"] += 1
    else:
        stats[side]["partial"] += 1


# Сводка
print(f"{'Outcome':<12} {'LONG':>8} {'SHORT':>8} {'Total':>8}")
print("-" * 42)
for k in ("win", "partial", "loss", "open", "no_setup"):
    l, s = stats["long"][k], stats["short"][k]
    print(f"{k:<12} {l:>8} {s:>8} {l+s:>8}")
tot_l = sum(stats["long"].values()); tot_s = sum(stats["short"].values())
print(f"{'Total':<12} {tot_l:>8} {tot_s:>8} {tot_l+tot_s:>8}")

def filled(side):
    return stats[side]["win"] + stats[side]["partial"] + stats[side]["loss"]

n_w = stats["long"]["win"] + stats["short"]["win"]
n_p = stats["long"]["partial"] + stats["short"]["partial"]
n_l = stats["long"]["loss"] + stats["short"]["loss"]
n_filled = n_w + n_p + n_l

print()
print(f"WR (win + partial.r>0) / filled:")
pos = sum(1 for r in r_values if r > 0)
print(f"  TOTAL: {pos/n_filled*100:.2f}% ({pos}/{n_filled})")
print(f"\nTotal R (sum of all outcomes): {sum_r:+.1f}R")
print(f"  LONG:   {sum_r_long:+.1f}R  ({filled('long')} trades)")
print(f"  SHORT:  {sum_r_short:+.1f}R  ({filled('short')} trades)")
print(f"Expectancy: {sum_r/n_filled:+.3f}R per trade")
print(f"\nR distribution:")
print(f"  max R: {max(r_values):+.2f}")
print(f"  min R: {min(r_values):+.2f}")
print(f"  median R: {sorted(r_values)[len(r_values)//2]:+.2f}")
avg_pos = sum(r for r in r_values if r > 0) / pos if pos else 0
avg_neg = sum(r for r in r_values if r <= 0) / (n_filled - pos) if (n_filled - pos) else 0
print(f"  avg positive: {avg_pos:+.3f}")
print(f"  avg negative: {avg_neg:+.3f}")
