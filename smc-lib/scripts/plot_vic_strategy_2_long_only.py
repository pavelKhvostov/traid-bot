"""Стратегия 2 по ViC — только LONG (исправлено).

LONG signal на двух 12h-свечах подряд i-1 и i:
  ВСЕ из {open(i-1), close(i-1), open(i), close(i)}
    строго ВЫШЕ ОБОИХ уровней {maxV(i-1), maxV(i)}.

Эквивалентно:
  min(open(i-1), close(i-1), open(i), close(i)) > max(maxV(i-1), maxV(i))

Цвет свечей (bull/bear) не важен.
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
from indicators.vic_asvk import calculate_vic_bar
from elements.fractal.code import detect_fractal

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_HOUR = 3600_000
TF12_MS = 12 * MS_HOUR
OUT_PNG = pathlib.Path.home() / "Desktop/i-rdrb-charts/vic_strategy_2_LONG.png"


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

# Aggregate 12h + LTF per bar
print("Aggregating 12h + maxV...")
bars12 = []
ltf_per_bar = {}
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

vic_per_bar = {}
for b in bars12:
    v = calculate_vic_bar(ltf_per_bar[b[0]])
    if v is not None: vic_per_bar[b[0]] = v


# Detect LONG signals (strict)
long_signals = []
for i in range(1, len(bars12)):
    bi_1 = bars12[i-1]; bi = bars12[i]
    v1 = vic_per_bar.get(bi_1[0]); v2 = vic_per_bar.get(bi[0])
    if v1 is None or v2 is None: continue
    if v1.maxV is None or v2.maxV is None: continue
    o1, c1 = bi_1[1], bi_1[4]
    o2, c2 = bi[1], bi[4]
    # все 4 значения выше ОБОИХ maxV
    floor_v = max(v1.maxV, v2.maxV)
    if min(o1, c1, o2, c2) > floor_v:
        long_signals.append(i)

print(f"LONG signals (strict): {len(long_signals)}")


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M')


# Pick 3 examples: 1 recent + 2 with clearest wick depth
def wick_depth(i_pick):
    bi_1, bi = bars12[i_pick - 1], bars12[i_pick]
    v1, v2 = vic_per_bar[bi_1[0]], vic_per_bar[bi[0]]
    floor_v = max(v1.maxV, v2.maxV)
    body_min = min(bi_1[1], bi_1[4], bi[1], bi[4])
    return body_min - floor_v


scored = sorted([(wick_depth(i), i) for i in long_signals], reverse=True)
recent_cutoff = bars12[-1][0] - 1 * 365 * 24 * 3600 * 1000
recent = [i for s, i in scored if bars12[i][0] > recent_cutoff][:2]
# also pick one big depth that's older
historic = next(i for s, i in scored if bars12[i][0] <= recent_cutoff)
picks = recent[:2] + [historic]
print(f"\nPicks: {[fmt(bars12[i][0]) for i in picks]}")


fig, axes = plt.subplots(1, 3, figsize=(22, 8))


def draw_panel(ax, i_pick):
    lo_idx = max(0, i_pick - 5)
    hi_idx = min(len(bars12), i_pick + 6)
    ctx = bars12[lo_idx:hi_idx]

    for j, b in enumerate(ctx):
        ts, o, h, l, c, v = b
        x = j
        color = '#26a69a' if c >= o else '#ef5350'
        ax.plot([x, x], [l, h], color='black', linewidth=0.8, zorder=1)
        bt = max(o, c); bb = min(o, c)
        height = bt - bb if bt > bb else (h - l) * 0.02
        rect = Rectangle((x - 0.4, bb), 0.8, height,
                         facecolor=color, edgecolor=color, zorder=2)
        ax.add_patch(rect)
        vic = vic_per_bar.get(ts)
        if vic and vic.maxV is not None:
            ax.scatter(x, vic.maxV, marker='D', color='purple', s=90, zorder=10,
                       edgecolor='black', linewidth=0.8)
            ax.plot([x - 0.45, x + 0.45], [vic.maxV, vic.maxV],
                    color='purple', linewidth=1.0, linestyle='--', alpha=0.5, zorder=3)

    # Pair highlight
    i_local = i_pick - lo_idx
    ax.axvspan(i_local - 1.5, i_local + 0.5, color='lightgreen', alpha=0.18, zorder=0)

    # Draw open/close horizontal markers for pair to make rule visible
    for j_off, b in enumerate([bars12[i_pick - 1], bars12[i_pick]]):
        x = (i_local - 1) + j_off
        o, c = b[1], b[4]
        # open marker (tick on left)
        ax.plot([x - 0.45, x - 0.25], [o, o], color='blue', linewidth=2, zorder=5)
        # close marker (tick on right)
        ax.plot([x + 0.25, x + 0.45], [c, c], color='blue', linewidth=2, zorder=5)

    # Annotate maxV and pair labels
    for j_off, b in enumerate([bars12[i_pick - 1], bars12[i_pick]]):
        x = (i_local - 1) + j_off
        v = vic_per_bar[b[0]]
        ax.annotate(f"maxV={v.maxV:.0f}", (x, v.maxV),
                    textcoords="offset points",
                    xytext=(0, -22), fontsize=9, ha='center',
                    color='purple', fontweight='bold')

    ax.annotate("i-1", (i_local - 1, ctx[i_local - 1][2] * 1.003),
                fontsize=11, ha='center', fontweight='bold', color='darkblue')
    ax.annotate("i", (i_local, ctx[i_local][2] * 1.003),
                fontsize=11, ha='center', fontweight='bold', color='darkblue')

    # Find next FL fractal after i
    for k in range(i_pick - 2, min(len(bars12) - 2, i_pick + 8)):
        win = [Candle(open=bars12[m][1], high=bars12[m][2], low=bars12[m][3],
                      close=bars12[m][4], open_time=bars12[m][0])
               for m in range(k-2, k+3)]
        f = detect_fractal(win, n=2)
        if f is None or f.direction != "low": continue
        if lo_idx <= k < hi_idx:
            x = k - lo_idx
            ax.scatter(x, f.level, marker='*', s=300, color='gold',
                       edgecolor='black', linewidth=1.5, zorder=11)
            ax.annotate(f"FL {f.level:.0f}",
                        (x, f.level), textcoords="offset points",
                        xytext=(0, -22), fontsize=9, ha='center', fontweight='bold')

    pair_dt = fmt(bars12[i_pick][0])
    bi_1, bi = bars12[i_pick - 1], bars12[i_pick]
    v1, v2 = vic_per_bar[bi_1[0]], vic_per_bar[bi[0]]
    floor_v = max(v1.maxV, v2.maxV)
    body_min = min(bi_1[1], bi_1[4], bi[1], bi[4])
    # draw the floor (max of two maxV)
    ax.axhline(floor_v, color='red', linewidth=1.5, linestyle='-.', alpha=0.7, zorder=3,
               label=f'max(maxV)={floor_v:.0f}')
    ax.set_title(f"LONG signal at {pair_dt} MSK\n"
                 f"min(open,close обеих)={body_min:.0f} > max(maxV)={floor_v:.0f}",
                 fontsize=10, fontweight='bold')

    tick_pos = list(range(0, len(ctx), 2))
    tick_lab = [datetime.fromtimestamp(ctx[t][0] / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H')
                for t in tick_pos]
    ax.set_xticks(tick_pos)
    ax.set_xticklabels(tick_lab, rotation=45, ha='right', fontsize=8)
    ax.set_ylabel("Price")
    ax.grid(True, alpha=0.3)
    ax.set_xlim(-1, len(ctx))

    handles = [
        plt.scatter([], [], marker='D', color='purple', s=80, edgecolor='black', label='maxV (12h)'),
        plt.scatter([], [], marker='*', color='gold', s=300, edgecolor='black', label='FL after signal'),
        Rectangle((0, 0), 1, 1, facecolor='lightgreen', alpha=0.4, label='signal pair (i-1, i)'),
        plt.Line2D([0], [0], color='blue', linewidth=2, label='open/close ticks'),
    ]
    ax.legend(handles=handles, loc='upper left', fontsize=8, framealpha=0.9)


for ax, i_pick in zip(axes, picks):
    draw_panel(ax, i_pick)

fig.suptitle("Стратегия 2 по ViC (LONG only): maxV ниже open и close обеих свечей i-1, i  ·  12h BTC",
             fontsize=14, fontweight='bold')
plt.tight_layout()
OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(OUT_PNG, dpi=140, bbox_inches='tight')
print(f"\nSaved: {OUT_PNG}")
