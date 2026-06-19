"""Chart 2026-02-05 .. 2026-05-06 — BTC D candles + amplified maxV force bands.

Each D maxV event in the period drawn as horizontal Gaussian band at its LEVEL,
with thickness/opacity proportional to amplified force.

amplified = exp(-((p-L)/σ)²) × W_pos × W_age   (peak at LEVEL)
"""
from __future__ import annotations
import math, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.colors import LinearSegmentedColormap

MSK = timezone(timedelta(hours=3))
MS_M = 60_000

CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"

DATE_FROM = "2026-02-05"
DATE_TO = "2026-05-06"

start_ms = int(datetime.fromisoformat(DATE_FROM).replace(tzinfo=timezone.utc).timestamp() * 1000)
end_ms = int(datetime.fromisoformat(DATE_TO).replace(tzinfo=timezone.utc).timestamp() * 1000) + 24*3600*1000

# Load 1m
rows = []
with CSV_PATH.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        ts = int(t.timestamp() * 1000)
        if ts < start_ms: continue
        if ts >= end_ms: break
        rows.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
print(f"Loaded {len(rows)} 1m bars")

# Aggregate to D (anchor epoch = midnight UTC)
def agg(rs, tf_ms, anchor=0):
    out = []; cb = None; o = h = l = c = 0.0; v = 0.0
    for ts, oo, hh, ll, cc, vv in rs:
        b = ts - ((ts - anchor) % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out

barsD = agg(rows, 1440 * MS_M)
print(f"D candles: {len(barsD)}")

# Compute maxV per D candle (LTF=32m, mlt=45 canonical)
def maxv_for_d(rs, d_start, d_end, ltf_ms=32*MS_M):
    out = []; cb = None; o = h = l = c = 0.0; v = 0.0
    for ts, oo, hh, ll, cc, vv in rs:
        if ts < d_start: continue
        if ts >= d_end: break
        b = ts - ((ts - d_start) % ltf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    if not out: return None
    mb = max(out, key=lambda b: b[5])
    return mb  # (ts, o, h, l, c, v)

# Build maxV events
events = []
for db in barsD:
    d_start, d_o, d_h, d_l, d_c, d_v = db
    mb = maxv_for_d(rows, d_start, d_start + 1440 * MS_M)
    if mb is None: continue
    mb_ts, mb_o, mb_h, mb_l, mb_c, mb_v = mb
    body_lo, body_hi = min(d_o, d_c), max(d_o, d_c)
    if mb_c < body_lo: pos = "lower_wick"
    elif mb_c > body_hi: pos = "upper_wick"
    elif mb_c < (body_lo + body_hi)/2: pos = "body_bottom"
    else: pos = "body_top"
    events.append({
        "d_start": d_start, "d_o": d_o, "d_h": d_h, "d_l": d_l, "d_c": d_c,
        "level": mb_c, "zone_lo": mb_l, "zone_hi": mb_h, "V": mb_v,
        "position": pos,
    })

print(f"maxV events: {len(events)}")

# Amplification formula
def w_pos(p): return 1.5 if "wick" in p else 0.7
def w_age(days): return 1 + 0.3 * math.log(1 + max(days, 0) / 30)

# Current end (anchor for age) — use last bar timestamp
end_ts = barsD[-1][0] + 1440 * MS_M
for e in events:
    e["age_days"] = (end_ts - e["d_start"]) / (24 * 3600 * 1000)
    e["amp"] = w_pos(e["position"]) * w_age(e["age_days"])

# Sort events by amp descending
events_sorted = sorted(events, key=lambda e: -e["amp"])
print(f"\nTop 10 maxV events by amplification:")
for e in events_sorted[:10]:
    d = datetime.fromtimestamp(e["d_start"]/1000, tz=timezone.utc).strftime("%Y-%m-%d")
    print(f"  D {d}  level={e['level']:.0f}  pos={e['position']:<12}  age={e['age_days']:.0f}d  amp={e['amp']:.2f}")

# === Visualization ===
fig, ax = plt.subplots(figsize=(20, 11))

# 1) Draw D candlesticks
x_positions = []
for i, b in enumerate(barsD):
    x = i
    x_positions.append(x)
    o, h, l, c = b[1], b[2], b[3], b[4]
    color = "green" if c > o else ("red" if c < o else "gray")
    # Wick
    ax.plot([x, x], [l, h], color="black", lw=0.7, zorder=2)
    # Body
    ax.add_patch(Rectangle((x - 0.35, min(o, c)), 0.7, abs(c - o),
                            facecolor=color, edgecolor="black", lw=0.4, alpha=0.85, zorder=3))

# 2) Draw amplified force bands for each maxV
y_min = min(b[3] for b in barsD) * 0.98
y_max = max(b[2] for b in barsD) * 1.02
prices_grid = np.linspace(y_min, y_max, 300)

# Sort by amp ascending so high-amp draws on top
for e in sorted(events, key=lambda e: e["amp"]):
    L = e["level"]
    R = max(L - e["zone_lo"], e["zone_hi"] - L)
    if R <= 0: continue
    sigma = R / 2
    # Gaussian force at each price
    forces = np.exp(-((prices_grid - L) / sigma) ** 2) * e["amp"]
    # Find x range where this maxV is "active" — from formation to end of chart
    x_start = barsD.index([b for b in barsD if b[0] == e["d_start"]][0])
    x_end = len(barsD) - 1
    # Color by position
    if e["position"] == "lower_wick": base_color = "darkblue"
    elif e["position"] == "upper_wick": base_color = "darkred"
    else: base_color = "gray"
    # Draw fading horizontal band from formation forward
    # For visualization: draw thin horizontal bands at each price with alpha proportional to force
    for k in range(0, len(prices_grid), 4):  # sparse for speed
        p = prices_grid[k]
        f = forces[k]
        if f < 0.05: continue
        alpha = min(0.4, f * 0.15)  # cap to not oversaturate
        ax.hlines(p, x_start, x_end, color=base_color, alpha=alpha, lw=1.5, zorder=1)
    # Draw level line on top of band
    ax.hlines(L, x_start, x_end, color=base_color, lw=1.5 + 0.5 * e["amp"], alpha=0.5 + 0.15 * min(e["amp"], 3),
              zorder=4)

# 3) Labels
dates_to_show = list(range(0, len(barsD), max(1, len(barsD)//15)))
ax.set_xticks(dates_to_show)
ax.set_xticklabels([datetime.fromtimestamp(barsD[i][0]/1000, tz=timezone.utc).strftime("%m-%d") for i in dates_to_show], rotation=45)
ax.set_xlim(-1, len(barsD))
ax.set_ylim(y_min, y_max)
ax.set_xlabel("Date (D candles)", fontsize=11)
ax.set_ylabel("Price (USD)", fontsize=11)
ax.set_title(f"BTC D candles 2026-02-05 → 2026-05-06 + amplified maxV force bands\n"
             f"Blue = lower-wick maxV (long bias), Red = upper-wick (short bias), Gray = body\n"
             f"Band opacity ∝ amplified force = exp(-((p-L)/σ)²) × W_pos × W_age",
             fontsize=11)
ax.grid(alpha=0.2, zorder=0)

# Legend
from matplotlib.patches import Patch
legend = [
    Patch(facecolor="darkblue", alpha=0.5, label="lower-wick maxV (long support)"),
    Patch(facecolor="darkred", alpha=0.5, label="upper-wick maxV (short resistance)"),
    Patch(facecolor="gray", alpha=0.5, label="body maxV (weak)"),
]
ax.legend(handles=legend, loc="upper left", fontsize=10)

plt.tight_layout()
out = Path.home() / "Desktop" / "maxv_amplified_chart_feb-may.png"
plt.savefig(out, dpi=120, bbox_inches="tight")
print(f"\nSaved → {out}")
