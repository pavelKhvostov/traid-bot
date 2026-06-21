"""Картинка F2 = opposite_colors OR three_same_color на конкретных примерах.

Layout (5 панелей):
  1. Important REVERSAL (FH #3): i bear / i-1 bull → CATCHED by opp_colors
  2. Important REVERSAL (FL #1): i bull / i-1 bear → CATCHED by opp_colors
  3. Important CONTINUATION (FH #10): bull/bull/bull → CATCHED by 3_same
  4. Noise MIXED (FL #6): bull/bull/bear → EXCLUDED (2 same но не 3)
  5. Noise MIXED (FH #13): bull/bull/bear → EXCLUDED
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timezone, timedelta
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.fractal.code import detect_fractal

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
TF12_MS = 12 * 3600_000
OUT_PNG = pathlib.Path.home() / "Desktop/i-rdrb-charts/f2_candle_pattern.png"


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000),
                         float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def aggregate(d, tf_ms):
    out = []; cb = None; o = h = l = c = 0.0
    for ts, oo, hh, ll, cc in d:
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append((cb, o, h, l, c))
    return out


print("Loading...")
data = load_1m()
bars12 = aggregate(data, TF12_MS)
candles = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars12]


START_MS = int(datetime(2026, 2, 4, 0, 0, tzinfo=MSK).timestamp() * 1000)
fractals = []
for i in range(2, len(candles) - 2):
    f = detect_fractal(candles[i-2:i+3], n=2)
    if f is None: continue
    if candles[i].open_time < START_MS: continue
    fractals.append({"dir": f.direction, "level": f.level, "idx": i,
                     "center_ts": candles[i].open_time})

# Find target fractals by num
TARGETS = {1: "FL imp REVERSAL", 3: "FH imp REVERSAL", 10: "FH imp 3-SAME",
           11: "FL imp 3-SAME", 6: "FL noise MIXED", 13: "FH noise MIXED"}

picks = {}
for n, f in enumerate(fractals, 1):
    if n in TARGETS:
        picks[n] = f


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H')


def color_name(b):
    o, c = b[1], b[4]
    if c > o: return "bull"
    if c < o: return "bear"
    return "doji"


def color_emoji(b):
    o, c = b[1], b[4]
    if c > o: return "🟢"
    if c < o: return "🔴"
    return "⚪"


fig, axes = plt.subplots(2, 3, figsize=(20, 11))
axes = axes.flatten()


def draw_panel(ax, num, label_caption):
    f = picks[num]
    bidx = f["idx"]
    lo_idx = max(0, bidx - 5); hi_idx = min(len(bars12), bidx + 3)
    ctx = bars12[lo_idx:hi_idx]

    # Draw candles
    for j, b in enumerate(ctx):
        ts, o, h, l, c = b
        x = j
        color = '#26a69a' if c >= o else '#ef5350'
        ax.plot([x, x], [l, h], color='black', linewidth=0.8, zorder=1)
        bt = max(o, c); bb = min(o, c)
        height = bt - bb if bt > bb else (h - l) * 0.02
        rect = Rectangle((x - 0.4, bb), 0.8, height,
                         facecolor=color, edgecolor=color, zorder=2)
        ax.add_patch(rect)

    # Mark i-2, i-1, i
    i_local = bidx - lo_idx
    im1_local = i_local - 1
    im2_local = i_local - 2

    # Highlight band over the 3 critical bars
    ax.axvspan(im2_local - 0.5, i_local + 0.5, color='yellow', alpha=0.18, zorder=0)

    # Labels above each bar
    bar_top = max(b[2] for b in ctx)
    for offset, lbl in [(0, "i-2"), (1, "i-1"), (2, "i")]:
        x = im2_local + offset
        if 0 <= x < len(ctx):
            b = ctx[x]
            col_name = color_name(b)
            ax.annotate(f"{lbl}\n{color_emoji(b)}",
                        (x, bar_top * 1.005),
                        textcoords="offset points",
                        xytext=(0, 8), fontsize=11, ha='center',
                        fontweight='bold')

    # Mark fractal level
    color_lvl = 'red' if f["dir"] == "high" else 'green'
    glyph = "FH" if f["dir"] == "high" else "FL"
    ax.axhline(f["level"], color=color_lvl, linestyle='--', linewidth=1.5, alpha=0.6, zorder=3)
    ax.scatter(i_local, f["level"], marker='*', s=300, color='gold',
               edgecolor='black', linewidth=1.5, zorder=11)
    ax.annotate(f"{glyph} {f['level']:.0f}",
                (i_local, f["level"]),
                textcoords="offset points",
                xytext=(15, 0 if f["dir"] == "high" else -5),
                fontsize=9, ha='left', fontweight='bold', color=color_lvl)

    # Pattern annotation
    i_col = color_name(bars12[bidx])
    im1_col = color_name(bars12[bidx - 1])
    im2_col = color_name(bars12[bidx - 2])
    opp = (i_col != im1_col) and "doji" not in (i_col, im1_col)
    three_same = (i_col == im1_col == im2_col) and i_col != "doji"
    pass_F2 = opp or three_same

    pattern_desc = ""
    if opp:
        pattern_desc = "opp_colors ✓"
    elif three_same:
        pattern_desc = "3_same ✓"
    else:
        pattern_desc = "mixed (excluded)"

    verdict = "✅ PASS F2" if pass_F2 else "❌ EXCLUDED by F2"
    verdict_color = 'darkgreen' if pass_F2 else 'darkred'

    pivot_dt = datetime.fromtimestamp(f["center_ts"] / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M')
    ax.set_title(f"#{num} {label_caption}\n"
                 f"{pivot_dt} MSK · pattern: i-2={im2_col} → i-1={im1_col} → i={i_col} → {pattern_desc}\n"
                 f"{verdict}",
                 fontsize=10, fontweight='bold', color=verdict_color)

    tick_pos = list(range(len(ctx)))
    tick_lab = [fmt(b[0]) for b in ctx]
    ax.set_xticks(tick_pos)
    ax.set_xticklabels(tick_lab, rotation=45, ha='right', fontsize=8)
    ax.set_ylabel("Price")
    ax.grid(True, alpha=0.3)
    ax.set_xlim(-1, len(ctx))


# Layout: 6 panels (2 rows × 3 cols)
draw_panel(axes[0], 3, "FH important — REVERSAL (opp_colors)")
draw_panel(axes[1], 1, "FL important — REVERSAL (opp_colors)")
draw_panel(axes[2], 10, "FH important — CONTINUATION (3_same)")
draw_panel(axes[3], 11, "FL important — CONTINUATION (3_same)")
draw_panel(axes[4], 6, "FL noise — MIXED (excluded by F2)")
draw_panel(axes[5], 13, "FH noise — MIXED (excluded by F2)")


fig.suptitle("F2 = opposite_colors(i, i-1) OR three_same_color(i-2, i-1, i)\n"
             "Catches: REVERSAL patterns + CONTINUATION exhaustion. Excludes mixed 2-same-not-3.",
             fontsize=14, fontweight='bold', y=1.0)

plt.tight_layout()
OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(OUT_PNG, dpi=130, bbox_inches='tight')
print(f"Saved: {OUT_PNG}")
