"""Иллюстрация зоны интереса ob_liq.

5 свечей: prev-2, prev-1, prev, cur, cur+1.
- Зона входа = canon-OB (узкая, drop/rally area без breaker block).
- liq_zone = маркер ликвидности (нижняя/верхняя часть entry zone, где prev зафитилила свинг).
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


fig, (ax_l, ax_s) = plt.subplots(1, 2, figsize=(17, 9))

# =========================================================
# LONG ob_liq — synthetic
# Условия:
#  prev_lower (11) > 3 * cur_lower (6)  ✓
#  prev_lower (11) > prev_body (4)      ✓
#  prev.low (85) < min(прочих low) = 92 ✓
# =========================================================
long_candles = [
    ("prev-2", 95, 98, 92, 97),     # bull
    ("prev-1", 97, 101, 94, 100),   # bull
    ("prev",  100, 102, 85, 96),    # bear, длинный нижний фитиль
    ("cur",    96, 104, 94, 103),   # bull, cur.close (103) > prev.open (100) ✓
    ("cur+1", 103, 108, 95, 106),   # bull
]

for i, (_, o, h, l, c) in enumerate(long_candles):
    draw_candle(ax_l, i + 1.0, o, h, l, c)

ax_l.set_xlim(0.3, 7.6)
ax_l.set_ylim(82, 112)
ax_l.set_title("LONG ob_liq — synthetic (выраженный нижний фитиль prev = liquidity sweep)",
               fontsize=12, fontweight="bold")

zone_left, zone_right = 0.5, 6.7
prev_open, prev_low, cur_low = 100, 85, 94

# Зона входа canon-OB: [min(prev.low, cur.low), prev.open] = [85, 100]
# liq_zone: [prev.low, cur.low] = [85, 94] — нижняя часть entry zone
ax_l.add_patch(mpatches.Rectangle((zone_left, cur_low), zone_right - zone_left, prev_open - cur_low,
                                  facecolor="#fff3e0", edgecolor="#ff9800", linewidth=1.2,
                                  linestyle="--", alpha=0.55, zorder=1,
                                  label=f"entry (без liq) [{cur_low}, {prev_open}] (h={prev_open - cur_low})"))
ax_l.add_patch(mpatches.Rectangle((zone_left, prev_low), zone_right - zone_left, cur_low - prev_low,
                                  facecolor="#bbdefb", edgecolor="#1565c0", linewidth=1.4,
                                  alpha=0.7, zorder=1,
                                  label=f"liq_zone [{prev_low}, {cur_low}] (h={cur_low - prev_low})"))
# Полная зона входа — рамка
ax_l.add_patch(mpatches.Rectangle((zone_left, prev_low), zone_right - zone_left, prev_open - prev_low,
                                  facecolor="none", edgecolor="#bf360c", linewidth=2.0, zorder=2))

annotate_label(ax_l, zone_right, prev_low, f"{prev_low} = prev.low (liq.bot = entry.bot)")
annotate_label(ax_l, zone_right, cur_low, f"{cur_low} = cur.low (liq.top, protective)")
annotate_label(ax_l, zone_right, prev_open, f"{prev_open} = prev.open (entry.top)")

for i, (role, o, h, l, c) in enumerate(long_candles):
    color = "#26a69a" if c >= o else "#ef5350"
    annotate_label(ax_l, i + 1.0, h + 0.8, role, color=color, offset=(0, 8), ha="center", fontsize=8.5)

# Аннотация sweep
ax_l.annotate("liquidity sweep\nprev_wick > 3× cur_wick\nprev.low = 5-bar LL",
              xy=(3.0, 85), xytext=(1.6, 88),
              fontsize=9, color="#1565c0", fontweight="bold",
              arrowprops=dict(arrowstyle="->", color="#1565c0", lw=1.3),
              ha="center", va="bottom",
              bbox=dict(boxstyle="round,pad=0.3", facecolor="#e3f2fd", edgecolor="#1565c0", alpha=0.85))

ax_l.text(5.2, (prev_low + prev_open) / 2 + 1, f"ENTRY [{prev_low}, {prev_open}]",
          fontsize=11, fontweight="bold", color="#bf360c", ha="center",
          bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#bf360c", alpha=0.85))

ax_l.set_ylabel("Price")
ax_l.set_xticks([])
ax_l.grid(True, alpha=0.25, axis="y")
ax_l.legend(loc="upper right", fontsize=8.5, framealpha=0.92)

# =========================================================
# SHORT ob_liq — зеркальный synthetic
# =========================================================
short_candles = [
    ("prev-2", 205, 208, 202, 203),   # bear
    ("prev-1", 203, 206, 199, 200),   # bear
    ("prev",   200, 215, 198, 204),   # bull, длинный верхний фитиль
    ("cur",    204, 206, 196, 197),   # bear, cur.close (197) < prev.open (200) ✓
    ("cur+1",  197, 205, 192, 194),   # bear
]

for i, (_, o, h, l, c) in enumerate(short_candles):
    draw_candle(ax_s, i + 1.0, o, h, l, c)

ax_s.set_xlim(0.3, 7.6)
ax_s.set_ylim(188, 218)
ax_s.set_title("SHORT ob_liq — synthetic (выраженный верхний фитиль prev = liquidity sweep)",
               fontsize=12, fontweight="bold")

prev_open_s, prev_high, cur_high = 200, 215, 206

# Entry: [prev.open, max(prev.high, cur.high)] = [200, 215]
# liq_zone: [cur.high, prev.high] = [206, 215] — верхняя часть entry zone
ax_s.add_patch(mpatches.Rectangle((zone_left, prev_open_s), zone_right - zone_left, cur_high - prev_open_s,
                                  facecolor="#fff3e0", edgecolor="#ff9800", linewidth=1.2,
                                  linestyle="--", alpha=0.55, zorder=1,
                                  label=f"entry (без liq) [{prev_open_s}, {cur_high}] (h={cur_high - prev_open_s})"))
ax_s.add_patch(mpatches.Rectangle((zone_left, cur_high), zone_right - zone_left, prev_high - cur_high,
                                  facecolor="#bbdefb", edgecolor="#1565c0", linewidth=1.4,
                                  alpha=0.7, zorder=1,
                                  label=f"liq_zone [{cur_high}, {prev_high}] (h={prev_high - cur_high})"))
ax_s.add_patch(mpatches.Rectangle((zone_left, prev_open_s), zone_right - zone_left, prev_high - prev_open_s,
                                  facecolor="none", edgecolor="#bf360c", linewidth=2.0, zorder=2))

annotate_label(ax_s, zone_right, prev_open_s, f"{prev_open_s} = prev.open (entry.bot)")
annotate_label(ax_s, zone_right, cur_high, f"{cur_high} = cur.high (liq.bot, protective)")
annotate_label(ax_s, zone_right, prev_high, f"{prev_high} = prev.high (liq.top = entry.top)")

for i, (role, o, h, l, c) in enumerate(short_candles):
    color = "#26a69a" if c >= o else "#ef5350"
    annotate_label(ax_s, i + 1.0, l - 0.8, role, color=color, offset=(0, -8), ha="center", fontsize=8.5)

ax_s.annotate("liquidity sweep\nprev_wick > 3× cur_wick\nprev.high = 5-bar HH",
              xy=(3.0, 215), xytext=(4.6, 211),
              fontsize=9, color="#1565c0", fontweight="bold",
              arrowprops=dict(arrowstyle="->", color="#1565c0", lw=1.3),
              ha="center", va="top",
              bbox=dict(boxstyle="round,pad=0.3", facecolor="#e3f2fd", edgecolor="#1565c0", alpha=0.85))

ax_s.text(5.2, (prev_open_s + prev_high) / 2 - 1, f"ENTRY [{prev_open_s}, {prev_high}]",
         fontsize=11, fontweight="bold", color="#bf360c", ha="center",
         bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#bf360c", alpha=0.85))

ax_s.set_ylabel("Price")
ax_s.set_xticks([])
ax_s.grid(True, alpha=0.25, axis="y")
ax_s.legend(loc="lower right", fontsize=8.5, framealpha=0.92)

fig.suptitle("ob_liq — entry zone (canon-OB, узкая) + liq_zone (маркер ликвидности, подмножество entry)",
             fontsize=13, fontweight="bold", y=1.00)
plt.tight_layout()

OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/ob_liq_zone_example.png"
plt.savefig(OUT, dpi=130, bbox_inches="tight")
plt.close()
print(f"Saved {OUT}")
