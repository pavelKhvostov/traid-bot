"""Обратная гипотеза: 3-TF sync = trend CONTINUATION, не reversal.

  3×OB → LONG (бычатся все ТФ → продолжение вверх)
  3×OS → SHORT (медведят все ТФ → продолжение вниз)

Плюс отдельная гипотеза — true reversal сигнал = LTF выходит из sync первым:
  1h NOT in OB AND 2h+3h still in OB → bearish divergence (early reversal)
  1h NOT in OS AND 2h+3h still in OS → bullish divergence

Финально: R-trade simulation, выбираем рабочую гипотезу.
"""
from __future__ import annotations

import csv
import pathlib
import sys
import time
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from indicators.rsi_asvk import adjusted_rsi, asvk_zone

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
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
    res["ts_open"] = ts_open; res["closes"] = closes; res["tf_min"] = tf_min; res["bars"] = bars
    return res


tf1h = compute_tf(60); tf2h = compute_tf(120); tf3h = compute_tf(180)
print(f"3 TFs ready ({time.time()-t0:.1f}s)")


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


# ATR
hi1 = np.array([b[2] for b in tf1h["bars"]])
lo1 = np.array([b[3] for b in tf1h["bars"]])
cl1 = np.array([b[4] for b in tf1h["bars"]])
prev_cl = np.concatenate([[cl1[0]], cl1[:-1]])
tr = np.maximum.reduce([hi1 - lo1, np.abs(hi1 - prev_cl), np.abs(lo1 - prev_cl)])
atr20 = np.zeros_like(tr)
for i in range(len(tr)):
    atr20[i] = tr[:i+1].mean() if i < 19 else tr[i-19:i+1].mean()

ts_arr = np.array([r[0] for r in data], dtype=np.int64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)


def idx_at(ms):
    return int(np.searchsorted(ts_arr, ms, side='left'))


def simulate_atr_trade(entry_idx_1h, side, atr_unit, rr=1.0, max_hold_h=48):
    entry_ts = tf1h["ts_open"][entry_idx_1h] + 60 * 60_000
    entry_price = tf1h["closes"][entry_idx_1h]
    sl = entry_price + atr_unit if side == "short" else entry_price - atr_unit
    tp = entry_price - rr * atr_unit if side == "short" else entry_price + rr * atr_unit
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


# === Find sync events ===
last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
start_i = next(i for i, ts in enumerate(tf1h["ts_open"]) if ts >= window_start_ms)
n = len(tf1h["ts_open"])

# Track 3-sync transitions AND divergence events (1h breaks out while 2h+3h still in)
events_3sync = []   # transition into 3xOB/OS
events_div = []     # 1h exits OB/OS while HTF still in

prev_sync = None
prev_states = (None, None, None)

for i in range(start_i, n):
    z1 = zone_of(tf1h, i)
    ts_close = tf1h["ts_open"][i] + 60 * 60_000
    i2 = htf_idx_at(tf2h, ts_close); i3 = htf_idx_at(tf3h, ts_close)
    if i2 < 0 or i3 < 0:
        prev_sync = None; prev_states = (None, None, None); continue
    z2 = zone_of(tf2h, i2); z3 = zone_of(tf3h, i3)
    biases = [zone_bias(z1), zone_bias(z2), zone_bias(z3)]
    dominant = max(set(biases), key=biases.count)
    sync_count = biases.count(dominant)

    # 3-sync entry event
    cur = f"{sync_count}×{dominant}" if dominant != "N" and sync_count == 3 else None
    if cur != prev_sync and cur is not None:
        events_3sync.append({"i": i, "dominant": dominant, "atr": float(atr20[i])})
    prev_sync = cur

    # Divergence: 1h leaves bias while 2h AND 3h still in it
    prev_b1, prev_b2, prev_b3 = prev_states
    cur_b1, cur_b2, cur_b3 = biases
    if (prev_b1 is not None and prev_b1 in ("OB", "OS")
            and cur_b1 == "N"
            and cur_b2 == prev_b1 and cur_b3 == prev_b1):
        # 1h just exited; HTF still in
        events_div.append({"i": i, "exited_bias": prev_b1, "atr": float(atr20[i])})
    prev_states = (cur_b1, cur_b2, cur_b3)


ob_evt = [e for e in events_3sync if e["dominant"] == "OB"]
os_evt = [e for e in events_3sync if e["dominant"] == "OS"]
div_ob = [e for e in events_div if e["exited_bias"] == "OB"]  # 1h leaves OB → bearish reversal candidate
div_os = [e for e in events_div if e["exited_bias"] == "OS"]
print(f"3-sync events: OB={len(ob_evt)}, OS={len(os_evt)}")
print(f"1h-exit-divergence: from-OB={len(div_ob)}, from-OS={len(div_os)}")


