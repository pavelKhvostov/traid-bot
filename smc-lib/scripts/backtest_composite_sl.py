"""Composite SL для LONG i-RDRB+FVG.

Логика SL:
1. Если есть валидный 15m FL в [pattern_low, block.bottom] → SL = highest FL.low
2. Иначе если есть unmitigated bullish 15m FVG в [pattern_low, block.bottom] → SL = highest FVG.bottom
3. Иначе → SL = pattern_low + 0.1 × (block.bottom − pattern_low)

Entry = 0.5 block (unchanged). TP = entry + (entry − pattern_low) (baseline TP price).
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
MS_15M = 15 * 60_000
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


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


# 15m FLs (Williams N=2)
fl_15m = []
for i in range(N_FRACTAL, len(candles_15m) - N_FRACTAL):
    l_i = candles_15m[i].low
    if all(l_i < candles_15m[j].low for j in range(i - N_FRACTAL, i)) and \
       all(l_i < candles_15m[j].low for j in range(i + 1, i + N_FRACTAL + 1)):
        fl_15m.append({
            "open_ts": candles_15m[i].open_time,
            "low_price": l_i,
            "confirm_ts": candles_15m[i + N_FRACTAL].open_time + MS_15M,
        })

# 15m bullish FVGs
fvgs_15m = []
for i in range(len(candles_15m) - 2):
    c1 = candles_15m[i]; c3 = candles_15m[i + 2]
    if c1.high < c3.low:
        fvg = {"formed_ts": c3.open_time + MS_15M, "top": c3.low, "bottom": c1.high, "c3_idx": i + 2}
        fvg["mit_ts"] = None
        for j in range(i + 3, len(candles_15m)):
            if candles_15m[j].low <= fvg["top"]:
                fvg["mit_ts"] = candles_15m[j].open_time; break
        fvgs_15m.append(fvg)


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


# Pattern detection
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None or ir.direction != "long": continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != "long": continue
    patterns.append((ir, c5))


# Composite backtest
stats_composite = {"win": 0, "loss": 0, "n": 0, "total_r_new": 0.0, "total_r_base": 0.0,
                    "fl_used": 0, "fvg_used": 0, "default_used": 0}

stats_baseline = {"win": 0, "loss": 0, "n": 0, "total_r": 0.0}
stats_01 = {"win": 0, "loss": 0, "n": 0, "total_r_new": 0.0, "total_r_base": 0.0}
rr_per_win = []

for ir, c5 in patterns:
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    pl = min(c.low for c in all5)
    r_unit_base = entry - pl
    if r_unit_base <= 0: continue
    tp = entry + r_unit_base
    c5_close_ms = c5.open_time + MS_HOUR
    pattern_start = ir.rdrb.c1.open_time

    # pattern_low ts
    j0 = idx_at(pattern_start); j1 = idx_at(c5_close_ms)
    p_low_ts = None
    for k_ in range(j0, j1):
        if abs(data[k_][3] - pl) < 1e-6: p_low_ts = data[k_][0]; break
    if p_low_ts is None:
        bl = float("inf")
        for k_ in range(j0, j1):
            if data[k_][3] < bl: bl = data[k_][3]; p_low_ts = data[k_][0]

    # Валидные FL в зоне
    valid_fls = [f for f in fl_15m
                 if pattern_start <= f["open_ts"] <= c5_close_ms
                 and f["confirm_ts"] <= c5_close_ms
                 and f["open_ts"] > p_low_ts
                 and f["low_price"] > pl
                 and f["low_price"] <= block_b]

    # Валидные FVG в зоне (unmitigated, в окне паттерна)
    valid_fvgs = [f for f in fvgs_15m
                  if pattern_start <= f["formed_ts"] <= c5_close_ms
                  and f["bottom"] >= pl
                  and f["top"] <= block_b
                  and (f["mit_ts"] is None or f["mit_ts"] > c5_close_ms)]

    # Composite SL
    sl_default_01 = pl + 0.10 * (block_b - pl)
    if valid_fls:
        sl_composite = max(f["low_price"] for f in valid_fls)
        sl_source = "FL"
    elif valid_fvgs:
        sl_composite = max(f["bottom"] for f in valid_fvgs)
        sl_source = "FVG"
    else:
        sl_composite = sl_default_01
        sl_source = "default 0.1"

    # Safety: SL не должен быть выше entry
    if sl_composite >= entry: continue
    r_unit_composite = entry - sl_composite
    rr_composite = r_unit_base / r_unit_composite

    # Composite simulation
    out_c = simulate(entry, sl_composite, tp, c5_close_ms)
    if out_c in ("win", "loss"):
        stats_composite["n"] += 1
        stats_composite[sl_source.lower().replace(" ", "_").replace(".", "")[:8] + "_used"] = \
            stats_composite.get(sl_source.lower().replace(" ", "_").replace(".", "")[:8] + "_used", 0)
        if sl_source == "FL": stats_composite["fl_used"] += 1
        elif sl_source == "FVG": stats_composite["fvg_used"] += 1
        else: stats_composite["default_used"] += 1
        if out_c == "win":
            stats_composite["win"] += 1
            stats_composite["total_r_new"] += rr_composite
            stats_composite["total_r_base"] += 1.0
            rr_per_win.append(rr_composite)
        else:
            stats_composite["loss"] += 1
            stats_composite["total_r_new"] -= 1.0
            stats_composite["total_r_base"] += (sl_composite - entry) / r_unit_base  # fractional loss

    # Baseline (SL = pattern_low)
    out_b = simulate(entry, pl, tp, c5_close_ms)
    if out_b in ("win", "loss"):
        stats_baseline["n"] += 1
        stats_baseline[out_b] += 1
        stats_baseline["total_r"] += 1.0 if out_b == "win" else -1.0

    # SL 0.1 baseline
    if entry - sl_default_01 > 0:
        rr_01 = r_unit_base / (entry - sl_default_01)
        out_01 = simulate(entry, sl_default_01, tp, c5_close_ms)
        if out_01 in ("win", "loss"):
            stats_01["n"] += 1
            stats_01[out_01] += 1
            if out_01 == "win":
                stats_01["total_r_new"] += rr_01
                stats_01["total_r_base"] += 1.0
            else:
                stats_01["total_r_new"] -= 1.0
                stats_01["total_r_base"] += (sl_default_01 - entry) / r_unit_base


print(f"=== Composite SL стратегия (LONG only) ===\n")
print(f"Source распределение:")
print(f"  FL used:       {stats_composite['fl_used']} patterns")
print(f"  FVG used:      {stats_composite['fvg_used']} patterns")
print(f"  Default 0.1:   {stats_composite['default_used']} patterns")
print(f"  Total:         {stats_composite['n']} patterns\n")

n = stats_composite["n"]
n_w = stats_composite["win"]; n_l = stats_composite["loss"]
print(f"WIN: {n_w}, LOSS: {n_l}")
print(f"WR:  {n_w / n * 100:.2f}%")
print(f"ΣR (new R-units):     {stats_composite['total_r_new']:+.1f}")
print(f"ΣR (baseline units):  {stats_composite['total_r_base']:+.1f}")
if rr_per_win:
    print(f"avg RR per win:       {sum(rr_per_win)/len(rr_per_win):.2f}")
    print(f"median RR per win:    {sorted(rr_per_win)[len(rr_per_win)//2]:.2f}")
print(f"R/tr (new):           {stats_composite['total_r_new']/n:+.3f}")


print(f"\n=== Сравнение со ставками-эталонами ===\n")
print(f"{'Strategy':<28} {'n':<6} {'WIN':<6} {'LOSS':<6} {'WR%':<7} {'ΣR_new':<10} {'ΣR_base':<10}")
print("-" * 80)

# Baseline
b = stats_baseline
print(f"{'A baseline (pl)':<28} {b['n']:<6} {b['win']:<6} {b['loss']:<6} {b['win']/(b['win']+b['loss'])*100:<7.2f} {b['total_r']:<+10.1f} {b['total_r']:<+10.1f}")
# SL 0.1
b1 = stats_01
print(f"{'B SL 0.1 (uniform)':<28} {b1['n']:<6} {b1['win']:<6} {b1['loss']:<6} {b1['win']/(b1['win']+b1['loss'])*100:<7.2f} {b1['total_r_new']:<+10.1f} {b1['total_r_base']:<+10.1f}")
# Composite
c = stats_composite
print(f"{'C Composite FL/FVG/0.1':<28} {c['n']:<6} {c['win']:<6} {c['loss']:<6} {c['win']/(c['win']+c['loss'])*100:<7.2f} {c['total_r_new']:<+10.1f} {c['total_r_base']:<+10.1f}")
