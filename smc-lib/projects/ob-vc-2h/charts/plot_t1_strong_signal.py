"""Признаки «сильного» LONG OB:
  1) extreme = prev (prev.low < cur.low)
  2) prev wick low ≥ 2× cur wick low

Пример: наш T1 cur 05-06 23:00 МСК — ratio 3.25×.
"""
import pathlib
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch
from matplotlib.lines import Line2D

BULL = "#01a648"; BEAR = "#131b1b"
RED = "#c0392b"; GREEN = "#27ae60"; PURPLE = "#9b59b6"


def draw_candle(ax, x, o, h, l, c, w=0.55):
    col = BULL if c > o else (BEAR if c < o else "#888")
    ax.vlines(x, l, h, color=col, linewidth=2.2, zorder=4)
    ax.add_patch(Rectangle((x - w/2, min(o, c)), w, max(abs(o-c), 0.1),
                            facecolor=col, edgecolor=col,
                            linewidth=2.2, zorder=4))


fig, ax = plt.subplots(figsize=(14, 11))
fig.suptitle("Признаки сильного LONG OB  —  T1 SWEPT с глубоким prev wick",
             fontsize=15, fontweight="bold", y=0.97)

# prev BEAR: open=100, close=94, low=88, high=101
# cur BULL: open=94, close=110, low=92, high=112
PREV = dict(o=100, h=101, l=88, c=94)
CUR  = dict(o=94, h=112, l=92, c=110)

draw_candle(ax, 1, **PREV)
draw_candle(ax, 2, **CUR)

# Body bottoms
prev_body_lo = min(PREV["o"], PREV["c"])  # = 94
cur_body_lo = min(CUR["o"], CUR["c"])    # = 94
prev_wick = prev_body_lo - PREV["l"]      # = 6
cur_wick  = cur_body_lo - CUR["l"]        # = 2
ratio = prev_wick / cur_wick

# Mark prev wick with bracket
ax.annotate("", xy=(0.45, PREV["l"]), xytext=(0.45, prev_body_lo),
            arrowprops=dict(arrowstyle="<->", color=RED, lw=2.5),
            zorder=5)
ax.text(0.32, (PREV["l"] + prev_body_lo)/2, f"prev wick\n${prev_wick:.0f}",
        ha="right", va="center", fontsize=12, fontweight="bold", color=RED, zorder=6)

# Mark cur wick with bracket
ax.annotate("", xy=(2.55, CUR["l"]), xytext=(2.55, cur_body_lo),
            arrowprops=dict(arrowstyle="<->", color=GREEN, lw=2.5),
            zorder=5)
ax.text(2.68, (CUR["l"] + cur_body_lo)/2, f"cur wick\n${cur_wick:.0f}",
        ha="left", va="center", fontsize=12, fontweight="bold", color=GREEN, zorder=6)

# Mark extreme (low)
ax.axhline(PREV["l"], xmin=0.05, xmax=0.95, color=PURPLE, linewidth=1.0,
           linestyle=(0, (3, 3)), zorder=2)
ax.text(0.1, PREV["l"] + 0.3, f"  extreme low = prev.low = {PREV['l']}",
        color=PURPLE, fontsize=11, fontweight="bold", va="bottom", zorder=10)

# Mark cur.low for contrast
ax.scatter([2], [CUR["l"]], s=80, color=GREEN, marker="o", zorder=11,
            edgecolors="white", linewidths=1.5)
ax.text(2.0, CUR["l"] - 1.0, f"cur.low\n{CUR['l']}", color=GREEN,
        fontsize=10, fontweight="bold", ha="center", va="top", zorder=11)

# Ratio annotation top
ax.text(1.5, 117, f"prev wick / cur wick  =  ${prev_wick:.0f} / ${cur_wick:.0f}  =  {ratio:.2f}×",
        ha="center", fontsize=15, fontweight="bold", color="#222",
        bbox=dict(facecolor="#fff8e1", edgecolor="#f1c40f", boxstyle="round,pad=0.6", linewidth=2))

# Candle labels
ax.text(1, 105, "prev (bear)", ha="center", fontsize=12, color=BEAR, fontweight="bold")
ax.text(2, 115, "cur (bull engulf)", ha="center", fontsize=12, color=BULL, fontweight="bold")

# Side text — conditions
cond_text = (
    "✅  Условие 1:  extreme = prev\n"
    f"      prev.low ({PREV['l']}) < cur.low ({CUR['l']})\n"
    "      → prev сделал deepest dip (sweep)\n\n"
    "✅  Условие 2:  prev_wick ≥ 2× cur_wick\n"
    f"      ${prev_wick:.0f}  ≥  2 × ${cur_wick:.0f}  ({ratio:.2f}× в нашем кейсе)\n"
    "      → cur не пошёл глубоко →\n"
    "          покупатели уже стояли,\n"
    "          bull engulf начался почти сразу"
)
ax.text(3.8, 100, cond_text, ha="left", va="center", fontsize=11,
        color="#222",
        bbox=dict(facecolor="#eafaf1", edgecolor=GREEN, boxstyle="round,pad=0.8",
                  linewidth=1.5))

# Bottom interpretation
interp = (
    "📌 Интерпретация:\n"
    "Структурно это «classical bullish exhaustion-after-sweep»:\n"
    "  • prev wick down = stop-hunt (institutional liquidity grab)\n"
    "  • cur shallow wick = немедленный bull-impulse без deep retracement\n"
    "  • → setup сильнее обычного T1\n\n"
    "Гипотеза: T1 с ratio ≥ 2× может иметь WR > 60% (vs 54.8% baseline)\n"
    "→ Кандидат на Stage B winning sub-filter"
)
ax.text(0.05, 86,
        interp,
        ha="left", va="top", fontsize=10.5, color="#333",
        bbox=dict(facecolor="#fafafa", edgecolor="#999", boxstyle="round,pad=0.6"),
        transform=ax.transData)


ax.set_xlim(-0.2, 8.5)
ax.set_ylim(78, 121)
ax.set_xticks([]); ax.set_yticks([])
for spine in ax.spines.values(): spine.set_visible(False)

plt.tight_layout()
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/ob_vc_2h_T1_strong_wick_ratio.png"
plt.savefig(out, dpi=140, bbox_inches="tight")
print(f"Saved: {out}")
