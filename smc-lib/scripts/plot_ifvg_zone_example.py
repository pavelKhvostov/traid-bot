"""Иллюстрация iFVG (Inverse FVG).

iFVG = FVG-B противоположного направления, первая после untouched FVG-A,
свечи которой ПЕРВЫМИ касаются зоны A. После события зона A инвертирует роль
(support → resistance или наоборот).

LEFT — bull→bear iFVG (зона A была support, становится resistance).
RIGHT — bear→bull iFVG (зона A была resistance, становится support).
"""
from __future__ import annotations

import pathlib

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt


def draw_candle(ax, x, o, h, l, c, width=0.5, alpha=0.95):
    color = "#26a69a" if c >= o else "#ef5350"
    ax.plot([x, x], [l, h], color=color, linewidth=1.4, zorder=3)
    body_low, body_high = min(o, c), max(o, c)
    if body_high - body_low < 0.005 * max(1, h - l):
        body_high = body_low + 0.005 * max(1, h - l)
    ax.add_patch(mpatches.Rectangle((x - width / 2, body_low), width, body_high - body_low,
                                    facecolor=color, edgecolor=color, alpha=alpha, zorder=4))


def annotate_label(ax, x, y, text, color="#37474f", offset=(6, 0), ha="left", fontsize=8.5):
    ax.annotate(text, (x, y), xytext=offset, textcoords="offset points",
                fontsize=fontsize, color=color, fontweight="bold", ha=ha, va="center", zorder=6)


fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(18, 9))

# =========================================================
# LEFT: bull→bear iFVG (FVG-A bullish, B bearish)
# =========================================================
# FVG-A (bullish): c1.high < c3.low
A_l = [
    (100, 105, 99, 104),    # c1_A bull
    (104, 120, 103, 119),   # c2_A bull displacement up
    (119, 124, 115, 122),   # c3_A bull (low=115)
]
# FVG-B (bearish): c1.low > c3.high. c2_B пробивает зону A первой.
B_l = [
    (130, 132, 118, 119),   # c1_B bear (low=118)
    (119, 120, 102, 104),   # c2_B bear displacement down (touches FVG-A first)
    (104, 108, 100, 105),   # c3_B bear (high=108)
]

xs = [1, 2, 3, 4.5, 5.5, 6.5]
for x, c in zip(xs[:3], A_l): draw_candle(ax_l, x, *c)
for x, c in zip(xs[3:], B_l): draw_candle(ax_l, x, *c)

ax_l.axvline(3.75, color="#9e9e9e", linestyle=":", linewidth=1.2, zorder=2)
ax_l.text(3.75, 134, "… untouched bars …", fontsize=8.5, color="#757575", ha="center", style="italic")

zone_left, zone_right = 0.5, 7.2
fvg_a = (105, 115)        # bull FVG-A: [c1.high, c3.low]
fvg_b = (108, 118)        # bear FVG-B: [c3.high, c1.low]
overlap = (max(fvg_a[0], fvg_b[0]), min(fvg_a[1], fvg_b[1]))  # [108, 115]

# FVG-A
ax_l.add_patch(mpatches.Rectangle((zone_left, fvg_a[0]), zone_right - zone_left, fvg_a[1] - fvg_a[0],
                                  facecolor="#c8e6c9", edgecolor="#2e7d32", linewidth=1.6,
                                  alpha=0.55, zorder=1,
                                  label=f"FVG-A bullish (was support) [{fvg_a[0]}, {fvg_a[1]}]"))
# FVG-B
ax_l.add_patch(mpatches.Rectangle((zone_left, fvg_b[0]), zone_right - zone_left, fvg_b[1] - fvg_b[0],
                                  facecolor="#ffcdd2", edgecolor="#c62828", linewidth=1.6,
                                  linestyle="--", alpha=0.45, zorder=1,
                                  label=f"FVG-B bearish (the iFVG) [{fvg_b[0]}, {fvg_b[1]}]"))
# Overlap
ax_l.add_patch(mpatches.Rectangle((zone_left, overlap[0]), zone_right - zone_left, overlap[1] - overlap[0],
                                  facecolor="#fff59d", edgecolor="#f57f17", linewidth=2.0,
                                  alpha=0.85, zorder=2,
                                  label=f"overlap (iFVG event zone) [{overlap[0]}, {overlap[1]}]"))

annotate_label(ax_l, zone_right, fvg_a[0], f"{fvg_a[0]} = A.c1.high (A.bottom)")
annotate_label(ax_l, zone_right, overlap[0], f"{overlap[0]} = B.c3.high (B.bottom)")
annotate_label(ax_l, zone_right, overlap[1], f"{overlap[1]} = A.c3.low (A.top)")
annotate_label(ax_l, zone_right, fvg_b[1], f"{fvg_b[1]} = B.c1.low (B.top)")

# Подписи свечей
for x, c, lbl, col in zip(xs[:3], A_l, ["A.c1", "A.c2 (displ)", "A.c3"], ["#26a69a"] * 3):
    annotate_label(ax_l, x, c[1] + 1.2, lbl, color=col, offset=(0, 8), ha="center", fontsize=8)
for x, c, lbl, col in zip(xs[3:], B_l, ["B.c1", "B.c2 (displ, touch)", "B.c3"], ["#ef5350"] * 3):
    annotate_label(ax_l, x, c[1] + 1.2, lbl, color=col, offset=(0, 8), ha="center", fontsize=8)

# Стрелка-аннотация инверсии
ax_l.annotate("A: support → resistance", xy=(6.5, fvg_a[1]), xytext=(5.0, 128),
              fontsize=10, fontweight="bold", color="#bf360c",
              arrowprops=dict(arrowstyle="->", color="#bf360c", lw=1.4),
              ha="center")