def stats(name, evlist, side, rr=1.0):
    if not evlist:
        print(f"  {name:<46} (no events)")
        return
    outs = [simulate_atr_trade(e["i"], side, e["atr"], rr=rr) for e in evlist]
    w = outs.count("win"); l = outs.count("loss"); ne = outs.count("no_exit")
    total = w + l
    wr = w/total*100 if total else 0
    sr = w*rr - l
    rtr = sr/total if total else 0
    print(f"  {name:<46} n={len(evlist):>4}  W={w:>3}  L={l:>3}  NoExit={ne:>3}  "
          f"WR={wr:>5.2f}%  ΣR={sr:>+6.1f}  R/tr={rtr:+.3f}")


print("\n" + "=" * 90)
print(" CONTINUATION hypothesis: 3-TF sync → продолжение тренда")
print("=" * 90)
print("\n--- RR=1.0 ---")
stats("3xOB → LONG (continuation)", ob_evt, "long", rr=1.0)
stats("3xOS → SHORT (continuation)", os_evt, "short", rr=1.0)

print("\n--- RR=1.5 ---")
stats("3xOB → LONG (continuation) RR=1.5", ob_evt, "long", rr=1.5)
stats("3xOS → SHORT (continuation) RR=1.5", os_evt, "short", rr=1.5)

print("\n--- RR=2.0 ---")
stats("3xOB → LONG (continuation) RR=2.0", ob_evt, "long", rr=2.0)
stats("3xOS → SHORT (continuation) RR=2.0", os_evt, "short", rr=2.0)

# combined
all_cont_rr1 = [(e, "long") for e in ob_evt] + [(e, "short") for e in os_evt]
outs = [simulate_atr_trade(e["i"], s, e["atr"], rr=1.0) for e, s in all_cont_rr1]
w = outs.count("win"); l = outs.count("loss")
n_cl = w + l
print(f"\n  COMBINED continuation RR=1.0:  n={len(all_cont_rr1)}  cl={n_cl}  WR={w/n_cl*100:.2f}%  ΣR={w-l:+}  R/tr={(w-l)/n_cl:+.3f}")


print("\n" + "=" * 90)
print(" DIVERGENCE hypothesis: 1h exits bias, HTF stays — early reversal")
print("=" * 90)
print("\n--- RR=1.0 ---")
stats("1h_exits_OB → SHORT (reversal)", div_ob, "short", rr=1.0)
stats("1h_exits_OS → LONG (reversal)", div_os, "long", rr=1.0)

print("\n--- RR=1.5 ---")
stats("1h_exits_OB → SHORT RR=1.5", div_ob, "short", rr=1.5)
stats("1h_exits_OS → LONG RR=1.5", div_os, "long", rr=1.5)

print("\n--- RR=2.0 ---")
stats("1h_exits_OB → SHORT RR=2.0", div_ob, "short", rr=2.0)
stats("1h_exits_OS → LONG RR=2.0", div_os, "long", rr=2.0)

all_div_rr15 = [(e, "short") for e in div_ob] + [(e, "long") for e in div_os]
outs = [simulate_atr_trade(e["i"], s, e["atr"], rr=1.5) for e, s in all_div_rr15]
w = outs.count("win"); l = outs.count("loss"); ne = outs.count("no_exit")
n_cl = w + l
print(f"\n  COMBINED divergence RR=1.5:  n={len(all_div_rr15)}  cl={n_cl}  WR={w/n_cl*100:.2f}%  ΣR={w*1.5-l:+.1f}  R/tr={(w*1.5-l)/n_cl:+.3f}")


print("\n" + "=" * 90)
print(" Per-year — CONTINUATION RR=1.0 combined")
print("=" * 90)

year_buckets = {}
for e, s in all_cont_rr1:
    y = datetime.fromtimestamp(tf1h["ts_open"][e["i"]] / 1000, tz=timezone.utc).year
    out = simulate_atr_trade(e["i"], s, e["atr"], rr=1.0)
    year_buckets.setdefault(y, []).append((s, out))

for y in sorted(year_buckets):
    rows = year_buckets[y]
    w = sum(1 for _, o in rows if o == "win")
    l = sum(1 for _, o in rows if o == "loss")
    n_cl = w + l
    wr = w/n_cl*100 if n_cl else 0
    sr = w - l
    print(f"  {y}  n={len(rows):>3}  cl={n_cl:>3}  WR={wr:>5.2f}%  ΣR={sr:>+5d}  R/tr={sr/n_cl if n_cl else 0:+.3f}")


print(f"\nTotal: {time.time()-t0:.1f}s")
