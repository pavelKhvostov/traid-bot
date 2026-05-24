"""Тестирует VWAP-фильтры на baseline (0.5 block, RR=1, pattern SL).

Идея: используем VWAP не как TP, а как ФИЛЬТР входа — отсекаем сетапы,
где VWAP в момент C5 close сигнализирует "плохую" зону. Цель — повысить WR.

Метрики VWAP в момент C5 close:
- VWAP относительно entry (выше / ниже / в block)
- VWAP slope (положительный / отрицательный за период anchor → C5)

Anchor: pattern_low (long) / pattern_high (short) — как обсуждали раньше.
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


def load_1m_full():
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


print("Loading 1m..."); data = load_1m_full(); ts_arr = [r[0] for r in data]
candles_1h = aggregate_1h(data); print(f"Loaded {len(data):,} 1m → {len(candles_1h):,} 1h\n")


def idx_at(ms):
    lo, hi = 0, len(ts_arr)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_arr[m] < ms: lo = m + 1
        else: hi = m
    return lo


def find_extreme_1m(s, e, side, val):
    for k in range(idx_at(s), idx_at(e)):
        if side == "long" and data[k][3] == val: return k
        if side == "short" and data[k][2] == val: return k
    return None


# Найти паттерны и вычислить метрики
print("Detecting patterns...")
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
    if side == "long":
        sl = min(c.low for c in all5)
    else:
        sl = max(c.high for c in all5)
    r_unit = (entry - sl) if side == "long" else (sl - entry)
    if r_unit <= 0: continue

    # VWAP anchor at pattern_low (long) / pattern_high (short)
    anchor_k = find_extreme_1m(c1.open_time, c5.open_time + MS_HOUR, side, sl)
    if anchor_k is None: continue
    end_anchor_k = idx_at(c5.open_time + MS_HOUR)
    cum_pv = 0.0; cum_vol = 0.0
    vwap_at_c1 = None  # at C1 close
    for k in range(anchor_k, end_anchor_k):
        _, _, _, _, cc, vv = data[k]
        cum_pv += vv * cc; cum_vol += vv
        if vwap_at_c1 is None and data[k][0] >= c1.open_time + MS_HOUR:
            vwap_at_c1 = cum_pv / cum_vol if cum_vol else 0
    vwap_at_c5 = cum_pv / cum_vol if cum_vol else 0
    slope = vwap_at_c5 - (vwap_at_c1 if vwap_at_c1 is not None else vwap_at_c5)

    # Simulate baseline (RR=1) trade
    start_k = end_anchor_k
    end_k = min(start_k + MAX_HOLD_MIN, len(data))
    tp = entry + r_unit if side == "long" else entry - r_unit
    in_trade = False
    outcome = "open"; r_val = 0.0
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

    if outcome == "open":
        continue

    # признаки для фильтрации
    vwap_rel_entry = vwap_at_c5 - entry  # positive = VWAP above entry
    in_block = block_b <= vwap_at_c5 <= block_t
    above_block = vwap_at_c5 > block_t
    below_block = vwap_at_c5 < block_b
    slope_dir = "up" if slope > 0 else ("down" if slope < 0 else "flat")
    slope_match = (side == "long" and slope > 0) or (side == "short" and slope < 0)

    records.append({
        "side": side, "outcome": outcome, "r_val": r_val,
        "vwap_at_c5": vwap_at_c5, "entry": entry, "r_unit": r_unit,
        "vwap_rel_entry": vwap_rel_entry, "in_block": in_block,
        "above_block": above_block, "below_block": below_block,
        "slope": slope, "slope_match": slope_match,
    })

print(f"Total closed trades: {len(records)}\n")


def report(name, items):
    if not items:
        print(f"{name:<55} n=0"); return
    n = len(items); w = sum(1 for x in items if x["outcome"] == "win")
    sr = sum(x["r_val"] for x in items)
    wr = w / n * 100
    exp = sr / n
    nl = sum(1 for x in items if x["side"] == "long")
    ns = sum(1 for x in items if x["side"] == "short")
    rl = sum(x["r_val"] for x in items if x["side"] == "long")
    rs = sum(x["r_val"] for x in items if x["side"] == "short")
    print(f"{name:<55} n={n:<5} WR={wr:5.2f}%  ΣR={sr:+7.1f}  R/tr={exp:+.3f}  L={nl}/{rl:+.1f}R  S={ns}/{rs:+.1f}R")


print(f"{'Filter':<55} {'n':<7} {'WR':<10} {'ΣR':<10} {'R/tr':<10} {'LONG':<15} {'SHORT':<15}")
print("-" * 130)
report("BASELINE (all trades)", records)
print()
report("F1 VWAP in block", [x for x in records if x["in_block"]])
report("F2 VWAP above block (long) / below (short)",
       [x for x in records if (x["side"] == "long" and x["above_block"]) or (x["side"] == "short" and x["below_block"])])
report("F3 VWAP below block (long) / above (short)",
       [x for x in records if (x["side"] == "long" and x["below_block"]) or (x["side"] == "short" and x["above_block"])])
print()
report("F4 VWAP > entry (long) / < entry (short)",
       [x for x in records if (x["side"] == "long" and x["vwap_rel_entry"] > 0) or (x["side"] == "short" and x["vwap_rel_entry"] < 0)])
report("F5 VWAP < entry (long) / > entry (short)",
       [x for x in records if (x["side"] == "long" and x["vwap_rel_entry"] < 0) or (x["side"] == "short" and x["vwap_rel_entry"] > 0)])
print()
report("F6 slope match direction", [x for x in records if x["slope_match"]])
report("F7 slope OPPOSITE direction", [x for x in records if not x["slope_match"]])
print()
report("F8 in_block AND slope_match", [x for x in records if x["in_block"] and x["slope_match"]])
report("F9 in_block AND VWAP > entry (long)/< entry (short)",
       [x for x in records if x["in_block"] and ((x["side"] == "long" and x["vwap_rel_entry"] > 0) or (x["side"] == "short" and x["vwap_rel_entry"] < 0))])
report("F10 in_block AND VWAP < entry (long)/> entry (short)",
       [x for x in records if x["in_block"] and ((x["side"] == "long" and x["vwap_rel_entry"] < 0) or (x["side"] == "short" and x["vwap_rel_entry"] > 0))])
