"""Объяснение SWEPT по канону Strategy 1.1.1 (check_swept).

Канон (strategy_1_1_1_floating.py:194-214):
  LONG:  min(prev.low,  cur.low)  <  min(n-1.low,  n-2.low)
  SHORT: max(prev.high, cur.high) >  max(n-1.high, n-2.high)

Где n-1, n-2 — 2 бара НЕПОСРЕДСТВЕННО перед OB-парой (prev+cur).
"""
import pathlib
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

BULL = "#01a648"; BEAR = "#131b1b"; DOJI = "#888"
ORANGE = "#e67e22"
GRAY_LINE = "#7f8c8d"


def draw_candles(ax, candles, x_start=0, w=0.6, labels=None):
    """candles: list of (o, h, l, c) tuples."""
    for i, (o, h, l, c) in enumerate(candles):
        x = x_start + i
        col = BULL if c > o else (BEAR if c < o else DOJI)
        ax.vlines(x, l, h, color=col, linewidth=1.6, zorder=4)
        ax.add_patch(Rectangle((x - w/2, min(o, c)), w, max(abs(o-c), 0.05),
                                facecolor=col, edgecolor=col,
                                linewidth=1.6, zorder=4))
        if labels:
            ax.text(x, l - 0.5, labels[i], ha="center", va="top",
                    fontsize=10, fontweight="bold", color="#333")


fig, axes = plt.subplots(2, 2, figsize=(20, 12))
fig.suptitle("SWEPT по канону Strategy 1.1.1  —  check_swept(...)",
             fontsize=18, fontweight="bold", y=0.97)

LABELS = ["n-2", "n-1", "prev", "cur"]


# ─── Panel 1: LONG SWEPT ────────────────────────────────────
ax = axes[0, 0]
candles = [
    # (o, h, l, c)
    (101, 103, 100, 102),    # n-2 — bull
    (102, 103, 99, 100),     # n-1 — bear, low=99
    (100, 101, 96, 97),      # prev — bear, low=96  ← already < 99
    (97, 106, 95, 105),      # cur — bull engulf, low=95 (deeper sweep)
]
draw_candles(ax, candles, labels=LABELS)

# Level: min(n-1.low, n-2.low) = min(99, 100) = 99
LVL = 99
ax.axhline(LVL, xmin=0.05, xmax=0.95, color=ORANGE, linewidth=1.5,
           linestyle=(0, (5, 4)), zorder=2)
ax.text(0.1, LVL + 0.3, "  min(n-1.low, n-2.low) = $99", color=ORANGE,
        fontsize=11, fontweight="bold", va="bottom", zorder=10)

# Highlight sweep
ax.annotate("min(prev.low, cur.low) = $95\n→ < $99 → SWEPT ✓",
            xy=(3, 95), xytext=(0.3, 91),
            fontsize=11.5, fontweight="bold", color="#185c34",
            arrowprops=dict(arrowstyle="->", color="#185c34", lw=2), zorder=11)

# Mark OB pair
ax.add_patch(Rectangle((1.55, 95), 1.9, 12, facecolor="#4a90e2", alpha=0.08,
                        edgecolor="#4a90e2", linewidth=1.2,
                        linestyle=(0, (4, 4)), zorder=1))
ax.text(2.5, 107.5, "OB pair (prev+cur)", color="#2169b3",
        fontsize=10, fontweight="bold", ha="center", zorder=10)

ax.set_title("LONG SWEPT  ✓", fontsize=14, fontweight="bold", color="#185c34")
ax.set_xlim(-0.7, 3.7)
ax.set_ylim(89, 110)
ax.set_xticks([]); ax.set_yticks([])
for spine in ax.spines.values(): spine.set_visible(False)


# ─── Panel 2: LONG no-sweep ─────────────────────────────────
ax = axes[0, 1]
candles = [
    (101, 103, 100, 102),    # n-2 — bull, low=100
    (102, 103, 99, 100),     # n-1 — bear, low=99
    (100, 101, 99, 100),     # prev — small bear/doji, low=99 (= LVL, NOT < LVL)
    (100, 106, 99.5, 105),   # cur — bull engulf, low=99.5
]
draw_candles(ax, candles, labels=LABELS)

LVL = 99
ax.axhline(LVL, xmin=0.05, xmax=0.95, color=ORANGE, linewidth=1.5,
           linestyle=(0, (5, 4)), zorder=2)
ax.text(0.1, LVL + 0.3, "  min(n-1.low, n-2.low) = $99", color=ORANGE,
        fontsize=11, fontweight="bold", va="bottom", zorder=10)

ax.annotate("min(prev.low, cur.low) = $99\n→ НЕ < $99 → no sweep ✗",
            xy=(3, 99.5), xytext=(0.3, 91),
            fontsize=11.5, fontweight="bold", color="#7f8c8d",
            arrowprops=dict(arrowstyle="->", color="#7f8c8d", lw=2), zorder=11)

ax.add_patch(Rectangle((1.55, 99), 1.9, 8, facecolor="#4a90e2", alpha=0.08,
                        edgecolor="#4a90e2", linewidth=1.2,
                        linestyle=(0, (4, 4)), zorder=1))
