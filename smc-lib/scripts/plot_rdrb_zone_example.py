"""Иллюстрация зоны интереса RDRB (POI + block + liq).

LONG V1 — synthetic (block примыкает к верху POI, liq снизу).
SHORT V1 — canon BTC 1h 2026-05-22 (block примыкает к низу POI, liq сверху).
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


fig, (ax_l, ax_s) = plt.subplots(1, 2, figsize=(17, 9))

# =========================================================
# LONG V1 — synthetic
# =========================================================
c1_l = (100, 130, 99, 120)    # bull
c2_l = (120, 140, 119, 138)   # bull (displacement up, close > C1.high)
c3_l = (138, 139, 124, 129)   # bear

for i, (o, h, l, c) in enumerate([c1_l, c2_l, c3_l]):
    draw_candle(ax_l, i + 1.0, o, h, l, c)

ax_l.set_xlim(0.3, 5.0)
ax_l.set_ylim(95, 145)
ax_l.set_title("LONG V1 RDRB — synthetic (block сверху POI, liq снизу)",
               fontsize=13, fontweight="bold")

zone_left, zone_right = 0.5, 4.6
poi_low, poi_high = 120, 129
block_low, block_high = 124, 129
liq_low, liq_high = 120, 124

# liq (подзона) — снизу
ax_l.add_patch(mpatches.Rectangle((zone_left, liq_low), zone_right - zone_left, liq_high - liq_low,
                                  facecolor="#fff3e0", edgecolor="#ff9800", linewidth=1.2,
                                  linestyle="--", alpha=0.6, zorder=1,
                                  label=f"liq [{liq_low}, {liq_high}] (h={liq_high - liq_low})"))
# block (подзона) — сверху
ax_l.add_patch(mpatches.Rectangle((zone_left, block_low), zone_right - zone_left, block_high - block_low,
                                  facecolor="#ffcc80", edgecolor="#ef6c00", linewidth=1.4,
                                  alpha=0.78, zorder=1,
                                  label=f"block [{block_low}, {block_high}] (h={block_high - block_low})"))
# POI рамка
ax_l.add_patch(mpatches.Rectangle((zone_left, poi_low), zone_right - zone_left, poi_high - poi_low,
                                  facecolor="none", edgecolor="#bf360c", linewidth=2.0, zorder=2))

annotate_label(ax_l, zone_right, poi_low, f"{poi_low} = C1.body_top (POI.bottom = liq.bottom)")
annotate_label(ax_l, zone_right, block_low, f"{block_low} = max(C1.body_top, C3.low) (liq.top = block.bottom)")
annotate_label(ax_l, zone_right, block_high, f"{block_high} = min(C1.high, C3.body_bottom) (POI.top = block.top)")

annotate_label(ax_l, 1.0, c1_l[1] + 1, "C1 (bull)", color="#26a69a", offset=(0, 8), ha="center")
annotate_label(ax_l, 2.0, c2_l[1] + 1, "C2 (bull, displacement)", color="#26a69a", offset=(0, 8), ha="center")
annotate_label(ax_l, 3.0, c3_l[1] + 1, "C3 (bear)", color="#ef5350", offset=(0, 8), ha="center")

ax_l.text(3.7, (poi_low + poi_high) / 2, f"POI [{poi_low}, {poi_high}]",
          fontsize=11, fontweight="bold", color="#bf360c", ha="center",
          bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#bf360c", alpha=0.85))

ax_l.set_ylabel("Price")
ax_l.set_xticks([])
ax_l.grid(True, alpha=0.25, axis="y")
ax_l.legend(loc="upper left", fontsize=9, framealpha=0.92)

# =========================================================
# SHORT V1 — canon BTC 1h 2026-05-22
# =========================================================
c1_s = (77423.41, 77543.38, 77288.77, 77408.06)  # bear
c2_s = (77408.07, 77535.00, 77216.00, 77267.38)  # bear (displacement down)
c3_s = (77267.39, 77360.00, 77200.00, 77307.11)  # bull

for i, (o, h, l, c) in enumerate([c1_s, c2_s, c3_s]):
    draw_candle(ax_s, i + 1.0, o, h, l, c)

ax_s.set_xlim(0.3, 5.0)
ax_s.set_ylim(77150, 77600)
ax_s.set_title("SHORT V1 RDRB — BTC 1h 2026-05-22 (canon)",
               fontsize=13, fontweight="bold")

poi_low_s, poi_high_s = 77307.11, 77408.06
block_low_s, block_high_s = 77307.11, 77360.00
liq_low_s, liq_high_s = 77360.00, 77408.06

# liq (подзона) — сверху
ax_s.add_patch(mpatches.Rectangle((zone_left, liq_low_s), zone_right - zone_left, liq_high_s - liq_low_s,
                                  facecolor="#fff3e0", edgecolor="#ff9800", linewidth=1.2,
                                  linestyle="--", alpha=0.6, zorder=1,
                                  label=f"liq [{liq_low_s:.2f}, {liq_high_s:.2f}] (h={liq_high_s - liq_low_s:.2f})"))
# block (подзона) — снизу
ax_s.add_patch(mpatches.Rectangle((zone_left, block_low_s), zone_right - zone_left, block_high_s - block_low_s,
                                  facecolor="#ffcc80", edgecolor="#ef6c00", linewidth=1.4,
                                  alpha=0.78, zorder=1,
                                  label=f"block [{block_low_s:.2f}, {block_high_s:.2f}] (h={block_high_s - block_low_s:.2f})"))
# POI рамка
ax_s.add_patch(mpatches.Rectangle((zone_left, poi_low_s), zone_right - zone_left, poi_high_s - poi_low_s,
                                  facecolor="none", edgecolor="#bf360c", linewidth=2.0, zorder=2))

annotate_label(ax_s, zone_right, poi_low_s, f"{poi_low_s:.2f} = max(C1.low, C3.body_top) (POI.bottom = block.bottom)")
annotate_label(ax_s, zone_right, block_high_s, f"{block_high_s:.2f} = min(C1.body_bottom, C3.high) (block.top = liq.bottom)")
annotate_label(ax_s, zone_right, poi_high_s, f"{poi_high_s:.2f} = C1.body_bottom (POI.top = liq.top)")

annotate_label(ax_s, 1.0, c1_s[2] - 6, "C1 (bear)", color="#ef5350", offset=(0, -12), ha="center")
annotate_label(ax_s, 2.0, c2_s[2] - 6, "C2 (bear, displacement)", color="#ef5350", offset=(0, -12), ha="center")
annotate_label(ax_s, 3.0, c3_s[2] - 6, "C3 (bull)", color="#26a69a", offset=(0, -12), ha="center")

ax_s.text(3.7, (poi_low_s + poi_high_s) / 2, f"POI [{poi_low_s:.2f}, {poi_high_s:.2f}]",
          fontsize=11, fontweight="bold", color="#bf360c", ha="center",
          bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#bf360c", alpha=0.85))

ax_s.set_ylabel("Price (USDT)")
ax_s.set_xticks([])
ax_s.grid(True, alpha=0.25, axis="y")
ax_s.legend(loc="lower left", fontsize=9, framealpha=0.92)

fig.suptitle("RDRB — POI (зона интереса) = block (эффективность) + liq (ликвидность)  ·  V1: liq ≠ ∅",
             fontsize=14, fontweight="bold", y=1.00)
plt.tight_layout()

OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/rdrb_zone_example.png"
plt.savefig(OUT, dpi=130, bbox_inches="tight")
plt.close()
print(f"Saved {OUT}")
