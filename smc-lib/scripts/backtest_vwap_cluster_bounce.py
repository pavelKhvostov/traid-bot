"""Стратегия A: VWAP Cluster Bounce (mean reversion).

Пул VWAP-якорей = последние N подтверждённых Williams FH + N FL на 1h.
Кластер = 3+ VWAP в полосе ±max_spread относительно среднего.

Сигнал на 1h close:
- LONG reject at support cluster (центр кластера ≤ current price):
  - candle.low ≤ cluster_top
  - candle.close > cluster_top
  - candle.close > candle.open (bullish close)
- SHORT mirror.

Entry: close reject-свечи. SL: low-0.5×ATR (long) / high+0.5×ATR (short).
TP: RR=2 от entry.
"""
from __future__ import annotations

import csv
import pathlib
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000

# Параметры стратегии v2: жёстче
TF_MIN = 60
FRACTAL_N = 5             # сильные swing-точки (N=5 = high > 5 left + 5 right)
POOL_SIZE = 8
CLUSTER_MIN = 4           # минимум 4 VWAP в кластере
CLUSTER_SPREAD = 0.0015   # 0.15%
BIAS_RATIO = 0.7          # для long cluster ≥ 70% FL; short ≥ 70% FH
DEDUP_HOURS = 24          # не повторять сигнал в той же зоне < 24h
DEDUP_PCT = 0.005         # ±0.5% от cluster_mean
ATR_PERIOD = 14
SL_ATR_MULT = 0.5
RR = 2.0
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


print("Loading 1m..."); data = load_1m()
print("Aggregating to 1h..."); candles = aggregate_1h(data)
print(f"{len(data):,} 1m → {len(candles):,} 1h")

# Cumulative arrays for O(1) VWAP queries
print("Building cumulative VWAP arrays...")
cum_pv = [0.0] * (len(data) + 1)
cum_vol = [0.0] * (len(data) + 1)
for i, (_, _, _, _, c, v) in enumerate(data):
    cum_pv[i + 1] = cum_pv[i] + v * c
    cum_vol[i + 1] = cum_vol[i] + v

ts_1m = [r[0] for r in data]


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def vwap(anchor_idx_1m, current_idx_1m):
    """VWAP от anchor (incl) до current (incl)."""
    pv_sum = cum_pv[current_idx_1m + 1] - cum_pv[anchor_idx_1m]
    vol_sum = cum_vol[current_idx_1m + 1] - cum_vol[anchor_idx_1m]
    return pv_sum / vol_sum if vol_sum > 0 else 0


# Williams fractals на 1h
print("Detecting Williams fractals on 1h...")
fractals = []  # (1h_idx, type='FH'/'FL', anchor_ms)
n = len(candles)
for i in range(FRACTAL_N, n - FRACTAL_N):
    is_fh = all(candles[i].high > candles[j].high for j in range(i - FRACTAL_N, i)) and \
            all(candles[i].high > candles[j].high for j in range(i + 1, i + FRACTAL_N + 1))
    is_fl = all(candles[i].low < candles[j].low for j in range(i - FRACTAL_N, i)) and \
            all(candles[i].low < candles[j].low for j in range(i + 1, i + FRACTAL_N + 1))
    if is_fh:
        fractals.append((i, "FH", candles[i].open_time))
    elif is_fl:
        fractals.append((i, "FL", candles[i].open_time))
fh_count = sum(1 for f in fractals if f[1] == "FH")
fl_count = sum(1 for f in fractals if f[1] == "FL")
print(f"Found {fh_count} FH + {fl_count} FL on 1h\n")

# ATR(14) на 1h (Wilder)
atr_arr = [0.0] * n
trs = [0.0] * n
for i in range(1, n):
    trs[i] = max(candles[i].high - candles[i].low,
                 abs(candles[i].high - candles[i - 1].close),
                 abs(candles[i].low - candles[i - 1].close))
for i in range(ATR_PERIOD, n):
    if i == ATR_PERIOD:
        atr_arr[i] = sum(trs[1:ATR_PERIOD + 1]) / ATR_PERIOD
    else:
        atr_arr[i] = (atr_arr[i - 1] * (ATR_PERIOD - 1) + trs[i]) / ATR_PERIOD


