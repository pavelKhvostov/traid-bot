"""VWAP от десяти крайних подтверждённых D-фракталов (FH/FL)."""
from __future__ import annotations

import csv
import pathlib
from datetime import datetime, timedelta, timezone

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_HOUR = 3600_000
MS_D = 24 * MS_HOUR
N_FRACTAL = 2
N_LAST = 10


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


print("Loading 1m..."); data = load_1m()
candles_D = aggregate(data, 1440)
candles_4h = aggregate(data, 240)
ts_1m = [r[0] for r in data]

cum_pv = [0.0] * (len(data) + 1); cum_vol = [0.0] * (len(data) + 1)
for i, (_, _, _, _, c, v) in enumerate(data):
    cum_pv[i + 1] = cum_pv[i] + v * c
    cum_vol[i + 1] = cum_vol[i] + v


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def vwap(a, e):
    pv = cum_pv[e + 1] - cum_pv[a]; vol = cum_vol[e + 1] - cum_vol[a]
    return pv / vol if vol > 0 else 0


fractals = []
for i in range(N_FRACTAL, len(candles_D) - N_FRACTAL):
    h_i = candles_D[i][2]; l_i = candles_D[i][3]
    if all(h_i > candles_D[j][2] for j in range(i - N_FRACTAL, i)) and \
       all(h_i > candles_D[j][2] for j in range(i + 1, i + N_FRACTAL + 1)):
        fractals.append(("FH", i, candles_D[i][0], candles_D[i][2]))
    elif all(l_i < candles_D[j][3] for j in range(i - N_FRACTAL, i)) and \
         all(l_i < candles_D[j][3] for j in range(i + 1, i + N_FRACTAL + 1)):
        fractals.append(("FL", i, candles_D[i][0], candles_D[i][3]))

now_ms = data[-1][0]
confirmed = [f for f in fractals if f[2] + (N_FRACTAL + 1) * MS_D <= now_ms]
last10 = confirmed[-N_LAST:]


def fmt(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M')


print(f"Total D fractals: {len(fractals)}, confirmed: {len(confirmed)}, taking last {N_LAST}:")
for kind, idx, ts, price in last10:
    print(f"  {kind}  {fmt(ts)[:10]}  price={price:.2f}")

anchors = [(kind, ts, price, idx_at(ts)) for kind, _, ts, price in last10]

display_start_ms = min(a[1] for a in anchors) - 2 * MS_D
display_end_ms = now_ms
display_candles = [c for c in candles_4h if display_start_ms <= c[0] <= display_end_ms]

vwap_lines = []
for kind, anchor_ts, anchor_price, anchor_idx in anchors:
    ys = []
    for b in display_candles:
        bar_end_idx = idx_at(b[0] + 4 * MS_HOUR) - 1
        ys.append(vwap(anchor_idx, bar_end_idx) if bar_end_idx >= anchor_idx else None)
    vwap_lines.append((kind, anchor_ts, anchor_price, ys))

fig, ax = plt.subplots(figsize=(20, 10))
WIDTH = 4 * 0.7

for ts, o, h, l, c, _ in display_candles:
    x = mdates.date2num(datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(MSK))
    color = "#26a69a" if c >= o else "#ef5350"
    ax.plot([x, x], [l, h], color=color, linewidth=0.5, zorder=2)
    body_low, body_high = min(o, c), max(o, c)
    if body_high - body_low < 0.01: body_high = body_low + 0.01
    ax.add_patch(mpatches.Rectangle((x - WIDTH / 2 / 24, body_low), WIDTH / 24, body_high - body_low,
                                    facecolor=color, edgecolor=color, alpha=0.85, zorder=3))

xs = [mdates.date2num(datetime.fromtimestamp(b[0] / 1000, tz=timezone.utc).astimezone(MSK)) for b in display_candles]

fh_i = fl_i = 0
n_fh = sum(1 for k, *_ in vwap_lines if k == 'FH')
n_fl = sum(1 for k, *_ in vwap_lines if k == 'FL')

for kind, anchor_ts, anchor_price, ys in vwap_lines:
    xs_v = [xs[i] for i in range(len(xs)) if ys[i] is not None]
    ys_v = [v for v in ys if v is not None]
    if kind == "FH":
        shade = 0.35 + 0.55 * fh_i / max(1, n_fh - 1) if n_fh > 1 else 0.7
        color = plt.cm.Reds(shade)
        fh_i += 1
    else:
        shade = 0.35 + 0.55 * fl_i / max(1, n_fl - 1) if n_fl > 1 else 0.7
        color = plt.cm.Greens(shade)
        fl_i += 1
    label = f"VWAP {kind} {fmt(anchor_ts)[:10]} ({anchor_price:.0f})"
    ax.plot(xs_v, ys_v, color=color, linewidth=1.6, label=label, zorder=4, alpha=0.9)

    a_x = mdates.date2num(datetime.fromtimestamp(anchor_ts / 1000, tz=timezone.utc).astimezone(MSK))
    marker = "v" if kind == "FH" else "^"
    ax.scatter([a_x], [anchor_price], s=140, marker=marker, color=color, edgecolor="black", linewidths=0.8, zorder=6)

ax.set_title(f"BTC 4h — VWAP от {N_LAST} крайних подтверждённых D-фракталов (по состоянию на {fmt(now_ms)} MSK)", fontsize=13)
ax.set_ylabel("Price (USDT)")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d", tz=MSK))
ax.xaxis.set_major_locator(mdates.AutoDateLocator(tz=MSK, maxticks=14))
ax.grid(True, alpha=0.3)
ax.legend(loc="best", fontsize=8, framealpha=0.9, ncol=2)
plt.xticks(rotation=30)
plt.tight_layout()

OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/d_10_fractals_vwap.png"
plt.savefig(OUT, dpi=120, bbox_inches="tight")
plt.close()
print(f"\nSaved {OUT}")

print("\n=== Текущие значения VWAP ===")
last_close = data[-1][4]
for kind, anchor_ts, anchor_price, anchor_idx in anchors:
    v_now = vwap(anchor_idx, len(data) - 1)
    delta = (last_close - v_now) / v_now * 100
    print(f"  {kind} {fmt(anchor_ts)[:10]} (anchor={anchor_price:.2f}):  VWAP_now = {v_now:.2f}  ({delta:+.2f}%)")
print(f"\n  Last close: {last_close:.2f} ({fmt(now_ms)} MSK)")
