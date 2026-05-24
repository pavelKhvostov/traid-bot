"""Считаем 4h RDRB, у которых после C3 close было первое касание зон block или liq.

Для LONG RDRB:
- block = [block.bottom, block.top] (верхняя зона POI)
- liq = [C1.body_top, block.bottom] (нижняя зона POI, если non-empty)
Касание: price low <= zone.top AND price high >= zone.bottom.

Для SHORT mirror.
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.rdrb.code import detect_rdrb

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_4H = 4 * 3600_000


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
            if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
    return out


print("Loading..."); data = load_1m()
candles_4h = aggregate(data, 240)
ts_1m = [r[0] for r in data]


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


# Detect 4h RDRB
rdrbs = []
for i in range(len(candles_4h) - 2):
    r = detect_rdrb(candles_4h[i], candles_4h[i + 1], candles_4h[i + 2])
    if r is None: continue
    c3_close_ms = candles_4h[i + 2].open_time + MS_4H
    rdrbs.append({"r": r, "c3_close_ms": c3_close_ms, "c1_idx": i})
print(f"4h RDRB total: {len(rdrbs)}\n")


# Для каждого RDRB найти время первого касания block и liq
stats = {
    "long_block_touched": 0, "long_liq_touched": 0, "long_either_touched": 0,
    "long_no_liq": 0, "long_no_touch": 0,
    "short_block_touched": 0, "short_liq_touched": 0, "short_either_touched": 0,
    "short_no_liq": 0, "short_no_touch": 0,
    "long_block_first": 0, "long_liq_first": 0, "long_same_first": 0,
    "short_block_first": 0, "short_liq_first": 0, "short_same_first": 0,
}
times_to_block = {"long": [], "short": []}
times_to_liq = {"long": [], "short": []}

for rec in rdrbs:
    r = rec["r"]; c3_close_ms = rec["c3_close_ms"]
    side = r.direction
    bb, bt = r.block
    if r.liq:
        lb, lt = r.liq
    else:
        lb, lt = None, None
        stats[f"{side}_no_liq"] += 1

    # Сканируем 1m с c3_close
    start_k = idx_at(c3_close_ms)
    block_touch_ts = None; liq_touch_ts = None
    for k in range(start_k, len(data)):
        ts, _, h_, l_, _, _ = data[k]
        # Block touch
        if block_touch_ts is None:
            if l_ <= bt and h_ >= bb: block_touch_ts = ts
        # Liq touch
        if lb is not None and liq_touch_ts is None:
            if l_ <= lt and h_ >= lb: liq_touch_ts = ts
        if block_touch_ts is not None and (lb is None or liq_touch_ts is not None):
            break

    if block_touch_ts is not None:
        stats[f"{side}_block_touched"] += 1
        times_to_block[side].append((block_touch_ts - c3_close_ms) / 3600_000)  # hours
    if liq_touch_ts is not None:
        stats[f"{side}_liq_touched"] += 1
        times_to_liq[side].append((liq_touch_ts - c3_close_ms) / 3600_000)
    if block_touch_ts is not None or liq_touch_ts is not None:
        stats[f"{side}_either_touched"] += 1
    if block_touch_ts is None and liq_touch_ts is None:
        stats[f"{side}_no_touch"] += 1

    # First-touch logic
    if block_touch_ts is not None and liq_touch_ts is not None:
        if block_touch_ts < liq_touch_ts: stats[f"{side}_block_first"] += 1
        elif liq_touch_ts < block_touch_ts: stats[f"{side}_liq_first"] += 1
        else: stats[f"{side}_same_first"] += 1
    elif block_touch_ts is not None:
        stats[f"{side}_block_first"] += 1
    elif liq_touch_ts is not None:
        stats[f"{side}_liq_first"] += 1


n_long = sum(1 for x in rdrbs if x["r"].direction == "long")
n_short = sum(1 for x in rdrbs if x["r"].direction == "short")

print(f"=== LONG 4h RDRB ({n_long}) ===")
print(f"  Block touched (хоть раз):     {stats['long_block_touched']}  ({stats['long_block_touched']/n_long*100:.1f}%)")
print(f"  Liq   touched (хоть раз):     {stats['long_liq_touched']}    (из {n_long - stats['long_no_liq']} V1 с liq)")
print(f"  Either touched (block OR liq): {stats['long_either_touched']}  ({stats['long_either_touched']/n_long*100:.1f}%)")
print(f"  No-touch (ни одна не задета):  {stats['long_no_touch']}  ({stats['long_no_touch']/n_long*100:.1f}%)")
print(f"  V2 (no liq):                  {stats['long_no_liq']}")
print(f"  First-touch:")
print(f"    block first: {stats['long_block_first']}")
print(f"    liq first:   {stats['long_liq_first']}")

print(f"\n=== SHORT 4h RDRB ({n_short}) ===")
print(f"  Block touched (хоть раз):     {stats['short_block_touched']}  ({stats['short_block_touched']/n_short*100:.1f}%)")
print(f"  Liq   touched (хоть раз):     {stats['short_liq_touched']}    (из {n_short - stats['short_no_liq']} V1 с liq)")
print(f"  Either touched (block OR liq): {stats['short_either_touched']}  ({stats['short_either_touched']/n_short*100:.1f}%)")
print(f"  No-touch:                     {stats['short_no_touch']}  ({stats['short_no_touch']/n_short*100:.1f}%)")
print(f"  V2 (no liq):                  {stats['short_no_liq']}")
print(f"  First-touch:")
print(f"    block first: {stats['short_block_first']}")
print(f"    liq first:   {stats['short_liq_first']}")

print(f"\n=== ИТОГО 4h RDRB ({len(rdrbs)}) ===")
total_either = stats['long_either_touched'] + stats['short_either_touched']
total_no_touch = stats['long_no_touch'] + stats['short_no_touch']
print(f"  Хотя бы одна зона задета:   {total_either}  ({total_either/len(rdrbs)*100:.1f}%)")
print(f"  Ни одна зона не задета:     {total_no_touch}  ({total_no_touch/len(rdrbs)*100:.1f}%)")

# Time stats
import statistics
for side in ("long", "short"):
    if times_to_block[side]:
        ts_b = times_to_block[side]
        print(f"\n  {side.upper()} block touch:")
        print(f"    median: {statistics.median(ts_b):.1f}h, mean: {sum(ts_b)/len(ts_b):.1f}h")
        print(f"    <4h: {sum(1 for t in ts_b if t<4)}, <24h: {sum(1 for t in ts_b if t<24)}, <1week: {sum(1 for t in ts_b if t<168)}")
    if times_to_liq[side]:
        ts_l = times_to_liq[side]
        print(f"  {side.upper()} liq touch:")
        print(f"    median: {statistics.median(ts_l):.1f}h, mean: {sum(ts_l)/len(ts_l):.1f}h")
