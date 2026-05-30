"""Подсчёт 15m RDRB ниже 1h block в окне паттерна для LONG i-RDRB+FVG.

Условия:
- 15m RDRB (любого направления, по smc-lib detect_rdrb)
- Сформирован внутри окна паттерна (C1.open → C5.close)
- 15m block ПОЛНОСТЬЮ под 1h block: 15m_block.top ≤ 1h_block.bottom
- (Для аналогии с FL): 15m RDRB.C2 формируется ПОСЛЕ pattern_low_ts
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
print(f"{len(data):,} 1m → {len(candles_15m):,} 15m, {len(candles_1h):,} 1h")

# Detect all 15m RDRBs
print("Detecting all 15m RDRBs...")
rdrbs_15m = []  # list of dicts: direction, block, c1, c2, c3, formed_ts (= c3.open+15m)
for i in range(len(candles_15m) - 2):
    r = detect_rdrb(candles_15m[i], candles_15m[i + 1], candles_15m[i + 2])
    if r is None: continue
    rdrbs_15m.append({
        "direction": r.direction, "variant": r.variant,
        "block": r.block,  # (bottom, top)
        "c2_open_ts": candles_15m[i + 1].open_time,
        "formed_ts": candles_15m[i + 2].open_time + MS_15M,  # после закрытия C3
    })
print(f"Found {len(rdrbs_15m)} RDRBs на 15m")
long_count = sum(1 for r in rdrbs_15m if r["direction"] == "long")
short_count = sum(1 for r in rdrbs_15m if r["direction"] == "short")
print(f"  LONG (C2 bull):  {long_count}")
print(f"  SHORT (C2 bear): {short_count}\n")


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


# Pattern detection (LONG only)
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None or ir.direction != "long": continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != "long": continue
    patterns.append((ir, c5))
print(f"{len(patterns)} LONG patterns\n")


records = []
for ir, c5 in patterns:
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    sl = min(c.low for c in all5)  # pattern_low
    r_unit = entry - sl
    if r_unit <= 0: continue
    tp = entry + r_unit
    c5_close_ms = c5.open_time + MS_HOUR
    pattern_start = ir.rdrb.c1.open_time

    # pattern_low ts
    j0 = idx_at(pattern_start); j1 = idx_at(c5_close_ms)
    p_low_ts = None
    for k_ in range(j0, j1):
        if abs(data[k_][3] - sl) < 1e-6: p_low_ts = data[k_][0]; break
    if p_low_ts is None:
        bl = float("inf")
        for k_ in range(j0, j1):
            if data[k_][3] < bl: bl = data[k_][3]; p_low_ts = data[k_][0]

    # Backtest
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

    # 15m RDRBs в зоне [pattern_low, 1h_block.bottom], внутри окна паттерна
    in_zone_all = [r for r in rdrbs_15m
                   if pattern_start <= r["formed_ts"] <= c5_close_ms
                   and r["c2_open_ts"] > p_low_ts        # C2 после pattern_low
                   and r["block"][1] <= block_b           # 15m block.top ≤ 1h block.bottom
                   and r["block"][0] > sl]                # 15m block.bottom > pattern_low
    in_zone_long = [r for r in in_zone_all if r["direction"] == "long"]
    in_zone_short = [r for r in in_zone_all if r["direction"] == "short"]

    records.append({
        "outcome": outcome,
        "n_total": len(in_zone_all),
        "n_long": len(in_zone_long),
        "n_short": len(in_zone_short),
    })


# Анализ
n = len(records)
wins = [r for r in records if r["outcome"] == "win"]
losses = [r for r in records if r["outcome"] == "loss"]
n_w = len(wins); n_l = len(losses)
print(f"Total LONG closed: {n}  WIN: {n_w}  LOSS: {n_l}\n")


def section(title, items):
    total_all = sum(x["n_total"] for x in items)
    total_long = sum(x["n_long"] for x in items)
    total_short = sum(x["n_short"] for x in items)
    n_with = sum(1 for x in items if x["n_total"] >= 1)
    print(f"=== {title} (n={len(items)}) ===")
    print(f"  с ≥1 15m RDRB в зоне:  {n_with} ({n_with/len(items)*100:.1f}%)")
    print(f"  Total 15m RDRB events: {total_all}  (LONG: {total_long}, SHORT: {total_short})")
    print(f"  Avg на trade:          {total_all/len(items):.2f}")
    print(f"  Distribution 0/1/2/3+: ", end="")
    for n_target in (0, 1, 2):
        cnt = sum(1 for x in items if x["n_total"] == n_target)
        print(f"{cnt}/", end="")
    cnt3 = sum(1 for x in items if x["n_total"] >= 3)
    print(f"{cnt3}")
    print()


section("ТОЛЬКО WIN", wins)
section("ТОЛЬКО LOSS (для контекста)", losses)


print("=== WR по количеству 15m RDRB (все 392 LONG) ===")
for n_target in (0, 1, 2):
    sub = [r for r in records if r["n_total"] == n_target]
    if sub:
        w = sum(1 for x in sub if x["outcome"] == "win")
        print(f"  {n_target} RDRB: n={len(sub):>4} WR={w/len(sub)*100:5.2f}% (wins={w})")
sub3 = [r for r in records if r["n_total"] >= 3]
if sub3:
    w = sum(1 for x in sub3 if x["outcome"] == "win")
    print(f"  ≥3 RDRB: n={len(sub3):>4} WR={w/len(sub3)*100:5.2f}% (wins={w})")

print("\n=== WR по NAPRAVLENIYU 15m RDRB ===")
print("--- По LONG RDRB (15m bullish reversal) ---")
for n_target in (0, 1, 2):
    sub = [r for r in records if r["n_long"] == n_target]
    if sub:
        w = sum(1 for x in sub if x["outcome"] == "win")
        print(f"  {n_target} LONG-RDRB: n={len(sub):>4} WR={w/len(sub)*100:5.2f}%")

print("--- По SHORT RDRB (15m bearish reversal) ---")
for n_target in (0, 1, 2):
    sub = [r for r in records if r["n_short"] == n_target]
    if sub:
        w = sum(1 for x in sub if x["outcome"] == "win")
        print(f"  {n_target} SHORT-RDRB: n={len(sub):>4} WR={w/len(sub)*100:5.2f}%")
