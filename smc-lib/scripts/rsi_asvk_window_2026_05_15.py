"""RSI ASVK на конкретном окне 2026-05-15 21:00 → 2026-05-20 03:00 MSK
на трёх ТФ 1h / 2h / 3h синхронно.

Что показываю на каждом 1h-баре:
  time MSK | close | 1h(zone/ema3/above/below/sqz_pct) | 2h(zone/ema3) | 3h(zone/ema3) | sync_marker
+ диагноз: где переходы зон, sync events.
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

WIN_START_MSK = datetime(2026, 5, 15, 21, 0, tzinfo=MSK)
WIN_END_MSK   = datetime(2026, 5, 20, 3, 0, tzinfo=MSK)
WIN_START_MS = int(WIN_START_MSK.timestamp() * 1000)
WIN_END_MS   = int(WIN_END_MSK.timestamp() * 1000)

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


def compute(tf_min):
    bars = aggregate(data, tf_min)
    closes = [b[4] for b in bars]
    ts_open = [b[0] for b in bars]
    res = adjusted_rsi(closes, period=14)
    res["ts_open"] = ts_open; res["closes"] = closes; res["tf_min"] = tf_min
    return res


tf1h = compute(60); tf2h = compute(120); tf3h = compute(180)
print(f"  3 TFs ready ({time.time()-t0:.1f}s)")


def zone_of(t, i):
    return asvk_zone(t["ema_3"][i], t["above"][i], t["below"][i],
                     t["nwe_upper"][i], t["nwe_lower"][i])


def zone_bias(z):
    if z in ("red", "yellow_ob"): return "OB"
    if z in ("green", "yellow_os"): return "OS"
    return "N"


def band_width(t, i):
    u = t["nwe_upper"][i]; l = t["nwe_lower"][i]
    return (u - l) if (u is not None and l is not None) else None


def squeeze_pct(t, i, win=200):
    bw_now = band_width(t, i)
    if bw_now is None: return None
    lo = max(0, i - win + 1)
    window = [band_width(t, k) for k in range(lo, i+1)]
    window = [x for x in window if x is not None]
    if len(window) < 20: return None
    return sum(1 for x in window if x < bw_now) / len(window)


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


def fmt_msk(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H:%M')


# Find window indices on 1h
start_idx = next(i for i, ts in enumerate(tf1h["ts_open"]) if ts >= WIN_START_MS)
end_idx = next((i for i, ts in enumerate(tf1h["ts_open"]) if ts > WIN_END_MS), len(tf1h["ts_open"]))
print(f"  1h window: {start_idx} → {end_idx}  ({end_idx-start_idx} bars)")


def zone_glyph(z):
    return {"red": "🔴red    ", "yellow_ob": "🟡y_ob   ", "neutral": "⚪neutral",
            "yellow_os": "🟡y_os   ", "green": "🟢green  "}.get(z, z)


# --- Print mini-headers + per-bar state ---
print(f"\n{'='*128}")
print(f" Окно: {WIN_START_MSK.strftime('%Y-%m-%d %H:%M')} → {WIN_END_MSK.strftime('%Y-%m-%d %H:%M')} MSK")
print(f"{'='*128}")
print(f"{'time MSK':>11}  {'close':>8} | "
      f"{'1h(zone/ema3/above/below/sqz%)':<46} | "
      f"{'2h(zone/ema3/above/below)':<38} | "
      f"{'3h(zone/ema3/above/below)':<38} | sync")
print("-" * 168)

events_log = []
prev_z1 = None; prev_z2_idx = -1; prev_z2 = None; prev_z3_idx = -1; prev_z3 = None
prev_sync = None

for i in range(start_idx, end_idx):
    ts_open = tf1h["ts_open"][i]
    ts_close = ts_open + 60 * 60_000
    close_price = tf1h["closes"][i]

    z1 = zone_of(tf1h, i)
    e1 = tf1h["ema_3"][i]
    a1 = tf1h["above"][i]; b1 = tf1h["below"][i]
    sqz1 = squeeze_pct(tf1h, i)

    i2 = htf_idx_at(tf2h, ts_close)
    z2 = zone_of(tf2h, i2) if i2 >= 0 else "n/a"
    e2 = tf2h["ema_3"][i2] if i2 >= 0 else 0
    a2 = tf2h["above"][i2] if i2 >= 0 else 0
    b2 = tf2h["below"][i2] if i2 >= 0 else 0

    i3 = htf_idx_at(tf3h, ts_close)
    z3 = zone_of(tf3h, i3) if i3 >= 0 else "n/a"
    e3 = tf3h["ema_3"][i3] if i3 >= 0 else 0
    a3 = tf3h["above"][i3] if i3 >= 0 else 0
    b3 = tf3h["below"][i3] if i3 >= 0 else 0

    biases = [zone_bias(z1), zone_bias(z2), zone_bias(z3)]
    dominant = max(set(biases), key=biases.count)
    sync_n = biases.count(dominant)
    sync_str = f"{sync_n}×{dominant}" if dominant != "N" else f"{sync_n}×N"

    marker = ""
    if sync_n == 3 and dominant != "N" and sync_str != prev_sync:
        marker = f"  ← ⭐ 3×{dominant} ENTRY"
        events_log.append((fmt_msk(ts_close), "SYNC", dominant, close_price))
    if z1 != prev_z1 and prev_z1 is not None:
        marker += f"  ← 1h: {prev_z1}→{z1}"
        events_log.append((fmt_msk(ts_close), "1h-zone", f"{prev_z1}→{z1}", close_price))
    if i2 != prev_z2_idx:  # new 2h bar
        if prev_z2 is not None and z2 != prev_z2:
            marker += f"  ← 2h: {prev_z2}→{z2}"
            events_log.append((fmt_msk(ts_close), "2h-zone", f"{prev_z2}→{z2}", close_price))
        prev_z2 = z2; prev_z2_idx = i2
    if i3 != prev_z3_idx:
        if prev_z3 is not None and z3 != prev_z3:
            marker += f"  ← 3h: {prev_z3}→{z3}"
            events_log.append((fmt_msk(ts_close), "3h-zone", f"{prev_z3}→{z3}", close_price))
        prev_z3 = z3; prev_z3_idx = i3

    prev_z1 = z1
    if prev_z2 is None: prev_z2 = z2; prev_z2_idx = i2
    if prev_z3 is None: prev_z3 = z3; prev_z3_idx = i3
    prev_sync = sync_str

    c1_str = f"{zone_glyph(z1)}/{(e1 or 0):>5.1f}/{(a1 or 0):>5.1f}/{(b1 or 0):>4.1f}/{(sqz1 or 0)*100:>4.0f}%"
    c2_str = f"{zone_glyph(z2)}/{(e2 or 0):>5.1f}/{(a2 or 0):>5.1f}/{(b2 or 0):>4.1f}"
    c3_str = f"{zone_glyph(z3)}/{(e3 or 0):>5.1f}/{(a3 or 0):>5.1f}/{(b3 or 0):>4.1f}"

    print(f"{fmt_msk(ts_open):>11}  {close_price:>8.0f} | {c1_str:<46} | {c2_str:<38} | {c3_str:<38} | {sync_str:>4}{marker}")


# Price summary
print(f"\n--- Price summary в окне ---")
window_closes = [tf1h["closes"][i] for i in range(start_idx, end_idx)]
window_hi = max(tf1h["closes"][i] for i in range(start_idx, end_idx))
window_lo = min(tf1h["closes"][i] for i in range(start_idx, end_idx))
print(f"  Start: {window_closes[0]:.0f}  End: {window_closes[-1]:.0f}  "
      f"High: {window_hi:.0f}  Low: {window_lo:.0f}  "
      f"Range: {window_hi-window_lo:.0f} (~{(window_hi-window_lo)/window_lo*100:.2f}%)")
print(f"  Net move: {window_closes[-1]-window_closes[0]:+.0f} ({(window_closes[-1]-window_closes[0])/window_closes[0]*100:+.2f}%)")

print(f"\n--- Key events в окне ({len(events_log)} total) ---")
for ts_s, kind, val, price in events_log:
    print(f"  {ts_s}  {kind:<8}  {val:<25}  close={price:.0f}")
