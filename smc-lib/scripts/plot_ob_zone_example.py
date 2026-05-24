"""Иллюстрация зоны интереса OB по synthetic-эталонам из elements/ob/definition.md."""
from __future__ import annotations

import pathlib

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt


def draw_candle(ax, x, o, h, l, c, width=0.5):
    color = "#26a69a" if c >= o else "#ef5350"
    ax.plot([x, x], [l, h], color=color, linewidth=1.4, zorder=3)
    body_low, body_high = min(o, c), max(o, c)
    if body_high - body_low < 0.05: body_high = body_low + 0.05
    ax.add_patch(mpatches.Rectangle((x - width / 2, body_low), width, body_high - body_low,
                                    facecolor=color, edgecolor=color, alpha=0.95, zorder=4))


def annotate_price(ax, x, y, text, color="#37474f", offset=(8, 0), ha="left"):
    ax.annotate(text, (x, y), xytext=offset, textcoords="offset points",
                fontsize=9, color=color, fontweight="bold", ha=ha, va="center", zorder=6)


fig, (ax_l, ax_s) = plt.subplots(1, 2, figsize=(16, 8))

# === LONG OB ===
prev_l = (100, 102, 95, 96)   # bear
cur_l = (96, 105, 94, 104)    # bull

x_prev, x_cur = 1.0, 2.0
draw_candle(ax_l, x_prev, *prev_l)
draw_candle(ax_l, x_cur, *cur_l)

ax_l.set_xlim(0.3, 3.4)
ax_l.set_ylim(91, 108)
ax_l.set_title("LONG OB — synthetic example", fontsize=13, fontweight="bold")

zone_left, zone_right = 0.5, 3.2
breaker_left, breaker_right = 2.55, 3.2

# Зона интереса: [94, 104]
ax_l.add_patch(mpatches.Rectangle((zone_left, 94), zone_right - zone_left, 100 - 94,
                                  facecolor="#fff3e0", edgecolor="#ff9800", linewidth=1.2,
                                  linestyle="--", alpha=0.55, zorder=1, label="drop area [94, 100]"))
ax_l.add_patch(mpatches.Rectangle((zone_left, 100), zone_right - zone_left, 104 - 100,
                                  facecolor="#ffcc80", edgecolor="#ef6c00", linewidth=1.4,
                                  alpha=0.75, zorder=1, label="breaker block [100, 104]"))
ax_l.add_patch(mpatches.Rectangle((zone_left, 94), zone_right - zone_left, 104 - 94,
                                  facecolor="none", edgecolor="#bf360c", linewidth=2.0,
                                  linestyle="-", alpha=0.9, zorder=2))

annotate_price(ax_l, zone_right, 94, "94 = min(prev.low, cur.low)", offset=(6, 0))
annotate_price(ax_l, zone_right, 100, "100 = prev.open", offset=(6, 0))
annotate_price(ax_l, zone_right, 104, "104 = cur.close", offset=(6, 0))

annotate_price(ax_l, x_prev, 103, "prev (bear)", color="#ef5350", offset=(0, 12), ha="center")
annotate_price(ax_l, x_cur, 106, "cur (bull)", color="#26a69a", offset=(0, 12), ha="center")

ax_l.text(1.85, 96.5, "ZONE [94, 104]", fontsize=11, fontweight="bold", color="#bf360c", ha="center")

ax_l.set_ylabel("Price")
ax_l.set_xticks([])
ax_l.grid(True, alpha=0.25, axis="y")
ax_l.legend(loc="upper left", fontsize=9, framealpha=0.92)

# === SHORT OB ===
prev_s = (100, 105, 98, 104)   # bull
cur_s = (104, 106, 95, 96)     # bear

draw_candle(ax_s, x_prev, *prev_s)
draw_candle(ax_s, x_cur, *cur_s)

ax_s.set_xlim(0.3, 3.4)
ax_s.set_ylim(91, 108)
ax_s.set_title("SHORT OB — synthetic example", fontsize=13, fontweight="bold")

ax_s.add_patch(mpatches.Rectangle((zone_left, 100), zone_right - zone_left, 106 - 100,
                                  facecolor="#fff3e0", edgecolor="#ff9800", linewidth=1.2,
                                  linestyle="--", alpha=0.55, zorder=1, label="rally area [100, 106]"))
ax_s.add_patch(mpatches.Rectangle((zone_left, 96), zone_right - zone_left, 100 - 96,
                                  facecolor="#ffcc80", edgecolor="#ef6c00", linewidth=1.4,
                                  alpha=0.75, zorder=1, label="breaker block [96, 100]"))
ax_s.add_patch(mpatches.Rectangle((zone_left, 96), zone_right - zone_left, 106 - 96,
                                  facecolor="none", edgecolor="#bf360c", linewidth=2.0,
                                  linestyle="-", alpha=0.9, zorder=2))

annotate_price(ax_s, zone_right, 96, "96 = cur.close", offset=(6, 0))
annotate_price(ax_s, zone_right, 100, "100 = prev.open", offset=(6, 0))
annotate_price(ax_s, zone_right, 106, "106 = max(prev.high, cur.high)", offset=(6, 0))

annotate_price(ax_s, x_prev, 105.5, "prev (bull)", color="#26a69a", offset=(0, 12), ha="center")
annotate_price(ax_s, x_cur, 93.5, "cur (bear)", color="#ef5350", offset=(0, -14), ha="center")

ax_s.text(1.85, 103, "ZONE [96, 106]", fontsize=11, fontweight="bold", color="#bf360c", ha="center")

ax_s.set_xticks([])
ax_s.grid(True, alpha=0.25, axis="y")
ax_s.legend(loc="lower left", fontsize=9, framealpha=0.92)

fig.suptitle("OB — зона интереса = breaker block (подзона) + drop / rally area (подзона)",
             fontsize=14, fontweight="bold", y=1.00)
plt.tight_layout()

OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/ob_zone_example.png"
plt.savefig(OUT, dpi=130, bbox_inches="tight")
plt.close()
print(f"Saved {OUT}")