ax_l.set_xlim(0.3, 7.7)
ax_l.set_ylim(96, 137)
ax_l.set_title("bull → bear iFVG  (FVG-A была support, становится resistance)",
               fontsize=12, fontweight="bold")
ax_l.set_ylabel("Price")
ax_l.set_xticks([])
ax_l.grid(True, alpha=0.25, axis="y")
ax_l.legend(loc="lower right", fontsize=8.5, framealpha=0.92)

# =========================================================
# RIGHT: bear→bull iFVG (FVG-A bearish, B bullish)
# =========================================================
# FVG-A (bearish): c1.low > c3.high
A_r = [
    (100, 101, 95, 96),     # c1_A bear (low=95)
    (96, 97, 80, 81),       # c2_A bear displacement down
    (81, 85, 76, 78),       # c3_A bear (high=85)
]
# FVG-B (bullish): c1.high < c3.low. c2_B пробивает зону A первой.
B_r = [
    (70, 82, 68, 81),       # c1_B bull (high=82)
    (81, 98, 80, 96),       # c2_B bull displacement up (touches FVG-A first)
    (96, 100, 92, 95),      # c3_B bull (low=92)
]

for x, c in zip(xs[:3], A_r): draw_candle(ax_r, x, *c)
for x, c in zip(xs[3:], B_r): draw_candle(ax_r, x, *c)

ax_r.axvline(3.75, color="#9e9e9e", linestyle=":", linewidth=1.2, zorder=2)
ax_r.text(3.75, 67, "… untouched bars …", fontsize=8.5, color="#757575", ha="center", style="italic")

fvg_a_r = (85, 95)         # bear FVG-A: [c3.high, c1.low]
fvg_b_r = (82, 92)         # bull FVG-B: [c1.high, c3.low]
overlap_r = (max(fvg_a_r[0], fvg_b_r[0]), min(fvg_a_r[1], fvg_b_r[1]))  # [85, 92]

ax_r.add_patch(mpatches.Rectangle((zone_left, fvg_a_r[0]), zone_right - zone_left, fvg_a_r[1] - fvg_a_r[0],
                                  facecolor="#ffcdd2", edgecolor="#c62828", linewidth=1.6,
                                  alpha=0.55, zorder=1,
                                  label=f"FVG-A bearish (was resistance) [{fvg_a_r[0]}, {fvg_a_r[1]}]"))
ax_r.add_patch(mpatches.Rectangle((zone_left, fvg_b_r[0]), zone_right - zone_left, fvg_b_r[1] - fvg_b_r[0],
                                  facecolor="#c8e6c9", edgecolor="#2e7d32", linewidth=1.6,
                                  linestyle="--", alpha=0.45, zorder=1,
                                  label=f"FVG-B bullish (the iFVG) [{fvg_b_r[0]}, {fvg_b_r[1]}]"))
ax_r.add_patch(mpatches.Rectangle((zone_left, overlap_r[0]), zone_right - zone_left, overlap_r[1] - overlap_r[0],
                                  facecolor="#fff59d", edgecolor="#f57f17", linewidth=2.0,
                                  alpha=0.85, zorder=2,
                                  label=f"overlap (iFVG event zone) [{overlap_r[0]}, {overlap_r[1]}]"))

annotate_label(ax_r, zone_right, fvg_b_r[0], f"{fvg_b_r[0]} = B.c1.high (B.bottom)")
annotate_label(ax_r, zone_right, overlap_r[0], f"{overlap_r[0]} = A.c3.high (A.bottom)")
annotate_label(ax_r, zone_right, overlap_r[1], f"{overlap_r[1]} = B.c3.low (B.top)")
annotate_label(ax_r, zone_right, fvg_a_r[1], f"{fvg_a_r[1]} = A.c1.low (A.top)")

for x, c, lbl, col in zip(xs[:3], A_r, ["A.c1", "A.c2 (displ)", "A.c3"], ["#ef5350"] * 3):
    annotate_label(ax_r, x, c[2] - 1.5, lbl, color=col, offset=(0, -10), ha="center", fontsize=8)
for x, c, lbl, col in zip(xs[3:], B_r, ["B.c1", "B.c2 (displ, touch)", "B.c3"], ["#26a69a"] * 3):
    annotate_label(ax_r, x, c[1] + 1.2, lbl, color=col, offset=(0, 8), ha="center", fontsize=8)

ax_r.annotate("A: resistance → support", xy=(6.5, fvg_a_r[0]), xytext=(5.0, 72),
              fontsize=10, fontweight="bold", color="#2e7d32",
              arrowprops=dict(arrowstyle="->", color="#2e7d32", lw=1.4),
              ha="center")

ax_r.set_xlim(0.3, 7.7)
ax_r.set_ylim(65, 103)
ax_r.set_title("bear → bull iFVG  (FVG-A была resistance, становится support)",
               fontsize=12, fontweight="bold")
ax_r.set_ylabel("Price")
ax_r.set_xticks([])
ax_r.grid(True, alpha=0.25, axis="y")
ax_r.legend(loc="upper right", fontsize=8.5, framealpha=0.92)

fig.suptitle("iFVG (Inverse FVG) — противоположная FVG-B первой касается untouched FVG-A → роль A инвертирует",
             fontsize=13, fontweight="bold", y=1.00)
plt.tight_layout()

OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/ifvg_zone_example.png"
plt.savefig(OUT, dpi=130, bbox_inches="tight")
plt.close()
print(f"Saved {OUT}")
