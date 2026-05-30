"""Анализ EVoT (maxV в окне паттерна) — расширенные features.

Для каждого i-RDRB+FVG паттерна:
- EVoT direction (BULL/BEAR) внутри C1-C5
- В какой свече C1-C5 случился maxV
- Расстояние maxV от entry в R-unit
- Bull/Bear volume ratio

Срезы по этим features + baseline RR=1.
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


def aggregate_1h(d):
    out = []; cb = None; o = h = l = c = 0
    for ts, oo, hh, ll, cc, _ in d:
        b = ts - (ts % MS_HOUR)
        if b != cb:
            if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
    return out


print("Loading..."); data = load_1m(); ts_arr = [r[0] for r in data]
candles_1h = aggregate_1h(data)
print(f"{len(data):,} 1m → {len(candles_1h):,} 1h\n")


def idx_at(ms):
    lo, hi = 0, len(ts_arr)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_arr[m] < ms: lo = m + 1
        else: hi = m
    return lo


def evot_in_pattern(c1_ms, c5_close_ms):
    """maxV direction, value, time, vol_ratio в окне 1m [c1, c5_close)."""
    j0 = idx_at(c1_ms); j1 = idx_at(c5_close_ms)
    max_bv = 0; max_bc = None; max_bt = None
    max_sv = 0; max_sc = None; max_st = None
    for k in range(j0, j1):
        ts, o, _, _, c, v = data[k]
        if c > o:
            if v > max_bv: max_bv = v; max_bc = c; max_bt = ts
        elif c < o:
            if v > max_sv: max_sv = v; max_sc = c; max_st = ts
    if max_bv > max_sv:
        return "BULL", max_bc, max_bt, max_bv, max_sv
    elif max_sv > max_bv:
        return "BEAR", max_sc, max_st, max_sv, max_bv
    return "NONE", None, None, 0, 0


def time_bucket(maxv_ts, c1_ms):
    """В какой свече паттерна (C1..C5) maxV?"""
    delta = (maxv_ts - c1_ms) // MS_HOUR
    return f"C{min(5, max(1, int(delta) + 1))}"


patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    patterns.append((ir, c5))
print(f"{len(patterns)} patterns")

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

    # EVoT inside pattern
    direction, mv, mv_ts, dom_v, opp_v = evot_in_pattern(ir.rdrb.c1.open_time, c5.open_time + MS_HOUR)
    if mv is None: continue

    delta_to_entry = (mv - entry) if side == "long" else (entry - mv)
    delta_r = delta_to_entry / r_unit  # < 0 для long если maxV ниже entry
    vol_ratio = dom_v / opp_v if opp_v > 0 else float("inf")
    tbucket = time_bucket(mv_ts, ir.rdrb.c1.open_time)

    # Baseline backtest
    c5_close_idx = idx_at(c5.open_time + MS_HOUR)
    start_k = c5_close_idx
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
    records.append({
        "side": side, "outcome": outcome, "r": r_val,
        "evot_dir": direction, "delta_r": delta_r, "vol_ratio": vol_ratio,
        "tbucket": tbucket,
    })

print(f"Closed trades: {len(records)}\n")


def report(name, items):
    if not items: print(f"{name:<58}  n=0"); return
    n = len(items); w = sum(1 for x in items if x["outcome"]=="win")
    sr = sum(x["r"] for x in items)
    wr = w/n*100; exp = sr/n
    print(f"{name:<58}  n={n:<5}  WR={wr:5.2f}%  ΣR={sr:+7.1f}  R/tr={exp:+.3f}")


# === Срез по EVoT direction ===
print("=== По EVoT direction (внутри паттерна) ===")
report("BASELINE", records)
print("LONG only:")
report("  LONG, EVoT=BULL", [x for x in records if x["side"]=="long" and x["evot_dir"]=="BULL"])
report("  LONG, EVoT=BEAR", [x for x in records if x["side"]=="long" and x["evot_dir"]=="BEAR"])
print("SHORT only:")
report("  SHORT, EVoT=BULL", [x for x in records if x["side"]=="short" and x["evot_dir"]=="BULL"])
report("  SHORT, EVoT=BEAR", [x for x in records if x["side"]=="short" and x["evot_dir"]=="BEAR"])

# === Срез по времени maxV в паттерне ===
print("\n=== По свече maxV (LONG) ===")
for bucket in ("C1", "C2", "C3", "C4", "C5"):
    report(f"  LONG, maxV в {bucket}", [x for x in records if x["side"]=="long" and x["tbucket"]==bucket])
print("=== По свече maxV (SHORT) ===")
for bucket in ("C1", "C2", "C3", "C4", "C5"):
    report(f"  SHORT, maxV в {bucket}", [x for x in records if x["side"]=="short" and x["tbucket"]==bucket])

# === Срез по расстоянию maxV от entry в R-unit (LONG) ===
print("\n=== По расстоянию maxV от entry в R-unit (LONG) ===")
long_records = [x for x in records if x["side"]=="long"]
buckets = [(-2.0, -0.5, "≤ -0.5R (deep below)"), (-0.5, -0.2, "(-0.5, -0.2)"), (-0.2, 0.0, "(-0.2, 0)"), (0.0, 1.0, "≥ 0 (выше entry)")]
for lo, hi, name in buckets:
    sub = [x for x in long_records if lo <= x["delta_r"] < hi]
    report(f"  LONG, delta_R ∈ {name}", sub)

print("\n=== По расстоянию maxV от entry в R-unit (SHORT) ===")
short_records = [x for x in records if x["side"]=="short"]
for lo, hi, name in buckets:
    sub = [x for x in short_records if lo <= x["delta_r"] < hi]
    report(f"  SHORT, delta_R ∈ {name}", sub)

# === Композитные срезы ===
print("\n=== Композит: LONG, maxV deep below (≤−0.5R) ===")
sub = [x for x in long_records if x["delta_r"] <= -0.5]
report("  ALL", sub)
for d in ("BULL", "BEAR"):
    report(f"  + EVoT={d}", [x for x in sub if x["evot_dir"]==d])

print("\n=== Композит: LONG, maxV в C1 или C2 (early bears done) ===")
sub = [x for x in long_records if x["tbucket"] in ("C1", "C2")]
report("  ALL", sub)
for d in ("BULL", "BEAR"):
    report(f"  + EVoT={d}", [x for x in sub if x["evot_dir"]==d])
