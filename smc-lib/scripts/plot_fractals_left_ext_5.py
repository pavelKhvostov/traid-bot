"""Визуализация left_ext_5 правила на 12h фракталах.

3 панели:
  1. ВЕРХНЯЯ — обзор всего окна с 56 фракталами; цветовая разметка:
       ★ зеленый — important + passes left_ext_5
       ★ оранжевый — important (все 18 проходят, для контроля)
       ✓ синий — noise, passes left_ext_5 (=23 noise оставшихся после фильтра)
       ✗ красный — noise, FAILS left_ext_5 (=15 noise отсеяны)
  2. СРЕДНЯЯ — пример важного fractal которое PASSES left_ext_5
  3. НИЖНЯЯ — пример noise fractal которое FAILS left_ext_5
       (видно: бар слева пробил pivot — left_ext_5 = False)
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timezone, timedelta
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.fractal.code import detect_fractal

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
TF12_MS = 12 * 3600_000
START_MS = int(datetime(2026, 2, 4, 0, 0, tzinfo=MSK).timestamp() * 1000)

IMPORTANT = {1, 3, 4, 5, 9, 10, 11, 14, 15, 20, 23, 26, 29, 40, 41, 42, 47, 48}
OUT_PNG = pathlib.Path.home() / "Desktop/i-rdrb-charts/fractals_12h_left_ext_5.png"


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
fractals = []
for i in range(2, len(candles) - 2):
    f = detect_fractal(candles[i-2:i+3], n=2)
    if f is None: continue
    if candles[i].open_time < START_MS: continue
    fractals.append({"dir": f.direction, "level": f.level, "idx": i,
                     "center_ts": candles[i].open_time})


def left_ext_5(f):
    bidx = f["idx"]
    win_lo = max(0, bidx - 5); win_hi = bidx  # exclude i itself
    slice_ = bars12[win_lo:win_hi]
    if not slice_: return True
    if f["dir"] == "high":
        return f["level"] > max(b[2] for b in slice_)
    else:
        return f["level"] < min(b[3] for b in slice_)


for n, f in enumerate(fractals, 1):
    f["num"] = n
    f["is_important"] = (n in IMPORTANT)
    f["passes_ext5"] = left_ext_5(f)

# Stats
imp_pass = sum(1 for f in fractals if f["is_important"] and f["passes_ext5"])
imp_fail = sum(1 for f in fractals if f["is_important"] and not f["passes_ext5"])
noise_pass = sum(1 for f in fractals if not f["is_important"] and f["passes_ext5"])
noise_fail = sum(1 for f in fractals if not f["is_important"] and not f["passes_ext5"])
print(f"Important: pass={imp_pass}, fail={imp_fail}")
print(f"Noise:     pass={noise_pass}, fail={noise_fail}")

# Pick examples
imp_example = next(f for f in fractals if f["num"] == 1)  # #1 FL 60000 important pass
noise_fail_example = next(f for f in fractals if not f["is_important"] and not f["passes_ext5"])
# Find a clear noise+fail example
candidates_fail = [f for f in fractals if not f["is_important"] and not f["passes_ext5"]]
# choose first one with broad context
noise_fail_example = candidates_fail[2] if len(candidates_fail) > 2 else candidates_fail[0]
print(f"Example important: #{imp_example['num']} ({imp_example['dir']} {imp_example['level']:.0f}) at idx {imp_example['idx']}")
print(f"Example noise+fail: #{noise_fail_example['num']} ({noise_fail_example['dir']} {noise_fail_example['level']:.0f}) at idx {noise_fail_example['idx']}")


# === Plot ===
fig = plt.figure(figsize=(20, 14))
gs = fig.add_gridspec(3, 2, height_ratios=[2, 1.3, 1.3], hspace=0.35, wspace=0.15)

# Top panel: full window
ax_top = fig.add_subplot(gs[0, :])

start_idx_plot = next(i for i, b in enumerate(bars12) if b[0] >= START_MS)
end_idx_plot = len(bars12)
sub_bars = bars12[start_idx_plot:end_idx_plot]


def fmt_msk(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d')


def draw_candles(ax, bars, x_offset=0):
    """Draw OHLC candles. bars = list of (ts, o, h, l, c)."""
    for i, b in enumerate(bars):
        ts, o, h, l, c = b
        x = i + x_offset
        color = '#26a69a' if c >= o else '#ef5350'
        # wick
        ax.plot([x, x], [l, h], color='black', linewidth=0.5, zorder=1)
        # body
        body_low = min(o, c); body_high = max(o, c)
        height = body_high - body_low if body_high > body_low else (h - l) * 0.01
        rect = Rectangle((x - 0.4, body_low), 0.8, height, facecolor=color, edgecolor=color, zorder=2)
        ax.add_patch(rect)


draw_candles(ax_top, sub_bars)
ax_top.set_xlim(-1, len(sub_bars))
y_min = min(b[3] for b in sub_bars) * 0.99
y_max = max(b[2] for b in sub_bars) * 1.01
ax_top.set_ylim(y_min, y_max)

# Plot fractal markers
for f in fractals:
    x = f["idx"] - start_idx_plot
    y = f["level"]
    if f["is_important"] and f["passes_ext5"]:
        ax_top.scatter(x, y, marker='*', s=240, color='gold', edgecolor='black', linewidth=1.5, zorder=10)
        label = "★"
    elif f["is_important"] and not f["passes_ext5"]:
        ax_top.scatter(x, y, marker='*', s=240, color='orange', edgecolor='red', linewidth=1.5, zorder=10)
        label = "★!"
    elif not f["is_important"] and f["passes_ext5"]:
        ax_top.scatter(x, y, marker='o', s=80, color='royalblue', edgecolor='black', linewidth=0.5, alpha=0.7, zorder=5)
        label = "·"
    else:
        ax_top.scatter(x, y, marker='x', s=80, color='red', linewidth=1.5, alpha=0.7, zorder=5)
        label = "✗"
    ax_top.annotate(f"#{f['num']}", (x, y),
                    textcoords="offset points",
                    xytext=(0, 8 if f["dir"] == "high" else -16),
                    fontsize=6, ha='center', alpha=0.8)

# X ticks: каждые ~14 баров
tick_positions = list(range(0, len(sub_bars), 14))
tick_labels = [fmt_msk(sub_bars[t][0]) for t in tick_positions]
ax_top.set_xticks(tick_positions)
ax_top.set_xticklabels(tick_labels, rotation=45, ha='right', fontsize=8)

ax_top.set_title(f"56 fractals 12h (с 2026-02-04 MSK) — left_ext_5 фильтр", fontsize=14, fontweight='bold')
ax_top.set_ylabel("Price (USD)", fontsize=11)
ax_top.grid(True, alpha=0.3)

# Legend
legend_elems = [
    plt.scatter([], [], marker='*', s=240, color='gold', edgecolor='black', label=f'★ important + passes left_ext_5 ({imp_pass})'),
    plt.scatter([], [], marker='*', s=240, color='orange', edgecolor='red', label=f'★! important but FAILS ({imp_fail})'),
    plt.scatter([], [], marker='o', s=80, color='royalblue', alpha=0.7, label=f'noise — passes (остался шум, {noise_pass})'),
    plt.scatter([], [], marker='x', s=80, color='red', label=f'noise — отсеян по left_ext_5 ({noise_fail})'),
]
ax_top.legend(handles=legend_elems, loc='upper left', fontsize=10, framealpha=0.9)


# === Bottom-left: important + passes ===
def draw_example(ax, f, title_prefix):
    bidx = f["idx"]
    lo = max(0, bidx - 7); hi = min(len(bars12), bidx + 3)
    ex_bars = bars12[lo:hi]
    draw_candles(ax, ex_bars)

    # Highlight pivot
    pivot_x = bidx - lo
    ax.axvline(pivot_x, color='gold', linewidth=2, alpha=0.5, zorder=0, label='pivot i')

    # Highlight left 5 window (i-5..i-1)
    left_lo = max(0, pivot_x - 5)
    left_hi = pivot_x  # exclusive
    ax.axvspan(left_lo - 0.5, left_hi - 0.5, color='lightyellow', alpha=0.5, zorder=0)

    # Draw pivot level line
    color_level = 'green' if f["dir"] == "low" else 'red'
    ax.axhline(f["level"], color=color_level, linestyle='--', linewidth=1.5, alpha=0.8,
               label=f'pivot level={f["level"]:.0f}')

    # Compute comparison reference
    left_bars = ex_bars[left_lo:left_hi]
    if f["dir"] == "high":
        ref_level = max(b[2] for b in left_bars) if left_bars else 0
        ref_label = f'max high in i-5..i-1 = {ref_level:.0f}'
    else:
        ref_level = min(b[3] for b in left_bars) if left_bars else 0
        ref_label = f'min low in i-5..i-1 = {ref_level:.0f}'
    ax.axhline(ref_level, color='blue', linestyle=':', linewidth=1.5, alpha=0.8, label=ref_label)

    # Title
    glyph = "FH" if f["dir"] == "high" else "FL"
    status = "PASSES left_ext_5 ✓" if f["passes_ext5"] else "FAILS left_ext_5 ✗"
    color = 'darkgreen' if f["passes_ext5"] else 'darkred'
    important_label = " ★ IMPORTANT" if f["is_important"] else " (noise)"
    ax.set_title(f"{title_prefix}: #{f['num']} {glyph} {f['level']:.0f}{important_label} — {status}",
                 fontsize=11, fontweight='bold', color=color)

    # X labels
    ax.set_xticks([])
    # Annotate pivot/i-5..i-1
    if f["dir"] == "high":
        ax.annotate("i (pivot)", (pivot_x, f["level"]), textcoords="offset points",
                    xytext=(0, 12), fontsize=9, ha='center', fontweight='bold')
    else:
        ax.annotate("i (pivot)", (pivot_x, f["level"]), textcoords="offset points",
                    xytext=(0, -18), fontsize=9, ha='center', fontweight='bold')
    ax.legend(loc='upper left', fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.3)

    # Add MSK label below
    ts_pivot = datetime.fromtimestamp(ex_bars[pivot_x][0] / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M MSK')
    ax.set_xlabel(f"pivot at {ts_pivot}", fontsize=9)


# Example 1: important + passes (e.g. #1)
ax_ex1 = fig.add_subplot(gs[1, 0])
draw_example(ax_ex1, imp_example, "Example A")

# Example 2: noise + FAILS — show how a left bar exceeds pivot
ax_ex2 = fig.add_subplot(gs[1, 1])
draw_example(ax_ex2, noise_fail_example, "Example B")

# Example 3: noise + passes (still kept after filter — for context)
noise_pass_candidates = [f for f in fractals if not f["is_important"] and f["passes_ext5"]]
noise_pass_example = noise_pass_candidates[len(noise_pass_candidates) // 2]
ax_ex3 = fig.add_subplot(gs[2, 0])
draw_example(ax_ex3, noise_pass_example, "Example C")

# Example 4: another noise + FAILS
noise_fail_2 = candidates_fail[-3] if len(candidates_fail) >= 3 else candidates_fail[0]
ax_ex4 = fig.add_subplot(gs[2, 1])
draw_example(ax_ex4, noise_fail_2, "Example D")

# Text explainer
fig.suptitle("left_ext_5: pivot.level должен быть строгим экстремумом vs макс/мин 5 предыдущих 12h-баров (i-5..i-1)",
             fontsize=13, y=0.99)

OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
plt.tight_layout()
plt.savefig(OUT_PNG, dpi=130, bbox_inches='tight')
print(f"\nSaved: {OUT_PNG}")
print(f"Size: {OUT_PNG.stat().st_size // 1024} KB")
