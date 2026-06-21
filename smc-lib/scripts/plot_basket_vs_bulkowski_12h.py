"""12h chart of last 2 months — overlay Vadim C1-C7 basket vs Andrey Bulkowski.

Vadim basket markers (in_basket=True):
  ▲ green at low: LL confirmed
  ▽ light-green: LL not confirmed
  ▼ red at high: HH confirmed
  △ light-red: HH not confirmed

Andrey Bulkowski markers (at signal close = time + 12h):
  ● green (long side)
  ● red (short side)
  size by pattern category, label = pattern name

Saved: ~/Desktop/basket_vs_bulkowski_12h_2mo.png
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

MSK = timezone(timedelta(hours=3))
MS_M = 60_000
TF_MIN = 720  # 12h
TF_MS = TF_MIN * MS_M
CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
DAYS = 90
END_DT = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
START_DT = END_DT - timedelta(days=DAYS)

# === Load 1m and aggregate ===
print("Loading 1m + aggregating 12h...")
rows = []
with CSV_PATH.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        ts = int(t.timestamp() * 1000)
        if ts < int(START_DT.timestamp()*1000) - TF_MS: continue
        if ts >= int(END_DT.timestamp()*1000): break
        rows.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))

def agg(d, tf_ms):
    out = []; cb = None; o = h = l = c = v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out

bars12 = agg(rows, TF_MS)
last_close = rows[-1][4]
print(f"  12h bars: {len(bars12)}")

# === Load Vadim basket ===
df_b = pd.read_parquet(Path.home() / "Desktop" / "pred12h_baseline_c1c7.parquet")
df_b = df_b[df_b["in_basket"] == True].copy()
df_b["pivot_open_ts"] = pd.to_datetime(df_b["pivot_open_ts_ms"], unit="ms", utc=True)
df_b_win = df_b[(df_b["pivot_open_ts"] >= START_DT) & (df_b["pivot_open_ts"] < END_DT)].copy()
print(f"  Vadim basket in window: {len(df_b_win)}")

# === Load Andrey Bulkowski ===
df_a = pd.read_csv(Path.home() / "Desktop" / "etap_172_signals.csv", parse_dates=["time"])
df_a["close_ts"] = df_a["time"] + pd.Timedelta(hours=12)
if df_a["close_ts"].dt.tz is None:
    df_a["close_ts"] = df_a["close_ts"].dt.tz_localize("UTC")
df_a_win = df_a[(df_a["close_ts"] >= START_DT) & (df_a["close_ts"] < END_DT)].copy()
print(f"  Andrey Bulkowski in window: {len(df_a_win)}")

# === Plot ===
BULL = '#01a648'; BEAR = '#131b1b'; DOJI = '#888'
CURRENT = '#c62828'

def to_dt(ms): return datetime.fromtimestamp(ms/1000, MSK)

fig, ax = plt.subplots(figsize=(24, 12))

# 12h candles
bar_w = (TF_MIN/60)/24 * 0.6
for b in bars12:
    t = to_dt(b[0] + TF_MS//2)
    o, h, l, c = b[1], b[2], b[3], b[4]
    color_b = BULL if c > o else (BEAR if c < o else DOJI)
    ax.vlines(t, l, h, color=color_b, linewidth=1.0, zorder=2)
    ax.add_patch(plt.Rectangle((mdates.date2num(t) - bar_w/2, min(o, c)),
                               bar_w, max(abs(o - c), 0.01),
                               facecolor=color_b, edgecolor=color_b,
                               linewidth=1.0, zorder=2))

# === Vadim basket markers — at pivot bar CENTER (open + 6h), placed at low/high ===
for _, r in df_b_win.iterrows():
    bar = next((b for b in bars12 if b[0] == r["pivot_open_ts_ms"]), None)
    if bar is None: continue
    o, h, l, c = bar[1], bar[2], bar[3], bar[4]
    bar_center = to_dt(bar[0] + TF_MS // 2)
    if r["direction"] == "high":
        ax.scatter(bar_center, h * 1.005, marker="v", s=150, color="#d32f2f",
                   edgecolors='black', linewidths=0.8, zorder=8)
    else:
        ax.scatter(bar_center, l * 0.995, marker="^", s=150, color="#01a648",
                   edgecolors='black', linewidths=0.8, zorder=8)

# === Andrey Bulkowski markers — at signal bar CENTER ===
for _, r in df_a_win.iterrows():
    target_ms = int(r["close_ts"].timestamp() * 1000) - TF_MS  # bar open = close - 12h
    bar = next((b for b in bars12 if b[0] == target_ms), None)
    if bar is None: continue
    o, h, l, c = bar[1], bar[2], bar[3], bar[4]
    bar_center = to_dt(bar[0] + TF_MS // 2)
    col = "#1976d2" if r["side"] == "long" else "#f57c00"
    ax.scatter(bar_center, c, marker="o", s=180, color=col,
               edgecolors='white', linewidths=1.5, zorder=7, alpha=0.85)
    ax.annotate(r["pattern"], (bar_center, c), xytext=(0, 14 if r["side"]=="long" else -22),
                textcoords="offset points",
                ha='center', fontsize=7, color=col, fontweight='bold',
                bbox=dict(facecolor='white', edgecolor='none', alpha=0.7, pad=1))

# Current price
ax.axhline(y=last_close, color=CURRENT, linewidth=0.9, linestyle=':', alpha=1.0, zorder=3)

# Format
ax.xaxis.set_major_formatter(mdates.DateFormatter('%d-%m', tz=MSK))
ax.yaxis.tick_right()
ax.yaxis.set_label_position('right')
ax.grid(True, alpha=0.15)

# Title
n_vad = len(df_b_win)
n_and = len(df_a_win)
title = (f"BTC | 12h | {END_DT.strftime('%d-%m-%Y %H:%M')} UTC | last {DAYS}d  "
         f"|  Vadim C1-C7 basket: {n_vad}  |  Andrey Bulkowski: {n_and}")
fig.text(0.5, 0.97, title, ha='center', va='top', fontsize=12, fontweight='bold')

# Legend
from matplotlib.lines import Line2D
legend_elements = [
    Line2D([0], [0], marker='^', color='w', label='Vadim LL (low pivot)', markerfacecolor='#01a648', markersize=12, markeredgecolor='black'),
    Line2D([0], [0], marker='v', color='w', label='Vadim HH (high pivot)', markerfacecolor='#d32f2f', markersize=12, markeredgecolor='black'),
    Line2D([0], [0], marker='o', color='w', label='Andrey long', markerfacecolor='#1976d2', markersize=10, markeredgecolor='white'),
    Line2D([0], [0], marker='o', color='w', label='Andrey short', markerfacecolor='#f57c00', markersize=10, markeredgecolor='white'),
]
ax.legend(handles=legend_elements, loc='upper left', fontsize=9, framealpha=0.9)

ax.set_xlim(START_DT.astimezone(MSK), END_DT.astimezone(MSK))
plt.tight_layout()
plt.subplots_adjust(top=0.94)
out = Path.home() / "Desktop" / "basket_vs_bulkowski_12h_3mo.png"
plt.savefig(out, dpi=140)
print(f"\n→ Saved: {out}")
