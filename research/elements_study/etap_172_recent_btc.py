"""Re-run etap_172 Bulkowski detectors on FRESH BTC 12h up to today,
print recent signals with full geometry, render an annotated chart.

Driver only — reuses detectors from etap_172_bulkowski_patterns.py (no dup logic).
Output:
  output/etap_172_recent_signals.csv  — recent signals (full geometry)
  output/etap_172_recent_btc.png      — annotated 12h chart
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("etap172", HERE / "etap_172_bulkowski_patterns.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

load_df = m.load_df
compose_from_base = m.compose_from_base
DETECTORS = m.DETECTORS
LOOKBACK = m.LOOKBACK
SWING_N = m.SWING_N


def _confirmed_swings_safe(highs, lows, start, end, n=2):
    """Bounds-safe clone of m.confirmed_swings: identical for every non-terminal
    bar, but never reads past the array end (baseline IndexError on last bar)."""
    sh, sl = [], []
    for j in range(max(start, n), min(end - n + 1, len(highs) - n)):
        hh = highs[j]
        if all(hh > highs[j - k] for k in range(1, n + 1)) and \
           all(hh > highs[j + k] for k in range(1, n + 1)):
            sh.append((j, hh))
        ll = lows[j]
        if all(ll < lows[j - k] for k in range(1, n + 1)) and \
           all(ll < lows[j + k] for k in range(1, n + 1)):
            sl.append((j, ll))
    return sh, sl


# detectors look up confirmed_swings in the module namespace at call time
m.confirmed_swings = _confirmed_swings_safe

RECENT_FROM = pd.Timestamp("2026-01-01", tz="UTC")   # window for "recent" listing
PLOT_BARS = 360                                       # ~180 days of 12h

print("Loading BTC 1h -> 12h ...")
df1h = load_df("BTCUSDT", "1h")
df12 = compose_from_base(df1h, "12h")
df12 = df12[df12.index >= pd.Timestamp("2025-01-01", tz="UTC")].copy()
df12 = df12.reset_index()
if "time" not in df12.columns:
    df12 = df12.rename(columns={df12.columns[0]: "time"})
print(f"  12h bars: {len(df12)}  range {df12['time'].iloc[0]} -> {df12['time'].iloc[-1]}")

# Run every detector on every bar
sigs = []
for i in range(LOOKBACK + SWING_N + 2, len(df12)):
    for det in DETECTORS:
        s = det(df12, i)
        if s is not None:
            s = dict(s)
            s["time"] = df12["time"].iloc[i]
            sigs.append(s)

recent = [s for s in sigs if s["time"] >= RECENT_FROM]
recent.sort(key=lambda s: s["time"])

print()
print("=" * 96)
print(f"RECENT SIGNALS since {RECENT_FROM.date()}  (total {len(recent)})")
print("=" * 96)
print(f"{'#':>2}  {'time':<16}  {'pattern':<14}  {'side':<5}  {'breakout':>10}  "
      f"{'low':>10}  {'high':>10}  {'neck':>10}  {'H%':>5}")
print("-" * 96)
for k, s in enumerate(recent, 1):
    print(f"{k:>2}  {str(s['time'])[:16]:<16}  {s['pattern']:<14}  {s['side']:<5}  "
          f"{s['breakout_price']:>10.1f}  {s['low_price']:>10.1f}  {s['high_price']:>10.1f}  "
          f"{s['neck_price']:>10.1f}  {s['height_pct']:>5.1f}")

# Save recent signals
out_dir = HERE / "output"
out_dir.mkdir(parents=True, exist_ok=True)
pd.DataFrame(recent).to_csv(out_dir / "etap_172_recent_signals.csv", index=False)
print()
print(f"Saved: {out_dir / 'etap_172_recent_signals.csv'}")

# ---- Plot ----
plot_df = df12.iloc[-PLOT_BARS:].reset_index(drop=True)
t = mdates.date2num(plot_df["time"].dt.tz_localize(None))
o = plot_df["open"].values; h = plot_df["high"].values
l = plot_df["low"].values; c = plot_df["close"].values

fig, ax = plt.subplots(figsize=(20, 10))
w = 0.30
for x, oo, hh, ll, cc in zip(t, o, h, l, c):
    col = "#26a69a" if cc >= oo else "#ef5350"
    ax.plot([x, x], [ll, hh], color=col, lw=0.6, zorder=1)
    ax.add_patch(plt.Rectangle((x - w / 2, min(oo, cc)), w, abs(cc - oo) + 1e-9,
                               color=col, zorder=2))

# Annotate signals that fall in the plotted window
plot_start = plot_df["time"].iloc[0]
COLOR = {"long": "#1b7837", "short": "#b2182b"}
y_lo, y_hi = l.min(), h.max()
pad = (y_hi - y_lo) * 0.06
for s in recent:
    if s["time"] < plot_start:
        continue
    x = mdates.date2num(pd.Timestamp(s["time"]).tz_localize(None))
    long = s["side"] == "long"
    col = COLOR[s["side"]]
    yb = s["breakout_price"]
    ytxt = (s["low_price"] - pad) if long else (s["high_price"] + pad)
    ax.scatter([x], [yb], marker="^" if long else "v", s=120, color=col, zorder=5,
               edgecolors="black", linewidths=0.5)
    ax.annotate(s["pattern"], (x, ytxt), color=col, fontsize=8, fontweight="bold",
                ha="center", va="top" if long else "bottom", rotation=90, zorder=6)

ax.xaxis.set_major_locator(mdates.AutoDateLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
fig.autofmt_xdate()
ax.set_title(f"BTCUSDT 12h — Bulkowski reversal signals (etap_172) | as of {df12['time'].iloc[-1].date()} | "
             f"{len([s for s in recent if s['time']>=plot_start])} signals shown", fontsize=13)
ax.set_ylabel("price")
ax.grid(True, alpha=0.2)
fig.tight_layout()
fig.savefig(out_dir / "etap_172_recent_btc.png", dpi=110)
print(f"Saved: {out_dir / 'etap_172_recent_btc.png'}")
print("last close:", c[-1], "at", plot_df["time"].iloc[-1])
