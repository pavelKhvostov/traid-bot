"""Chart 12h BTC за весь Andrey OOS window с E_pct ≥ 3% events.

Markers:
  ▼ красный (filled) — FH confirmed
  ▼ красный (open)   — FH not confirmed
  ▲ зелёный (filled) — FL confirmed
  ▲ зелёный (open)   — FL not confirmed

Подписи: E_pct % значение возле каждого маркера.
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
TF_12H_MS = 720 * 60_000

# Load CSV
df_m = pd.read_csv(Path.home()/"Desktop/basket_andrey_magnitude.csv")
df_m["dt"] = pd.to_datetime(df_m["dt"], utc=True)
df_m_3 = df_m[df_m["E_pct"]>=3.0].copy()
print(f"Events with E_pct ≥ 3%: {len(df_m_3)}")
print(f"  confirmed: {int(df_m_3['confirmed'].sum())} / not: {len(df_m_3) - int(df_m_3['confirmed'].sum())}")
print(f"  high (FH): {(df_m_3['direction']=='high').sum()}  low (FL): {(df_m_3['direction']=='low').sum()}")

# Period: OOS window
START = df_m["dt"].min() - pd.Timedelta(days=7)
END = df_m["dt"].max() + pd.Timedelta(days=7)
print(f"\nWindow: {START} → {END}")

CSV_PATH = Path.home()/"traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(START.timestamp()*1000)
END_MS = int(END.timestamp()*1000)

print("Loading 1m and aggregating 12h...")
rows=[]
with CSV_PATH.open() as f:
    rd=csv.reader(f); next(rd)
    for r in rd:
        ts=int(datetime.fromisoformat(r[0]).timestamp()*1000)
        if ts<START_MS: continue
        if ts>END_MS: break
        rows.append((ts,float(r[1]),float(r[2]),float(r[3]),float(r[4])))

def agg(rs, tf_ms):
    out=[]; cb=None; o=h=l=c=0.0
    for ts,oo,hh,ll,cc in rs:
        b=ts-(ts%tf_ms)
        if b!=cb:
            if cb is not None: out.append((cb,o,h,l,c))
            cb=b; o,h,l,c=oo,hh,ll,cc
        else: h=max(h,hh); l=min(l,ll); c=cc
    if cb is not None: out.append((cb,o,h,l,c))
    return out

bars12 = agg(rows, TF_12H_MS)
print(f"  12h bars: {len(bars12)}")

# Plot
fig, ax = plt.subplots(figsize=(28, 13))
BULL = '#01a648'; BEAR = '#131b1b'; DOJI = '#888'

def to_dt(ms): return datetime.fromtimestamp(ms/1000, MSK)
bar_w = (12/24) * 0.6

for b in bars12:
    t = to_dt(b[0] + TF_12H_MS//2)
    o, h, l, c = b[1], b[2], b[3], b[4]
    color_b = BULL if c > o else (BEAR if c < o else DOJI)
    ax.vlines(t, l, h, color=color_b, linewidth=0.8, zorder=2)
    ax.add_patch(plt.Rectangle((mdates.date2num(t) - bar_w/2, min(o, c)),
                               bar_w, max(abs(o - c), 0.01),
                               facecolor=color_b, edgecolor=color_b,
                               linewidth=0.8, zorder=2))

ts_to_bar = {b[0]: b for b in bars12}

# Plot E_pct ≥ 3% markers
for _, r in df_m_3.iterrows():
    ts = int(r["dt"].timestamp()*1000)
    bar = ts_to_bar.get(ts)
    if bar is None: continue
    t_center = to_dt(bar[0] + TF_12H_MS//2)
    high_p = bar[2]; low_p = bar[3]
    confirmed = bool(r["confirmed"])
    if r["direction"]=="high":
        col = "#d32f2f"
        fc = col if confirmed else "white"
        ax.scatter(t_center, high_p*1.005, marker="v", s=200, facecolor=fc, edgecolor=col, linewidth=1.5, zorder=8)
        # Label E_pct above
        label = f"{r['E_pct']:.1f}%"
        ax.annotate(label, (t_center, high_p*1.005), xytext=(0, 14), textcoords="offset points",
                    ha='center', fontsize=8, color=col, fontweight='bold',
                    bbox=dict(facecolor='white', edgecolor=col, lw=0.5, pad=1.5))
    else:
        col = "#01a648"
        fc = col if confirmed else "white"
        ax.scatter(t_center, low_p*0.995, marker="^", s=200, facecolor=fc, edgecolor=col, linewidth=1.5, zorder=8)
        label = f"{r['E_pct']:.1f}%"
        ax.annotate(label, (t_center, low_p*0.995), xytext=(0, -22), textcoords="offset points",
                    ha='center', fontsize=8, color=col, fontweight='bold',
                    bbox=dict(facecolor='white', edgecolor=col, lw=0.5, pad=1.5))

ax.xaxis.set_major_formatter(mdates.DateFormatter('%d-%m-%y', tz=MSK))
ax.xaxis.set_major_locator(mdates.MonthLocator())
ax.yaxis.tick_right()
ax.grid(True, alpha=0.15)

# Title
n_total = len(df_m_3)
n_conf = int(df_m_3["confirmed"].sum())
wr = n_conf/n_total*100
title = (f"BTC | 12h | Basket events E_pct ≥ 3% (Andrey magnitude) | "
         f"OOS 2025-01-05 → 2026-05-21 | "
         f"N={n_total} (FH={(df_m_3['direction']=='high').sum()}, FL={(df_m_3['direction']=='low').sum()}) | "
         f"confirmed={n_conf}/{n_total} = {wr:.1f}%")
fig.text(0.5, 0.97, title, ha='center', va='top', fontsize=11, fontweight='bold')

# Legend
from matplotlib.lines import Line2D
legend_elements = [
    Line2D([0],[0], marker='v', color='w', label='FH confirmed', markerfacecolor='#d32f2f', markeredgecolor='#d32f2f', markersize=13),
    Line2D([0],[0], marker='v', color='w', label='FH not confirmed', markerfacecolor='white', markeredgecolor='#d32f2f', markersize=13),
    Line2D([0],[0], marker='^', color='w', label='FL confirmed', markerfacecolor='#01a648', markeredgecolor='#01a648', markersize=13),
    Line2D([0],[0], marker='^', color='w', label='FL not confirmed', markerfacecolor='white', markeredgecolor='#01a648', markersize=13),
]
ax.legend(handles=legend_elements, loc='upper left', fontsize=10)

ax.set_xlim(to_dt(bars12[0][0]), to_dt(bars12[-1][0]+TF_12H_MS))
plt.tight_layout()
plt.subplots_adjust(top=0.93)
out = Path.home()/"Desktop/basket_e_pct_3plus_oos.png"
plt.savefig(out, dpi=140)
print(f"\nSaved: {out}")
