"""RSI ASVK signal validation — честная оценка edge.

Метрики:
  net_move_pct(close_idx, h) = (close[idx+h] - close[idx]) / close[idx] * 100
    положительный = вверх. Для OB ожидаем negative; для OS — positive.

  В отличие от max-favorable, NET move симметрично оценивается:
    OB сигнал работает если avg(net@h) < baseline (рынок чаще вниз после OB)
    OS сигнал работает если avg(net@h) > baseline

Сравнение с baseline (1000 random 1h ts) даёт абсолютный edge.

Доп: R-trade simulation:
  Entry на close 1h-бара sync-event
  SL = ATR(20,1h) против направления
  TP = ATR(20,1h) по направлению
  → классические WR / ΣR / R/trade

Comparisons:
  - 3×OB baseline vs depth-filtered vs squeeze-preceded
  - 3×OS to same
"""
from __future__ import annotations

import csv
import pathlib
import sys
import time
from datetime import datetime, timezone, timedelta
import numpy as np
import random

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from indicators.rsi_asvk import adjusted_rsi, asvk_zone

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_HOUR = 3600_000

t0 = time.time()


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000),
                         float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate(d, tf_min):
    bucket = tf_min * 60_000
    out = []; cb = None; o = h = l = c = v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - (ts % bucket)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


print("Loading...")
data = load_1m()


def compute_tf(tf_min):
    bars = aggregate(data, tf_min)
    closes = [b[4] for b in bars]
    ts_open = [b[0] for b in bars]
    res = adjusted_rsi(closes, period=14)
    res["ts_open"] = ts_open
    res["closes"] = closes
    res["tf_min"] = tf_min
    res["bars"] = bars
    return res


tf1h = compute_tf(60)
tf2h = compute_tf(120)
tf3h = compute_tf(180)
print(f"3 TFs computed ({time.time()-t0:.1f}s)")


def zone_of(t, i):
    return asvk_zone(t["ema_3"][i], t["above"][i], t["below"][i],
                     t["nwe_upper"][i], t["nwe_lower"][i])


def zone_bias(z):
    if z in ("red", "yellow_ob"): return "OB"
    if z in ("green", "yellow_os"): return "OS"
    return "N"


def htf_idx_at(htf, query_ts):
    tf_ms = htf["tf_min"] * 60_000
    n = len(htf["ts_open"])
    lo, hi = 0, n
    while lo < hi:
        m = (lo + hi) // 2
        if htf["ts_open"][m] + tf_ms <= query_ts:
            lo = m + 1
        else:
            hi = m
    return lo - 1


def band_width(t, i):
    u = t["nwe_upper"][i]; l = t["nwe_lower"][i]
    return (u - l) if (u is not None and l is not None) else None


def depth(t, i):
    e = t["ema_3"][i]; a = t["above"][i]; b = t["below"][i]
    bw = band_width(t, i)
    if e is None or a is None or b is None or not bw or bw == 0: return None
    if e > a: return (e - a) / bw
    if e < b: return (e - b) / bw
    return 0.0


# Squeeze percentile rolling 200
def compute_squeeze_pct(t, win=200):
    bw = [band_width(t, i) for i in range(len(t["ts_open"]))]
    out = [None] * len(bw)
    for i in range(len(bw)):
        if bw[i] is None: continue
        lo = max(0, i - win + 1)
        window = [x for x in bw[lo:i+1] if x is not None]
        if len(window) < 20: continue
        rank = sum(1 for x in window if x < bw[i]) / len(window)
        out[i] = rank
    return out


tf1h["squeeze"] = compute_squeeze_pct(tf1h)


# Time in OB/OS bias state (consecutive in same bias)
def time_in_bias(t):
    out = [0] * len(t["ts_open"])
    prev_b = None
    streak = 0
    for i in range(len(t["ts_open"])):
        b = zone_bias(zone_of(t, i))
        if b == prev_b:
            streak += 1
        else:
            streak = 1
        out[i] = streak
        prev_b = b
    return out


