"""TP grid sweep на 506 trades (F1 ∪ F2 filter).

Entry = 0.5 block (baseline), SL = pattern_extreme (baseline).
TP = entry ± RR × (entry - pattern_extreme).
RR sweep: 0.1 → 3.0 step 0.1.
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
MAX_HOLD_MIN = 30 * 24 * 60
HTF_LIST = [("4h", 4 * MS_HOUR), ("6h", 6 * MS_HOUR), ("8h", 8 * MS_HOUR),
            ("12h", 12 * MS_HOUR), ("1D", 24 * MS_HOUR)]


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

# HTF candles
htf_candles = {name: aggregate(data, ms // 60_000) for name, ms in HTF_LIST}

# HTF OBs
htf_obs = {}
for name, cs in htf_candles.items():
    tf_ms = next(ms for n, ms in HTF_LIST if n == name)
    obs = []
    for i in range(len(cs) - 1):
        c, nxt = cs[i], cs[i + 1]
        if c.close < c.open and nxt.close > c.high:
            obs.append({"dir": "long", "open_ts": c.open_time, "end_ts": c.open_time + tf_ms})
        elif c.close > c.open and nxt.close < c.low:
            obs.append({"dir": "short", "open_ts": c.open_time, "end_ts": c.open_time + tf_ms})
    htf_obs[name] = obs

# HTF RDRBs
htf_rdrbs = {}
for name, cs in htf_candles.items():
    tf_ms = next(ms for n, ms in HTF_LIST if n == name)
    rdrbs = []
    for i in range(len(cs) - 2):
        r = detect_rdrb(cs[i], cs[i + 1], cs[i + 2])
        if r is None: continue
        rdrbs.append({"dir": r.direction, "c1_ts": cs[i].open_time,
                      "c3_end_ts": cs[i + 2].open_time + tf_ms,
                      "window_end_ts": cs[i].open_time + 3 * tf_ms})
    htf_rdrbs[name] = rdrbs


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def check_f1(pattern_candles, direction):
    for name, obs in htf_obs.items():
        for ob in obs:
            if ob["dir"] != direction: continue
            for c in pattern_candles:
                if ob["open_ts"] <= c.open_time < ob["end_ts"]:
                    return True
    return False


def check_f2_same(pattern_candles, direction, fill_close_ms):
    htf_dir_target = "short" if direction == "long" else "long"
    for name, rdrbs in htf_rdrbs.items():
        for r in rdrbs:
            if r["dir"] != htf_dir_target: continue
            if r["c3_end_ts"] > fill_close_ms: continue
            for c in pattern_candles:
                if r["c1_ts"] <= c.open_time < r["window_end_ts"]:
                    return True
    return False


def simulate(side, entry, sl, tp, start_ms):
    sk = idx_at(start_ms); ek = min(sk + MAX_HOLD_MIN, len(data))
    in_trade = False; fill_ms = None
    for k in range(sk, ek):
        ts, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if side == "long":
                if l_ <= entry:
                    in_trade = True; fill_ms = ts
                    if l_ <= sl: return "loss", fill_ms
                    if h_ >= tp: return "win", fill_ms
            else:
                if h_ >= entry:
                    in_trade = True; fill_ms = ts
                    if h_ >= sl: return "loss", fill_ms
                    if l_ <= tp: return "win", fill_ms
        else:
            if side == "long":
                if l_ <= sl: return "loss", fill_ms
                if h_ >= tp: return "win", fill_ms
            else:
                if h_ >= sl: return "loss", fill_ms
                if l_ <= tp: return "win", fill_ms
    return "no_fill", fill_ms


# Detect patterns
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    patterns.append((ir, c5))

# Apply F1 ∪ F2 filter and collect filtered trades
filtered = []
for ir, c5 in patterns:
    side = ir.direction
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    sl = min(c.low for c in all5) if side == "long" else max(c.high for c in all5)
    r_unit = abs(entry - sl)
    if r_unit <= 0: continue
    c5_close_ms = c5.open_time + MS_HOUR

    # First simulate baseline (RR=1) to find fill time (needed for F2)
    tp_baseline = entry + r_unit if side == "long" else entry - r_unit
    out, fill_ms = simulate(side, entry, sl, tp_baseline, c5_close_ms)
    if out not in ("win", "loss"): continue
    fill_close_ms = (fill_ms or c5_close_ms) + MS_HOUR

    f1 = check_f1(all5, side)
    f2 = check_f2_same(all5, side, fill_close_ms)
    if not (f1 or f2): continue  # filter out
    filtered.append({"side": side, "entry": entry, "sl": sl, "r_unit": r_unit,
                     "c5_close_ms": c5_close_ms})

print(f"F1 ∪ F2 filtered: {len(filtered)} patterns")

# TP sweep
import numpy as np
rr_values = [round(0.1 * i, 1) for i in range(1, 31)]  # 0.1 ... 3.0

print(f"\n{'RR':<5} {'n':<6} {'WIN':<5} {'LOSS':<5} {'NoFill':<8} {'WR%':<8} {'ΣR':<8} {'R/tr':<8}")
print("-" * 70)
best_rr = None; best_sr = -999
results = []
for rr in rr_values:
    n_w = 0; n_l = 0; n_nf = 0
    total_r = 0.0
    for t in filtered:
        tp = t["entry"] + rr * t["r_unit"] if t["side"] == "long" else t["entry"] - rr * t["r_unit"]
        out, _ = simulate(t["side"], t["entry"], t["sl"], tp, t["c5_close_ms"])
        if out == "win": n_w += 1; total_r += rr
        elif out == "loss": n_l += 1; total_r -= 1.0
        else: n_nf += 1
    n = n_w + n_l
    wr = n_w / n * 100 if n else 0
    rtr = total_r / n if n else 0
    print(f"{rr:<5} {n:<6} {n_w:<5} {n_l:<5} {n_nf:<8} {wr:<8.2f} {total_r:<+8.1f} {rtr:<+8.3f}")
    if total_r > best_sr:
        best_sr = total_r; best_rr = rr
    results.append((rr, n, n_w, n_l, wr, total_r))

print(f"\nBest RR = {best_rr}, ΣR = {best_sr:+.1f}")
