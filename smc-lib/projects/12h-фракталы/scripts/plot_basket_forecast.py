"""Chart: BTC 12h + Basket fractal predictions с 2026-02-01.
Bottom sub-panel: Binance BTC funding rate (per-8h, in bps).

Canon style per ~/smc-lib/chart_format.md:
  - BULL #01a648, BEAR #131b1b, DOJI #888
  - right Y axis (step 1000), Monday ticks MSK
  - current price red dotted horizontal + boxed tick
  - markers: ▼ red FH (short pivot), ▲ green FL (long pivot)
  - marker size by n_confluent (more confluence = bigger)
  - filled = confirmed Williams n=2, hollow = not yet confirmed
  - funding bars: BEAR-red for positive (longs pay), BULL-green for negative
"""
from __future__ import annotations
import pathlib
from datetime import datetime, timezone, timedelta
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import pandas as pd
import numpy as np
from _lib import load_12h, OUT_DIR, load_baseline, match_pivots, TF12

# ─── Window ────────────────────────────────────────────────────
MSK = timezone(timedelta(hours=3))
WIN_START_MS = int(datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)

# ─── Style (canon chart_format.md) ─────────────────────────────
BULL = "#01a648"
BEAR = "#131b1b"
DOJI = "#888"
CURRENT = "#c62828"
FH_COLOR = "#c62828"  # SHORT (top pivot)
FL_COLOR = "#2e7d32"  # LONG (bottom pivot)
BAR_GAP = 0.5
BAR_WIDTH_FRAC = 1.0 - BAR_GAP
BAR_LW = 1.1

# ─── Load 12h bars in window ──────────────────────────────────
bars = load_12h()
mask = bars["t"] >= WIN_START_MS
t = bars["t"][mask]; o = bars["o"][mask]; h = bars["h"][mask]
l = bars["l"][mask]; c = bars["c"][mask]
print(f"12h bars in window: {len(t)}  ({datetime.fromtimestamp(t[0]/1000, MSK):%d-%m-%Y} → "
      f"{datetime.fromtimestamp(t[-1]/1000, MSK):%d-%m-%Y})")

# ─── Load events + restrict to Basket (A4 baseline matched) ────
events_all = pd.read_parquet(OUT_DIR / "events_with_funding_confluent.parquet")
baseline = load_baseline()
pmap = match_pivots(bars, baseline)

# Keep only events that match a baseline pivot (real Basket)
def in_basket(row):
    return (int(row["bar_idx"]), row["direction"]) in pmap

events_all["in_basket"] = events_all.apply(in_basket, axis=1)
events = events_all[events_all["in_basket"] & (events_all["ts_ms"] >= WIN_START_MS)].copy()

def is_confirmed(row):
    k = int(row["bar_idx"]); d = row["direction"]
    return pmap[(k, d)][0]
events["confirmed"] = events.apply(is_confirmed, axis=1)

print(f"All events in window: {(events_all['ts_ms'] >= WIN_START_MS).sum()}")
print(f"Basket-matched in window: {len(events)}")

# ─── Chart ─────────────────────────────────────────────────────
def to_dt(ms): return datetime.fromtimestamp(int(ms)/1000, MSK)

fig, (ax, ax_f) = plt.subplots(2, 1, figsize=(24, 15),
                                 gridspec_kw={"height_ratios": [4, 1]},
                                 sharex=True)
TF_HOURS = 12
bar_w = TF_HOURS / 24 * BAR_WIDTH_FRAC

# Candles
for i in range(len(t)):
    dt = to_dt(t[i])
    o_, h_, l_, c_ = o[i], h[i], l[i], c[i]
    col = BULL if c_ > o_ else (BEAR if c_ < o_ else DOJI)
    ax.vlines(dt, l_, h_, color=col, linewidth=BAR_LW, zorder=3)
    ax.add_patch(plt.Rectangle((mdates.date2num(dt) - bar_w/2, min(o_, c_)),
                                bar_w, max(abs(o_ - c_), 0.01),
                                facecolor=col, edgecolor=col, linewidth=BAR_LW, zorder=3))

# ─── Markers: ▼ FH SHORT (top), ▲ FL LONG (bottom) ─────────────
def marker_size(n_confluent):
    return 80 + 40 * (n_confluent - 1)  # base 80, +40 per extra confluence

for _, ev in events.iterrows():
    dt = to_dt(ev["ts_ms"])
    # Find bar index in window
    idx = np.searchsorted(t, ev["ts_ms"])
    if idx >= len(t): continue
    if ev["direction"] == "short":
        y = h[idx] + (h[idx] - l[idx]) * 0.15  # above high
        marker = "v"; color = FH_COLOR
    else:
        y = l[idx] - (h[idx] - l[idx]) * 0.15  # below low
        marker = "^"; color = FL_COLOR
    facecolor = color if ev["confirmed"] else "white"
    ax.scatter([dt], [y], s=marker_size(ev["n_confluent"]), marker=marker,
                edgecolors=color, facecolors=facecolor, linewidths=2, zorder=5)
    # Label: n_confluent
    ax.text(dt, y + (h[idx] - l[idx]) * 0.18 * (1 if ev["direction"] == "short" else -1),
            str(ev["n_confluent"]),
            ha="center", va="center", fontsize=7, color=color, fontweight="bold", zorder=6)

# ─── X-ticks: Mondays ──────────────────────────────────────────
today_dt = to_dt(t[-1])
start_dt = to_dt(t[0])
weekday = today_dt.weekday()
last_monday = (today_dt - timedelta(days=weekday)).replace(hour=0, minute=0, second=0, microsecond=0)
week_ticks = []
d = last_monday
while d >= start_dt:
    week_ticks.append(d)
    d -= timedelta(days=7)
