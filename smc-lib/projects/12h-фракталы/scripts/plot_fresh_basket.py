"""Fresh chart — BTC 12h + Basket (Stage 4 combined) + funding panel.

Window: 2026-02-01 → now.
Все markers tier-coloured per D-layer prediction:
    Premium  — большой red/green
    Strong   — средний
    Standard — маленький
    Weak     — точка
filled = Williams n=2 confirmed, hollow = not yet
"""
from __future__ import annotations
import pathlib
from datetime import datetime, timezone, timedelta
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import pandas as pd
import numpy as np
from _lib import load_12h, OUT_DIR, TF12

MSK = timezone(timedelta(hours=3))
WIN_START_MS = int(datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)

# Canon palette
BULL = "#01a648"
BEAR = "#131b1b"
DOJI = "#888"
CURRENT = "#c62828"

# Tier colours / sizes
TIER_STYLE = {
    "Premium":  {"size": 280, "lw": 2.5},
    "Strong":   {"size": 180, "lw": 2.0},
    "Standard": {"size": 100, "lw": 1.5},
    "Weak":     {"size": 50,  "lw": 1.0},
}
BAR_LW = 1.1
BAR_W_FRAC = 0.5

# ─── Load data ─────────────────────────────────────────────────
bars = load_12h()
mask = bars["t"] >= WIN_START_MS
t = bars["t"][mask]; o = bars["o"][mask]; h = bars["h"][mask]
l = bars["l"][mask]; c = bars["c"][mask]
print(f"12h bars in window: {len(t)}  "
      f"{datetime.fromtimestamp(t[0]/1000, MSK):%d-%m-%Y} → "
      f"{datetime.fromtimestamp(t[-1]/1000, MSK):%d-%m-%Y}")

combined = pd.read_parquet(OUT_DIR / "D_stage4_combined.parquet")
events = combined[combined["ts_ms"] >= WIN_START_MS].copy().reset_index(drop=True)
print(f"Basket events with tier: {len(events)}")

# ─── Chart ─────────────────────────────────────────────────────
def to_dt(ms): return datetime.fromtimestamp(int(ms)/1000, MSK)

fig, ax = plt.subplots(1, 1, figsize=(24, 12))
TF_HOURS = 12
bar_w = TF_HOURS / 24 * BAR_W_FRAC

# Candles
for i in range(len(t)):
    dt = to_dt(t[i])
    col = BULL if c[i] > o[i] else (BEAR if c[i] < o[i] else DOJI)
    ax.vlines(dt, l[i], h[i], color=col, linewidth=BAR_LW, zorder=3)
    ax.add_patch(plt.Rectangle((mdates.date2num(dt) - bar_w/2, min(o[i], c[i])),
                                bar_w, max(abs(o[i] - c[i]), 0.01),
                                facecolor=col, edgecolor=col,
                                linewidth=BAR_LW, zorder=3))

# Markers by tier
for _, ev in events.iterrows():
    dt = to_dt(ev["ts_ms"])
    idx = np.searchsorted(t, ev["ts_ms"])
    if idx >= len(t): continue
    direction = ev["direction"]
    tier = ev["tier"]
    confirmed = ev["confirmed"]
    style = TIER_STYLE.get(tier, TIER_STYLE["Weak"])

    if direction == "short":
        y = h[idx] + (h[idx] - l[idx]) * 0.18
        marker = "v"; color = "#c62828"
    else:
        y = l[idx] - (h[idx] - l[idx]) * 0.18
        marker = "^"; color = "#2e7d32"
    facecolor = color if confirmed else "white"
    ax.scatter([dt], [y], s=style["size"], marker=marker,
                edgecolors=color, facecolors=facecolor,
                linewidths=style["lw"], zorder=5)

    # Label tier letter
    if tier in ("Premium", "Strong"):
        ax.text(dt, y + (h[idx] - l[idx]) * 0.10 *
                 (1 if direction == "short" else -1),
                 tier[0],   # P / S
                 ha="center", va="center", fontsize=9,
                 color=color, fontweight="bold", zorder=6)