tf1h["tib"] = time_in_bias(tf1h)


# ATR(20) на 1h
hi1 = np.array([b[2] for b in tf1h["bars"]])
lo1 = np.array([b[3] for b in tf1h["bars"]])
cl1 = np.array([b[4] for b in tf1h["bars"]])
prev_cl = np.concatenate([[cl1[0]], cl1[:-1]])
tr = np.maximum.reduce([hi1 - lo1, np.abs(hi1 - prev_cl), np.abs(lo1 - prev_cl)])
atr20 = np.zeros_like(tr)
for i in range(len(tr)):
    atr20[i] = tr[:i+1].mean() if i < 19 else tr[i-19:i+1].mean()


# === Find sync events on 6y ===
last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
start_i = next(i for i, ts in enumerate(tf1h["ts_open"]) if ts >= window_start_ms)
n = len(tf1h["ts_open"])

events = []
prev_sync = None
for i in range(start_i, n):
    z1 = zone_of(tf1h, i)
    ts_close = tf1h["ts_open"][i] + 60 * 60_000
    i2 = htf_idx_at(tf2h, ts_close); i3 = htf_idx_at(tf3h, ts_close)
    if i2 < 0 or i3 < 0:
        prev_sync = None; continue
    z2 = zone_of(tf2h, i2); z3 = zone_of(tf3h, i3)
    biases = [zone_bias(z1), zone_bias(z2), zone_bias(z3)]
    dominant = max(set(biases), key=biases.count)
    sync_count = biases.count(dominant)
    cur = f"{sync_count}×{dominant}" if dominant != "N" and sync_count == 3 else None
    if cur != prev_sync and cur is not None:
        events.append({
            "i": i, "dominant": dominant,
            "depth": depth(tf1h, i),
            "squeeze_min6": min((tf1h["squeeze"][k] for k in range(max(0, i-6), i)
                                  if tf1h["squeeze"][k] is not None), default=None),
            "tib": tf1h["tib"][i],
            "atr": float(atr20[i]),
            "close": tf1h["closes"][i],
            "ts": ts_close,
        })
    prev_sync = cur

ob = [e for e in events if e["dominant"] == "OB"]
os_ = [e for e in events if e["dominant"] == "OS"]
print(f"Total sync events: {len(events)} (OB={len(ob)}, OS={len(os_)})")


def net_move_pct(idx, h):
    """Net close-to-close move % at idx+h, in absolute %."""
    j = idx + h
    if j >= len(tf1h["closes"]): return None
    return (tf1h["closes"][j] - tf1h["closes"][idx]) / tf1h["closes"][idx] * 100


# === Baseline random sample of 1h indices ===
random.seed(42)
rand_idx = random.sample(range(start_i + 20, n - 50), 2000)
baseline_net = {h: [] for h in [6, 12, 24, 48]}
for i in rand_idx:
    for h in baseline_net:
        m = net_move_pct(i, h)
        if m is not None: baseline_net[h].append(m)
print(f"\nBaseline (random 2000 samples): avg NET move:")
for h in [6, 12, 24, 48]:
    print(f"  @{h:>2}h: avg={sum(baseline_net[h])/len(baseline_net[h]):+.3f}%  "
          f"median={sorted(baseline_net[h])[len(baseline_net[h])//2]:+.3f}%")


