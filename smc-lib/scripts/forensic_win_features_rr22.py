"""Forensic анализ WIN сделок i-RDRB+FVG 1h при RR=2.2 (entry=0.5 block, SL=pattern_extreme).
Цель — найти общие фичи WIN-сегмента vs LOSS.
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
ATR_PERIOD = 14
N_FRACTAL = 2
RR_TARGET = 2.2

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

htf_candles = {name: aggregate(data, ms // 60_000) for name, ms in HTF_LIST}

# ATR(14) on 1h
atr_1h = [0.0] * len(candles_1h)
trs = [0.0] * len(candles_1h)
for i in range(1, len(candles_1h)):
    trs[i] = max(candles_1h[i].high - candles_1h[i].low,
                 abs(candles_1h[i].high - candles_1h[i - 1].close),
                 abs(candles_1h[i].low - candles_1h[i - 1].close))
for i in range(ATR_PERIOD, len(candles_1h)):
    if i == ATR_PERIOD:
        atr_1h[i] = sum(trs[1:ATR_PERIOD + 1]) / ATR_PERIOD
    else:
        atr_1h[i] = (atr_1h[i - 1] * (ATR_PERIOD - 1) + trs[i]) / ATR_PERIOD


# HTF OB / RDRB
htf_obs = {}; htf_rdrbs = {}
for name, cs in htf_candles.items():
    tf_ms = next(ms for n, ms in HTF_LIST if n == name)
    obs = []; rdrbs = []
    for i in range(len(cs) - 1):
        c, nxt = cs[i], cs[i + 1]
        if c.close < c.open and nxt.close > c.high:
            obs.append({"dir": "long", "open_ts": c.open_time, "end_ts": c.open_time + tf_ms})
        elif c.close > c.open and nxt.close < c.low:
            obs.append({"dir": "short", "open_ts": c.open_time, "end_ts": c.open_time + tf_ms})
    htf_obs[name] = obs
    for i in range(len(cs) - 2):
        r = detect_rdrb(cs[i], cs[i + 1], cs[i + 2])
        if r is None: continue
        rdrbs.append({"dir": r.direction, "c1_ts": cs[i].open_time,
                      "c3_end_ts": cs[i + 2].open_time + tf_ms,
                      "window_end_ts": cs[i].open_time + 3 * tf_ms})
    htf_rdrbs[name] = rdrbs


# Williams fractals on 15m
candles_15m = aggregate(data, 15)
fl_15m = []
for i in range(N_FRACTAL, len(candles_15m) - N_FRACTAL):
    l_i = candles_15m[i].low
    if all(l_i < candles_15m[j].low for j in range(i - N_FRACTAL, i)) and \
       all(l_i < candles_15m[j].low for j in range(i + 1, i + N_FRACTAL + 1)):
        fl_15m.append({"open_ts": candles_15m[i].open_time, "low": l_i,
                       "confirm_ts": candles_15m[i + N_FRACTAL].open_time + 15 * 60_000})
fh_15m = []
for i in range(N_FRACTAL, len(candles_15m) - N_FRACTAL):
    h_i = candles_15m[i].high
    if all(h_i > candles_15m[j].high for j in range(i - N_FRACTAL, i)) and \
       all(h_i > candles_15m[j].high for j in range(i + 1, i + N_FRACTAL + 1)):
        fh_15m.append({"open_ts": candles_15m[i].open_time, "high": h_i,
                       "confirm_ts": candles_15m[i + N_FRACTAL].open_time + 15 * 60_000})


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def simulate(side, entry, sl, tp, start_ms):
    sk = idx_at(start_ms); ek = min(sk + MAX_HOLD_MIN, len(data))
    in_trade = False
    for k in range(sk, ek):
        _, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if side == "long":
                if l_ <= entry:
                    in_trade = True
                    if l_ <= sl: return "loss"
                    if h_ >= tp: return "win"
            else:
                if h_ >= entry:
                    in_trade = True
                    if h_ >= sl: return "loss"
                    if l_ <= tp: return "win"
        else:
            if side == "long":
                if l_ <= sl: return "loss"
                if h_ >= tp: return "win"
            else:
                if h_ >= sl: return "loss"
                if l_ <= tp: return "win"
    return "no_fill"


def evot_in_pattern(c1_ms, c5_close_ms):
    j0 = idx_at(c1_ms); j1 = idx_at(c5_close_ms)
    max_bv = 0; max_bt = None
    max_sv = 0; max_st = None
    for k in range(j0, j1):
        ts, o, _, _, c, v = data[k]
        if c > o and v > max_bv: max_bv = v; max_bt = ts
        elif c < o and v > max_sv: max_sv = v; max_st = ts
    if max_bv > max_sv: return "BULL", max_bt
    if max_sv > max_bv: return "BEAR", max_st
    return "NONE", None


def check_f1(pattern_candles, direction):
    for name, obs in htf_obs.items():
        for ob in obs:
            if ob["dir"] != direction: continue
            for c in pattern_candles:
                if ob["open_ts"] <= c.open_time < ob["end_ts"]: return True
    return False


def check_f2_same(pattern_candles, direction, fill_close_ms):
    htf_dir = "short" if direction == "long" else "long"
    for name, rdrbs in htf_rdrbs.items():
        for r in rdrbs:
            if r["dir"] != htf_dir: continue
            if r["c3_end_ts"] > fill_close_ms: continue
            for c in pattern_candles:
                if r["c1_ts"] <= c.open_time < r["window_end_ts"]: return True
    return False


# Detect patterns + features
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
    all5 = [c1, c2, c3, c4, c5]
    pl = min(c.low for c in all5)
    ph = max(c.high for c in all5)
    sl = pl if side == "long" else ph
    r_unit_base = abs(entry - sl)
    if r_unit_base <= 0: continue

    tp_rr1 = entry + r_unit_base if side == "long" else entry - r_unit_base  # for fill timing
    tp_rr22 = entry + RR_TARGET * r_unit_base if side == "long" else entry - RR_TARGET * r_unit_base
    c5_close_ms = c5.open_time + MS_HOUR

    # Simulate at RR=2.2
    out = simulate(side, entry, sl, tp_rr22, c5_close_ms)
    if out not in ("win", "loss"): continue

    # Features
    block_height = block_t - block_b
    liq_height = (ir.rdrb.liq[1] - ir.rdrb.liq[0]) if ir.rdrb.liq else 0
    fvg_height = fvg.zone[1] - fvg.zone[0]
    c1_body = abs(c1.close - c1.open); c2_body = abs(c2.close - c2.open)
    c3_body = abs(c3.close - c3.open); c4_body = abs(ir.c4.close - ir.c4.open)
    c5_body = abs(c5.close - c5.open)
    atr_c5 = atr_1h[i + 4] if atr_1h[i + 4] > 0 else 1
    r_atr = r_unit_base / atr_c5
    if side == "long":
        c4_overshoot_r = (ir.c4.close - block_t) / r_unit_base
    else:
        c4_overshoot_r = (block_b - ir.c4.close) / r_unit_base

    evot_dir, mv_ts = evot_in_pattern(c1.open_time, c5_close_ms)
    evot_t_bucket = "NONE"
    if mv_ts:
        evot_t_bucket = f"C{min(5, max(1, int((mv_ts - c1.open_time) // MS_HOUR) + 1))}"

    f1 = check_f1(all5, side)
    # For F2 use fill at RR=1 (for timing)
    fill_close_ms = c5_close_ms + MS_HOUR  # approx
    f2 = check_f2_same(all5, side, fill_close_ms)

    # 15m FL count in zone (LONG only, similar for SHORT with FH)
    j0 = idx_at(c1.open_time); j1 = idx_at(c5_close_ms)
    p_low_ts = None; p_high_ts = None
    for k_ in range(j0, j1):
        if abs(data[k_][3] - pl) < 1e-6: p_low_ts = data[k_][0]; break
    for k_ in range(j0, j1):
        if abs(data[k_][2] - ph) < 1e-6: p_high_ts = data[k_][0]; break

    n_15m_fl_in_zone = 0
    if side == "long" and p_low_ts:
        for f in fl_15m:
            if c1.open_time <= f["open_ts"] <= c5_close_ms \
               and f["confirm_ts"] <= c5_close_ms \
               and f["open_ts"] > p_low_ts \
               and f["low"] > pl and f["low"] <= block_b:
                n_15m_fl_in_zone += 1
    elif side == "short" and p_high_ts:
        for f in fh_15m:
            if c1.open_time <= f["open_ts"] <= c5_close_ms \
               and f["confirm_ts"] <= c5_close_ms \
               and f["open_ts"] > p_high_ts \
               and f["high"] < ph and f["high"] >= block_t:
                n_15m_fl_in_zone += 1

    fill_dt = datetime.fromtimestamp(c5_close_ms / 1000, tz=timezone.utc)
    records.append({
        "outcome": out, "side": side, "variant": ir.rdrb.variant,
        "r_atr": r_atr,
        "block_h_r": block_height / r_unit_base,
        "liq_h_r": liq_height / r_unit_base,
        "fvg_h_r": fvg_height / r_unit_base,
        "c2_body_r": c2_body / r_unit_base,
        "c4_body_r": c4_body / r_unit_base,
        "c4_overshoot_r": c4_overshoot_r,
        "c5_body_r": c5_body / r_unit_base,
        "evot_dir": evot_dir, "evot_t": evot_t_bucket,
        "f1": f1, "f2": f2, "f1_or_f2": f1 or f2, "f1_and_f2": f1 and f2,
        "n_15m_fract_in_zone": n_15m_fl_in_zone,
        "hour_utc": fill_dt.hour,
        "dow": fill_dt.weekday(),
        "year": fill_dt.year,
    })


n = len(records)
n_w = sum(1 for x in records if x["outcome"] == "win")
n_l = n - n_w
print(f"\n=== RR=2.2 baseline на 1h: {n} closed, WIN {n_w}, LOSS {n_l}, WR {n_w/n*100:.2f}%, ΣR={n_w*2.2 - n_l:+.1f} ===\n")
print(f"Break-even WR for RR=2.2: {1/(1+2.2)*100:.2f}%\n")


def report(name, items, baseline_wr=None):
    if baseline_wr is None: baseline_wr = n_w / n * 100
    if not items: print(f"  {name:<55} n=0"); return
    nn = len(items); w = sum(1 for x in items if x["outcome"] == "win")
    sr = w * 2.2 - (nn - w)
    dprec = w/nn*100 - baseline_wr
    print(f"  {name:<55} n={nn:<5} WR={w/nn*100:5.2f}% (Δ{dprec:+5.2f}pp)  ΣR={sr:+6.1f}  R/tr={sr/nn:+.3f}")


def cat(key, name):
    print(f"\n--- {name} ---")
    vals = sorted({x[key] for x in records}, key=str)
    for v in vals:
        sub = [x for x in records if x[key] == v]
        report(f"{key}={v}", sub)


def num(key, bins, name):
    print(f"\n--- {name} ---")
    for lo, hi, label in bins:
        sub = [x for x in records if lo <= x[key] < hi]
        report(label, sub)


# Категории
cat("side", "Side")
cat("variant", "RDRB variant")
cat("evot_dir", "EVoT direction")
cat("evot_t", "EVoT time bucket")
cat("f1", "F1 (HTF OB)")
cat("f2", "F2_same (HTF RDRB)")
cat("f1_or_f2", "F1 ∪ F2")
cat("f1_and_f2", "F1 ∩ F2")

# Числовые
num("r_atr", [(0, 0.5, "<0.5"), (0.5, 0.85, "[0.5, 0.85)"), (0.85, 1.1, "[0.85, 1.1)"),
              (1.1, 1.5, "[1.1, 1.5)"), (1.5, 99, "≥1.5")], "R/ATR(14)")
num("c4_body_r", [(0, 0.3, "<0.3"), (0.3, 0.6, "[0.3, 0.6)"), (0.6, 1.0, "[0.6, 1.0)"),
                   (1.0, 1.5, "[1.0, 1.5)"), (1.5, 99, "≥1.5")], "C4 body / R_unit")
num("c4_overshoot_r", [(-99, 0, "<0"), (0, 0.3, "[0, 0.3)"), (0.3, 0.7, "[0.3, 0.7)"),
                       (0.7, 1.5, "[0.7, 1.5)"), (1.5, 99, "≥1.5")], "C4 overshoot R")
num("c2_body_r", [(0, 0.5, "<0.5"), (0.5, 1.0, "[0.5, 1.0)"),
                   (1.0, 1.5, "[1.0, 1.5)"), (1.5, 99, "≥1.5")], "C2 body / R_unit")
num("c5_body_r", [(0, 0.2, "<0.2"), (0.2, 0.5, "[0.2, 0.5)"),
                   (0.5, 1.0, "[0.5, 1.0)"), (1.0, 99, "≥1.0")], "C5 body / R_unit")
num("block_h_r", [(0, 0.1, "<0.1"), (0.1, 0.3, "[0.1, 0.3)"),
                   (0.3, 0.7, "[0.3, 0.7)"), (0.7, 99, "≥0.7")], "Block height / R_unit")
num("n_15m_fract_in_zone", [(0, 1, "0"), (1, 2, "1"), (2, 3, "2"), (3, 99, "≥3")],
    "15m fractals in zone")
num("hour_utc", [(0, 4, "0-3 UTC"), (4, 8, "4-7"), (8, 12, "8-11"),
                  (12, 16, "12-15"), (16, 20, "16-19"), (20, 24, "20-23")], "Hour UTC")
num("dow", [(0, 1, "Mon"), (1, 2, "Tue"), (2, 3, "Wed"), (3, 4, "Thu"),
            (4, 5, "Fri"), (5, 6, "Sat"), (6, 7, "Sun")], "Day of Week")
