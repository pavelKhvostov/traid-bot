"""Plot SMA-8 and HMA-8 evolution hourly through 08-06 (1d TF).

For each hour h in 00..23 UTC:
  - Take all closed 1d bars (up to 07-06 close)
  - Add current 1m close at h:00 as partial-bar close (running)
  - Compute SMA-8 and HMA-8 from this series
"""
from __future__ import annotations
import csv
import pathlib
import sys
from datetime import datetime, timezone, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

sys.path.insert(0, "/Users/vadim/smc-lib/projects/ob-vc/ml_v3")
from features._common import aggregate_all_tfs, hma_np, TF_SPECS


BTC_CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/btc_ma_hourly_08_06.png"
MSK = timezone(timedelta(hours=3))
L = 8


def load_1m():
    rows = []
    with BTC_CSV.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
            rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return np.array(rows, dtype=np.float64)


rows_1m = load_1m()
bars = aggregate_all_tfs(rows_1m)
bar_1d = bars["1d"]
ts_1d = bar_1d[:, 0].astype(np.int64)
close_1d = bar_1d[:, 4]
ts_1m = rows_1m[:, 0].astype(np.int64)
close_1m = rows_1m[:, 4]
TF_MS_1D = TF_SPECS["1d"]

# Anchor: 08-06 = 2026-06-08 (UTC)
day_open_ms = int(datetime(2026, 6, 8, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
day_close_ms = day_open_ms + TF_MS_1D

# Find indices of closed 1d bars up to (but not including) 08-06
cutoff_for_closed = day_open_ms - 1
closed_idx = int(np.searchsorted(ts_1d, day_open_ms, side="left") - 1)
print(f"Last closed 1d bar idx: {closed_idx}")
print(f"  open: {datetime.fromtimestamp(ts_1d[closed_idx]/1000, timezone.utc):%Y-%m-%d}")
print(f"  close: ${close_1d[closed_idx]:,.1f}")

# Hourly snapshots through 08-06 (00:00 → 23:00 UTC)
hours = list(range(24))
times_ms = [day_open_ms + h * 3600 * 1000 for h in hours]
times_dt_msk = [datetime.fromtimestamp(t / 1000, MSK) for t in times_ms]

partial_closes = []
sma_8 = []
hma_8 = []

for moment_ms in times_ms:
    # current 1m close at moment
    i_1m = int(np.searchsorted(ts_1m, moment_ms, side="right") - 1)
    if i_1m < 0:
        partial_closes.append(np.nan); sma_8.append(np.nan); hma_8.append(np.nan)
        continue
    cur_close = close_1m[i_1m]
    partial_closes.append(cur_close)

    # Series: closed 1d closes + current partial
    series = np.concatenate([close_1d[:closed_idx+1], [cur_close]])

    # SMA-8 = mean of last 8 closes in series
    if len(series) >= L:
        sma_val = float(np.mean(series[-L:]))
    else:
        sma_val = np.nan
    sma_8.append(sma_val)

    # HMA-8
    hma_arr = hma_np(series, L)
    hma_8.append(float(hma_arr[-1]) if not np.isnan(hma_arr[-1]) else np.nan)

# Reference: HMA-8 and SMA-8 at 07-06 close and 08-06 close (true closes, no partial)
hma_07_close = float(hma_np(close_1d[:closed_idx+1], L)[-1])
sma_07_close = float(np.mean(close_1d[closed_idx-L+1:closed_idx+1]))
hma_08_close = float(hma_np(close_1d[:closed_idx+2], L)[-1])
sma_08_close = float(np.mean(close_1d[closed_idx-L+2:closed_idx+2]))
true_close_08 = float(close_1d[closed_idx+1])

print(f"\nAt 07-06 close: HMA-8=${hma_07_close:,.1f}, SMA-8=${sma_07_close:,.1f}")
print(f"At 08-06 close: HMA-8=${hma_08_close:,.1f}, SMA-8=${sma_08_close:,.1f}, true close=${true_close_08:,.1f}")

# ─── PLOT ──────────
fig, ax = plt.subplots(figsize=(20, 11))

# BTC partial price hourly
ax.plot(times_dt_msk, partial_closes, color="#222", lw=1.5, marker="o", markersize=5,
        label="BTC цена (1m close на момент часа)", zorder=4)

# SMA-8 evolution
ax.plot(times_dt_msk, sma_8, color="#e67e22", lw=2.5, marker="s", markersize=6,
        label=f"SMA-{L} (intraday partial-bar)", zorder=3)

# HMA-8 evolution
ax.plot(times_dt_msk, hma_8, color="#27ae60", lw=2.5, marker="^", markersize=7,
        label=f"HMA-{L} (intraday partial-bar)", zorder=3)

# Reference lines
ax.axhline(hma_07_close, color="#27ae60", ls="--", lw=1.2, alpha=0.5)
ax.text(times_dt_msk[0], hma_07_close, f"  HMA-{L} на 07-06 close = ${hma_07_close:,.0f}  ",
        va="bottom", ha="left", fontsize=10, color="#1b6a3a", fontweight="bold",
        bbox=dict(facecolor="white", edgecolor="#27ae60", lw=1, boxstyle="round,pad=0.2"))

ax.axhline(hma_08_close, color="#27ae60", ls=":", lw=1.5, alpha=0.7)
ax.text(times_dt_msk[-1], hma_08_close, f"  HMA-{L} на 08-06 close = ${hma_08_close:,.0f}",
        va="bottom", ha="right", fontsize=10, color="#1b6a3a", fontweight="bold",
        bbox=dict(facecolor="white", edgecolor="#27ae60", lw=1, boxstyle="round,pad=0.2"))

ax.axhline(sma_07_close, color="#e67e22", ls="--", lw=1.2, alpha=0.5)
ax.axhline(sma_08_close, color="#e67e22", ls=":", lw=1.5, alpha=0.7)

# Annotation at 14:35 MSK (= 11:35 UTC)
moment_1435 = datetime(2026, 6, 8, 14, 35, tzinfo=MSK)
moment_1435_ms = int(moment_1435.timestamp() * 1000)
i_1m_1435 = int(np.searchsorted(ts_1m, moment_1435_ms, side="right") - 1)
price_1435 = float(close_1m[i_1m_1435])
series_1435 = np.concatenate([close_1d[:closed_idx+1], [price_1435]])
hma_1435 = float(hma_np(series_1435, L)[-1])
sma_1435 = float(np.mean(series_1435[-L:]))

ax.axvline(moment_1435, color="#7e3c9e", ls=":", lw=1.5, alpha=0.6)
ax.text(moment_1435, ax.get_ylim()[1] if False else max(max(partial_closes), max(hma_8)) + 100,
        f"  14:35 МСК:\n  BTC=${price_1435:,.0f}\n  HMA-{L}=${hma_1435:,.0f}\n  SMA-{L}=${sma_1435:,.0f}",
        va="top", ha="left", fontsize=10, color="#4a2364", fontweight="bold",
        bbox=dict(facecolor="#f3e5f5", edgecolor="#7e3c9e", lw=1.3, boxstyle="round,pad=0.4"))

ax.set_xlabel("Время МСК (08-06)", fontsize=12)
ax.set_ylabel("BTC цена / MA значение, USD", fontsize=12)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:00", tz=MSK))
ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
ax.grid(alpha=0.3)
ax.legend(loc="upper left", fontsize=11, framealpha=0.95)

fig.suptitle(
    f"BTC SMA-{L} и HMA-{L} на 1d TF — движение каждый час 08-06 (UTC)\n"
    f"Метод: closes закрытых 1d баров + partial-bar close на момент часа",
    fontsize=14, fontweight="bold", y=0.99)

plt.subplots_adjust(left=0.05, right=0.97, top=0.93, bottom=0.07)
plt.savefig(OUT, dpi=130, bbox_inches="tight")
print(f"\nSaved: {OUT}")

# Print table
print(f"\n{'Час МСК':<10} {'BTC':>10} {'SMA-8':>10} {'HMA-8':>10}")
print("─" * 45)
for dt, pc, sma, hma in zip(times_dt_msk, partial_closes, sma_8, hma_8):
    print(f"{dt.strftime('%H:%M'):<10} ${pc:>9,.0f} ${sma:>9,.0f} ${hma:>9,.0f}")
