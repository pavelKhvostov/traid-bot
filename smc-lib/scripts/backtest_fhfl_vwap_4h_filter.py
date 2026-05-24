"""Бэктест: фильтр по расстоянию VWAP-FL/FH 4h от entry в R-unit.

Для LONG: VWAP-FL 4h должен быть в пределах X R-unit от entry.
Для SHORT: VWAP-FH 4h аналогично.

VWAP'ы заякорены на ближайшие FH/FL 4h, подтверждённые ДО C1.
Значения берутся на момент C5 close (момент detection).

Срезы по distance bucket.
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
MS_4H = 4 * MS_HOUR
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
candles_4h = aggregate(data, 240)
ts_1m = [r[0] for r in data]
candles_1h_data = aggregate(data, 60)
candles_1h = [Candle(open=o, high=h, low=l, close=c, open_time=ts) for ts, o, h, l, c, _ in candles_1h_data]
print(f"{len(data):,} 1m → {len(candles_4h):,} 4h, {len(candles_1h):,} 1h")

# Cumulative for O(1) VWAP
cum_pv = [0.0] * (len(data) + 1); cum_vol = [0.0] * (len(data) + 1)
for i, (_, _, _, _, c, v) in enumerate(data):
    cum_pv[i + 1] = cum_pv[i] + v * c
    cum_vol[i + 1] = cum_vol[i] + v


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def vwap(a, e):
    pv = cum_pv[e + 1] - cum_pv[a]; vol = cum_vol[e + 1] - cum_vol[a]
    return pv / vol if vol > 0 else 0


# Williams fractals on 4h
fh_4h = []; fl_4h = []
for i in range(N_FRACTAL, len(candles_4h) - N_FRACTAL):
    h_i = candles_4h[i][2]; l_i = candles_4h[i][3]
    if all(h_i > candles_4h[j][2] for j in range(i - N_FRACTAL, i)) and \
       all(h_i > candles_4h[j][2] for j in range(i + 1, i + N_FRACTAL + 1)):
        fh_4h.append((i, candles_4h[i][0]))
    elif all(l_i < candles_4h[j][3] for j in range(i - N_FRACTAL, i)) and \
         all(l_i < candles_4h[j][3] for j in range(i + 1, i + N_FRACTAL + 1)):
        fl_4h.append((i, candles_4h[i][0]))
print(f"Found {len(fh_4h)} FH + {len(fl_4h)} FL на 4h")


def confirmed_before(frac_list, ref_ms):
    # Линейный поиск, fine для 6y
    out = None
    for f_idx, f_ts in frac_list:
        if f_ts + (N_FRACTAL + 1) * MS_4H <= ref_ms:
            out = (f_idx, f_ts)
        else:
            break
    return out


# Detect patterns
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    patterns.append((ir, c5))
print(f"{len(patterns)} patterns\n")


records = []
for ir, c5 in patterns:
    side = ir.direction
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    if side == "long":
        sl = min(c.low for c in all5)
    else:
        sl = max(c.high for c in all5)
    r_unit = (entry - sl) if side == "long" else (sl - entry)
    if r_unit <= 0: continue
    tp = entry + r_unit if side == "long" else entry - r_unit

    # FH/FL 4h до C1
    fh_pre = confirmed_before(fh_4h, ir.rdrb.c1.open_time)
    fl_pre = confirmed_before(fl_4h, ir.rdrb.c1.open_time)
    if fh_pre is None or fl_pre is None: continue
    fh_anchor = idx_at(fh_pre[1])
    fl_anchor = idx_at(fl_pre[1])
    c5_close_idx = idx_at(c5.open_time + MS_HOUR) - 1

    vw_fh = vwap(fh_anchor, c5_close_idx)
    vw_fl = vwap(fl_anchor, c5_close_idx)

    if side == "long":
        # delta vwap_fl to entry (positive = above entry)
        delta_fl = (vw_fl - entry) / r_unit
        delta_fh = (vw_fh - entry) / r_unit
        # For long, both VWAPs above is bearish macro
        # Filter metric: VWAP-FL distance above entry
        relevant_vwap = vw_fl
        delta_r = delta_fl
    else:
        delta_fh = (entry - vw_fh) / r_unit
        delta_fl = (entry - vw_fl) / r_unit
        relevant_vwap = vw_fh
        delta_r = delta_fh

    # Baseline backtest
    start_k = c5_close_idx + 1
    end_k = min(start_k + MAX_HOLD_MIN, len(data))
    in_trade = False; outcome = "no_fill"; r_val = 0.0
    for k in range(start_k, end_k):
        _, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if side == "long" and l_ <= entry:
                in_trade = True
                if l_ <= sl: outcome = "loss"; r_val = -1.0; break
                if h_ >= tp: outcome = "win"; r_val = +1.0; break
            elif side == "short" and h_ >= entry:
                in_trade = True
                if h_ >= sl: outcome = "loss"; r_val = -1.0; break
                if l_ <= tp: outcome = "win"; r_val = +1.0; break
        else:
            if side == "long":
                if l_ <= sl: outcome = "loss"; r_val = -1.0; break
                if h_ >= tp: outcome = "win"; r_val = +1.0; break
            else:
                if h_ >= sl: outcome = "loss"; r_val = -1.0; break
                if l_ <= tp: outcome = "win"; r_val = +1.0; break
    if outcome not in ("win", "loss"):
        continue
    records.append({"side": side, "outcome": outcome, "r": r_val,
                    "delta_r": delta_r, "delta_fl": (vw_fl - entry) / r_unit,
                    "delta_fh": (vw_fh - entry) / r_unit})

print(f"Closed trades with FH/FL 4h available: {len(records)}\n")


def report(name, items):
    if not items: print(f"{name:<58}  n=0"); return
    n = len(items); w = sum(1 for x in items if x["outcome"]=="win")
    sr = sum(x["r"] for x in items)
    print(f"{name:<58}  n={n:<5}  WR={w/n*100:5.2f}%  ΣR={sr:+7.1f}  R/tr={sr/n:+.3f}")


print("=== По расстоянию relevant VWAP от entry в R-unit ===")
print()
print("--- LONG (relevant = VWAP-FL 4h) ---")
long_recs = [x for x in records if x["side"]=="long"]
report("ALL LONG", long_recs)
buckets = [
    (-99, -0.5, "deep below (< -0.5R)"),
    (-0.5, 0.0, "ниже entry (-0.5, 0)"),
    (0.0, 1.0, "[0, 1) R над entry"),
    (1.0, 2.0, "[1, 2) R"),
    (2.0, 3.0, "[2, 3) R"),
    (3.0, 99.0, "≥ 3R (далеко наверху)"),
]
for lo, hi, name in buckets:
    sub = [x for x in long_recs if lo <= x["delta_r"] < hi]
    report(f"  LONG, delta_R(VWAP-FL) ∈ {name}", sub)

print()
print("--- SHORT (relevant = VWAP-FH 4h) ---")
short_recs = [x for x in records if x["side"]=="short"]
report("ALL SHORT", short_recs)
for lo, hi, name in buckets:
    sub = [x for x in short_recs if lo <= x["delta_r"] < hi]
    report(f"  SHORT, delta_R(VWAP-FH) ∈ {name}", sub)

# Композит: фильтр delta_r ≤ 2R
print()
print("=== Композит: оба VWAP в пределах 2R от entry ===")
sub_long = [x for x in long_recs if x["delta_r"] <= 2.0]
sub_short = [x for x in short_recs if x["delta_r"] <= 2.0]
report("LONG, VWAP-FL ≤ 2R над entry", sub_long)
report("SHORT, VWAP-FH ≤ 2R над entry", sub_short)
combined = sub_long + sub_short
report("BOTH sides combined", combined)
