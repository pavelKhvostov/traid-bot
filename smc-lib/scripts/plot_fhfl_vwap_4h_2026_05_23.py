"""График 2026-05-23 LONG (LOSS) с двумя VWAP, заякоренными на 4h FH и FL ДО паттерна."""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_HOUR = 3600_000
MS_4H = 4 * MS_HOUR
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
candles_4h = aggregate(data, 240)
candles_15m = aggregate(data, 15)
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


fh_4h = []; fl_4h = []
for i in range(N_FRACTAL, len(candles_4h) - N_FRACTAL):
    h_i = candles_4h[i][2]; l_i = candles_4h[i][3]
    if all(h_i > candles_4h[j][2] for j in range(i - N_FRACTAL, i)) and \
       all(h_i > candles_4h[j][2] for j in range(i + 1, i + N_FRACTAL + 1)):
        fh_4h.append((i, candles_4h[i][0]))
    elif all(l_i < candles_4h[j][3] for j in range(i - N_FRACTAL, i)) and \
         all(l_i < candles_4h[j][3] for j in range(i + 1, i + N_FRACTAL + 1)):
        fl_4h.append((i, candles_4h[i][0]))
print(f"Found {len(fh_4h)} FH + {len(fl_4h)} FL на 4h")

# 2026-05-23 LONG (LOSS)
c1_ts_ms = int(datetime(2026, 5, 22, 23, 0, tzinfo=timezone.utc).timestamp() * 1000)  # 02:00 MSK 23-го
c5_close_ms = int(datetime(2026, 5, 23, 4, 0, tzinfo=timezone.utc).timestamp() * 1000)  # 07:00 MSK
entry = 75494.92; sl = 75220.00; tp = 75769.84
block = (75489.84, 75500.00); poi = (75489.84, 75539.50)
fill_ms = int(datetime(2026, 5, 23, 5, 24, tzinfo=timezone.utc).timestamp() * 1000)
exit_ms = int(datetime(2026, 5, 23, 7, 31, tzinfo=timezone.utc).timestamp() * 1000)


def confirmed_before(frac_list, ref_ms):
    out = None
    for f_idx, f_ts in frac_list:
        if f_ts + (N_FRACTAL + 1) * MS_4H <= ref_ms:
            out = (f_idx, f_ts)
        else:
            break
    return out


fh_pre = confirmed_before(fh_4h, c1_ts_ms)
fl_pre = confirmed_before(fl_4h, c1_ts_ms)


