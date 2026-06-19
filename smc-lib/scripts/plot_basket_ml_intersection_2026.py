"""Chart 12h BTC за 2026 год: где basket AND Andrey ML предсказывают.

Intersection events: basket pivot signal + Andrey ML signal (p_main ≥ 0.3).
Markers с label: p_main + tier + E_pct.
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

# Load basket-181 with E_pct
df_m = pd.read_csv(Path.home()/"Desktop/basket_andrey_magnitude.csv")
df_m["dt"] = pd.to_datetime(df_m["dt"], utc=True)
df_m["key"] = df_m["ts"].astype(str)+"_"+df_m["direction"]

# Load Andrey signals_caught
sig = pd.read_csv(Path.home()/"Desktop/etap_173_signals_caught.csv", parse_dates=["time_utc"])
sig["ts_ms"] = sig["time_utc"].apply(lambda t: int(t.timestamp()*1000))
sig["dir_us"] = sig["side"].map({"SHORT":"high","LONG":"low"})
sig["key"] = sig["ts_ms"].astype(str)+"_"+sig["dir_us"]
sig_sub = sig[["key","p_main","tier"]]

# Merge: basket + ML signal
df_join = df_m.merge(sig_sub, on="key", how="inner")
print(f"Intersection (basket + ML p≥0.3): {len(df_join)}")

# Filter 2026 year
df_2026 = df_join[df_join["dt"]>=pd.Timestamp("2026-01-01",tz="UTC")].copy()
df_2026 = df_2026[df_2026["dt"]<=pd.Timestamp("2026-12-31",tz="UTC")]
print(f"In 2026 year: {len(df_2026)}")
print(f"  confirmed: {int(df_2026['confirmed'].sum())}")

# Load 1m + aggregate 12h for chart window
START = pd.Timestamp("2026-01-01", tz="UTC") - pd.Timedelta(days=2)
END = pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=2)  # включаем актуальный бар
CSV_PATH = Path.home()/"traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
rows=[]
with CSV_PATH.open() as f:
    rd=csv.reader(f); next(rd)
    for r in rd:
        ts=int(datetime.fromisoformat(r[0]).timestamp()*1000)
        if ts<int(START.timestamp()*1000): continue
        if ts>int(END.timestamp()*1000): break
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
print(f"12h bars: {len(bars12)}")

# Plot
fig, ax = plt.subplots(figsize=(24, 13))
BULL = '#01a648'; BEAR = '#131b1b'; DOJI = '#888'
def to_dt(ms): return datetime.fromtimestamp(ms/1000, MSK)
bar_w = (12/24) * 0.6

for b in bars12:
    t = to_dt(b[0] + TF_12H_MS//2)
    o,h,l,c = b[1],b[2],b[3],b[4]
    color_b = BULL if c>o else (BEAR if c<o else DOJI)
    ax.vlines(t, l, h, color=color_b, linewidth=1.0, zorder=2)
    ax.add_patch(plt.Rectangle((mdates.date2num(t)-bar_w/2, min(o,c)),
                               bar_w, max(abs(o-c), 0.01),
                               facecolor=color_b, edgecolor=color_b, linewidth=1.0, zorder=2))

ts_to_bar = {b[0]: b for b in bars12}

# Tier colors
TIER_COLORS = {
    "A_sniper": "#1a237e",  # deep blue (strongest)
    "B_strong": "#283593",
    "C_signal": "#3949ab",
    "D_watch":  "#7e57c2",
    "E_weak":   "#9575cd",
    "F_min":    "#b39ddb",
}

# Plot intersection markers
for _, r in df_2026.iterrows():
    ts = int(r["ts"])
    bar = ts_to_bar.get(ts)
    if bar is None: continue
    t_center = to_dt(bar[0] + TF_12H_MS//2)
    high_p = bar[2]; low_p = bar[3]
    confirmed = bool(r["confirmed"])
    is_high = r["direction"]=="high"

    if is_high:
        col_marker = "#d32f2f"
        fc = col_marker if confirmed else "white"
        ax.scatter(t_center, high_p*1.005, marker="v", s=260,
                   facecolor=fc, edgecolor=col_marker, linewidth=1.8, zorder=8)
        label = f"p={r['p_main']:.2f}\nE={r['E_pct']:.1f}%\n{r['tier'][0]}"
        ax.annotate(label, (t_center, high_p*1.005), xytext=(0, 18),
                    textcoords="offset points", ha='center', fontsize=8.5,
                    color=col_marker, fontweight='bold',
                    bbox=dict(facecolor='white', edgecolor=col_marker, lw=0.7, pad=2))
    else:
        col_marker = "#01a648"
        fc = col_marker if confirmed else "white"
        ax.scatter(t_center, low_p*0.995, marker="^", s=260,
                   facecolor=fc, edgecolor=col_marker, linewidth=1.8, zorder=8)
        label = f"p={r['p_main']:.2f}\nE={r['E_pct']:.1f}%\n{r['tier'][0]}"
        ax.annotate(label, (t_center, low_p*0.995), xytext=(0, -32),
                    textcoords="offset points", ha='center', fontsize=8.5,
                    color=col_marker, fontweight='bold',
                    bbox=dict(facecolor='white', edgecolor=col_marker, lw=0.7, pad=2))

ax.xaxis.set_major_formatter(mdates.DateFormatter('%d-%m', tz=MSK))
ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
ax.yaxis.tick_right()
ax.grid(True, alpha=0.15)

n_total = len(df_2026)
n_conf = int(df_2026["confirmed"].sum())
n_fh = (df_2026["direction"]=="high").sum()
n_fl = (df_2026["direction"]=="low").sum()
title = (f"BTC | 12h | 2026 год | Basket ∩ Andrey ML (p≥0.3) — оба сигнала together  |  "
         f"N={n_total} (FH={n_fh}, FL={n_fl})  |  "
         f"confirmed={n_conf}/{n_total} = {n_conf/n_total*100:.1f}% если есть"
         if n_total else "BTC | 12h | 2026 | NO intersection events")
fig.text(0.5, 0.97, title, ha='center', va='top', fontsize=12, fontweight='bold')

# Legend
from matplotlib.lines import Line2D
legend = [
    Line2D([0],[0], marker='v', color='w', label='FH conf', markerfacecolor='#d32f2f', markeredgecolor='#d32f2f', markersize=14),
    Line2D([0],[0], marker='v', color='w', label='FH not conf', markerfacecolor='white', markeredgecolor='#d32f2f', markersize=14),
    Line2D([0],[0], marker='^', color='w', label='FL conf', markerfacecolor='#01a648', markeredgecolor='#01a648', markersize=14),
    Line2D([0],[0], marker='^', color='w', label='FL not conf', markerfacecolor='white', markeredgecolor='#01a648', markersize=14),
]
ax.legend(handles=legend, loc='upper left', fontsize=10,
          title="Label: p=p_main (Andrey ML)  E=E_pct (предсказанная амплитуда)  letter=tier (A=sniper, B=strong, ...)")

if len(bars12)>0:
    ax.set_xlim(to_dt(bars12[0][0]), to_dt(bars12[-1][0]+TF_12H_MS))

plt.tight_layout()
plt.subplots_adjust(top=0.93)
out = Path.home()/"Desktop/basket_ml_intersection_2026.png"
plt.savefig(out, dpi=140)
print(f"\nSaved: {out}")