week_ticks.reverse()
if today_dt.date() != last_monday.date():
    week_ticks.append(today_dt)
ax.set_xticks(week_ticks)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m", tz=MSK))
ax.grid(False)

# ─── Y-axis right, step 5000 ──────────────────────────────────
ax.yaxis.tick_right()
ax.yaxis.set_label_position("right")
ax.yaxis.set_major_locator(MultipleLocator(5000))

# Current price (last close)
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

# Today's Monday tick highlight
fig.canvas.draw()
for tick_label, tick_dt in zip(ax.get_xticklabels(), week_ticks):
    if tick_dt == today_dt:
        tick_label.set_color("white")
        tick_label.set_weight("bold")
        tick_label.set_fontsize(11)
        tick_label.set_bbox(dict(facecolor=CURRENT, edgecolor=CURRENT, pad=4))

# ─── Title ─────────────────────────────────────────────────────
n_total = len(events)
n_conf = int(events["confirmed"].sum())
wr = 100 * n_conf / n_total if n_total else 0
n_short = int((events["direction"] == "short").sum())
n_long = int((events["direction"] == "long").sum())

fig.text(0.5, 0.97,
         f"BTC  |  12h  |  Basket fractal predictions  |  "
         f"{to_dt(WIN_START_MS).strftime('%d-%m-%Y')} → {to_dt(t[-1]).strftime('%d-%m-%Y %H:%M MSK')}  |  "
         f"events: {n_total} ({n_short}▼ + {n_long}▲)  |  confirmed: {n_conf}/{n_total} = {wr:.1f}%",
         ha="center", va="top", fontsize=13, fontweight="bold")

# Legend (compact)
ax.text(0.01, 0.99,
        "▼ SHORT (FH pivot)  |  ▲ LONG (FL pivot)\n"
        "filled = Williams n=2 confirmed   |   hollow = not yet confirmed\n"
        "число = n_confluent (1-7 B-блоков сработало)\n"
        "размер маркера ∝ n_confluent",
        transform=ax.transAxes, ha="left", va="top", fontsize=9,
        bbox=dict(facecolor="white", edgecolor="#888", alpha=0.9, pad=6),
        zorder=10)

# ─── Funding rate panel (bottom) ───────────────────────────────
funding_cache = pathlib.Path.home() / "Desktop/btc_funding_binance.parquet"
fdf = pd.read_parquet(funding_cache)
fdf = fdf.sort_values("fundingTime").reset_index(drop=True)
fdf_win = fdf[(fdf["fundingTime"] >= WIN_START_MS)
              & (fdf["fundingTime"] <= int(t[-1]) + TF12)].copy()
fdf_win["bps"] = fdf_win["fundingRate"] * 10_000
fdf_win["dt"] = pd.to_datetime(fdf_win["fundingTime"], unit="ms", utc=True).dt.tz_convert(MSK)

# Bar colors: positive (longs pay shorts) = BEAR-red, negative = BULL-green
fund_bar_w = 8 / 24 * BAR_WIDTH_FRAC  # 8h bar width
for _, fr in fdf_win.iterrows():
    bps = fr["bps"]
    col = BEAR if bps > 0 else BULL
    # Highlight extremes (|bps| ≥ 3) с насыщенным цветом, обычные — приглушенный
    extreme = abs(bps) >= 3
    alpha = 1.0 if extreme else 0.55
    ax_f.bar(fr["dt"], bps, width=fund_bar_w, color=col, alpha=alpha,
             edgecolor=col, linewidth=0.8 if extreme else 0.4, zorder=3)

# Zero line + extreme thresholds
ax_f.axhline(0, color="#888", linewidth=0.7, zorder=1)
ax_f.axhline(3, color="#888", linewidth=0.5, linestyle="--", alpha=0.5, zorder=1)
ax_f.axhline(-3, color="#888", linewidth=0.5, linestyle="--", alpha=0.5, zorder=1)
ax_f.text(start_dt, 3, " extreme +3 bps ", fontsize=7, va="center", color="#666")
ax_f.text(start_dt, -3, " extreme −3 bps ", fontsize=7, va="center", color="#666")

ax_f.yaxis.tick_right()
ax_f.yaxis.set_label_position("right")
ax_f.set_ylabel("Funding bps (per-8h)", fontsize=10, rotation=270, labelpad=18)
ax_f.grid(False)
ax_f.set_axisbelow(True)

# Stats annotation
mean_f = fdf_win["bps"].mean()
max_f = fdf_win["bps"].max()
min_f = fdf_win["bps"].min()
n_extreme = (fdf_win["bps"].abs() >= 3).sum()
ax_f.text(0.01, 0.97,
          f"Funding stats:  mean = {mean_f:+.2f} bps   "
          f"max = {max_f:+.1f}   min = {min_f:+.1f}   "
          f"extreme (|≥3|): {n_extreme} of {len(fdf_win)}",
          transform=ax_f.transAxes, ha="left", va="top", fontsize=9,
          bbox=dict(facecolor="white", edgecolor="#888", alpha=0.9, pad=4))

plt.subplots_adjust(left=0.02, right=0.96, top=0.94, bottom=0.05, hspace=0.05)
out = pathlib.Path.home() / f"Desktop/i-rdrb-charts/basket_v3_forecast_funding_2026-02-01_to_now.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=140)
print(f"\nSaved: {out}")
