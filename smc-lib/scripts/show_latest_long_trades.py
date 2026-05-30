"""Показывает 5 последних LONG i-RDRB+FVG паттернов на 1h BTC + результат сделки.

Entry = 0.5 RDRB block, SL = pattern low, TP = RR 1:1.
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
MSK = timezone(timedelta(hours=3))
N = 5
SIDE = sys.argv[1] if len(sys.argv) > 1 else "long"


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


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime("%Y-%m-%d %H:%M")


print("Loading...")
rows_1m = load_1m()
candles_1h = aggregate(rows_1m, 60)
ts_1m = [r[0] for r in rows_1m]


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        mid = (lo + hi) // 2
        if ts_1m[mid] < ms:
            lo = mid + 1
        else:
            hi = mid
    return lo


# Найти все LONG (или SHORT) i-RDRB+FVG
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None or ir.direction != SIDE:
        continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != SIDE:
        continue
    patterns.append((ir, c5, fvg))

# Берём 5 последних по C1 времени
latest = sorted(patterns, key=lambda x: x[0].rdrb.c1.open_time, reverse=True)[:N]


def simulate(ir, c5, side):
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    pattern_low = min(c.low for c in all5)
    pattern_high = max(c.high for c in all5)
    if side == "long":
        sl = pattern_low
        r_val = entry - sl
        tp = entry + r_val
    else:
        sl = pattern_high
        r_val = sl - entry
        tp = entry - r_val

    start_ms = c5.open_time + 3600_000
    j = idx_at(start_ms)
    in_trade = False
    fill_ms = None
    exit_ms = None
    outcome = "no_fill"
    for k in range(j, len(rows_1m)):
        ts, o_, h_, l_, c_ = rows_1m[k]
        if not in_trade:
            if side == "long":
                if l_ <= entry:
                    in_trade = True
                    fill_ms = ts
                    if l_ <= sl:
                        outcome = "loss"; exit_ms = ts; break
                    if h_ >= tp:
                        outcome = "win"; exit_ms = ts; break
            else:
                if h_ >= entry:
                    in_trade = True
                    fill_ms = ts
                    if h_ >= sl:
                        outcome = "loss"; exit_ms = ts; break
                    if l_ <= tp:
                        outcome = "win"; exit_ms = ts; break
        else:
            if side == "long":
                if l_ <= sl:
                    outcome = "loss"; exit_ms = ts; break
                if h_ >= tp:
                    outcome = "win"; exit_ms = ts; break
            else:
                if h_ >= sl:
                    outcome = "loss"; exit_ms = ts; break
                if l_ <= tp:
                    outcome = "win"; exit_ms = ts; break
    return {
        "entry": entry, "sl": sl, "tp": tp, "r": r_val,
        "outcome": outcome, "fill_ms": fill_ms, "exit_ms": exit_ms,
    }


print(f"\n=== Latest {N} {SIDE.upper()} i-RDRB+FVG trades on 1h ===\n")
for idx, (ir, c5, fvg) in enumerate(latest, 1):
    res = simulate(ir, c5, SIDE)
    print(f"--- [{idx}] C1 start: {fmt(ir.rdrb.c1.open_time)} MSK ---")
    for label, c in [("C1", ir.rdrb.c1), ("C2", ir.rdrb.c2), ("C3", ir.rdrb.c3), ("C4", ir.c4), ("C5", c5)]:
        d_ = "BULL" if c.close > c.open else ("BEAR" if c.close < c.open else "DOJI")
        print(f"  {label} {fmt(c.open_time)}: O={c.open:.2f} H={c.high:.2f} L={c.low:.2f} C={c.close:.2f} {d_}")
    print(f"  RDRB: {ir.rdrb.direction} {ir.rdrb.variant}  block={ir.rdrb.block}")
    print(f"  FVG: zone={fvg.zone}")
    print(f"  Entry={res['entry']:.2f}  SL={res['sl']:.2f}  TP={res['tp']:.2f}  R={res['r']:.2f}")
    if res['outcome'] == "no_fill":
        print(f"  → NO FILL (price не вернулся к entry до конца данных)")
    else:
        hold_min = (res['exit_ms'] - res['fill_ms']) / 60_000
        wait_min = (res['fill_ms'] - (c5.open_time + 3600_000)) / 60_000
        print(f"  Fill at {fmt(res['fill_ms'])} (ждали {wait_min:.0f}m = {wait_min/60:.1f}h)")
        print(f"  Exit at {fmt(res['exit_ms'])} ({res['outcome'].upper()}, держали {hold_min:.0f}m = {hold_min/60:.1f}h)")
    print()
