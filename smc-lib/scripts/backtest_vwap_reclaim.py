"""Бэктест "VWAP reclaim" entry: ждём N последовательных 1m closes выше VWAP после first touch.

Гипотеза пользователя (по 3 графикам): после первого касания VWAP цена болтается
вокруг неё (close выше/ниже несколько раз), потом коммитится. Вход после
закрепления = более чистое подтверждение направления.

Правила:
- Detection: i-RDRB+FVG (8 patterns, LONG/SHORT) на 1h
- Anchor VWAP: 5m свеча, содержащая pattern_low (LONG) / pattern_high (SHORT)
- First touch: первое 1m с anchor+1 где VWAP ∈ [low, high]
- После first touch: считаем consecutive 1m closes ABOVE VWAP (LONG) / BELOW VWAP (SHORT)
  - Если close в обратную сторону — counter обнуляется
- Entry: бар где counter достиг N. Entry price = bar.close
- SL = pattern_extreme (low для long, high для short)
- TP = RR 1:1 от entry. R = entry − SL

Сравнение N ∈ {1, 2, 3, 5, 10}.
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
MS_5M = 5 * 60_000
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


print("Loading 1m..."); data = load_1m(); ts_arr = [r[0] for r in data]
candles_1h = aggregate_1h(data); print(f"{len(data):,} 1m → {len(candles_1h):,} 1h\n")


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


print("Detecting patterns...")
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    patterns.append((ir, c5))
print(f"{len(patterns)} patterns\n")


def run(N: int):
    """Запускает бэктест с N подтверждениями."""
    stats = {"long": {"win": 0, "loss": 0, "no_setup": 0},
             "short": {"win": 0, "loss": 0, "no_setup": 0}}
    sum_r = 0.0; sum_r_long = 0.0; sum_r_short = 0.0

    for ir, c5 in patterns:
        side = ir.direction
        all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
        if side == "long":
            sl = min(c.low for c in all5)
        else:
            sl = max(c.high for c in all5)

        anchor_1m = find_extreme_1m(ir.rdrb.c1.open_time, c5.open_time + MS_HOUR, side, sl)
        if anchor_1m is None:
            stats[side]["no_setup"] += 1; continue
        anchor_ms = data[anchor_1m][0]
        anchor_5m = anchor_ms - (anchor_ms % MS_5M)
        anchor_idx = idx_at(anchor_5m)
        c5_close_ms = c5.open_time + MS_HOUR

        cum_pv = 0.0; cum_vol = 0.0
        first_touch = False
        counter = 0
        in_trade = False
        outcome = "no_setup"; r_val = 0.0
        end_k = min(idx_at(c5_close_ms) + MAX_HOLD_MIN, len(data))

        for k in range(anchor_idx, end_k):
            ts, _, h_, l_, c_, v_ = data[k]
            cum_pv += v_ * c_; cum_vol += v_
            vwap = cum_pv / cum_vol if cum_vol else 0

            if ts < c5_close_ms:
                continue

            if not in_trade:
                if not first_touch:
                    if l_ <= vwap <= h_:
                        first_touch = True
                    continue
                # после first touch — считаем закрытия
                if side == "long":
                    if c_ > vwap:
                        counter += 1
                        if counter >= N:
                            in_trade = True
                            entry = c_
                            r_unit = entry - sl
                            if r_unit <= 0:
                                outcome = "no_setup"; break
                            tp = entry + r_unit
                            # check SL/TP в этой же 1m свече — но fill happened at close, so use future bars
                    else:
                        counter = 0
                else:
                    if c_ < vwap:
                        counter += 1
                        if counter >= N:
                            in_trade = True
                            entry = c_
                            r_unit = sl - entry
                            if r_unit <= 0:
                                outcome = "no_setup"; break
                            tp = entry - r_unit
                    else:
                        counter = 0
            else:
                # стандартный TP/SL мониторинг
                if side == "long":
                    if l_ <= sl: outcome = "loss"; r_val = -1.0; break
                    if h_ >= tp: outcome = "win"; r_val = +1.0; break
                else:
                    if h_ >= sl: outcome = "loss"; r_val = -1.0; break
                    if l_ <= tp: outcome = "win"; r_val = +1.0; break

        if outcome == "no_setup":
            stats[side]["no_setup"] += 1
        else:
            stats[side][outcome] += 1
            sum_r += r_val
            if side == "long": sum_r_long += r_val
            else: sum_r_short += r_val

    n_w = stats["long"]["win"] + stats["short"]["win"]
    n_l = stats["long"]["loss"] + stats["short"]["loss"]
    n_ns = stats["long"]["no_setup"] + stats["short"]["no_setup"]
    wr = n_w / (n_w + n_l) * 100 if (n_w + n_l) else 0
    wr_long = stats["long"]["win"] / (stats["long"]["win"] + stats["long"]["loss"]) * 100 if (stats["long"]["win"] + stats["long"]["loss"]) else 0
    wr_short = stats["short"]["win"] / (stats["short"]["win"] + stats["short"]["loss"]) * 100 if (stats["short"]["win"] + stats["short"]["loss"]) else 0
    exp = sum_r / (n_w + n_l) if (n_w + n_l) else 0
    return {
        "N": N, "trades": n_w + n_l, "no_setup": n_ns, "wr": wr,
        "sum_r": sum_r, "exp": exp, "wr_long": wr_long, "wr_short": wr_short,
        "sum_r_long": sum_r_long, "sum_r_short": sum_r_short,
        "n_long": stats["long"]["win"] + stats["long"]["loss"],
        "n_short": stats["short"]["win"] + stats["short"]["loss"],
    }


print(f"{'N':<4} {'Trades':<8} {'No setup':<10} {'WR%':<7} {'ΣR':<9} {'R/tr':<8} {'WR-L':<8} {'WR-S':<8} {'R-L':<9} {'R-S':<9}")
print("-" * 95)
results = []
for N in (1, 2, 3, 5, 10):
    r = run(N)
    results.append(r)
    print(f"{r['N']:<4} {r['trades']:<8} {r['no_setup']:<10} {r['wr']:<7.2f} {r['sum_r']:<+9.1f} {r['exp']:<+8.3f} "
          f"{r['wr_long']:<8.2f} {r['wr_short']:<8.2f} {r['sum_r_long']:<+9.1f} {r['sum_r_short']:<+9.1f}")