def find_clusters(values, min_size=CLUSTER_MIN, max_spread=CLUSTER_SPREAD):
    """values: list of (vwap_value, type='FH'/'FL'). Returns list of dicts with cluster info."""
    if len(values) < min_size: return []
    sorted_vals = sorted(values, key=lambda x: x[0])
    clusters = []
    i = 0
    while i < len(sorted_vals) - min_size + 1:
        # пытаемся максимально расширить кластер с i
        j = i + 1
        while j < len(sorted_vals):
            window = sorted_vals[i:j + 1]
            mean = sum(v for v, _ in window) / len(window)
            spread = (window[-1][0] - window[0][0]) / mean
            if spread > max_spread:
                break
            j += 1
        size = j - i
        if size >= min_size:
            window = sorted_vals[i:j]
            mean = sum(v for v, _ in window) / size
            clusters.append({
                "low": window[0][0], "high": window[-1][0], "mean": mean,
                "size": size, "fl_count": sum(1 for _, t in window if t == "FL"),
                "fh_count": sum(1 for _, t in window if t == "FH"),
            })
            i = j
        else:
            i += 1
    return clusters


# Backtest
print("Scanning signals...")
signals = []
recent_signals = []  # [(ts, side, cluster_mean), ...] для dedup

# Анчоры в виде 1m_idx (anchor at open_time of fractal candle)
fractal_pool_idx = {}  # 1h_idx → 1m_anchor_idx, type
for fi, ftype, fts in fractals:
    fractal_pool_idx[fi] = (idx_at(fts), ftype)

# Iterate 1h candles
for k in range(ATR_PERIOD + 5, n - 1):
    cur = candles[k]
    cur_close_ms = cur.open_time + MS_HOUR
    current_idx_1m = idx_at(cur_close_ms) - 1  # последний 1m бар в этом часу
    if current_idx_1m < 0 or current_idx_1m >= len(data):
        continue

    # Активные fractals: подтверждённые к моменту k (т.е. при i+N ≤ k → i ≤ k-N)
    active_fl = []
    active_fh = []
    for fi in sorted(fractal_pool_idx.keys(), reverse=True):
        if fi > k - FRACTAL_N:
            continue
        anchor_1m, ftype = fractal_pool_idx[fi]
        if anchor_1m > current_idx_1m:
            continue
        if ftype == "FL" and len(active_fl) < POOL_SIZE:
            active_fl.append((anchor_1m, ftype))
        elif ftype == "FH" and len(active_fh) < POOL_SIZE:
            active_fh.append((anchor_1m, ftype))
        if len(active_fl) >= POOL_SIZE and len(active_fh) >= POOL_SIZE:
            break

    pool = active_fl + active_fh
    if len(pool) < CLUSTER_MIN:
        continue

    # Вычисляем VWAP для каждого якоря
    vwap_values = []
    for anchor_1m, ftype in pool:
        v = vwap(anchor_1m, current_idx_1m)
        if v > 0:
            vwap_values.append((v, ftype))

    clusters = find_clusters(vwap_values)
    if not clusters:
        continue

    # Сначала чистим recent_signals от устаревших
    cutoff_ms = cur.open_time - DEDUP_HOURS * MS_HOUR
    recent_signals = [s for s in recent_signals if s[0] >= cutoff_ms]

    for cl in clusters:
        is_fl_dominant = cl["fl_count"] / cl["size"] >= BIAS_RATIO
        is_fh_dominant = cl["fh_count"] / cl["size"] >= BIAS_RATIO

        # LONG: cluster должен быть преимущественно FL (поддержка)
        if is_fl_dominant and cur.low <= cl["high"] and cur.close > cl["high"] and cur.close > cur.open:
            # dedup: близкий long сигнал был в последние DEDUP_HOURS?
            dup = any(s[1] == "long" and abs(s[2] - cl["mean"]) / cl["mean"] < DEDUP_PCT for s in recent_signals)
            if dup: continue
            entry = cur.close
            atr = atr_arr[k]
            sl = cur.low - SL_ATR_MULT * atr
            r = entry - sl
            if r <= 0: continue
            tp = entry + RR * r
            signals.append({
                "idx": k, "side": "long", "entry": entry, "sl": sl, "tp": tp,
                "cluster_mean": cl["mean"], "cluster_size": cl["size"],
                "fl": cl["fl_count"], "fh": cl["fh_count"],
            })
            recent_signals.append((cur.open_time, "long", cl["mean"]))
            break

        # SHORT mirror
        if is_fh_dominant and cur.high >= cl["low"] and cur.close < cl["low"] and cur.close < cur.open:
            dup = any(s[1] == "short" and abs(s[2] - cl["mean"]) / cl["mean"] < DEDUP_PCT for s in recent_signals)
            if dup: continue
            entry = cur.close
            atr = atr_arr[k]
            sl = cur.high + SL_ATR_MULT * atr
            r = sl - entry
            if r <= 0: continue
            tp = entry - RR * r
            signals.append({
                "idx": k, "side": "short", "entry": entry, "sl": sl, "tp": tp,
                "cluster_mean": cl["mean"], "cluster_size": cl["size"],
                "fl": cl["fl_count"], "fh": cl["fh_count"],
            })
            recent_signals.append((cur.open_time, "short", cl["mean"]))
            break

