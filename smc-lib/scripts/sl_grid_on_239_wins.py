"""WR и ΣR при SL=0.2/0.3/0.4/0.5 между pattern_low и block.bottom,
посчитано на 239 baseline WIN сделках LONG.

R считается в new R-units (= entry - SL_new). WIN = +new_RR, LOSS = -1.
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


patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None or ir.direction != "long": continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != "long": continue
    patterns.append((ir, c5))


# Сначала определим 239 baseline winners (SL = pattern_low)
baseline_winners = []
for ir, c5 in patterns:
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    pl = min(c.low for c in all5)
    r_unit_base = entry - pl
    if r_unit_base <= 0: continue
    tp = entry + r_unit_base
    c5_close_ms = c5.open_time + MS_HOUR
    out = simulate(entry, pl, tp, c5_close_ms)
    if out == "win":
        baseline_winners.append((ir, c5, entry, pl, tp, block_b, r_unit_base, c5_close_ms))

print(f"Baseline LONG winners: {len(baseline_winners)}\n")


# Sweep
print(f"{'SL offset':<12} {'WIN':<6} {'LOSS':<6} {'WR%':<8} {'ΣR (new units)':<16} {'avg RR per win':<14}")
print("-" * 70)
for offset in (0.2, 0.3, 0.4, 0.5):
    n_win = 0; n_loss = 0
    total_r = 0.0
    rr_sum_win = 0.0
    for ir, c5, entry, pl, tp, block_b, r_unit_base, c5_close_ms in baseline_winners:
        sl_new = pl + offset * (block_b - pl)
        r_unit_new = entry - sl_new
        if r_unit_new <= 0: continue
        rr = r_unit_base / r_unit_new
        out = simulate(entry, sl_new, tp, c5_close_ms)
        if out == "win":
            n_win += 1
            total_r += rr
            rr_sum_win += rr
        elif out == "loss":
            n_loss += 1
            total_r -= 1.0

    n = n_win + n_loss
    wr = n_win / n * 100 if n else 0
    avg_rr_win = rr_sum_win / n_win if n_win else 0
    print(f"{offset:<12.1f} {n_win:<6} {n_loss:<6} {wr:<8.2f} {total_r:<+16.1f} {avg_rr_win:<14.2f}")
