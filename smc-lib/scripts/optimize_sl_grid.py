"""SL grid sweep для LONG i-RDRB+FVG.

Entry: 0.5 block (unchanged). TP: entry + (entry - pattern_low) (unchanged baseline TP price).
SL: грид от pattern_low до pattern_low + 50% × (block.bottom − pattern_low), шаг 0.1.

Метрика R считается в NEW R-units (= entry - SL_new):
- WIN: r_realized = (TP - entry) / (entry - SL_new)  (≥ 1, растёт с tighter SL)
- LOSS: r_realized = -1
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


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None or ir.direction != "long": continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != "long": continue
    patterns.append((ir, c5))
print(f"{len(patterns)} LONG patterns")


def simulate(entry, sl, tp, start_ms):
    sk = idx_at(start_ms); ek = min(sk + MAX_HOLD_MIN, len(data))
    in_trade = False
    for k in range(sk, ek):
        _, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if l_ <= entry:
                in_trade = True
                if l_ <= sl: return "loss"
                if h_ >= tp: return "win"
        else:
            if l_ <= sl: return "loss"
            if h_ >= tp: return "win"
    return "no_fill"


# Sweep
ALPHAS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]

print(f"\n{'α':<6} {'SL position':<30} {'n':<6} {'WIN':<6} {'LOSS':<6} {'WR%':<8} {'ΣR (new units)':<16} {'effective_RR':<12}")
print("-" * 100)

results = []
for alpha in ALPHAS:
    total_r = 0.0
    n_win = 0; n_loss = 0
    rr_vals = []
    for ir, c5 in patterns:
        block_b, _ = ir.rdrb.block
        entry = (ir.rdrb.block[0] + ir.rdrb.block[1]) / 2
        all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
        pl = min(c.low for c in all5)
        r_unit_base = entry - pl
        if r_unit_base <= 0: continue
        tp = entry + r_unit_base
        sl_new = pl + alpha * (block_b - pl)
        r_unit_new = entry - sl_new
        if r_unit_new <= 0: continue
        c5_close_ms = c5.open_time + MS_HOUR
        rr = r_unit_base / r_unit_new
        rr_vals.append(rr)
        out = simulate(entry, sl_new, tp, c5_close_ms)
        if out == "win":
            n_win += 1
            total_r += rr  # WIN gives RR in new units
        elif out == "loss":
            n_loss += 1
            total_r -= 1.0

    n = n_win + n_loss
    wr = n_win / n * 100 if n else 0
    rr_avg = sum(rr_vals) / len(rr_vals) if rr_vals else 0
    sl_desc = f"pl + {alpha:.1f}×(bb-pl)"
    print(f"{alpha:<6} {sl_desc:<30} {n:<6} {n_win:<6} {n_loss:<6} {wr:<8.2f} {total_r:<+16.1f} {rr_avg:<12.3f}")
    results.append((alpha, n, n_win, n_loss, total_r, rr_avg))

# Best
best = max(results, key=lambda x: x[4])
print(f"\n=== Лучший: α = {best[0]:.1f}, ΣR = {best[4]:+.1f}R (new units), avg RR = {best[5]:.2f} ===")

# Также показать в baseline units для понимания
print(f"\n=== Тот же sweep, но R в baseline units (для прямого сравнения с baseline +86R) ===")
print(f"{'α':<6} {'n':<6} {'WIN':<6} {'LOSS':<6} {'ΣR baseline units':<20}")
print("-" * 60)
for alpha in ALPHAS:
    total_r_base = 0.0; n_win = 0; n_loss = 0
    for ir, c5 in patterns:
        block_b, _ = ir.rdrb.block
        entry = (ir.rdrb.block[0] + ir.rdrb.block[1]) / 2
        all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
        pl = min(c.low for c in all5)
        r_unit_base = entry - pl
        if r_unit_base <= 0: continue
        tp = entry + r_unit_base
        sl_new = pl + alpha * (block_b - pl)
        if entry - sl_new <= 0: continue
        c5_close_ms = c5.open_time + MS_HOUR
        out = simulate(entry, sl_new, tp, c5_close_ms)
        if out == "win":
            n_win += 1
            total_r_base += 1.0  # win = +1 baseline R
        elif out == "loss":
            n_loss += 1
            total_r_base += (sl_new - entry) / r_unit_base  # smaller absolute loss
    n = n_win + n_loss
    print(f"{alpha:<6} {n:<6} {n_win:<6} {n_loss:<6} {total_r_base:<+20.1f}")
