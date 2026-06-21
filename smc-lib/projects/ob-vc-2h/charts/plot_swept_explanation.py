"""Объяснение что такое SWEPT в контексте 2h ob_vc.

Показывает 4 сценария:
  LONG SWEPT   |  LONG no-sweep
  SHORT SWEPT  |  SHORT no-sweep

«Swept» = prev или cur 2h candle wick'ом пробила одну из последних 5 × 2h Williams N=2
fractal levels (FL для LONG, FH для SHORT). Это «liquidity sweep» — институциональный
stop hunt: цена опускается под frac-low, ловит чужие SL, потом разворот.
"""
import pathlib
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch

BULL = "#01a648"; BEAR = "#131b1b"; DOJI = "#888"
GREEN_ZONE = "#27ae60"
ORANGE = "#e67e22"
GRAY_LINE = "#7f8c8d"


def draw_candles(ax, candles, x_start=0, w=0.6):
    """candles: list of (o, h, l, c) tuples."""
    for i, (o, h, l, c) in enumerate(candles):
        x = x_start + i
        col = BULL if c > o else (BEAR if c < o else DOJI)
        ax.vlines(x, l, h, color=col, linewidth=1.5, zorder=4)
        ax.add_patch(Rectangle((x - w/2, min(o, c)), w, max(abs(o-c), 0.05),
                                facecolor=col, edgecolor=col,
                                linewidth=1.5, zorder=4))


fig, axes = plt.subplots(2, 2, figsize=(20, 12))
fig.suptitle("«SWEPT» в 2h ob_vc — что это", fontsize=18, fontweight="bold", y=0.97)

# ─── Panel 1: LONG SWEPT ──────────────────────────────────
ax = axes[0, 0]
# candles: bullish trend → bear retrace → fractal low → sweep wick → bull OB
candles = [
    (100, 102, 99, 101),   # 0
    (101, 104, 100, 103),  # 1
    (103, 105, 102, 104),  # 2
    (104, 105, 100, 101),  # 3 - bear retrace
    (101, 102, 96, 97),    # 4 - FL fractal center (low=96)
    (97, 99, 96, 98),      # 5
    (98, 100, 97, 99),     # 6
    (99, 100, 98, 99.5),   # 7 - prev (small bear/doji)
    (99.5, 100, 92, 93),   # 8 - cur prev → BEAR wick BELOW FL (sweep)
    (93, 105, 92.5, 104),  # 9 - cur cur → strong BULL engulf (OB LONG)
    (104, 106, 102, 105),  # 10
]
draw_candles(ax, candles)

# Mark FL with dashed line
FL = 96
ax.axhline(FL, xmin=0.05, xmax=0.95, color=ORANGE, linewidth=1.2,
           linestyle=(0, (5, 4)), zorder=2)
ax.text(0.5, FL + 0.5, "  FL = $96 (prior fractal low)", color=ORANGE,
        fontsize=10, fontweight="bold", va="bottom", zorder=10)

# Highlight sweep wick (bar 8)
ax.annotate("SWEEP — wick пробил FL\n(stop hunt)",
            xy=(8, 92), xytext=(5, 88),
            fontsize=11, fontweight="bold", color="#c0392b",
            arrowprops=dict(arrowstyle="->", color="#c0392b", lw=2), zorder=11)

# Mark OB
ax.add_patch(Rectangle((7.6, 92), 2.8, 13, facecolor="#4a90e2", alpha=0.10,
                        edgecolor="#4a90e2", linewidth=1.2,
                        linestyle=(0, (4, 4)), zorder=1))
ax.text(9, 106.5, "OB-2h LONG zone", color="#2169b3",
        fontsize=10, fontweight="bold", ha="center", zorder=10)

ax.set_title("LONG SWEPT  ✓\n"
             "prev/cur wick'ом пробивает recent FL → разворот", fontsize=13,
             fontweight="bold", color="#185c34")
ax.set_xlim(-0.5, 11)
ax.set_ylim(86, 110)
ax.set_xticks([]); ax.set_yticks([])
for spine in ax.spines.values(): spine.set_visible(False)


# ─── Panel 2: LONG no-sweep ───────────────────────────────
ax = axes[0, 1]
# Bull recovery WITHOUT sweeping FL — FL stays untouched
candles = [
    (100, 102, 99, 101),
    (101, 103, 100, 102),
    (102, 104, 101, 103),
    (103, 104, 99, 100),
    (100, 101, 96, 97),    # FL fractal (low=96)
    (97, 99, 96.5, 98),
    (98, 100, 97, 99),
    (99, 101, 98.5, 100),
    (100, 102, 99, 100.5), # prev (bear small body)
    (100.5, 106, 100, 105),# cur BULL engulf — LOW = 100 (НЕ касается FL 96)
    (105, 107, 103, 106),
]
draw_candles(ax, candles)

FL = 96
ax.axhline(FL, xmin=0.05, xmax=0.95, color=ORANGE, linewidth=1.2,
           linestyle=(0, (5, 4)), zorder=2)
ax.text(0.5, FL + 0.5, "  FL = $96 (untouched)", color=ORANGE,
        fontsize=10, fontweight="bold", va="bottom", zorder=10)

# Highlight: cur low НЕ доходит до FL
ax.annotate("cur.low = 100\nFL не задета\n→ no sweep",
            xy=(9, 100), xytext=(6, 88),
            fontsize=11, fontweight="bold", color=GRAY_LINE,
            arrowprops=dict(arrowstyle="->", color=GRAY_LINE, lw=2), zorder=11)

ax.add_patch(Rectangle((7.6, 99), 2.8, 8, facecolor="#4a90e2", alpha=0.10,
                        edgecolor="#4a90e2", linewidth=1.2,
                        linestyle=(0, (4, 4)), zorder=1))
