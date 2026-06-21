"""RSI ASVK — proper usage с 4 правильными метриками + multi-TF sync.

Метрики (на каждом TF и каждом баре):
  1. SQUEEZE     — band_width = NWE_upper - NWE_lower; squeeze_pct = percentile
                   band_width относительно rolling 200 баров (низкий percentile = compression)
  2. TIME_IN_ZONE — consecutive bars в текущей зоне (red/green/yellow_ob/yellow_os/neutral)
  3. DEPTH       — насколько глубоко в OB/OS: (ema_3 - above) / band_width для red, и т.д.
                   Большое depth = extreme exhaustion candidate
  4. SYNC        — кол-во TFs из {1h, 2h, 3h} в одной и той же зоне (или одного знака)

Запуск на BTC 1h данных за последние 7 дней + sample reversal events
+ 6y stats для multi-TF sync signal.
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
print(f"  {len(data):,} 1m rows ({time.time()-t0:.1f}s)")


def compute_tf(tf_min, name):
    bars = aggregate(data, tf_min)
    closes = [b[4] for b in bars]
    ts_open = [b[0] for b in bars]
    print(f"  computing ASVK on {name}: {len(bars)} bars...")
    res = adjusted_rsi(closes, period=14)
    return {"name": name, "tf_min": tf_min, "ts_open": ts_open, "closes": closes, **res}


tf1h = compute_tf(60, "1h")
tf2h = compute_tf(120, "2h")
tf3h = compute_tf(180, "3h")
print(f"All ASVKs done ({time.time()-t0:.1f}s)")


def zone_of(t, i):
    return asvk_zone(t["ema_3"][i], t["above"][i], t["below"][i],
                     t["nwe_upper"][i], t["nwe_lower"][i])


def band_width(t, i):
    u = t["nwe_upper"][i]; l = t["nwe_lower"][i]
    return (u - l) if (u is not None and l is not None) else None


def compute_squeeze_pct(t, win=200):
    """Percentile rank of current band_width vs rolling window. Low = compressed."""
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


print("Computing squeeze percentiles...")
tf1h["squeeze"] = compute_squeeze_pct(tf1h)
tf2h["squeeze"] = compute_squeeze_pct(tf2h)
tf3h["squeeze"] = compute_squeeze_pct(tf3h)
print(f"  done ({time.time()-t0:.1f}s)")


def time_in_zone(t):
    """For each bar i: consecutive bars in same zone (counting backwards)."""
    out = [0] * len(t["ts_open"])
    prev_z = None
    streak = 0
    for i in range(len(t["ts_open"])):
        z = zone_of(t, i)
        if z == prev_z:
            streak += 1
        else:
            streak = 1
        out[i] = streak
        prev_z = z
    return out


tf1h["tiz"] = time_in_zone(tf1h)
tf2h["tiz"] = time_in_zone(tf2h)
tf3h["tiz"] = time_in_zone(tf3h)


def depth(t, i):
    """How extreme is current ema_3 relative to above/below, normalized by band width.
    Returns positive = above above (red depth), negative = below below (green depth).
    """
    e = t["ema_3"][i]; a = t["above"][i]; b = t["below"][i]
    bw = band_width(t, i)
    if e is None or a is None or b is None or not bw or bw == 0: return None
    if e > a: return (e - a) / bw    # positive = red depth
    if e < b: return (e - b) / bw    # negative = green depth (b - e is positive, but signed neg)
    return 0.0


# === Index of last fully closed higher-TF bar at given 1h ts ===
def htf_idx_at(htf, query_ts):
    """Last i where htf.ts_open[i] + tf <= query_ts (= bar closed)."""
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


# === Compute multi-TF sync at each 1h bar ===
def sync_at(i1h):
    """Returns dict with zones on 1h/2h/3h at this 1h close ts."""
    ts = tf1h["ts_open"][i1h] + 60 * 60_000  # close of this 1h bar
    z1 = zone_of(tf1h, i1h)
    i2 = htf_idx_at(tf2h, ts)
    i3 = htf_idx_at(tf3h, ts)
    z2 = zone_of(tf2h, i2) if i2 >= 0 else "n/a"
    z3 = zone_of(tf3h, i3) if i3 >= 0 else "n/a"
    return z1, z2, z3, i2, i3


# Map zone to bias: red/yellow_ob = "OB"; green/yellow_os = "OS"; neutral = "N"
def zone_to_bias(z):
    if z in ("red", "yellow_ob"): return "OB"
    if z in ("green", "yellow_os"): return "OS"
    return "N"


# === Demo последних 7 дней ===
N_TAIL = 7 * 24


def fmt_msk(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H:%M')


print(f"\n{'='*120}")
print(f" Last {N_TAIL}h — multi-TF sync + squeeze + depth + tiz")
print(f"{'='*120}")
print(f"{'time MSK':>11}  {'close':>8}  "
      f"{'1h(zone/ema3/dpth/tiz/sqz)':>30}  "
      f"{'2h(zone/ema3/dpth/tiz)':>26}  "
      f"{'3h(zone/ema3)':>15}  sync")
print("-" * 120)

n = len(tf1h["ts_open"])
sync_events = []
for i in range(n - N_TAIL, n):
    if i < 0: continue
    z1, z2, z3, i2, i3 = sync_at(i)
    bias1, bias2, bias3 = zone_to_bias(z1), zone_to_bias(z2), zone_to_bias(z3)
    biases = [bias1, bias2, bias3]
    sync = max(biases.count(b) for b in set(biases))  # max count of same bias
    dominant = max(set(biases), key=biases.count)
    sync_str = f"{sync}×{dominant}"

    d1 = depth(tf1h, i); d2 = depth(tf2h, i2) if i2 >= 0 else None
    sqz1 = tf1h["squeeze"][i]
    tiz1 = tf1h["tiz"][i]
    tiz2 = tf2h["tiz"][i2] if i2 >= 0 else 0

    if i % 3 != 0 and sync < 3:
        continue  # print only every 3h unless full sync

    print(f"{fmt_msk(tf1h['ts_open'][i]):>11}  {tf1h['closes'][i]:>8.0f}  "
          f"{z1:>10}/{(tf1h['ema_3'][i] or 0):>5.1f}/{(d1 if d1 is not None else 0):>+5.2f}/{tiz1:>3}/{(sqz1 or 0):>4.2f}  "
          f"{z2:>10}/{(tf2h['ema_3'][i2] or 0):>5.1f}/{(d2 if d2 is not None else 0):>+5.2f}/{tiz2:>3}  "
          f"{z3:>10}/{(tf3h['ema_3'][i3] or 0):>5.1f}  "
          f"{sync_str}")

    if sync == 3 and dominant != "N":
        sync_events.append({
            "i": i, "ts": tf1h["ts_open"][i], "close": tf1h["closes"][i],
            "dominant": dominant, "depth1h": d1,
        })

print(f"\nSync events (all 3 TF agree, non-neutral) за {N_TAIL}h: {len(sync_events)}")
for e in sync_events[:10]:
    print(f"  {fmt_msk(e['ts'])}  close={e['close']:.0f}  bias={e['dominant']}  d_1h={(e['depth1h'] or 0):+.2f}")


# === Squeeze events за 7 days ===
print(f"\n--- Squeeze events за {N_TAIL}h (squeeze_pct ≤ 0.15) ---")
for i in range(n - N_TAIL, n):
    if i < 0: continue
    sqz = tf1h["squeeze"][i]
    if sqz is None or sqz > 0.15: continue
    z1 = zone_of(tf1h, i)
    print(f"  {fmt_msk(tf1h['ts_open'][i])}  close={tf1h['closes'][i]:.0f}  "
          f"squeeze_pct={sqz:.2f}  zone={z1}  bw={band_width(tf1h, i):.2f}")


# === 6y signal study: full multi-TF sync = signal? ===
print(f"\n{'='*120}")
print(f" 6y BTC: signals where all 3 TFs (1h, 2h, 3h) agree on non-neutral bias")
print(f"{'='*120}")

last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
start_i = next(i for i, ts in enumerate(tf1h["ts_open"]) if ts >= window_start_ms)

# Detect sync EVENT = transition into 3×OB or 3×OS (from less sync)
prev_sync = None
events = []
for i in range(start_i, n):
    z1, z2, z3, i2, i3 = sync_at(i)
    biases = [zone_to_bias(z1), zone_to_bias(z2), zone_to_bias(z3)]
    sync_count = max(biases.count(b) for b in set(biases))
    dominant = max(set(biases), key=biases.count)
    cur_sync = f"{sync_count}×{dominant}" if dominant != "N" and sync_count == 3 else None
    if cur_sync != prev_sync and cur_sync is not None:
        # transition INTO 3-sync state — register event
        events.append({
            "i": i, "ts": tf1h["ts_open"][i] + 60 * 60_000,  # close ts
            "close": tf1h["closes"][i], "dominant": dominant,
            "depth1h": depth(tf1h, i), "squeeze1h": tf1h["squeeze"][i],
            "tiz1h": tf1h["tiz"][i],
        })
    prev_sync = cur_sync

print(f"  Total sync entries (transitions into 3xOB or 3xOS): {len(events)}")
ob = [e for e in events if e["dominant"] == "OB"]
os_ = [e for e in events if e["dominant"] == "OS"]
print(f"  3xOB (reversal SHORT candidates): {len(ob)}")
print(f"  3xOS (reversal LONG candidates):  {len(os_)}")


# === Forward-look: средний move через 6h, 12h, 24h, 48h ===
def fwd_move(close_idx_1m, horizon_h, side):
    """Returns R-like measure: (price@horizon - close) / ATR, or just price delta.
    Use simple: % move в направлении ожидаемого reversal.
    For OB (expected DOWN): % = (close - low_in_window) / close
    For OS (expected UP):   % = (high_in_window - close) / close
    """
    target_ts = tf1h["ts_open"][close_idx_1m] + (horizon_h + 1) * MS_HOUR
    # find 1h bars within [close_idx, close_at_horizon]
    end_idx = None
    for k in range(close_idx_1m + 1, len(tf1h["ts_open"])):
        if tf1h["ts_open"][k] > target_ts: break
        end_idx = k
    if end_idx is None or end_idx <= close_idx_1m: return None
    return end_idx


def price_move(close_idx, horizon_h, side):
    end_i = fwd_move(close_idx, horizon_h, side)
    if end_i is None: return None
    cur_close = tf1h["closes"][close_idx]
    sub = list(range(close_idx + 1, end_i + 1))
    if not sub: return None
    if side == "OB":  # expecting price to drop
        target_price = min(tf1h["closes"][k] for k in sub)
        return (cur_close - target_price) / cur_close * 100  # % drop achieved
    else:  # OS, expecting price up
        target_price = max(tf1h["closes"][k] for k in sub)
        return (target_price - cur_close) / cur_close * 100


print(f"\n--- Forward move analysis (% in expected direction) ---")
print(f"  Bias        n    avg_move@6h   avg_move@12h   avg_move@24h   avg_move@48h")
for bias, evlist in [("OB (→DOWN)", ob), ("OS (→UP)", os_)]:
    moves = {h: [] for h in [6, 12, 24, 48]}
    for e in evlist:
        for h in moves:
            m = price_move(e["i"], h, e["dominant"])
            if m is not None: moves[h].append(m)
    avgs = []
    for h in [6, 12, 24, 48]:
        avg = sum(moves[h]) / len(moves[h]) if moves[h] else 0
        avgs.append(f"{avg:>+8.2f}%  (n={len(moves[h])})")
    print(f"  {bias:<12} {len(evlist):>4}  " + "  ".join(avgs))


# === Additional: split by depth и squeeze ===
print(f"\n--- 3xOB events: by 1h depth (extension intensity) ---")
print(f"  depth bin     n    avg_drop@24h")
for lo, hi in [(0, 0.3), (0.3, 0.6), (0.6, 1.0), (1.0, 5)]:
    sub = [e for e in ob if e["depth1h"] is not None and lo <= e["depth1h"] < hi]
    moves = [price_move(e["i"], 24, "OB") for e in sub]
    moves = [m for m in moves if m is not None]
    avg = sum(moves) / len(moves) if moves else 0
    print(f"  [{lo:.1f}, {hi:.1f})  {len(sub):>4}  {avg:>+6.2f}%")

print(f"\n--- 3xOS events: by 1h depth ---")
print(f"  depth bin     n    avg_rise@24h")
for lo, hi in [(-5, -1.0), (-1.0, -0.6), (-0.6, -0.3), (-0.3, 0)]:
    sub = [e for e in os_ if e["depth1h"] is not None and lo <= e["depth1h"] < hi]
    moves = [price_move(e["i"], 24, "OS") for e in sub]
    moves = [m for m in moves if m is not None]
    avg = sum(moves) / len(moves) if moves else 0
    print(f"  [{lo:>5.1f}, {hi:>5.1f})  {len(sub):>4}  {avg:>+6.2f}%")


print(f"\n--- Squeeze BEFORE sync event (was 1h squeeze_pct < 0.15 в окне 6 баров до event) ---")
ob_sq = []; ob_nosq = []
for e in ob:
    had_squeeze = False
    for k in range(max(0, e["i"] - 6), e["i"]):
        s = tf1h["squeeze"][k]
        if s is not None and s < 0.15:
            had_squeeze = True; break
    m = price_move(e["i"], 24, "OB")
    if m is None: continue
    (ob_sq if had_squeeze else ob_nosq).append(m)

os_sq = []; os_nosq = []
for e in os_:
    had_squeeze = False
    for k in range(max(0, e["i"] - 6), e["i"]):
        s = tf1h["squeeze"][k]
        if s is not None and s < 0.15:
            had_squeeze = True; break
    m = price_move(e["i"], 24, "OS")
    if m is None: continue
    (os_sq if had_squeeze else os_nosq).append(m)

def mean(lst): return sum(lst)/len(lst) if lst else 0
print(f"  3xOB after squeeze (n={len(ob_sq)}): avg drop@24h = {mean(ob_sq):+.2f}%")
print(f"  3xOB no squeeze    (n={len(ob_nosq)}): avg drop@24h = {mean(ob_nosq):+.2f}%")
print(f"  3xOS after squeeze (n={len(os_sq)}): avg rise@24h = {mean(os_sq):+.2f}%")
print(f"  3xOS no squeeze    (n={len(os_nosq)}): avg rise@24h = {mean(os_nosq):+.2f}%")


print(f"\nTotal time: {time.time()-t0:.1f}s")
