"""Иллюстрация зоны интереса FVG (Fair Value Gap).

LONG — synthetic.
SHORT — canon BTC 4h 2026-05-21 (FVG.c1, c2, c3 из elements/fvg/definition.md).
"""
from __future__ import annotations

import pathlib

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt


def draw_candle(ax, x, o, h, l, c, width=0.55, alpha=0.95):
    color = "#26a69a" if c >= o else "#ef5350"
    ax.plot([x, x], [l, h], color=color, linewidth=1.4, zorder=3)
    body_low, body_high = min(o, c), max(o, c)
    if body_high - body_low < 0.005 * max(1, h - l):
        body_high = body_low + 0.005 * max(1, h - l)
    ax.add_patch(mpatches.Rectangle((x - width / 2, body_low), width, body_high - body_low,
                                    facecolor=color, edgecolor=color, alpha=alpha, zorder=4))


def annotate_label(ax, x, y, text, color="#37474f", offset=(6, 0), ha="left"):
    ax.annotate(text, (x, y), xytext=offset, textcoords="offset points",
                fontsize=9, color=color, fontweight="bold", ha=ha, va="center", zorder=6)


fig, (ax_l, ax_s) = plt.subplots(1, 2, figsize=(16, 8))

# =========================================================
# LONG FVG — synthetic
# =========================================================
c1_l = (100, 105, 98, 104)    # bull
c2_l = (104, 115, 103, 113)   # bull (displacement up — большое тело)
c3_l = (113, 118, 110, 116)   # bull (c3.low > c1.high → gap)

for i, candle in enumerate([c1_l, c2_l, c3_l]):
    draw_candle(ax_l, i + 1.0, *candle)

ax_l.set_xlim(0.3, 4.8)
ax_l.set_ylim(95, 121)
ax_l.set_title("LONG FVG (bullish) — synthetic", fontsize=13, fontweight="bold")

zone_left, zone_right = 0.5, 4.4
c1_high_l, c3_low_l = c1_l[1], c3_l[2]   # 105, 110

ax_l.add_patch(mpatches.Rectangle((zone_left, c1_high_l), zone_right - zone_left, c3_low_l - c1_high_l,
                                  facecolor="#e1f5fe", edgecolor="#0277bd", linewidth=2.0,
                                  alpha=0.55, zorder=1,
                                  label=f"FVG zone [{c1_high_l}, {c3_low_l}] (h={c3_low_l - c1_high_l})"))

annotate_label(ax_l, zone_right, c1_high_l, f"{c1_high_l} = c1.high (zone.bottom)")
annotate_label(ax_l, zone_right, c3_low_l, f"{c3_low_l} = c3.low (zone.top)")

annotate_label(ax_l, 1.0, c1_l[1] + 0.5, "c1 (bull)", color="#26a69a", offset=(0, 10), ha="center")
annotate_label(ax_l, 2.0, c2_l[1] + 0.5, "c2 (bull, displacement)", color="#26a69a", offset=(0, 10), ha="center")
annotate_label(ax_l, 3.0, c3_l[1] + 0.5, "c3 (bull)", color="#26a69a", offset=(0, 10), ha="center")

ax_l.text(3.7, (c1_high_l + c3_low_l) / 2, "GAP",
          fontsize=12, fontweight="bold", color="#01579b", ha="center",
          bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#0277bd", alpha=0.9))

ax_l.set_ylabel("Price")
ax_l.set_xticks([])
ax_l.grid(True, alpha=0.25, axis="y")
ax_l.legend(loc="upper left", fontsize=9, framealpha=0.92)

# =========================================================
# SHORT FVG — canon BTC 4h 2026-05-21 (FVG.c1, c2, c3)
# =========================================================
c1_s = (78078.72, 78180.01, 77521.00, 77889.01)   # bear
c2_s = (77889.01, 78200.00, 77147.15, 77189.10)   # bear (displacement down)
c3_s = (77189.10, 77402.12, 76719.47, 77259.46)   # bull

for i, candle in enumerate([c1_s, c2_s, c3_s]):
    draw_candle(ax_s, i + 1.0, *candle)

ax_s.set_xlim(0.3, 4.8)
ax_s.set_ylim(76600, 78300)
ax_s.set_title("SHORT FVG (bearish) — BTC 4h 2026-05-21 (canon)", fontsize=13, fontweight="bold")

c3_high_s, c1_low_s = c3_s[1], c1_s[2]   # 77402.12, 77521.00

ax_s.add_patch(mpatches.Rectangle((zone_left, c3_high_s), zone_right - zone_left, c1_low_s - c3_high_s,
                                  facecolor="#e1f5fe", edgecolor="#0277bd", linewidth=2.0,
                                  alpha=0.55, zorder=1,
                                  label=f"FVG zone [{c3_high_s:.2f}, {c1_low_s:.2f}] (h={c1_low_s - c3_high_s:.2f})"))

annotate_label(ax_s, zone_right, c3_high_s, f"{c3_high_s:.2f} = c3.high (zone.bottom)")
annotate_label(ax_s, zone_right, c1_low_s, f"{c1_low_s:.2f} = c1.low (zone.top)")

annotate_label(ax_s, 1.0, c1_s[1] + 30, "c1 (bear)", color="#ef5350", offset=(0, 10), ha="center")
annotate_label(ax_s, 2.0, c2_s[1] + 30, "c2 (bear, displacement)", color="#ef5350", offset=(0, 10), ha="center")
annotate_label(ax_s, 3.0, c3_s[1] + 30, "c3 (bull)", color="#26a69a", offset=(0, 10), ha="center")

ax_s.text(3.7, (c3_high_s + c1_low_s) / 2, "GAP",
          fontsize=12, fontweight="bold", color="#01579b", ha="center",
          bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#0277bd", alpha=0.9))

ax_s.set_ylabel("Price (USDT)")
ax_s.set_xticks([])
ax_s.grid(True, alpha=0.25, axis="y")
ax_s.legend(loc="lower left", fontsize=9, framealpha=0.92)

fig.suptitle("FVG — Fair Value Gap: зона между c1 и c3, через которую c2 совершила displacement",
             fontsize=14, fontweight="bold", y=1.00)
plt.tight_layout()

OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/fvg_zone_example.png"
plt.savefig(OUT, dpi=130, bbox_inches="tight")
plt.close()
print(f"Saved {OUT}")
