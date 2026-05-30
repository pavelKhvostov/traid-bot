"""Подсчёт bullish FVG на 15m / 20m / 30m в зоне [pattern_low, block.bottom]
для каждого LONG i-RDRB+FVG паттерна.

Условия:
- TF: 15m, 20m, 30m (composed from 1m)
- Время формирования FVG: внутри окна паттерна (C1.open → C5.close)
- Цена FVG: целиком в [pattern_low, 1h block.bottom]
- Bullish FVG: c1.high < c3.low
- Unmitigated на C5 close
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
TFS = [(15, "15m"), (20, "20m"), (30, "30m")]


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


def detect_bull_fvgs(candles, tf_min):
    """Возвращает список bullish FVG с mitigation time."""
    tf_ms = tf_min * 60_000
    fvgs = []
    for i in range(len(candles) - 2):
        c1 = candles[i]; c3 = candles[i + 2]
        if c1[2] < c3[3]:  # c1.high < c3.low
            fvg = {"formed_ts": c3[0] + tf_ms, "top": c3[3], "bottom": c1[2], "c3_idx": i + 2}
            # mitigation
            fvg["mit_ts"] = None
            for j in range(i + 3, len(candles)):
                if candles[j][3] <= fvg["top"]:  # low <= FVG.top
                    fvg["mit_ts"] = candles[j][0]; break
            fvgs.append(fvg)
    return fvgs


print("Loading 1m..."); data = load_1m()
ts_1m = [r[0] for r in data]
candles_1h_raw = aggregate(data, 60)
candles_1h = [Candle(open=o, high=h, low=l, close=c, open_time=ts) for ts, o, h, l, c, _ in candles_1h_raw]
print(f"{len(data):,} 1m → {len(candles_1h):,} 1h")

# Composed TFs + FVGs
tf_fvgs = {}
for tf_min, name in TFS:
    cs = aggregate(data, tf_min)
    fvgs = detect_bull_fvgs(cs, tf_min)
    tf_fvgs[name] = fvgs
    print(f"  {name}: {len(cs):,} candles, {len(fvgs):,} bullish FVGs")


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


# Pattern detection
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    if ir.direction != "long": continue  # только LONG
    patterns.append((ir, c5))
print(f"\n{len(patterns)} LONG i-RDRB+FVG patterns\n")


# Backtest и подсчёт
records = []
for ir, c5 in patterns:
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    sl = min(c.low for c in all5)  # pattern_low
    r_unit = entry - sl
    if r_unit <= 0: continue
    tp = entry + r_unit
    c5_close_ms = c5.open_time + MS_HOUR
    pattern_start = ir.rdrb.c1.open_time

    # Backtest LONG baseline RR=1
    start_k = idx_at(c5_close_ms)
    end_k = min(start_k + MAX_HOLD_MIN, len(data))
    in_trade = False; outcome = "no_fill"; r_val = 0.0
    for k in range(start_k, end_k):
        _, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if l_ <= entry:
                in_trade = True
                if l_ <= sl: outcome = "loss"; r_val = -1.0; break
                if h_ >= tp: outcome = "win"; r_val = +1.0; break
        else:
            if l_ <= sl: outcome = "loss"; r_val = -1.0; break
            if h_ >= tp: outcome = "win"; r_val = +1.0; break
    if outcome not in ("win", "loss"):
        continue

    # Найти 1m с pattern_low (для time constraint)
    p_low_ts = None
    j0 = idx_at(pattern_start); j1 = idx_at(c5_close_ms)
    for k_ in range(j0, j1):
        if abs(data[k_][3] - sl) < 1e-6:
            p_low_ts = data[k_][0]; break
    if p_low_ts is None:
        best_low = float("inf")
        for k_ in range(j0, j1):
            if data[k_][3] < best_low:
                best_low = data[k_][3]; p_low_ts = data[k_][0]

    # Подсчёт FVGs с явным constraint: formed_ts > pattern_low_ts
    counts = {}
    counts_strict = {}
    for name, fvgs in tf_fvgs.items():
        # стандартный счёт (как раньше)
        cnt = sum(1 for f in fvgs
                  if pattern_start <= f["formed_ts"] <= c5_close_ms
                  and f["bottom"] >= sl
                  and f["top"] <= block_b
                  and (f["mit_ts"] is None or f["mit_ts"] > c5_close_ms))
        # строгий счёт: formed_ts > pattern_low_ts AND bottom > pattern_low (strict)
        cnt_strict = sum(1 for f in fvgs
                         if f["formed_ts"] > p_low_ts
                         and f["formed_ts"] <= c5_close_ms
                         and f["bottom"] > sl
                         and f["top"] <= block_b
                         and (f["mit_ts"] is None or f["mit_ts"] > c5_close_ms))
        counts[name] = cnt
        counts_strict[name + "_strict"] = cnt_strict
    records.append({"outcome": outcome, "r": r_val, **counts, **counts_strict})


n_total = len(records)
n_w = sum(1 for x in records if x["outcome"] == "win")
n_l = n_total - n_w
print(f"Total LONG closed: {n_total}  WIN: {n_w}  LOSS: {n_l}  WR: {n_w/n_total*100:.2f}%\n")


def summary_bucket(items):
    n = len(items)
    if n == 0: return "n=0"
    w = sum(1 for x in items if x["outcome"] == "win")
    sr = sum(x["r"] for x in items)
    return f"n={n:<5} WR={w/n*100:5.2f}%  ΣR={sr:+6.1f}  R/tr={sr/n:+.3f}"


wins_only = [x for x in records if x["outcome"] == "win"]
n_w = len(wins_only)

print(f"\n{'='*60}\n=== ТОЛЬКО WIN ({n_w} паттернов) ===\n{'='*60}\n")

print("По наличию ≥1 FVG в зоне [pattern_low, block.bottom]:")
for _, name in TFS:
    with_ = [x for x in wins_only if x[name] >= 1]
    print(f"  {name}: {len(with_)} winners ({len(with_)/n_w*100:.1f}%)")

print("\nРаспределение по количеству FVG:")
print(f"{'TF':<6} {'0 FVG':<10} {'1':<8} {'2':<8} {'3+':<8} {'sum FVG в WIN':<14}")
print("-" * 60)
for _, name in TFS:
    n0 = sum(1 for x in wins_only if x[name] == 0)
    n1 = sum(1 for x in wins_only if x[name] == 1)
    n2 = sum(1 for x in wins_only if x[name] == 2)
    n3 = sum(1 for x in wins_only if x[name] >= 3)
    total = sum(x[name] for x in wins_only)
    print(f"{name:<6} {n0:<10} {n1:<8} {n2:<8} {n3:<8} {total:<14}")

print("\nКомбинации по 3 TF одновременно (среди winners):")
all3 = sum(1 for x in wins_only if all(x[name] >= 1 for _, name in TFS))
any_ = sum(1 for x in wins_only if any(x[name] >= 1 for _, name in TFS))
none_ = sum(1 for x in wins_only if all(x[name] == 0 for _, name in TFS))
only_15m = sum(1 for x in wins_only if x["15m"] >= 1 and x["20m"] == 0 and x["30m"] == 0)
only_20m = sum(1 for x in wins_only if x["15m"] == 0 and x["20m"] >= 1 and x["30m"] == 0)
only_30m = sum(1 for x in wins_only if x["15m"] == 0 and x["20m"] == 0 and x["30m"] >= 1)
print(f"  Нет FVG ни на одном TF:        {none_} winners ({none_/n_w*100:.1f}%)")
print(f"  Есть хотя бы на одном TF:      {any_} winners ({any_/n_w*100:.1f}%)")
print(f"  Есть на всех 3 TF одновременно: {all3} winners ({all3/n_w*100:.1f}%)")
print(f"  Только 15m (без 20m/30m):       {only_15m}")
print(f"  Только 20m:                     {only_20m}")
print(f"  Только 30m:                     {only_30m}")

print(f"\n{'='*60}\n=== По наличию FVG (полная таблица с лоссами для контекста) ===\n{'='*60}\n")

print("=== По наличию FVG в каждом TF (≥1 в зоне) ===")
print(f"{'TF':<6} {'WITH FVG':<48} {'WITHOUT FVG':<48}")
print("-" * 100)
for _, name in TFS:
    with_ = [x for x in records if x[name] >= 1]
    without = [x for x in records if x[name] == 0]
    print(f"{name:<6} {summary_bucket(with_):<48} {summary_bucket(without):<48}")


print("\n=== Распределение по количеству FVG (TF) ===")
for _, name in TFS:
    print(f"\n--- {name} ---")
    for n_target in (0, 1, 2, 3):
        sub = [x for x in records if x[name] == n_target]
        if sub:
            print(f"  {n_target} FVG    {summary_bucket(sub)}")
    sub4plus = [x for x in records if x[name] >= 4]
    if sub4plus:
        print(f"  ≥4 FVG  {summary_bucket(sub4plus)}")


print("\n=== Total counts во всех WIN (245 в исходном bаseline без 30d cap) ===")
# Note: тут 239 wins из-за 30-day cap. Но сумма по TF — независима.
for _, name in TFS:
    wins_with = [x for x in records if x["outcome"] == "win" and x[name] >= 1]
    total_fvg_count = sum(x[name] for x in records if x["outcome"] == "win")
    losses_with = [x for x in records if x["outcome"] == "loss" and x[name] >= 1]
    print(f"  {name}:  В WIN-сделках всего FVG: {total_fvg_count}  |  WIN с ≥1 FVG: {len(wins_with)}/{n_w}  |  LOSS с ≥1 FVG: {len(losses_with)}/{n_l}")


print("\n=== Composite: FVG присутствует хотя бы на 1 TF ===")
any_tf = [x for x in records if any(x[name] >= 1 for _, name in TFS)]
no_tf = [x for x in records if all(x[name] == 0 for _, name in TFS)]
print(f"  Есть FVG хоть на одном из {{15m, 20m, 30m}}:  {summary_bucket(any_tf)}")
print(f"  Нет FVG ни на одном TF:                       {summary_bucket(no_tf)}")

all_tf = [x for x in records if all(x[name] >= 1 for _, name in TFS)]
print(f"\n=== Composite: FVG на ВСЕХ 3 TF одновременно ===")
print(f"  {summary_bucket(all_tf)}")
