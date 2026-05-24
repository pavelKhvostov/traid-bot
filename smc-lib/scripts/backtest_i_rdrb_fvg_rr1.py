"""Бэктест i-RDRB + FVG на BTC 1h за 6 лет.

Правила входа/выхода:
- Detection: i-RDRB (reversal) на C1-C4 + FVG (same direction) на C3-C4-C5.
- Entry: limit на 0.5 RDRB block (середина блока).
- SL: low (для long) / high (для short) всего паттерна (C1..C5).
- TP: RR 1:1 от entry.
- Лимитка ждёт fill индефинитно (до конца данных). Достижение TP до fill не отменяет сделку —
  мы всё равно ждём отката к entry, затем открываем позицию.
- После fill: TP/SL (приоритет SL при одновременном hit в одной 1m свече — консервативно).
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


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        reader = csv.reader(f)
        next(reader)
        for r in reader:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def aggregate(rows_1m, tf_min: int):
    bucket_ms = tf_min * 60 * 1000
    out: list[Candle] = []
    cur_b = None
    cur_o = cur_h = cur_l = cur_c = 0.0
    for ts, o, h, l, c in rows_1m:
        b = ts - (ts % bucket_ms)
        if b != cur_b:
            if cur_b is not None:
                out.append(Candle(open=cur_o, high=cur_h, low=cur_l, close=cur_c, open_time=cur_b))
            cur_b = b
            cur_o, cur_h, cur_l, cur_c = o, h, l, c
        else:
            cur_h = max(cur_h, h)
            cur_l = min(cur_l, l)
            cur_c = c
    if cur_b is not None:
        out.append(Candle(open=cur_o, high=cur_h, low=cur_l, close=cur_c, open_time=cur_b))
    return out


print("Loading 1m CSV...")
rows_1m = load_1m()
print(f"Loaded {len(rows_1m):,} 1m candles")

print("Aggregating to 1h...")
candles_1h = aggregate(rows_1m, 60)
print(f"Aggregated to {len(candles_1h):,} 1h candles\n")

# Найти все паттерны
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None:
        continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction:
        continue
    patterns.append((ir, c5))

print(f"Total i-RDRB+FVG patterns: {len(patterns)}\n")

# Индекс по времени для 1m
ts_1m = [r[0] for r in rows_1m]
MS_PER_MIN = 60_000
MS_PER_HOUR = 60 * MS_PER_MIN


def search_idx(target_ms):
    """Бинарный поиск индекса первого 1m с ts >= target."""
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        mid = (lo + hi) // 2
        if ts_1m[mid] < target_ms:
            lo = mid + 1
        else:
            hi = mid
    return lo


# Симуляция
stats = {
    "long": {"win": 0, "loss": 0, "no_fill": 0, "degenerate": 0},
    "short": {"win": 0, "loss": 0, "no_fill": 0, "degenerate": 0},
}
total_r = 0.0

for ir, c5 in patterns:
    direction = ir.direction
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    pattern_low = min(c.low for c in all5)
    pattern_high = max(c.high for c in all5)
    if direction == "long":
        sl = pattern_low
        r_val = entry - sl
        tp = entry + r_val
    else:
        sl = pattern_high
        r_val = sl - entry
        tp = entry - r_val

    if r_val <= 0:
        stats[direction]["degenerate"] += 1
        continue

    start_ms = c5.open_time + MS_PER_HOUR
    j = search_idx(start_ms)

    in_trade = False
    outcome = "no_fill"
    for k in range(j, len(rows_1m)):
        _, o_, h_, l_, c_ = rows_1m[k]
        if not in_trade:
            # ждём fill — игнорируем достижение TP/SL до открытия позиции
            if direction == "long":
                if l_ <= entry:
                    in_trade = True
                    if l_ <= sl:
                        outcome = "loss"
                        break
                    if h_ >= tp:
                        outcome = "win"
                        break
            else:
                if h_ >= entry:
                    in_trade = True
                    if h_ >= sl:
                        outcome = "loss"
                        break
                    if l_ <= tp:
                        outcome = "win"
                        break
        else:
            if direction == "long":
                if l_ <= sl:
                    outcome = "loss"
                    break
                if h_ >= tp:
                    outcome = "win"
                    break
            else:
                if h_ >= sl:
                    outcome = "loss"
                    break
                if l_ <= tp:
                    outcome = "win"
                    break

    stats[direction][outcome] += 1
    if outcome == "win":
        total_r += 1.0
    elif outcome == "loss":
        total_r -= 1.0


# Сводка
print(f"{'Outcome':<12} {'LONG':>8} {'SHORT':>8} {'Total':>8}")
print("-" * 42)
for outc in ("win", "loss", "no_fill", "degenerate"):
    l, s = stats["long"][outc], stats["short"][outc]
    print(f"{outc:<12} {l:>8} {s:>8} {l+s:>8}")

total_long = sum(stats["long"].values())
total_short = sum(stats["short"].values())
print(f"{'Total':<12} {total_long:>8} {total_short:>8} {total_long+total_short:>8}")


def wr(side):
    w = stats[side]["win"]
    l = stats[side]["loss"]
    return w / (w + l) * 100 if (w + l) else 0


print()
print(f"WR (win/(win+loss)):")
print(f"  LONG:   {wr('long'):.2f}% ({stats['long']['win']}/{stats['long']['win']+stats['long']['loss']})")
print(f"  SHORT:  {wr('short'):.2f}% ({stats['short']['win']}/{stats['short']['win']+stats['short']['loss']})")
total_w = stats['long']['win'] + stats['short']['win']
total_l = stats['long']['loss'] + stats['short']['loss']
print(f"  TOTAL:  {total_w/(total_w+total_l)*100:.2f}% ({total_w}/{total_w+total_l})")
print()
print(f"Total R (RR 1:1): {total_r:+.0f}R")
print(f"Expectancy: {total_r/(total_w+total_l):+.3f}R per filled trade")

filled = total_w + total_l
print(f"Fill rate: {filled/len(patterns)*100:.1f}% ({filled}/{len(patterns)})")
print(f"No fill (лимитка не сработала до конца данных): {stats['long']['no_fill']+stats['short']['no_fill']}")
print(f"Degenerate (R ≤ 0, вырожденный паттерн): {stats['long']['degenerate']+stats['short']['degenerate']}")
