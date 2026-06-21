"""Render-картинка моего понимания "Стратегия 2 по ViC":

  LL_signal (bullish reversal candidate):
    На двух 12h-свечах подряд i-1 и i:
      maxV(i-1) ≤ body_bottom(i-1)   (maxV в нижнем wick)
      maxV(i)   ≤ body_bottom(i)
    → крупный объём прошёл ниже body на обеих свечах, close восстановился = absorption.

  HH_signal зеркально:
      maxV(i-1) ≥ body_top(i-1)
      maxV(i)   ≥ body_top(i)

Найду в 6y BTC лучшие примеры обоих типов и нарисую side-by-side
с разметкой что произошло после (появился ли fractal LL/HH рядом).
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
from indicators.vic_asvk import calculate_vic_bar, auto_ltf_minutes
from elements.fractal.code import detect_fractal

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_HOUR = 3600_000
TF12_MS = 12 * MS_HOUR
OUT_PNG = pathlib.Path.home() / "Desktop/i-rdrb-charts/vic_strategy_2_concept.png"


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000),
                         float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


print("Loading...")
data = load_1m()

# Aggregate 12h bars + their LTF composition
# auto_ltf for 12h = 5m (5min), но в кеше 1m есть, так что используем 1m или сами агрегируем
# По canon: tfC=12h=43200s, rs=432s, min(43200,432)=432, smallest ≥432 = 600s=10m, но в VALID 600 → 10m
# Actually let me check: VALID_LTF_SECONDS = [60, 180, 300, 600...] → smallest ≥432 = 600. So 10m.
# Memory said "1m used by user". Let me use 1m (per memory).
ltf_min = 1
ltf_ms = ltf_min * 60_000

# Build 12h bars: (open_ts, o, h, l, c, v) + LTF composition for each
print("Aggregating 12h bars + maxV...")
bars12 = []
ltf_per_bar = {}  # 12h_open_ts -> list of LTF (1m) bars
cur_bucket = None
cur_o = cur_h = cur_l = cur_c = cur_v = 0.0
cur_ltf = []
for ts, o, h, l, c, v in data:
    b = ts - (ts % TF12_MS)
    if b != cur_bucket:
        if cur_bucket is not None:
            bars12.append((cur_bucket, cur_o, cur_h, cur_l, cur_c, cur_v))
            ltf_per_bar[cur_bucket] = cur_ltf
        cur_bucket = b; cur_o = o; cur_h = h; cur_l = l; cur_c = c; cur_v = v
        cur_ltf = [(ts, o, h, l, c, v)]
    else:
        cur_h = max(cur_h, h); cur_l = min(cur_l, l); cur_c = c; cur_v += v
        cur_ltf.append((ts, o, h, l, c, v))
if cur_bucket is not None:
    bars12.append((cur_bucket, cur_o, cur_h, cur_l, cur_c, cur_v))
    ltf_per_bar[cur_bucket] = cur_ltf

print(f"  {len(bars12)} 12h bars")

# Compute maxV for each
vic_per_bar = {}  # 12h_open_ts -> VICBar
for b in bars12:
    vic = calculate_vic_bar(ltf_per_bar[b[0]])
    if vic is not None:
        vic_per_bar[b[0]] = vic
print(f"  {len(vic_per_bar)} VIC bars computed")


# Detect signals
def body_top(b): return max(b[1], b[4])
def body_bot(b): return min(b[1], b[4])


ll_signals = []  # (idx) where ll signal triggers at bar idx (= i)
hh_signals = []
for i in range(1, len(bars12)):
    bi_1 = bars12[i-1]; bi = bars12[i]
    vic_i_1 = vic_per_bar.get(bi_1[0]); vic_i = vic_per_bar.get(bi[0])
    if vic_i_1 is None or vic_i is None: continue
    if vic_i_1.maxV is None or vic_i.maxV is None: continue

    # LL: maxV в нижнем wick на обеих
    if vic_i_1.maxV <= body_bot(bi_1) and vic_i.maxV <= body_bot(bi):
        ll_signals.append(i)
    # HH: maxV в верхнем wick на обеих
    if vic_i_1.maxV >= body_top(bi_1) and vic_i.maxV >= body_top(bi):
        hh_signals.append(i)

print(f"\nLL signals (maxV в lower wick 2 bars in row): {len(ll_signals)}")
print(f"HH signals (maxV в upper wick 2 bars in row):  {len(hh_signals)}")


# Pick best examples — recent ones with clear setup
def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M')


# Filter to relatively recent + clear (large wick)
def wick_size(b, vic, kind):
    if kind == "lower":
        return body_bot(b) - vic.maxV
    else:
        return vic.maxV - body_top(b)


# Score each example by wick magnitude
ll_scored = []
for i in ll_signals:
    bi_1, bi = bars12[i-1], bars12[i]
    v1, v2 = vic_per_bar[bi_1[0]], vic_per_bar[bi[0]]
    score = wick_size(bi_1, v1, "lower") + wick_size(bi, v2, "lower")
    ll_scored.append((score, i))

hh_scored = []
for i in hh_signals:
    bi_1, bi = bars12[i-1], bars12[i]
    v1, v2 = vic_per_bar[bi_1[0]], vic_per_bar[bi[0]]
    score = wick_size(bi_1, v1, "upper") + wick_size(bi, v2, "upper")
    hh_scored.append((score, i))

ll_scored.sort(reverse=True)
hh_scored.sort(reverse=True)

# Pick top example for each, prefer recent (last 2 years)
recent_cutoff = bars12[-1][0] - 2 * 365 * 24 * 3600 * 1000
ll_pick = next((i for s, i in ll_scored if bars12[i][0] > recent_cutoff), ll_scored[0][1])
hh_pick = next((i for s, i in hh_scored if bars12[i][0] > recent_cutoff), hh_scored[0][1])

print(f"\nLL pick: bar idx {ll_pick} at {fmt(bars12[ll_pick][0])}")
print(f"HH pick: bar idx {hh_pick} at {fmt(bars12[hh_pick][0])}")


# === Render ===
fig, axes = plt.subplots(1, 2, figsize=(18, 9))


def draw_panel(ax, i_pick, kind, title):
    """kind = 'LL' or 'HH'. i_pick = index of 'i' (second bar of pair)."""
    # Draw 10 bars context (5 before signal pair, then pair, then 4 after)
    lo_idx = max(0, i_pick - 5)
    hi_idx = min(len(bars12), i_pick + 6)
    ctx_bars = bars12[lo_idx:hi_idx]

    # Draw candles
    for j, b in enumerate(ctx_bars):
        ts, o, h, l, c, v = b
        x = j
        color = '#26a69a' if c >= o else '#ef5350'
        ax.plot([x, x], [l, h], color='black', linewidth=0.8, zorder=1)
        bt = max(o, c); bb = min(o, c)
        height = bt - bb if bt > bb else (h - l) * 0.02
        rect = Rectangle((x - 0.4, bb), 0.8, height,
                         facecolor=color, edgecolor=color, zorder=2)
        ax.add_patch(rect)

        # Plot maxV as dot + horizontal line through this bar
        vic = vic_per_bar.get(ts)
        if vic and vic.maxV is not None:
            maxV = vic.maxV
            # Marker
            ax.scatter(x, maxV, marker='D', color='purple', s=80, zorder=10,
                       edgecolor='black', linewidth=0.8)
            # Mini line
            ax.plot([x - 0.45, x + 0.45], [maxV, maxV],
                    color='purple', linewidth=1.0, linestyle='--', alpha=0.5, zorder=3)

    # Highlight the i-1, i pair
    i_local = i_pick - lo_idx  # x of 'i'
    pair_lo = i_local - 1
    pair_hi = i_local
    ax.axvspan(pair_lo - 0.5, pair_hi + 0.5, color='yellow', alpha=0.15, zorder=0)

    # Annotate pair
    bi_1 = bars12[i_pick - 1]
    bi = bars12[i_pick]
    v1 = vic_per_bar[bi_1[0]]; v2 = vic_per_bar[bi[0]]

    # Body boundaries for reference (for the two pair bars)
    for j_offset, b in enumerate([bi_1, bi]):
        x = (i_local - 1) + j_offset
        bb = min(b[1], b[4])
        bt = max(b[1], b[4])
        # Horizontal line showing body_bottom for LL or body_top for HH
        if kind == "LL":
            ax.plot([x - 0.45, x + 0.45], [bb, bb],
                    color='red', linewidth=1.8, alpha=0.7, zorder=4)
            ax.annotate(f"body_bot", (x, bb), xytext=(x + 0.5, bb),
                        fontsize=7, color='red', alpha=0.8)
        else:
            ax.plot([x - 0.45, x + 0.45], [bt, bt],
                    color='red', linewidth=1.8, alpha=0.7, zorder=4)

    # Labels at maxV of pair bars
    for j_offset, (b, v) in enumerate([(bi_1, v1), (bi, v2)]):
        x = (i_local - 1) + j_offset
        label = f"maxV={v.maxV:.0f}"
        ax.annotate(label, (x, v.maxV),
                    textcoords="offset points",
                    xytext=(0, -22 if kind == "LL" else 12),
                    fontsize=8, ha='center', color='purple',
                    fontweight='bold')

    # Pair labels i-1, i
    ax.annotate("i-1", ((i_local - 1), ctx_bars[i_local - 1][2] * 1.005),
                fontsize=11, ha='center', fontweight='bold', color='darkblue')
    ax.annotate("i", (i_local, ctx_bars[i_local][2] * 1.005),
                fontsize=11, ha='center', fontweight='bold', color='darkblue')

    # Find next fractal after i (within 5 bars window)
    fractals_after = []
    for k in range(i_pick - 2, min(len(bars12) - 2, i_pick + 8)):
        win = [Candle(open=bars12[m][1], high=bars12[m][2], low=bars12[m][3], close=bars12[m][4], open_time=bars12[m][0])
               for m in range(k-2, k+3)]
        f = detect_fractal(win, n=2)
        if f is None: continue
        if kind == "LL" and f.direction != "low": continue
        if kind == "HH" and f.direction != "high": continue
        fractals_after.append((k, f))

    # Mark fractal if found
    for k, f in fractals_after:
        if lo_idx <= k < hi_idx:
            x = k - lo_idx
            y = f.level
            ax.scatter(x, y, marker='*', s=300, color='gold',
                       edgecolor='black', linewidth=1.5, zorder=11)
            ax.annotate(f"{'FL' if f.direction=='low' else 'FH'} {f.level:.0f}",
                        (x, y), textcoords="offset points",
                        xytext=(0, -22 if f.direction == "low" else 14),
                        fontsize=9, ha='center', fontweight='bold')

    # Title with full date
    pair_dt = fmt(bi[0])
    if kind == "LL":
        verdict = "→ ожидается reversal UP (LL pivot near)" if fractals_after else "→ нет FL поблизости"
        ax.set_title(f"{title}\nLL signal at {pair_dt} MSK  ·  maxV в нижнем wick 2 свечи подряд\n{verdict}",
                     fontsize=11, fontweight='bold')
    else:
        verdict = "→ ожидается reversal DOWN (HH pivot near)" if fractals_after else "→ нет FH поблизости"
        ax.set_title(f"{title}\nHH signal at {pair_dt} MSK  ·  maxV в верхнем wick 2 свечи подряд\n{verdict}",
                     fontsize=11, fontweight='bold')

    # X labels
    tick_positions = list(range(0, len(ctx_bars), 2))
    tick_labels = [datetime.fromtimestamp(ctx_bars[t][0] / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H')
                   for t in tick_positions]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, rotation=45, ha='right', fontsize=8)
    ax.set_ylabel("Price")
    ax.grid(True, alpha=0.3)
    ax.set_xlim(-1, len(ctx_bars))

    # Legend
    handles = [
        plt.scatter([], [], marker='D', color='purple', s=80, edgecolor='black', label='maxV (12h)'),
        plt.scatter([], [], marker='*', color='gold', s=300, edgecolor='black', label='confirmed fractal'),
        Rectangle((0,0), 1, 1, facecolor='yellow', alpha=0.3, label='signal pair (i-1, i)'),
        plt.Line2D([0], [0], color='red', linewidth=2, label=f"body_{'bottom' if kind=='LL' else 'top'}"),
    ]
    ax.legend(handles=handles, loc='upper left', fontsize=8, framealpha=0.9)


draw_panel(axes[0], ll_pick, "LL", "A) LL signal (absorption → bullish reversal)")
draw_panel(axes[1], hh_pick, "HH", "B) HH signal (distribution → bearish reversal)")

fig.suptitle("Стратегия 2 по ViC: maxV в виках на 2 свечах подряд (12h BTC)",
             fontsize=14, fontweight='bold')
plt.tight_layout()
OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(OUT_PNG, dpi=140, bbox_inches='tight')
print(f"\nSaved: {OUT_PNG}")
print(f"Size: {OUT_PNG.stat().st_size // 1024} KB")