print(f"Found {len(signals)} signals\n")

# Simulate on 1m data
stats = {"long": {"win": 0, "loss": 0, "open": 0},
         "short": {"win": 0, "loss": 0, "open": 0}}
sum_r = 0.0; sum_r_long = 0.0; sum_r_short = 0.0
holds = []

for s in signals:
    side = s["side"]
    entry = s["entry"]; sl = s["sl"]; tp = s["tp"]
    r_unit = abs(entry - sl)
    start_ms = candles[s["idx"]].open_time + MS_HOUR  # после закрытия сигнальной свечи
    j0 = idx_at(start_ms)
    j1 = min(j0 + MAX_HOLD_MIN, len(data))
    outcome = "open"
    for j in range(j0, j1):
        _, _, h_, l_, _, _ = data[j]
        if side == "long":
            if l_ <= sl: outcome = "loss"; r_val = -1.0; break
            if h_ >= tp: outcome = "win"; r_val = +RR; break
        else:
            if h_ >= sl: outcome = "loss"; r_val = -1.0; break
            if l_ <= tp: outcome = "win"; r_val = +RR; break
    if outcome == "open":
        stats[side]["open"] += 1
        continue
    stats[side][outcome] += 1
    sum_r += r_val
    if side == "long": sum_r_long += r_val
    else: sum_r_short += r_val
    holds.append((j - j0))

# Report
print(f"{'Outcome':<10} {'LONG':>8} {'SHORT':>8} {'Total':>8}")
print("-" * 40)
for k_ in ("win", "loss", "open"):
    l, s = stats["long"][k_], stats["short"][k_]
    print(f"{k_:<10} {l:>8} {s:>8} {l+s:>8}")
tot_l = sum(stats["long"].values()); tot_s = sum(stats["short"].values())
print(f"{'Total':<10} {tot_l:>8} {tot_s:>8} {tot_l+tot_s:>8}")

n_w = stats["long"]["win"] + stats["short"]["win"]
n_l = stats["long"]["loss"] + stats["short"]["loss"]
wr = n_w / (n_w + n_l) * 100 if (n_w + n_l) else 0

print()
print(f"WR: {wr:.2f}% ({n_w}/{n_w + n_l})")
print(f"  LONG  WR: {stats['long']['win']/(stats['long']['win']+stats['long']['loss'])*100 if (stats['long']['win']+stats['long']['loss']) else 0:.2f}%")
print(f"  SHORT WR: {stats['short']['win']/(stats['short']['win']+stats['short']['loss'])*100 if (stats['short']['win']+stats['short']['loss']) else 0:.2f}%")
print(f"\nTotal R (RR={RR}): {sum_r:+.1f}R")
print(f"  LONG:   {sum_r_long:+.1f}R")
print(f"  SHORT:  {sum_r_short:+.1f}R")
exp = sum_r / (n_w + n_l) if (n_w + n_l) else 0
print(f"Expectancy: {exp:+.3f}R per trade")
if holds:
    holds_sorted = sorted(holds)
    print(f"\nMedian hold: {holds_sorted[len(holds)//2]:.0f}min ({holds_sorted[len(holds)//2]/60:.1f}h)")
