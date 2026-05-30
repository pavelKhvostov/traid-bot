"""Стратегия: limit-entry на 15m RDRB.block.bottom вместо 0.5 от 1h block.

Применяется только к LONG patterns с РОВНО 1 валидным 15m RDRB.
Для остальных — baseline (0.5 block 1h).

SL = pattern_low (unchanged). TP = entry_baseline + (entry_baseline - pattern_low) (фиксированный price).
R считается в baseline-юнитах для прямого сравнения.

Симуляция fill:
- Limit at 15m RDRB.block.bottom после C5 close
- Если low ≤ block.bottom → fill at block.bottom
- Если не дошёл → no fill (нет trade)
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


patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None or ir.direction != "long": continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != "long": continue
    patterns.append((ir, c5))


def simulate_with_entry(entry, sl, tp, start_ms):
    """Возвращает (outcome, exit_price)."""
    sk = idx_at(start_ms); ek = min(sk + MAX_HOLD_MIN, len(data))
    in_trade = False
    for k in range(sk, ek):
        _, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if l_ <= entry:
                in_trade = True
                if l_ <= sl: return "loss", sl
                if h_ >= tp: return "win", tp
        else:
            if l_ <= sl: return "loss", sl
            if h_ >= tp: return "win", tp
    return "no_fill", None


# Stats
stats = {
    "A_baseline_all": {"win": 0, "loss": 0, "n": 0, "total_r": 0.0},
    "E_rdrb_entry_for_1rdrb": {"win": 0, "loss": 0, "no_fill": 0, "n_attempted": 0, "total_r": 0.0,
                                "patterns_1rdrb_total": 0},
}

# Subset stats (для 1-RDRB patterns)
subset = {"A_baseline_1rdrb": {"win": 0, "loss": 0, "n": 0, "total_r": 0.0},
          "E_rdrb_entry_1rdrb": {"win": 0, "loss": 0, "no_fill": 0, "n": 0, "total_r": 0.0}}

for ir, c5 in patterns:
    block_b_1h, block_t_1h = ir.rdrb.block
    entry_base = (block_b_1h + block_t_1h) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    sl = min(c.low for c in all5)
    r_unit_base = entry_base - sl
    if r_unit_base <= 0: continue
    tp = entry_base + r_unit_base
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

    # 15m RDRBs в зоне
    in_zone = [r for r in rdrbs_15m
               if pattern_start <= r["formed_ts"] <= c5_close_ms
               and r["c2_open_ts"] > p_low_ts
               and r["block_top"] <= block_b_1h
               and r["block_bottom"] > sl]

    # Baseline A — все patterns
    out_a, exit_a = simulate_with_entry(entry_base, sl, tp, c5_close_ms)
    if out_a not in ("win", "loss"): continue
    r_a = +1.0 if out_a == "win" else -1.0
    stats["A_baseline_all"]["n"] += 1
    stats["A_baseline_all"][out_a] += 1
    stats["A_baseline_all"]["total_r"] += r_a

    # E применяется только при ровно 1 RDRB
    if len(in_zone) == 1:
        stats["E_rdrb_entry_for_1rdrb"]["patterns_1rdrb_total"] += 1
        subset["A_baseline_1rdrb"]["n"] += 1
        subset["A_baseline_1rdrb"][out_a] += 1
        subset["A_baseline_1rdrb"]["total_r"] += r_a

        # E: limit at 15m RDRB block.bottom
        new_entry = in_zone[0]["block_bottom"]
        out_e, exit_e = simulate_with_entry(new_entry, sl, tp, c5_close_ms)
        if out_e == "no_fill":
            stats["E_rdrb_entry_for_1rdrb"]["no_fill"] += 1
            subset["E_rdrb_entry_1rdrb"]["no_fill"] += 1
            r_e = 0.0
        elif out_e == "win":
            r_e = (tp - new_entry) / r_unit_base
            stats["E_rdrb_entry_for_1rdrb"]["win"] += 1
            subset["E_rdrb_entry_1rdrb"]["win"] += 1
        else:  # loss
            r_e = (sl - new_entry) / r_unit_base  # NEGATIVE, less than -1
            stats["E_rdrb_entry_for_1rdrb"]["loss"] += 1
            subset["E_rdrb_entry_1rdrb"]["loss"] += 1
        stats["E_rdrb_entry_for_1rdrb"]["total_r"] += r_e
        stats["E_rdrb_entry_for_1rdrb"]["n_attempted"] += 1
        subset["E_rdrb_entry_1rdrb"]["n"] += 1
        subset["E_rdrb_entry_1rdrb"]["total_r"] += r_e


print(f"=== Сравнение entry-стратегий для LONG i-RDRB+FVG ===\n")

a = stats["A_baseline_all"]
print(f"A baseline (0.5 block, все 392 patterns):")
print(f"  n={a['n']}, WIN={a['win']}, LOSS={a['loss']}, WR={a['win']/(a['win']+a['loss'])*100:.2f}%")
print(f"  ΣR = {a['total_r']:+.1f}, R/tr = {a['total_r']/a['n']:+.3f}\n")

print(f"=== Subset: patterns с РОВНО 1 валидным 15m RDRB ({stats['E_rdrb_entry_for_1rdrb']['patterns_1rdrb_total']} patterns) ===\n")
sub_a = subset["A_baseline_1rdrb"]
sub_e = subset["E_rdrb_entry_1rdrb"]
print(f"Baseline на этом subset:")
print(f"  n={sub_a['n']}, WIN={sub_a['win']}, LOSS={sub_a['loss']}, WR={sub_a['win']/(sub_a['win']+sub_a['loss'])*100:.2f}%")
print(f"  ΣR = {sub_a['total_r']:+.1f}, R/tr = {sub_a['total_r']/sub_a['n']:+.3f}\n")

n_e_filled = sub_e['win'] + sub_e['loss']
print(f"E (limit at 15m RDRB.block.bottom):")
print(f"  Attempted: {sub_e['n']}, Filled: {n_e_filled} ({n_e_filled/sub_e['n']*100:.1f}%), No fill: {sub_e['no_fill']}")
print(f"  WIN: {sub_e['win']}, LOSS: {sub_e['loss']}, WR (по filled): {sub_e['win']/n_e_filled*100 if n_e_filled else 0:.2f}%")
print(f"  ΣR = {sub_e['total_r']:+.1f} (baseline units)")
print(f"  R/tr (по attempted): {sub_e['total_r']/sub_e['n']:+.3f}")
print(f"  R/tr (по filled): {sub_e['total_r']/n_e_filled if n_e_filled else 0:+.3f}\n")

delta = sub_e['total_r'] - sub_a['total_r']
print(f"Δ ΣR (E vs A для 140 patterns): {delta:+.1f}R")

# Полная LONG-стратегия: E для 1-RDRB patterns + baseline для остальных
e_for_1rdrb = stats["E_rdrb_entry_for_1rdrb"]["total_r"]
n_1rdrb = stats["E_rdrb_entry_for_1rdrb"]["patterns_1rdrb_total"]
baseline_other = stats["A_baseline_all"]["total_r"] - sub_a["total_r"]
total_e_strategy = e_for_1rdrb + baseline_other
print(f"\n=== Полная стратегия E (RDRB-entry для 1-RDRB patterns, baseline для остальных) ===")
print(f"ΣR (subset 1-RDRB):  {e_for_1rdrb:+.1f}")
print(f"ΣR (other patterns): {baseline_other:+.1f}")
print(f"ΣR (total LONG):     {total_e_strategy:+.1f}")
print(f"vs Baseline A:        {stats['A_baseline_all']['total_r']:+.1f}")
print(f"Δ:                    {total_e_strategy - stats['A_baseline_all']['total_r']:+.1f}R")
