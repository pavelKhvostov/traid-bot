"""Для 87 LONG WIN с ровно 1 15m RDRB (всего 87 RDRB):
- Цена опускалась ниже 15m RDRB block.bottom до TP?
Дополнительно — все 119 RDRB events в WIN и 83 в LOSS для контекста.
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.rdrb.code import detect_rdrb
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
MS_15M = 15 * 60_000
MAX_HOLD_MIN = 30 * 24 * 60


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
candles_15m = aggregate(data, 15)
candles_1h = aggregate(data, 60)
ts_1m = [r[0] for r in data]

# Detect all 15m RDRBs
rdrbs_15m = []
for i in range(len(candles_15m) - 2):
    r = detect_rdrb(candles_15m[i], candles_15m[i + 1], candles_15m[i + 2])
    if r is None: continue
    rdrbs_15m.append({
        "direction": r.direction,
        "block_bottom": r.block[0], "block_top": r.block[1],
        "c2_open_ts": candles_15m[i + 1].open_time,
        "formed_ts": candles_15m[i + 2].open_time + MS_15M,
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


# Backtest и анализ
all_rdrbs_in_wins = []     # все RDRBs в WIN-сделках, с инфо о пробое
all_rdrbs_in_losses = []
patterns_with_count = {"win": [], "loss": []}  # per-pattern count of RDRBs

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

    j0 = idx_at(pattern_start); j1 = idx_at(c5_close_ms)
    p_low_ts = None
    for k_ in range(j0, j1):
        if abs(data[k_][3] - sl) < 1e-6: p_low_ts = data[k_][0]; break
    if p_low_ts is None:
        bl = float("inf")
        for k_ in range(j0, j1):
            if data[k_][3] < bl: bl = data[k_][3]; p_low_ts = data[k_][0]

    # Backtest, найти exit ts
    start_k = idx_at(c5_close_ms)
    end_k = min(start_k + MAX_HOLD_MIN, len(data))
    in_trade = False; outcome = "no_fill"; exit_ts = None
    for k in range(start_k, end_k):
        ts, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if l_ <= entry:
                in_trade = True
                if l_ <= sl: outcome = "loss"; exit_ts = ts; break
                if h_ >= tp: outcome = "win"; exit_ts = ts; break
        else:
            if l_ <= sl: outcome = "loss"; exit_ts = ts; break
            if h_ >= tp: outcome = "win"; exit_ts = ts; break
    if outcome not in ("win", "loss"): continue

    # 15m RDRB в зоне
    in_zone = [r for r in rdrbs_15m
               if pattern_start <= r["formed_ts"] <= c5_close_ms
               and r["c2_open_ts"] > p_low_ts
               and r["block_top"] <= block_b
               and r["block_bottom"] > sl]

    patterns_with_count[outcome].append(len(in_zone))

    # Для каждого RDRB — был ли пробит block.bottom до exit
    target_list = all_rdrbs_in_wins if outcome == "win" else all_rdrbs_in_losses
    for r in in_zone:
        scan_start = idx_at(r["formed_ts"])
        scan_end = idx_at(exit_ts) + 1
        pierced = False
        for k in range(scan_start, scan_end):
            if data[k][3] < r["block_bottom"]:
                pierced = True; break
        target_list.append({
            "n_rdrbs_in_pattern": len(in_zone),
            "direction": r["direction"],
            "block_bottom": r["block_bottom"],
            "block_top": r["block_top"],
            "pierced": pierced,
        })


print(f"=== Все 15m RDRB events в WIN patterns ({len(all_rdrbs_in_wins)} events) ===\n")
total = len(all_rdrbs_in_wins)
pierced = sum(1 for r in all_rdrbs_in_wins if r["pierced"])
print(f"15m RDRB block.bottom ПРОБИТ до TP:    {pierced} / {total}  ({pierced/total*100:.1f}%)")
print(f"15m RDRB block.bottom УДЕРЖАЛ до TP:   {total-pierced} / {total}  ({(total-pierced)/total*100:.1f}%)")

# По direction
print("\nПо direction RDRB:")
for d in ("long", "short"):
    sub = [r for r in all_rdrbs_in_wins if r["direction"] == d]
    if sub:
        p = sum(1 for r in sub if r["pierced"])
        print(f"  {d.upper()}-RDRB: total={len(sub)}, пробит={p} ({p/len(sub)*100:.1f}%), удержал={len(sub)-p} ({(len(sub)-p)/len(sub)*100:.1f}%)")

# Только в patterns с 1 RDRB (= 87 winners → 87 RDRBs)
print("\n--- Subset: только в WIN с РОВНО 1 RDRB (87 winners → 87 RDRB events) ---")
single = [r for r in all_rdrbs_in_wins if r["n_rdrbs_in_pattern"] == 1]
p_s = sum(1 for r in single if r["pierced"])
print(f"  Total: {len(single)},  пробит: {p_s} ({p_s/len(single)*100:.1f}%),  удержал: {len(single)-p_s} ({(len(single)-p_s)/len(single)*100:.1f}%)")

# Patterns с 2+ RDRB
multi = [r for r in all_rdrbs_in_wins if r["n_rdrbs_in_pattern"] >= 2]
if multi:
    p_m = sum(1 for r in multi if r["pierced"])
    print(f"  В WIN с ≥2 RDRB: total RDRB={len(multi)}, пробит={p_m} ({p_m/len(multi)*100:.1f}%)")


print(f"\n=== Для контекста — RDRB events в LOSS ({len(all_rdrbs_in_losses)}) ===")
total_l = len(all_rdrbs_in_losses)
pierced_l = sum(1 for r in all_rdrbs_in_losses if r["pierced"])
print(f"  Пробит: {pierced_l} ({pierced_l/total_l*100:.1f}%)")
print(f"  Удержал: {total_l-pierced_l} ({(total_l-pierced_l)/total_l*100:.1f}%)")