def fmt(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M')

print(f"C1: {fmt(c1_ts_ms)} MSK")
print(f"FH 4h pre-C1: ts={fmt(fh_pre[1])}, high={candles_4h[fh_pre[0]][2]:.2f}")
print(f"FL 4h pre-C1: ts={fmt(fl_pre[1])}, low={candles_4h[fl_pre[0]][3]:.2f}")

fh_anchor = idx_at(fh_pre[1])
fl_anchor = idx_at(fl_pre[1])

display_start_ms = min(fh_pre[1], fl_pre[1]) - 8 * MS_HOUR
display_end_ms = exit_ms + 4 * MS_HOUR
display_candles = [c for c in candles_15m if display_start_ms <= c[0] <= display_end_ms]

vwap_fh = []; vwap_fl = []
for b in display_candles:
    bar_end_idx = idx_at(b[0] + 15 * 60_000) - 1
    vwap_fh.append(vwap(fh_anchor, bar_end_idx) if bar_end_idx >= fh_anchor else None)
    vwap_fl.append(vwap(fl_anchor, bar_end_idx) if bar_end_idx >= fl_anchor else None)

# Plot
fig, ax = plt.subplots(figsize=(18, 9))
WIDTH = 15 * 0.7

for ts, o, h, l, c, _ in display_candles:
    x = mdates.date2num(datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(MSK))
    color = "#26a69a" if c >= o else "#ef5350"
    ax.plot([x, x], [l, h], color=color, linewidth=0.6, zorder=2)
    body_low, body_high = min(o, c), max(o, c)
    if body_high - body_low < 0.01: body_high = body_low + 0.01
    ax.add_patch(mpatches.Rectangle((x - WIDTH / 2 / 24 / 60, body_low), WIDTH / 24 / 60, body_high - body_low,
                                    facecolor=color, edgecolor=color, alpha=0.9, zorder=3))

xs = [mdates.date2num(datetime.fromtimestamp(b[0] / 1000, tz=timezone.utc).astimezone(MSK)) for b in display_candles]
xs_fh = [xs[i] for i in range(len(xs)) if vwap_fh[i] is not None]
ys_fh = [v for v in vwap_fh if v is not None]
xs_fl = [xs[i] for i in range(len(xs)) if vwap_fl[i] is not None]
ys_fl = [v for v in vwap_fl if v is not None]
ax.plot(xs_fh, ys_fh, color="#d32f2f", linewidth=2.2, label=f"VWAP from 4h FH ({candles_4h[fh_pre[0]][2]:.0f})", zorder=4)
ax.plot(xs_fl, ys_fl, color="#388e3c", linewidth=2.2, label=f"VWAP from 4h FL ({candles_4h[fl_pre[0]][3]:.0f})", zorder=4)

p_start = mdates.date2num(datetime.fromtimestamp(c1_ts_ms / 1000, tz=timezone.utc).astimezone(MSK))
p_end = mdates.date2num(datetime.fromtimestamp(display_end_ms / 1000, tz=timezone.utc).astimezone(MSK))
ax.add_patch(mpatches.Rectangle((p_start, poi[0]), p_end - p_start, poi[1] - poi[0],
                                facecolor="#fff8e1", edgecolor="#ffb300", alpha=0.4, zorder=1, label="POI"))
ax.add_patch(mpatches.Rectangle((p_start, block[0]), p_end - p_start, block[1] - block[0],
                                facecolor="#ffb300", edgecolor="#ff6f00", alpha=0.35, zorder=1, label="block"))

fill_x = mdates.date2num(datetime.fromtimestamp(fill_ms / 1000, tz=timezone.utc).astimezone(MSK))
exit_x = mdates.date2num(datetime.fromtimestamp(exit_ms / 1000, tz=timezone.utc).astimezone(MSK))
ax.hlines(entry, fill_x, exit_x, colors="blue", linewidth=2, label=f"Entry {entry:.2f}")
ax.hlines(sl, fill_x, exit_x, colors="red", linewidth=1.5, linestyles="--", label=f"SL {sl:.2f}")
ax.hlines(tp, fill_x, exit_x, colors="green", linewidth=1.5, linestyles="--", label=f"TP {tp:.2f}")
ax.scatter([fill_x], [entry], s=140, c="blue", marker="o", zorder=5)
ax.scatter([exit_x], [sl], s=160, c="red", marker="v", zorder=5, label="Exit LOSS")

fh_x = mdates.date2num(datetime.fromtimestamp(fh_pre[1] / 1000, tz=timezone.utc).astimezone(MSK))
fl_x = mdates.date2num(datetime.fromtimestamp(fl_pre[1] / 1000, tz=timezone.utc).astimezone(MSK))
ax.scatter([fh_x], [candles_4h[fh_pre[0]][2]], s=240, marker="v", color="#d32f2f", zorder=6, edgecolor="black")
ax.scatter([fl_x], [candles_4h[fl_pre[0]][3]], s=240, marker="^", color="#388e3c", zorder=6, edgecolor="black")
ax.annotate("FH 4h", (fh_x, candles_4h[fh_pre[0]][2]), xytext=(8, 10), textcoords="offset points",
            fontsize=11, fontweight="bold", color="#d32f2f")
ax.annotate("FL 4h", (fl_x, candles_4h[fl_pre[0]][3]), xytext=(8, -16), textcoords="offset points",
            fontsize=11, fontweight="bold", color="#388e3c")

candles_1h_disp = aggregate(data, 60)
for idx, c in enumerate([c for c in candles_1h_disp if c1_ts_ms <= c[0] < c5_close_ms]):
    x = mdates.date2num(datetime.fromtimestamp((c[0] + 30 * 60_000) / 1000, tz=timezone.utc).astimezone(MSK))
    y = c[2] + (poi[1] - poi[0]) * 0.6
    ax.annotate(f"C{idx+1}", (x, y), ha="center", fontsize=10, fontweight="bold", color="#1a237e", zorder=6)

ax.set_title("2026-05-23 LONG i-RDRB+FVG (LOSS) — VWAP от ближайших pre-pattern 4h FH/FL", fontsize=13)
ax.set_ylabel("Price (USDT)")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M", tz=MSK))
ax.xaxis.set_major_locator(mdates.AutoDateLocator(tz=MSK, maxticks=10))
ax.grid(True, alpha=0.3)
ax.legend(loc="best", fontsize=9, framealpha=0.9)
plt.xticks(rotation=30)
plt.tight_layout()
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/fhfl_vwap_4h_2026-05-23_long.png"
plt.savefig(OUT, dpi=120, bbox_inches="tight")
plt.close()
print(f"\nSaved {OUT}")


def vwap_at(a, ms):
    idx = idx_at(ms) - 1
    return vwap(a, idx) if idx >= a else None


print("\n=== VWAP в ключевых точках ===")
for label, ms in [("C1 close", c1_ts_ms + MS_HOUR),
                  ("C5 close", c5_close_ms),
                  ("Fill", fill_ms),
                  ("Exit/SL", exit_ms)]:
    v_fh = vwap_at(fh_anchor, ms)
    v_fl = vwap_at(fl_anchor, ms)
    print(f"  {label:<10} ({fmt(ms)[5:]}):  VWAP-FH = {v_fh:.2f}  VWAP-FL = {v_fl:.2f}")
print(f"\n  Entry: {entry}, SL: {sl}, TP: {tp}")
