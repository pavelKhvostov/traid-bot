"""Сравнение стратегий VWAP-TP на i-RDRB+FVG (BTC 1h, 6 лет).

Все варианты используют одинаковый entry (0.5 RDRB block, лимит ждёт fill) и SL = pattern_extreme.
Различаются способом расчёта TP:

A) baseline:        TP = entry + R (RR 1:1), R = entry − SL
B) vwap_same:       TP = текущий VWAP, anchor = pattern_extreme в направлении SL
                    (long → anchor at pattern_low, short → anchor at pattern_high)
C) vwap_opposite:   TP = текущий VWAP, anchor = противоположный extreme
                    (long → anchor at pattern_high, short → anchor at pattern_low)
D) vwap_c5:         TP = текущий VWAP, anchor = открытие C5 candle

R-метрика: для LOSS r = -1. Для WIN при baseline r = +1. Для VWAP-TP вариантов
r = (exit_price − entry) / (entry − SL), может быть от 0 до +∞.

Если за 30 дней ни SL ни TP не сработали — open (не входит в WR/sumR).
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
MAX_HOLD_MIN = 30 * 24 * 60  # 30 days


def load_1m_full():
    rows = []
    with CSV_PATH.open() as f:
        reader = csv.reader(f); next(reader)
        for r in reader:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate_to_1h(data_1m):
    out = []; cur_b = None; o = h = l = c = 0
    for ts, oo, hh, ll, cc, _ in data_1m:
        b = ts - (ts % MS_HOUR)
        if b != cur_b:
            if cur_b is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cur_b))
            cur_b = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cur_b is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cur_b))
    return out


print("Loading 1m..."); data = load_1m_full(); ts_arr = [r[0] for r in data]
print(f"Loaded {len(data):,} 1m candles")
candles_1h = aggregate_to_1h(data); print(f"Aggregated to {len(candles_1h):,} 1h candles")


def idx_at(ms):
    lo, hi = 0, len(ts_arr)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_arr[m] < ms: lo = m + 1
        else: hi = m
    return lo


def find_extreme_1m(start_ms, end_ms, side, extreme_val):
    j0 = idx_at(start_ms); j1 = idx_at(end_ms)
    for k in range(j0, j1):
        if side == "long" and data[k][3] == extreme_val: return k
        if side == "short" and data[k][2] == extreme_val: return k
    return None


# Найти паттерны
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    patterns.append((ir, c5))
print(f"Total i-RDRB+FVG patterns: {len(patterns)}\n")


def run_variant(name, tp_rule):
    """tp_rule(side, entry, sl, ir, c5) → возвращает функцию, которая принимает (ts, vwap_at_ts, low, high) и возвращает (outcome, r_val) или None.

    Для baseline: tp_rule = "rr1" — фиксированный TP.
    Для VWAP-TP: возвращает dict с anchor_ms и сравнивает с VWAP.
    """
    stats = {"long": {"win": 0, "loss": 0, "open": 0}, "short": {"win": 0, "loss": 0, "open": 0}}
    sum_r = 0.0; sum_r_long = 0.0; sum_r_short = 0.0; wins_r = []; losses_r = []

    for ir, c5 in patterns:
        side = ir.direction
        block_b, block_t = ir.rdrb.block
        entry = (block_b + block_t) / 2
        all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
        if side == "long":
            sl = min(c.low for c in all5)
            p_extreme_other = max(c.high for c in all5)
        else:
            sl = max(c.high for c in all5)
            p_extreme_other = min(c.low for c in all5)
        r_unit = (entry - sl) if side == "long" else (sl - entry)
        if r_unit <= 0:
            continue

        # Определяем anchor_ms для VWAP-варианта
        if tp_rule == "rr1":
            anchor_idx = None
        elif tp_rule == "vwap_same":
            # anchor = pattern_extreme в направлении SL (low для long, high для short)
            anchor_idx = find_extreme_1m(ir.rdrb.c1.open_time, c5.open_time + MS_HOUR, side, sl)
        elif tp_rule == "vwap_opposite":
            other_side = "short" if side == "long" else "long"
            anchor_idx = find_extreme_1m(ir.rdrb.c1.open_time, c5.open_time + MS_HOUR, other_side, p_extreme_other)
        elif tp_rule == "vwap_c5":
            anchor_idx = idx_at(c5.open_time)
        else:
            raise ValueError(tp_rule)

        # Считаем cumulative VWAP с anchor
        cum_pv = 0.0; cum_vol = 0.0
        if anchor_idx is not None:
            for k in range(anchor_idx, idx_at(c5.open_time + MS_HOUR)):
                _, _, _, _, cc, vv = data[k]
                cum_pv += vv * cc; cum_vol += vv

        # Сканируем после C5
        start_k = idx_at(c5.open_time + MS_HOUR)
        end_k = min(start_k + MAX_HOLD_MIN, len(data))
        in_trade = False
        outcome = "open"
        for k in range(start_k, end_k):
            ts, _, h_, l_, c_, v_ = data[k]
            if anchor_idx is not None:
                cum_pv += v_ * c_; cum_vol += v_
                vwap = cum_pv / cum_vol if cum_vol else 0
            if not in_trade:
                if side == "long":
                    if l_ <= entry:
                        in_trade = True
                        # check SL/TP в той же свече
                        if l_ <= sl:
                            outcome = "loss"; r_val = -1.0; break
                        if tp_rule == "rr1":
                            tp = entry + r_unit
                            if h_ >= tp: outcome = "win"; r_val = +1.0; break
                        else:
                            if vwap > entry and h_ >= vwap:
                                outcome = "win"; r_val = (vwap - entry) / r_unit; break
                else:
                    if h_ >= entry:
                        in_trade = True
                        if h_ >= sl:
                            outcome = "loss"; r_val = -1.0; break
                        if tp_rule == "rr1":
                            tp = entry - r_unit
                            if l_ <= tp: outcome = "win"; r_val = +1.0; break
                        else:
                            if vwap < entry and l_ <= vwap:
                                outcome = "win"; r_val = (entry - vwap) / r_unit; break
            else:
                if side == "long":
                    if l_ <= sl: outcome = "loss"; r_val = -1.0; break
                    if tp_rule == "rr1":
                        tp = entry + r_unit
                        if h_ >= tp: outcome = "win"; r_val = +1.0; break
                    else:
                        if vwap > entry and h_ >= vwap:
                            outcome = "win"; r_val = (vwap - entry) / r_unit; break
                else:
                    if h_ >= sl: outcome = "loss"; r_val = -1.0; break
                    if tp_rule == "rr1":
                        tp = entry - r_unit
                        if l_ <= tp: outcome = "win"; r_val = +1.0; break
                    else:
                        if vwap < entry and l_ <= vwap:
                            outcome = "win"; r_val = (entry - vwap) / r_unit; break

        if outcome == "open":
            stats[side]["open"] += 1
            continue
        stats[side][outcome] += 1
        sum_r += r_val
        if side == "long": sum_r_long += r_val
        else: sum_r_short += r_val
        if outcome == "win": wins_r.append(r_val)
        else: losses_r.append(r_val)

    n_w = stats["long"]["win"] + stats["short"]["win"]
    n_l = stats["long"]["loss"] + stats["short"]["loss"]
    n_o = stats["long"]["open"] + stats["short"]["open"]
    wr = n_w / (n_w + n_l) * 100 if (n_w + n_l) else 0
    exp_r = sum_r / (n_w + n_l) if (n_w + n_l) else 0
    avg_win = sum(wins_r) / len(wins_r) if wins_r else 0
    avg_loss = sum(losses_r) / len(losses_r) if losses_r else 0

    return {
        "name": name, "n_w": n_w, "n_l": n_l, "n_o": n_o, "wr": wr,
        "sum_r": sum_r, "exp_r": exp_r, "avg_win": avg_win, "avg_loss": avg_loss,
        "sum_r_long": sum_r_long, "sum_r_short": sum_r_short,
        "wr_long": stats["long"]["win"] / (stats["long"]["win"] + stats["long"]["loss"]) * 100 if (stats["long"]["win"] + stats["long"]["loss"]) else 0,
        "wr_short": stats["short"]["win"] / (stats["short"]["win"] + stats["short"]["loss"]) * 100 if (stats["short"]["win"] + stats["short"]["loss"]) else 0,
    }


print(f"\nRunning variants...\n")
variants = []
for name, rule in [("A baseline RR=1", "rr1"),
                    ("B vwap_same (anchor=SL extreme)", "vwap_same"),
                    ("C vwap_opposite (anchor=opposite extreme)", "vwap_opposite"),
                    ("D vwap_c5 (anchor=C5 open)", "vwap_c5")]:
    print(f"  ... {name}")
    variants.append(run_variant(name, rule))


print(f"\n{'Variant':<42} {'Trades':<8} {'WR%':<7} {'ΣR':<9} {'R/tr':<8} {'avgW':<7} {'avgL':<7} {'WR-L':<7} {'WR-S':<7} {'R-L':<9} {'R-S':<9}")
print("-" * 130)
for v in variants:
    print(f"{v['name']:<42} {v['n_w']+v['n_l']:<8} {v['wr']:<7.2f} {v['sum_r']:<+9.1f} {v['exp_r']:<+8.3f} "
          f"{v['avg_win']:<+7.3f} {v['avg_loss']:<+7.3f} {v['wr_long']:<7.2f} {v['wr_short']:<7.2f} "
          f"{v['sum_r_long']:<+9.1f} {v['sum_r_short']:<+9.1f}")