ax.text(9, 107.5, "OB-2h LONG zone", color="#2169b3",
        fontsize=10, fontweight="bold", ha="center", zorder=10)

ax.set_title("LONG no-sweep  ✗\n"
             "prev/cur low НЕ доходит до recent FL → нет sweep",
             fontsize=13, fontweight="bold", color="#7f8c8d")
ax.set_xlim(-0.5, 11)
ax.set_ylim(86, 110)
ax.set_xticks([]); ax.set_yticks([])
for spine in ax.spines.values(): spine.set_visible(False)


# ─── Panel 3: SHORT SWEPT ──────────────────────────────────
ax = axes[1, 0]
# Bear trend → bull retrace → fractal high → sweep wick UP → bear engulf
candles = [
    (100, 101, 98, 99),
    (99, 100, 96, 97),
    (97, 98, 95, 96),
    (96, 99, 95.5, 99),    # bull retrace
    (99, 104, 98, 102),    # FH fractal high=104
    (102, 103, 100, 101),
    (101, 102, 100, 101.5),
    (101.5, 102, 100, 100.5), # prev (small bull/doji)
    (100.5, 108, 100, 107),   # cur prev → BULL wick ABOVE FH (sweep)
    (107, 108, 95, 96),       # cur cur → strong BEAR engulf (OB SHORT)
    (96, 98, 94, 95),
]
draw_candles(ax, candles)

FH = 104
ax.axhline(FH, xmin=0.05, xmax=0.95, color=ORANGE, linewidth=1.2,
           linestyle=(0, (5, 4)), zorder=2)
ax.text(0.5, FH - 0.7, "  FH = $104 (prior fractal high)", color=ORANGE,
        fontsize=10, fontweight="bold", va="top", zorder=10)

ax.annotate("SWEEP — wick пробил FH\n(stop hunt вверх)",
            xy=(8, 108), xytext=(5, 112),
            fontsize=11, fontweight="bold", color="#c0392b",
            arrowprops=dict(arrowstyle="->", color="#c0392b", lw=2), zorder=11)

ax.add_patch(Rectangle((7.6, 95), 2.8, 13, facecolor="#c0392b", alpha=0.08,
                        edgecolor="#c0392b", linewidth=1.2,
                        linestyle=(0, (4, 4)), zorder=1))
ax.text(9, 109, "OB-2h SHORT zone", color="#7d0000",
        fontsize=10, fontweight="bold", ha="center", zorder=10)

ax.set_title("SHORT SWEPT  ✓\n"
             "prev/cur wick'ом пробивает recent FH → разворот",
             fontsize=13, fontweight="bold", color="#7d0000")
ax.set_xlim(-0.5, 11)
ax.set_ylim(93, 114)
ax.set_xticks([]); ax.set_yticks([])
for spine in ax.spines.values(): spine.set_visible(False)


# ─── Panel 4: SHORT no-sweep ───────────────────────────────
ax = axes[1, 1]
candles = [
    (100, 101, 98, 99),
    (99, 100, 97, 98),
    (98, 99, 96, 97),
    (97, 100, 96.5, 99),
    (99, 104, 98, 102),      # FH fractal high=104
    (102, 103, 100, 101),
    (101, 102, 99, 100),
    (100, 101, 98.5, 99.5),
    (99.5, 100, 98, 99),     # prev (small bear)
    (99, 100, 94, 95),       # cur BEAR engulf — HIGH = 100 (НЕ касается FH 104)
    (95, 96, 93, 94),
]
draw_candles(ax, candles)

FH = 104
ax.axhline(FH, xmin=0.05, xmax=0.95, color=ORANGE, linewidth=1.2,
           linestyle=(0, (5, 4)), zorder=2)
ax.text(0.5, FH - 0.7, "  FH = $104 (untouched)", color=ORANGE,
        fontsize=10, fontweight="bold", va="top", zorder=10)

ax.annotate("cur.high = 100\nFH не задета\n→ no sweep",
            xy=(9, 100), xytext=(6, 112),
            fontsize=11, fontweight="bold", color=GRAY_LINE,
            arrowprops=dict(arrowstyle="->", color=GRAY_LINE, lw=2), zorder=11)

ax.add_patch(Rectangle((7.6, 94), 2.8, 7, facecolor="#c0392b", alpha=0.08,
                        edgecolor="#c0392b", linewidth=1.2,
                        linestyle=(0, (4, 4)), zorder=1))
ax.text(9, 102, "OB-2h SHORT zone", color="#7d0000",
        fontsize=10, fontweight="bold", ha="center", zorder=10)

ax.set_title("SHORT no-sweep  ✗\n"
             "prev/cur high НЕ доходит до recent FH → нет sweep",
             fontsize=13, fontweight="bold", color="#7f8c8d")
ax.set_xlim(-0.5, 11)
ax.set_ylim(93, 114)
ax.set_xticks([]); ax.set_yticks([])
for spine in ax.spines.values(): spine.set_visible(False)


# ─── Bottom legend ────────────────────────────────────────
fig.text(0.5, 0.04,
         "SWEPT = «liquidity sweep» — wick пробил один из последних 5 × 2h Williams N=2 fractals (FL для LONG, FH для SHORT)   "
         "•   Это институциональный stop hunt: цена забирает SL'ы retail-трейдеров перед разворотом   "
         "•   ~60-65% всех 2h ob_vc на BTC оказываются SWEPT",
         ha="center", fontsize=10.5, color="#444", style="italic")

plt.subplots_adjust(left=0.03, right=0.97, top=0.92, bottom=0.07,
                    wspace=0.10, hspace=0.30)
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/ob_vc_swept_explanation.png"
plt.savefig(out, dpi=140, bbox_inches="tight")
print(f"Saved: {out}")