def evaluate(name, evlist, expected_sign):
    """expected_sign: -1 for OB (expect down), +1 for OS (expect up)."""
    print(f"\n=== {name} ({len(evlist)} events) ===")
    print(f"  horizon  avg_net  median_net  pct_in_direction  Edge_vs_baseline")
    for h in [6, 12, 24, 48]:
        moves = [net_move_pct(e["i"], h) for e in evlist]
        moves = [m for m in moves if m is not None]
        if not moves: continue
        avg = sum(moves) / len(moves)
        med = sorted(moves)[len(moves)//2]
        # pct in direction:
        in_dir = sum(1 for m in moves if (m > 0 and expected_sign > 0) or (m < 0 and expected_sign < 0)) / len(moves) * 100
        baseline_avg = sum(baseline_net[h]) / len(baseline_net[h])
        edge = expected_sign * (avg - baseline_avg)  # positive = signal works
        print(f"   @{h:>2}h    {avg:>+6.3f}%  {med:>+6.3f}%     "
              f"{in_dir:>5.1f}%       {edge:>+6.3f}% (signed)")


evaluate("3×OB baseline (expecting DOWN)", ob, -1)
evaluate("3×OS baseline (expecting UP)", os_, +1)


# === Filter by depth ===
print(f"\n--- Filter: OB depth >= 0.3 (more extreme extension) ---")
evaluate("3×OB depth>=0.3", [e for e in ob if e["depth"] is not None and e["depth"] >= 0.3], -1)
evaluate("3×OB depth<0.3", [e for e in ob if e["depth"] is not None and e["depth"] < 0.3], -1)

print(f"\n--- Filter: OS depth <= -0.3 (more extreme extension) ---")
evaluate("3×OS depth<=-0.3", [e for e in os_ if e["depth"] is not None and e["depth"] <= -0.3], +1)
evaluate("3×OS depth>-0.3", [e for e in os_ if e["depth"] is not None and e["depth"] > -0.3], +1)


# === Filter by squeeze BEFORE event ===
print(f"\n--- Filter: squeeze_min6 < 0.15 (compression preceded) ---")
evaluate("OB after squeeze", [e for e in ob if e["squeeze_min6"] is not None and e["squeeze_min6"] < 0.15], -1)
evaluate("OB no squeeze", [e for e in ob if e["squeeze_min6"] is None or e["squeeze_min6"] >= 0.15], -1)
evaluate("OS after squeeze", [e for e in os_ if e["squeeze_min6"] is not None and e["squeeze_min6"] < 0.15], +1)
evaluate("OS no squeeze", [e for e in os_ if e["squeeze_min6"] is None or e["squeeze_min6"] >= 0.15], +1)


# === Filter by time-in-bias (long stay in OB/OS) ===
print(f"\n--- Filter: tib >= 6 (long stay in OB/OS before sync) ---")
evaluate("OB tib>=6", [e for e in ob if e["tib"] >= 6], -1)
evaluate("OB tib<6", [e for e in ob if e["tib"] < 6], -1)
evaluate("OS tib>=6", [e for e in os_ if e["tib"] >= 6], +1)
evaluate("OS tib<6", [e for e in os_ if e["tib"] < 6], +1)


# === R-trade simulation: TP/SL = 1×ATR ===
print(f"\n{'='*80}")
print(f" R-trade simulation: SL/TP = 1×ATR(20,1h)")
print(f"{'='*80}")

ts_arr = np.array([r[0] for r in data], dtype=np.int64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)

def idx_at(ms):
    return int(np.searchsorted(ts_arr, ms, side='left'))


def simulate_atr_trade(entry_idx_1h, side, atr_unit, max_hold_h=48):
    entry_ts = tf1h["ts_open"][entry_idx_1h] + 60 * 60_000  # close ts
    entry_price = tf1h["closes"][entry_idx_1h]
    sl = entry_price + atr_unit if side == "short" else entry_price - atr_unit
    tp = entry_price - atr_unit if side == "short" else entry_price + atr_unit
    sk = idx_at(entry_ts); ek = min(sk + max_hold_h * 60, len(data))
    for k in range(sk, ek):
        h_ = hi_arr[k]; l_ = lo_arr[k]
        if side == "long":
            if l_ <= sl: return "loss"
            if h_ >= tp: return "win"
        else:
            if h_ >= sl: return "loss"
            if l_ <= tp: return "win"
    return "no_exit"


def trade_stats(evlist, side):
    outcomes = [simulate_atr_trade(e["i"], side, e["atr"]) for e in evlist]
    w = outcomes.count("win"); l = outcomes.count("loss"); ne = outcomes.count("no_exit")
    n = w + l
    wr = w/n*100 if n else 0
    sr = w - l
    rtr = sr/n if n else 0
    return {"n_total": len(evlist), "closed": n, "w": w, "l": l, "no_exit": ne,
            "wr": wr, "sr": sr, "rtr": rtr}


def print_trade(name, stats):
    print(f"  {name:<40} n={stats['n_total']:>4}  closed={stats['closed']:>4}  "
          f"W={stats['w']:>3}  L={stats['l']:>3}  NoExit={stats['no_exit']:>3}  "
          f"WR={stats['wr']:>5.2f}%  ΣR={stats['sr']:>+5.0f}  R/tr={stats['rtr']:+.3f}")


print_trade("OB baseline → SHORT", trade_stats(ob, "short"))
print_trade("OB depth>=0.3 → SHORT", trade_stats([e for e in ob if e["depth"] is not None and e["depth"] >= 0.3], "short"))
print_trade("OB depth>=0.6 → SHORT", trade_stats([e for e in ob if e["depth"] is not None and e["depth"] >= 0.6], "short"))
print_trade("OB tib>=6 → SHORT", trade_stats([e for e in ob if e["tib"] >= 6], "short"))
print_trade("OB squeeze<0.15 → SHORT", trade_stats([e for e in ob if e["squeeze_min6"] is not None and e["squeeze_min6"] < 0.15], "short"))
print_trade("OB depth>=0.3 AND tib>=6 → SHORT", trade_stats([e for e in ob if e["depth"] is not None and e["depth"] >= 0.3 and e["tib"] >= 6], "short"))

print()
print_trade("OS baseline → LONG", trade_stats(os_, "long"))
print_trade("OS depth<=-0.3 → LONG", trade_stats([e for e in os_ if e["depth"] is not None and e["depth"] <= -0.3], "long"))
print_trade("OS depth<=-0.6 → LONG", trade_stats([e for e in os_ if e["depth"] is not None and e["depth"] <= -0.6], "long"))
print_trade("OS tib>=6 → LONG", trade_stats([e for e in os_ if e["tib"] >= 6], "long"))
print_trade("OS squeeze<0.15 → LONG", trade_stats([e for e in os_ if e["squeeze_min6"] is not None and e["squeeze_min6"] < 0.15], "long"))
print_trade("OS depth<=-0.3 AND tib>=6 → LONG", trade_stats([e for e in os_ if e["depth"] is not None and e["depth"] <= -0.3 and e["tib"] >= 6], "long"))

# Combined: BOTH OB and OS = full strategy
all_trades_baseline = []
for e in ob: all_trades_baseline.append((e, "short"))
for e in os_: all_trades_baseline.append((e, "long"))
out_all = [simulate_atr_trade(e["i"], s, e["atr"]) for e, s in all_trades_baseline]
w = out_all.count("win"); l = out_all.count("loss")
n = w + l
print(f"\n  COMBINED (OB→SHORT + OS→LONG) baseline:  n={len(all_trades_baseline)}  cl={n}  "
      f"WR={w/n*100:.2f}%  ΣR={w-l:+}  R/tr={(w-l)/n:+.3f}" if n else "")

# Combined depth-filtered
filtered = [(e, "short") for e in ob if e["depth"] is not None and e["depth"] >= 0.3]
filtered += [(e, "long") for e in os_ if e["depth"] is not None and e["depth"] <= -0.3]
out_f = [simulate_atr_trade(e["i"], s, e["atr"]) for e, s in filtered]
w = out_f.count("win"); l = out_f.count("loss")
n = w + l
print(f"  COMBINED depth-filtered:  n={len(filtered)}  cl={n}  "
      f"WR={w/n*100:.2f}%  ΣR={w-l:+}  R/tr={(w-l)/n:+.3f}" if n else "")

print(f"\nTotal: {time.time()-t0:.1f}s")
