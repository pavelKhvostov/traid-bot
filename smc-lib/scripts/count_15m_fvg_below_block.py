"""Анализ: сколько LONG i-RDRB+FVG паттернов имеют немитигированный bullish FVG 15m
под 1h RDRB block (для дополнительного support-confluence).

FVG 15m bullish: candle1.high < candle3.low.
Unmitigated: с момента c3 close ни один 15m бар не пробил FVG.top вниз (low ≤ FVG.top).
"Под block": FVG.top ≤ 1h block.bottom.

Также проверяем mirror для SHORT (немитигированный bearish 15m FVG над block).
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
    out = []; cb = None; o = h = l = c = 0; v_sum = 0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - (ts % bucket)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v_sum))
            cb = b; o, h, l, c = oo, hh, ll, cc; v_sum = vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v_sum += vv
    if cb is not None: out.append((cb, o, h, l, c, v_sum))
    return out


print("Loading..."); data = load_1m()
candles_15m = aggregate(data, 15)
candles_1h_raw = aggregate(data, 60)
candles_1h = [Candle(open=o, high=h, low=l, close=c, open_time=ts) for ts, o, h, l, c, _ in candles_1h_raw]
ts_1m = [r[0] for r in data]
print(f"{len(data):,} 1m → {len(candles_15m):,} 15m, {len(candles_1h):,} 1h")


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


# Все 15m FVG
print("Detecting all 15m FVGs...")
fvgs_15m_bull = []  # (formed_ts, top, bottom, c3_idx, mitigation_ts)
fvgs_15m_bear = []
for i in range(len(candles_15m) - 2):
    c1 = candles_15m[i]; c3 = candles_15m[i + 2]
    if c1[2] < c3[3]:  # bullish: c1.high < c3.low
        fvgs_15m_bull.append({"formed_ts": c3[0] + MS_15M, "top": c3[3], "bottom": c1[2], "c3_idx": i + 2})
    elif c1[3] > c3[2]:  # bearish: c1.low > c3.high
        fvgs_15m_bear.append({"formed_ts": c3[0] + MS_15M, "top": c1[3], "bottom": c3[2], "c3_idx": i + 2})
print(f"  bullish 15m FVGs: {len(fvgs_15m_bull)}")
print(f"  bearish 15m FVGs: {len(fvgs_15m_bear)}")

# Mitigation time для каждого FVG
print("Computing mitigation times...")
for fvg in fvgs_15m_bull:
    fvg["mitigation_ts"] = None
    for j in range(fvg["c3_idx"] + 1, len(candles_15m)):
        if candles_15m[j][3] <= fvg["top"]:  # low <= FVG.top — touched/mitigated
            fvg["mitigation_ts"] = candles_15m[j][0]; break
for fvg in fvgs_15m_bear:
    fvg["mitigation_ts"] = None
    for j in range(fvg["c3_idx"] + 1, len(candles_15m)):
        if candles_15m[j][2] >= fvg["bottom"]:  # high >= FVG.bottom — touched
            fvg["mitigation_ts"] = candles_15m[j][0]; break


def fvg_active_at(fvgs, ts_ms):
    """Возвращает FVG, которые сформированы до ts и не митигированы до ts."""
    return [f for f in fvgs
            if f["formed_ts"] <= ts_ms
            and (f["mitigation_ts"] is None or f["mitigation_ts"] > ts_ms)]


# Detect patterns
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    patterns.append((ir, c5))
print(f"\n{len(patterns)} i-RDRB+FVG patterns\n")


# Для каждого LONG паттерна: считаем FVG 15m под block
results_long = []
results_short = []
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
    c5_close_ms = c5.open_time + MS_HOUR

    # Baseline backtest
    start_k = idx_at(c5_close_ms)
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

    # Окно паттерна: C1.open → C5.close (5 часов)
    pattern_start = ir.rdrb.c1.open_time
    pattern_end = c5_close_ms

    pattern_low = sl if side == "long" else min(c.low for c in all5)
    pattern_high = sl if side == "short" else max(c.high for c in all5)

    c5_close_price = c5.close
    c1_open_price = ir.rdrb.c1.open

    if side == "long":
        # bullish 15m FVG: внутри времени паттерна, целиком в [pattern_low, C5.close]
        intra = [f for f in fvgs_15m_bull
                 if pattern_start <= f["formed_ts"] <= pattern_end
                 and f["top"] <= c5_close_price
                 and f["bottom"] >= pattern_low
                 and (f["mitigation_ts"] is None or f["mitigation_ts"] > pattern_end)]
        results_long.append({"outcome": outcome, "r": r_val,
                             "n_fvgs": len(intra), "has_fvg": len(intra) >= 1})
    else:
        # bearish 15m FVG: внутри времени паттерна, целиком в [C5.close, pattern_high]
        intra = [f for f in fvgs_15m_bear
                 if pattern_start <= f["formed_ts"] <= pattern_end
                 and f["bottom"] >= c5_close_price
                 and f["top"] <= pattern_high
                 and (f["mitigation_ts"] is None or f["mitigation_ts"] > pattern_end)]
        results_short.append({"outcome": outcome, "r": r_val,
                              "n_fvgs": len(intra), "has_fvg": len(intra) >= 1})


# Сводка
def summary(name, items):
    if not items: return
    n = len(items)
    w = sum(1 for x in items if x["outcome"] == "win")
    sr = sum(x["r"] for x in items)
    print(f"  {name:<55} n={n:<5} WR={w/n*100:.2f}%  ΣR={sr:+.1f}  R/tr={sr/n:+.3f}")


print(f"=== LONG (всего {len(results_long)} закрытых сделок) ===\n")
n_w_long = sum(1 for x in results_long if x["outcome"] == "win")
print(f"Все LONG WIN: {n_w_long}, LOSS: {len(results_long)-n_w_long}\n")

print("Распределение по наличию bullish 15m FVG под block:")
with_fvg = [x for x in results_long if x["has_fvg"]]
no_fvg = [x for x in results_long if not x["has_fvg"]]
summary("WITH ≥1 unmitigated bullish 15m FVG below block", with_fvg)
summary("WITHOUT bullish 15m FVG below block", no_fvg)

print(f"\nИз 245 WIN LONG:")
w_with = sum(1 for x in with_fvg if x["outcome"] == "win")
w_no = sum(1 for x in no_fvg if x["outcome"] == "win")
print(f"  С FVG под block:  {w_with}")
print(f"  Без FVG под block: {w_no}")
print(f"  Всего WIN: {w_with + w_no} = {n_w_long}")

# Распределение по количеству FVG
print("\nПо количеству активных bullish 15m FVG под block:")
buckets = [(0, 0, "0 FVG"), (1, 1, "1"), (2, 3, "2-3"), (4, 9, "4-9"), (10, 999, "10+")]
for lo, hi, name in buckets:
    sub = [x for x in results_long if lo <= x["n_fvgs"] <= hi]
    summary(f"  {name}", sub)


print(f"\n\n=== SHORT (всего {len(results_short)} закрытых сделок) — mirror ===\n")
n_w_short = sum(1 for x in results_short if x["outcome"] == "win")
print(f"Все SHORT WIN: {n_w_short}, LOSS: {len(results_short)-n_w_short}\n")

with_fvg_s = [x for x in results_short if x["has_fvg"]]
no_fvg_s = [x for x in results_short if not x["has_fvg"]]
summary("WITH ≥1 unmitigated bearish 15m FVG above block", with_fvg_s)
summary("WITHOUT bearish 15m FVG above block", no_fvg_s)
