"""График сделки 2026-05-19 LONG с двумя VWAP, заякоренными на FH и FL ДО паттерна.

FH/FL — Williams fractals N=2 на 1h. Берём последние, подтверждённые до C1.open_time.
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_HOUR = 3600_000
MS_5M = 5 * 60_000
N_FRACTAL = 2


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
candles_1h = aggregate(data, 60)
candles_5m = aggregate(data, 5)
ts_1m = [r[0] for r in data]
print(f"{len(data):,} 1m, {len(candles_1h):,} 1h, {len(candles_5m):,} 5m")

# Cumulative arrays для O(1) VWAP
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


def vwap(anchor_idx_1m, end_idx_1m):
    pv = cum_pv[end_idx_1m + 1] - cum_pv[anchor_idx_1m]
    vol = cum_vol[end_idx_1m + 1] - cum_vol[anchor_idx_1m]
    return pv / vol if vol > 0 else 0


# Williams fractals на 1h
fh_list = []  # [(idx_1h, ts_ms)]
fl_list = []
for i in range(N_FRACTAL, len(candles_1h) - N_FRACTAL):
    h_i = candles_1h[i][2]; l_i = candles_1h[i][3]
    is_fh = all(h_i > candles_1h[j][2] for j in range(i - N_FRACTAL, i)) and \
            all(h_i > candles_1h[j][2] for j in range(i + 1, i + N_FRACTAL + 1))
    is_fl = all(l_i < candles_1h[j][3] for j in range(i - N_FRACTAL, i)) and \
            all(l_i < candles_1h[j][3] for j in range(i + 1, i + N_FRACTAL + 1))
    if is_fh: fh_list.append((i, candles_1h[i][0]))
    elif is_fl: fl_list.append((i, candles_1h[i][0]))
print(f"Found {len(fh_list)} FH + {len(fl_list)} FL on 1h\n")

# Параметры паттерна 2026-05-19 LONG
c1_ts_ms = int(datetime(2026, 5, 19, 13, 0, tzinfo=timezone.utc).timestamp() * 1000)  # 16:00 MSK
c5_close_ms = int(datetime(2026, 5, 19, 18, 0, tzinfo=timezone.utc).timestamp() * 1000)  # 21:00 MSK
entry = 76635.88; sl = 76144.71; tp = 77127.05
block = (76596.00, 76675.76); poi = (76596.00, 76872.75)

# Найти C1 idx в 1h
c1_idx = next(i for i, c in enumerate(candles_1h) if c[0] == c1_ts_ms)
# Последний FH/FL подтверждённый ДО C1 (idx <= c1_idx - N_FRACTAL - 1)
confirm_cutoff = c1_idx - N_FRACTAL  # fractal at i confirmed at i+2; we want i+2 <= c1_idx, so i <= c1_idx-2
fh_pre = max((f for f in fh_list if f[0] < confirm_cutoff), key=lambda x: x[0], default=None)
fl_pre = max((f for f in fl_list if f[0] < confirm_cutoff), key=lambda x: x[0], default=None)
print(f"C1: {datetime.fromtimestamp(c1_ts_ms/1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M')} MSK")
print(f"FH (последний до C1): 1h_idx={fh_pre[0]}, ts={datetime.fromtimestamp(fh_pre[1]/1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M')} MSK, value={candles_1h[fh_pre[0]][2]:.2f}")
print(f"FL (последний до C1): 1h_idx={fl_pre[0]}, ts={datetime.fromtimestamp(fl_pre[1]/1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M')} MSK, value={candles_1h[fl_pre[0]][3]:.2f}")

fh_anchor_1m = idx_at(fh_pre[1])
fl_anchor_1m = idx_at(fl_pre[1])

# Entry fill / exit (из ранее)
fill_ms = int(datetime(2026, 5, 20, 0, 12, tzinfo=timezone.utc).timestamp() * 1000)
exit_ms = int(datetime(2026, 5, 20, 5, 11, tzinfo=timezone.utc).timestamp() * 1000)

# Окно отображения: от FH/FL_anchor до exit + 2h
display_start = min(fh_anchor_1m, fl_anchor_1m) - 30  # +30 1m чтобы было видно начало
display_start = max(0, display_start)
display_start_ms = data[display_start][0]
display_end_ms = exit_ms + 2 * MS_HOUR

# 5m свечи в окне
display_5m = [c for c in candles_5m if display_start_ms <= c[0] <= display_end_ms]

# VWAP series — value в каждый 5m bar
vwap_fh = []; vwap_fl = []
for b in display_5m:
    bar_end_1m_idx = idx_at(b[0] + 5 * 60_000) - 1
    if bar_end_1m_idx < fh_anchor_1m:
        vwap_fh.append(None)
    else:
        vwap_fh.append(vwap(fh_anchor_1m, bar_end_1m_idx))
    if bar_end_1m_idx < fl_anchor_1m:
        vwap_fl.append(None)
    else:
        vwap_fl.append(vwap(fl_anchor_1m, bar_end_1m_idx))

# Plot
fig, ax = plt.subplots(figsize=(16, 9))
width_min = 5 * 0.7

for ts, o, h, l, c, _ in display_5m:
    x = mdates.date2num(datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(MSK))
    color = "#26a69a" if c >= o else "#ef5350"
    ax.plot([x, x], [l, h], color=color, linewidth=0.7, zorder=2)
    body_low, body_high = min(o, c), max(o, c)
    if body_high - body_low < 0.01: body_high = body_low + 0.01
    rect = mpatches.Rectangle((x - width_min / 2 / 24 / 60, body_low), width_min / 24 / 60, body_high - body_low,
                              facecolor=color, edgecolor=color, alpha=0.9, zorder=3)
    ax.add_patch(rect)

# VWAP lines
xs = [mdates.date2num(datetime.fromtimestamp(b[0] / 1000, tz=timezone.utc).astimezone(MSK)) for b in display_5m]
xs_fh = [xs[i] for i in range(len(xs)) if vwap_fh[i] is not None]
ys_fh = [v for v in vwap_fh if v is not None]
xs_fl = [xs[i] for i in range(len(xs)) if vwap_fl[i] is not None]
ys_fl = [v for v in vwap_fl if v is not None]
ax.plot(xs_fh, ys_fh, color="#d32f2f", linewidth=2, label=f"VWAP from FH ({candles_1h[fh_pre[0]][2]:.0f})", zorder=4)
ax.plot(xs_fl, ys_fl, color="#388e3c", linewidth=2, label=f"VWAP from FL ({candles_1h[fl_pre[0]][3]:.0f})", zorder=4)

# Block / POI shading на интервале C1 → exit
p_start = mdates.date2num(datetime.fromtimestamp(c1_ts_ms / 1000, tz=timezone.utc).astimezone(MSK))
p_end = mdates.date2num(datetime.fromtimestamp(display_end_ms / 1000, tz=timezone.utc).astimezone(MSK))
ax.add_patch(mpatches.Rectangle((p_start, poi[0]), p_end - p_start, poi[1] - poi[0],
                                facecolor="#fff8e1", edgecolor="#ffb300", alpha=0.4, zorder=1, label="POI"))
ax.add_patch(mpatches.Rectangle((p_start, block[0]), p_end - p_start, block[1] - block[0],
                                facecolor="#ffb300", edgecolor="#ff6f00", alpha=0.35, zorder=1, label="block"))

# Entry / SL / TP
fill_x = mdates.date2num(datetime.fromtimestamp(fill_ms / 1000, tz=timezone.utc).astimezone(MSK))
exit_x = mdates.date2num(datetime.fromtimestamp(exit_ms / 1000, tz=timezone.utc).astimezone(MSK))
ax.hlines(entry, fill_x, exit_x, colors="blue", linewidth=2, label=f"Entry {entry:.2f}")
ax.hlines(sl, fill_x, exit_x, colors="red", linewidth=1.5, linestyles="--", label=f"SL {sl:.2f}")
ax.hlines(tp, fill_x, exit_x, colors="green", linewidth=1.5, linestyles="--", label=f"TP {tp:.2f}")
ax.scatter([fill_x], [entry], s=120, c="blue", marker="o", zorder=5)
ax.scatter([exit_x], [tp], s=140, c="green", marker="^", zorder=5, label="Exit (WIN)")

# Pattern labels
pattern_candles_1h = [c for c in candles_1h if c1_ts_ms <= c[0] < c5_close_ms]
for idx, c in enumerate(pattern_candles_1h):
    x = mdates.date2num(datetime.fromtimestamp((c[0] + 30 * 60_000) / 1000, tz=timezone.utc).astimezone(MSK))
    y = c[2] + (poi[1] - poi[0]) * 0.2
    ax.annotate(f"C{idx+1}", (x, y), ha="center", fontsize=11, fontweight="bold", color="#1a237e", zorder=6)

# Annotate FH / FL anchor points
fh_x = mdates.date2num(datetime.fromtimestamp(fh_pre[1] / 1000, tz=timezone.utc).astimezone(MSK))
fl_x = mdates.date2num(datetime.fromtimestamp(fl_pre[1] / 1000, tz=timezone.utc).astimezone(MSK))
ax.scatter([fh_x], [candles_1h[fh_pre[0]][2]], s=200, marker="v", color="#d32f2f", zorder=6, edgecolor="black")
ax.scatter([fl_x], [candles_1h[fl_pre[0]][3]], s=200, marker="^", color="#388e3c", zorder=6, edgecolor="black")
ax.annotate("FH anchor", (fh_x, candles_1h[fh_pre[0]][2]), xytext=(5, 10), textcoords="offset points",
            fontsize=10, fontweight="bold", color="#d32f2f")
ax.annotate("FL anchor", (fl_x, candles_1h[fl_pre[0]][3]), xytext=(5, -15), textcoords="offset points",
            fontsize=10, fontweight="bold", color="#388e3c")

ax.set_title(f"2026-05-19 LONG i-RDRB+FVG (WIN) — VWAP от ближайших pre-pattern FH/FL", fontsize=13)
ax.set_ylabel("Price (USDT)")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M", tz=MSK))
ax.xaxis.set_major_locator(mdates.AutoDateLocator(tz=MSK, maxticks=10))
ax.grid(True, alpha=0.3)
ax.legend(loc="best", fontsize=9, framealpha=0.9)
plt.xticks(rotation=30)
plt.tight_layout()

OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/fhfl_vwap_2026-05-19_long.png"
plt.savefig(OUT, dpi=120, bbox_inches="tight")
plt.close()
print(f"\nSaved {OUT}")

# Также сообщим значения VWAP в ключевых точках
def vwap_at_ms(anchor_idx, ts_ms):
    idx = idx_at(ts_ms) - 1
    if idx < anchor_idx: return None
    return vwap(anchor_idx, idx)

print("\n=== Значения VWAP в ключевых точках ===")
for label, ms in [("C1 close", c1_ts_ms + MS_HOUR),
                   ("C5 close", c5_close_ms),
                   ("Fill (08:12 MSK +1d)", fill_ms),
                   ("Exit/TP (13:11 MSK +1d)", exit_ms)]:
    v_fh = vwap_at_ms(fh_anchor_1m, ms)
    v_fl = vwap_at_ms(fl_anchor_1m, ms)
    t = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H:%M')
    print(f"  {label} ({t}):  VWAP-FH = {v_fh:.2f}  VWAP-FL = {v_fl:.2f}")