ax.text(2.5, 107.5, "OB pair (prev+cur)", color="#2169b3",
        fontsize=10, fontweight="bold", ha="center", zorder=10)

ax.set_title("LONG no-sweep  ✗", fontsize=14, fontweight="bold", color="#7f8c8d")
ax.set_xlim(-0.7, 3.7)
ax.set_ylim(89, 110)
ax.set_xticks([]); ax.set_yticks([])
for spine in ax.spines.values(): spine.set_visible(False)


# ─── Panel 3: SHORT SWEPT ───────────────────────────────────
ax = axes[1, 0]
candles = [
    (99, 100, 97, 98),       # n-2 — bear
    (98, 101, 97, 100),      # n-1 — bull, high=101
    (100, 104, 99, 103),     # prev — bull, high=104 ← already > 101
    (103, 105, 94, 95),      # cur — bear engulf, high=105
]
draw_candles(ax, candles, labels=LABELS)

# Level: max(n-1.high, n-2.high) = max(101, 100) = 101
LVL = 101
ax.axhline(LVL, xmin=0.05, xmax=0.95, color=ORANGE, linewidth=1.5,
           linestyle=(0, (5, 4)), zorder=2)
ax.text(0.1, LVL - 0.3, "  max(n-1.high, n-2.high) = $101", color=ORANGE,
        fontsize=11, fontweight="bold", va="top", zorder=10)

ax.annotate("max(prev.high, cur.high) = $105\n→ > $101 → SWEPT ✓",
            xy=(3, 105), xytext=(0.3, 109),
            fontsize=11.5, fontweight="bold", color="#7d0000",
            arrowprops=dict(arrowstyle="->", color="#7d0000", lw=2), zorder=11)

ax.add_patch(Rectangle((1.55, 94), 1.9, 11, facecolor="#c0392b", alpha=0.07,
                        edgecolor="#c0392b", linewidth=1.2,
                        linestyle=(0, (4, 4)), zorder=1))
ax.text(2.5, 92, "OB pair (prev+cur)", color="#7d0000",
        fontsize=10, fontweight="bold", ha="center", zorder=10)

ax.set_title("SHORT SWEPT  ✓", fontsize=14, fontweight="bold", color="#7d0000")
ax.set_xlim(-0.7, 3.7)
ax.set_ylim(89, 112)
ax.set_xticks([]); ax.set_yticks([])
for spine in ax.spines.values(): spine.set_visible(False)


# ─── Panel 4: SHORT no-sweep ────────────────────────────────
ax = axes[1, 1]
candles = [
    (99, 100, 97, 98),       # n-2
    (98, 101, 97, 100),      # n-1, high=101
    (100, 101, 99, 100),     # prev, high=101 (= LVL, NOT > LVL)
    (100, 101, 94, 95),      # cur — bear, high=101
]
draw_candles(ax, candles, labels=LABELS)

LVL = 101
ax.axhline(LVL, xmin=0.05, xmax=0.95, color=ORANGE, linewidth=1.5,
           linestyle=(0, (5, 4)), zorder=2)
ax.text(0.1, LVL - 0.3, "  max(n-1.high, n-2.high) = $101", color=ORANGE,
        fontsize=11, fontweight="bold", va="top", zorder=10)

ax.annotate("max(prev.high, cur.high) = $101\n→ НЕ > $101 → no sweep ✗",
            xy=(3, 100.5), xytext=(0.3, 109),
            fontsize=11.5, fontweight="bold", color="#7f8c8d",
            arrowprops=dict(arrowstyle="->", color="#7f8c8d", lw=2), zorder=11)

ax.add_patch(Rectangle((1.55, 94), 1.9, 8, facecolor="#c0392b", alpha=0.07,
                        edgecolor="#c0392b", linewidth=1.2,
                        linestyle=(0, (4, 4)), zorder=1))
ax.text(2.5, 92, "OB pair (prev+cur)", color="#7d0000",
        fontsize=10, fontweight="bold", ha="center", zorder=10)

ax.set_title("SHORT no-sweep  ✗", fontsize=14, fontweight="bold", color="#7f8c8d")
ax.set_xlim(-0.7, 3.7)
ax.set_ylim(89, 112)
ax.set_xticks([]); ax.set_yticks([])
for spine in ax.spines.values(): spine.set_visible(False)


# Bottom formula
fig.text(0.5, 0.04,
         "LONG SWEPT  ⇔  min(prev.low,  cur.low)  <  min(n-1.low,  n-2.low)        "
         "SHORT SWEPT  ⇔  max(prev.high, cur.high)  >  max(n-1.high, n-2.high)",
         ha="center", fontsize=12, fontweight="bold", color="#222", family="monospace")
fig.text(0.5, 0.015,
         "n-1 и n-2 = два бара НЕПОСРЕДСТВЕННО перед OB-парой (на той же HTF: 2h или 1h)",
         ha="center", fontsize=10.5, color="#444", style="italic")

plt.subplots_adjust(left=0.03, right=0.97, top=0.92, bottom=0.09,
                    wspace=0.08, hspace=0.25)
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/ob_vc_swept_1_1_1.png"
plt.savefig(out, dpi=140, bbox_inches="tight")
print(f"Saved: {out}")
