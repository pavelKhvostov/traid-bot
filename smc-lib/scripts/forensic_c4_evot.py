"""Feature mining: C4 size + EVoT для поиска фильтра >400 trades с WR boost.

Features:
- c4_body_pct = |C4.close - C4.open| / entry * 100
- c4_body_atr = body / ATR(14)
- c4_body_runit = body / r_unit_base
- c4_close_overshoot = (C4.close - block.top) / r_unit_base (LONG) — насколько C4 вышел за block.top
- EVoT direction in pattern
- EVoT time bucket
- EVoT distance from entry

Цель: фильтр с >400 trades и WR ≥ 60%.
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
MAX_HOLD_MIN = 30 * 24 * 60
ATR_PERIOD = 14


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
candles_1h = aggregate(data, 60)
ts_1m = [r[0] for r in data]

# ATR(14) on 1h (Wilder)
atr_arr = [0.0] * len(candles_1h)
trs = [0.0] * len(candles_1h)
for i in range(1, len(candles_1h)):
    trs[i] = max(candles_1h[i].high - candles_1h[i].low,
                 abs(candles_1h[i].high - candles_1h[i - 1].close),
                 abs(candles_1h[i].low - candles_1h[i - 1].close))
for i in range(ATR_PERIOD, len(candles_1h)):
    if i == ATR_PERIOD:
        atr_arr[i] = sum(trs[1:ATR_PERIOD + 1]) / ATR_PERIOD
    else:
        atr_arr[i] = (atr_arr[i - 1] * (ATR_PERIOD - 1) + trs[i]) / ATR_PERIOD


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def evot_in_pattern(c1_ms, c5_close_ms):
    j0 = idx_at(c1_ms); j1 = idx_at(c5_close_ms)
    max_bv = 0; max_bc = None; max_bt = None
    max_sv = 0; max_sc = None; max_st = None
    for k in range(j0, j1):
        ts, o, _, _, c, v = data[k]
        if c > o:
            if v > max_bv: max_bv = v; max_bc = c; max_bt = ts
        elif c < o:
            if v > max_sv: max_sv = v; max_sc = c; max_st = ts
    if max_bv > max_sv: return "BULL", max_bc, max_bt
    if max_sv > max_bv: return "BEAR", max_sc, max_st
    return "NONE", None, None


# Detect patterns + features + outcomes
records = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue

    side = ir.direction
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    if side == "long":
        sl = min(c.low for c in all5)
    else:
        sl = max(c.high for c in all5)
    r_unit_base = abs(entry - sl)
    if r_unit_base <= 0: continue
    tp = entry + r_unit_base if side == "long" else entry - r_unit_base
    c5_close_ms = c5.open_time + MS_HOUR

    # Backtest
    start_k = idx_at(c5_close_ms)
    end_k = min(start_k + MAX_HOLD_MIN, len(data))
    in_trade = False; outcome = "no_fill"
    for k in range(start_k, end_k):
        _, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if side == "long" and l_ <= entry:
                in_trade = True
                if l_ <= sl: outcome = "loss"; break
                if h_ >= tp: outcome = "win"; break
            elif side == "short" and h_ >= entry:
                in_trade = True
                if h_ >= sl: outcome = "loss"; break
                if l_ <= tp: outcome = "win"; break
        else:
            if side == "long":
                if l_ <= sl: outcome = "loss"; break
                if h_ >= tp: outcome = "win"; break
            else:
                if h_ >= sl: outcome = "loss"; break
                if l_ <= tp: outcome = "win"; break
    if outcome not in ("win", "loss"): continue

    # C4 features
    c4_body = abs(ir.c4.close - ir.c4.open)
    c4_body_pct = c4_body / entry * 100
    c4_body_atr = c4_body / atr_arr[i + 3] if atr_arr[i + 3] > 0 else 0  # ATR at C4 index
    c4_body_runit = c4_body / r_unit_base
    if side == "long":
        c4_overshoot = (ir.c4.close - block_t) / r_unit_base
    else:
        c4_overshoot = (block_b - ir.c4.close) / r_unit_base
    c4_range = ir.c4.high - ir.c4.low
    c4_range_atr = c4_range / atr_arr[i + 3] if atr_arr[i + 3] > 0 else 0

    # EVoT
    evot_dir, mv, mv_ts = evot_in_pattern(ir.rdrb.c1.open_time, c5_close_ms)
    if mv is not None:
        evot_t_bucket = f"C{min(5, max(1, int((mv_ts - ir.rdrb.c1.open_time) // MS_HOUR) + 1))}"
        evot_delta_r = ((mv - entry) if side == "long" else (entry - mv)) / r_unit_base
    else:
        evot_t_bucket = "NONE"; evot_delta_r = 0

    # R/ATR
    r_atr = r_unit_base / atr_arr[i + 4] if atr_arr[i + 4] > 0 else 0

    records.append({
        "side": side, "outcome": outcome,
        "c4_body_pct": c4_body_pct,
        "c4_body_atr": c4_body_atr,
        "c4_body_runit": c4_body_runit,
        "c4_overshoot": c4_overshoot,
        "c4_range_atr": c4_range_atr,
        "evot_dir": evot_dir, "evot_t_bucket": evot_t_bucket, "evot_delta_r": evot_delta_r,
        "r_atr": r_atr,
    })


n_total = len(records)
n_w = sum(1 for x in records if x["outcome"] == "win")
print(f"Total closed: {n_total}, WIN: {n_w}, WR baseline: {n_w/n_total*100:.2f}%\n")


def report(name, items):
    if not items: return
    n = len(items); w = sum(1 for x in items if x["outcome"] == "win")
    wr = w / n * 100; r = (w - (n - w))
    print(f"  {name:<45} n={n:<5}  WR={wr:5.2f}%  ΣR={r:+5d}  Δprec={wr-n_w/n_total*100:+5.2f}pp")


def num_buckets(key, bins, name):
    print(f"\n--- {name} ---")
    for lo, hi, label in bins:
        sub = [r for r in records if lo <= r[key] < hi]
        report(label, sub)


# C4 features
num_buckets("c4_body_pct", [
    (0, 0.2, "<0.2%"), (0.2, 0.4, "[0.2, 0.4)"), (0.4, 0.7, "[0.4, 0.7)"),
    (0.7, 1.0, "[0.7, 1.0)"), (1.0, 99, "≥1.0%")
], "C4 body % entry")

num_buckets("c4_body_atr", [
    (0, 0.3, "<0.3"), (0.3, 0.5, "[0.3, 0.5)"), (0.5, 0.8, "[0.5, 0.8)"),
    (0.8, 1.2, "[0.8, 1.2)"), (1.2, 1.6, "[1.2, 1.6)"), (1.6, 99, "≥1.6")
], "C4 body / ATR(14)")

num_buckets("c4_body_runit", [
    (0, 0.3, "<0.3"), (0.3, 0.6, "[0.3, 0.6)"), (0.6, 1.0, "[0.6, 1.0)"),
    (1.0, 1.5, "[1.0, 1.5)"), (1.5, 99, "≥1.5")
], "C4 body / R_unit_base")

num_buckets("c4_overshoot", [
    (-99, 0, "<0 (С4 ниже block.top)"), (0, 0.2, "[0, 0.2)R"), (0.2, 0.5, "[0.2, 0.5)R"),
    (0.5, 1.0, "[0.5, 1.0)R"), (1.0, 2.0, "[1.0, 2.0)R"), (2.0, 99, "≥2.0R")
], "C4 close vs block.top (overshoot in R)")

num_buckets("c4_range_atr", [
    (0, 0.5, "<0.5"), (0.5, 1.0, "[0.5, 1.0)"), (1.0, 1.5, "[1.0, 1.5)"),
    (1.5, 2.0, "[1.5, 2.0)"), (2.0, 99, "≥2.0")
], "C4 range / ATR(14)")

# Composite: R/ATR sweet spot
print("\n--- R/ATR ∈ [0.5, 0.85) (sweet spot из памяти) ---")
sub_ratr = [r for r in records if 0.5 <= r["r_atr"] < 0.85]
report("All sides", sub_ratr)

# C4 overshoot + EVoT C1-C3 combo
print("\n--- C4 overshoot ≥ 0.5R + EVoT в C1-C3 ---")
combo = [r for r in records if r["c4_overshoot"] >= 0.5 and r["evot_t_bucket"] in ("C1", "C2", "C3")]
report("All sides", combo)

# Looser: C4 size moderate + R/ATR loose
print("\n--- C4 body/ATR ≥ 0.5 (sufficient displacement) ---")
sub = [r for r in records if r["c4_body_atr"] >= 0.5]
report("All sides", sub)

# Try: c4_body_atr ≥ 0.5 + R/ATR loose [0.5, 1.1)
print("\n--- C4 body/ATR ≥ 0.5 AND R/ATR ∈ [0.5, 1.1) ---")
sub = [r for r in records if r["c4_body_atr"] >= 0.5 and 0.5 <= r["r_atr"] < 1.1]
report("All sides", sub)

# C4 overshoot strong + R/ATR sweet
print("\n--- C4 overshoot ≥ 0.3R AND R/ATR ∈ [0.5, 1.1) ---")
sub = [r for r in records if r["c4_overshoot"] >= 0.3 and 0.5 <= r["r_atr"] < 1.1]
report("All sides", sub)

# c4_body_runit moderate + EVoT
print("\n--- C4 body/r_unit ≥ 0.4 (strong displacement) ---")
sub = [r for r in records if r["c4_body_runit"] >= 0.4]
report("All sides", sub)