# X-ticks Mondays
today_dt = to_dt(t[-1])
start_dt = to_dt(t[0])
weekday = today_dt.weekday()
last_monday = (today_dt - timedelta(days=weekday)).replace(
    hour=0, minute=0, second=0, microsecond=0)
week_ticks = []
d = last_monday
while d >= start_dt:
    week_ticks.append(d); d -= timedelta(days=7)
week_ticks.reverse()
if today_dt.date() != last_monday.date():
    week_ticks.append(today_dt)
ax.set_xticks(week_ticks)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m", tz=MSK))
ax.grid(False)

# Right Y axis step 5000
ax.yaxis.tick_right()
ax.yaxis.set_label_position("right")
ax.yaxis.set_major_locator(MultipleLocator(5000))

current_price = c[-1]
ax.axhline(y=current_price, color=CURRENT, linewidth=0.9, linestyle=":", zorder=1)
fig.canvas.draw()
existing = list(ax.get_yticks())
filtered = [tt for tt in existing if abs(tt - current_price) > 2500]
all_ticks = sorted(set(filtered + [current_price]))
ax.set_yticks(all_ticks)
labels = []
for tt in all_ticks:
    if abs(tt - current_price) < 0.5:
        labels.append(f" {current_price:,.0f} ")
    else:
        labels.append(f"{int(tt):,}")
ax.set_yticklabels(labels)
for tick_label, tt in zip(ax.get_yticklabels(), all_ticks):
    if abs(tt - current_price) < 0.5:
        tick_label.set_color("white")
        tick_label.set_weight("bold")
        tick_label.set_fontsize(11)
        tick_label.set_bbox(dict(facecolor=CURRENT, edgecolor=CURRENT, pad=4))

fig.canvas.draw()
for tick_label, tick_dt in zip(ax.get_xticklabels(), week_ticks):
    if tick_dt == today_dt:
        tick_label.set_color("white"); tick_label.set_weight("bold")
        tick_label.set_fontsize(11)
        tick_label.set_bbox(dict(facecolor=CURRENT, edgecolor=CURRENT, pad=4))

# Title
n_total = len(events)
n_conf = int(events["confirmed"].sum())
wr = 100 * n_conf / n_total if n_total else 0
n_premium = (events["tier"] == "Premium").sum()
n_strong = (events["tier"] == "Strong").sum()
n_standard = (events["tier"] == "Standard").sum()
n_weak = (events["tier"] == "Weak").sum()
n_long = (events["direction"] == "long").sum()
n_short = (events["direction"] == "short").sum()

fig.text(0.5, 0.97,
         f"BTC  |  12h  |  Basket × D-layer  |  "
         f"{to_dt(WIN_START_MS).strftime('%d-%m-%Y')} → "
         f"{to_dt(t[-1]).strftime('%d-%m-%Y %H:%M MSK')}  |  "
         f"events: {n_total} ({n_short}▼ + {n_long}▲)  |  "
         f"confirmed: {n_conf}/{n_total} = {wr:.1f}%",
         ha="center", va="top", fontsize=13, fontweight="bold")

ax.text(0.005, 0.99,
        f"▼ SHORT (FH)  |  ▲ LONG (FL)\n"
        f"P = Premium ({n_premium})   "
        f"S = Strong ({n_strong})\n"
        f"·  Standard ({n_standard})   "
        f"·  Weak ({n_weak})\n"
        f"filled = confirmed   hollow = pending\n"
        f"размер ∝ tier",
        transform=ax.transAxes, ha="left", va="top", fontsize=9,
        bbox=dict(facecolor="white", edgecolor="#888", alpha=0.9, pad=6),
        zorder=10)

plt.subplots_adjust(left=0.02, right=0.96, top=0.94, bottom=0.05)
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/basket_fresh_2026-02-01.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=140)
print(f"\nSaved: {out}")
