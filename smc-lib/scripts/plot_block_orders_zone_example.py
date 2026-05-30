"""Иллюстрация зоны интереса block_orders.

LONG — canon-эталон BTC 1h 2026-05-05 (N₁=2, N₂=2) из elements/block_orders/definition.md.
SHORT — synthetic из tests/test_block_orders.py::test_short_block_synthetic.
"""
from __future__ import annotations

import pathlib

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt


def draw_candle(ax, x, o, h, l, c, width=0.55, alpha=0.95):
    color = "#26a69a" if c >= o else "#ef5350"
    ax.plot([x, x], [l, h], color=color, linewidth=1.4, zorder=3)
    body_low, body_high = min(o, c), max(o, c)
    if body_high - body_low < 0.01 * max(1, h - l): body_high = body_low + 0.01 * max(1, h - l)
    ax.add_patch(mpatches.Rectangle((x - width / 2, body_low), width, body_high - body_low,
                                    facecolor=color, edgecolor=color, alpha=alpha, zorder=4))


def annotate_label(ax, x, y, text, color="#37474f", offset=(0, 10), ha="center"):
    ax.annotate(text, (x, y), xytext=offset, textcoords="offset points",
                fontsize=9, color=color, fontweight="bold", ha=ha, va="center", zorder=6)


fig, (ax_l, ax_s) = plt.subplots(1, 2, figsize=(18, 9))

# =========================================================
# LONG — BTC 1h 2026-05-05 canon-эталон (preceding + 2 initial + 2 counter)
# =========================================================
candles_long = [
    ("preceding", 79936.70, 80383.15, 79936.70, 80259.17, "bull"),
    ("initial #1", 80259.18, 80397.19, 80042.84, 80067.23, "bear"),
    ("initial #2", 80067.22, 80067.22, 79744.91, 79861.01, "bear"),
    ("counter #1", 79861.01, 80183.33, 79808.72, 80170.66, "bull (no cross)"),
    ("counter #2", 80170.66, 80385.06, 80080.76, 80352.00, "bull (CROSS)"),
]

for i, (role, o, h, l, c, kind) in enumerate(candles_long):
    draw_candle(ax_l, i + 1.0, o, h, l, c)

ax_l.set_xlim(0.3, 6.8)
ax_l.set_ylim(79600, 80500)
ax_l.set_title("LONG block_orders — BTC 1h 2026-05-05 (canon, N₁=2, N₂=2)", fontsize=13, fontweight="bold")

zone_left, zone_right = 0.5, 6.5
block_open = 80259.18
block_close = 80352.00
pattern_low = 79744.91
pattern_high = 80397.19

# drop area (подзона) — снизу
ax_l.add_patch(mpatches.Rectangle((zone_left, pattern_low), zone_right - zone_left, block_open - pattern_low,
                                  facecolor="#fff3e0", edgecolor="#ff9800", linewidth=1.2,
                                  linestyle="--", alpha=0.55, zorder=1,
                                  label=f"drop area [{pattern_low:.2f}, {block_open:.2f}] (h={block_open - pattern_low:.2f})"))
# breaker block (подзона) — сверху
ax_l.add_patch(mpatches.Rectangle((zone_left, block_open), zone_right - zone_left, block_close - block_open,
                                  facecolor="#ffcc80", edgecolor="#ef6c00", linewidth=1.4,
                                  alpha=0.75, zorder=1,
                                  label=f"breaker block [{block_open:.2f}, {block_close:.2f}] (h={block_close - block_open:.2f})"))
# полная зона — рамка
ax_l.add_patch(mpatches.Rectangle((zone_left, pattern_low), zone_right - zone_left, block_close - pattern_low,
                                  facecolor="none", edgecolor="#bf360c", linewidth=2.0, zorder=2))

# Подписи ключевых уровней справа
annotate_label(ax_l, zone_right, pattern_low, f"{pattern_low:.2f} = pattern.low (= initial #2 low)", offset=(6, 0), ha="left")
annotate_label(ax_l, zone_right, block_open, f"{block_open:.2f} = block.open (initial #1 open)", offset=(6, 0), ha="left")
annotate_label(ax_l, zone_right, block_close, f"{block_close:.2f} = block.close (counter #2, first-cross)", offset=(6, 0), ha="left")
annotate_label(ax_l, zone_right, pattern_high, f"{pattern_high:.2f} = pattern.high (NOT in zone)", color="#9e9e9e", offset=(6, 0), ha="left")

# Метки ролей под свечами
for i, (role, o, h, l, c, kind) in enumerate(candles_long):
    color = "#26a69a" if c >= o else "#ef5350"
    ax_l.annotate(role, (i + 1.0, l), xytext=(0, -14), textcoords="offset points",
                  fontsize=8.5, color=color, fontweight="bold", ha="center", va="top")

ax_l.text(3.5, (pattern_low + block_close) / 2 + 90, f"ZONE [{pattern_low:.2f}, {block_close:.2f}]",
          fontsize=12, fontweight="bold", color="#bf360c", ha="center",
          bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#bf360c", alpha=0.85))

ax_l.set_ylabel("Price (USDT)")
ax_l.set_xticks([])
ax_l.grid(True, alpha=0.25, axis="y")
ax_l.legend(loc="upper left", fontsize=8.5, framealpha=0.92)

# =========================================================
# SHORT — synthetic из test_short_block_synthetic (N₁=2, N₂=1)
# =========================================================
candles_short = [
    ("preceding", 110, 112, 99, 100, "bear"),
    ("initial #1", 100, 108, 99, 105, "bull"),
    ("initial #2", 105, 112, 104, 110, "bull"),
    ("counter #1", 110, 111, 95, 98, "bear (CROSS)"),
]

for i, (role, o, h, l, c, kind) in enumerate(candles_short):
    draw_candle(ax_s, i + 1.0, o, h, l, c)

ax_s.set_xlim(0.3, 6.2)
ax_s.set_ylim(92, 115)
ax_s.set_title("SHORT block_orders — synthetic (N₁=2, N₂=1)", fontsize=13, fontweight="bold")

zone_left_s, zone_right_s = 0.5, 5.7
block_open_s = 100
block_close_s = 98
pattern_low_s = 95
pattern_high_s = 112

# rally area (подзона) — сверху
ax_s.add_patch(mpatches.Rectangle((zone_left_s, block_open_s), zone_right_s - zone_left_s, pattern_high_s - block_open_s,
                                  facecolor="#fff3e0", edgecolor="#ff9800", linewidth=1.2,
                                  linestyle="--", alpha=0.55, zorder=1,
                                  label=f"rally area [{block_open_s}, {pattern_high_s}] (h={pattern_high_s - block_open_s})"))
# breaker block (подзона) — снизу
ax_s.add_patch(mpatches.Rectangle((zone_left_s, block_close_s), zone_right_s - zone_left_s, block_open_s - block_close_s,
                                  facecolor="#ffcc80", edgecolor="#ef6c00", linewidth=1.4,
                                  alpha=0.75, zorder=1,
                                  label=f"breaker block [{block_close_s}, {block_open_s}] (h={block_open_s - block_close_s})"))
# полная зона
ax_s.add_patch(mpatches.Rectangle((zone_left_s, block_close_s), zone_right_s - zone_left_s, pattern_high_s - block_close_s,
                                  facecolor="none", edgecolor="#bf360c", linewidth=2.0, zorder=2))

annotate_label(ax_s, zone_right_s, pattern_low_s, f"{pattern_low_s} = pattern.low (NOT in zone)", color="#9e9e9e", offset=(6, 0), ha="left")
annotate_label(ax_s, zone_right_s, block_close_s, f"{block_close_s} = block.close (counter, first-cross)", offset=(6, 0), ha="left")
annotate_label(ax_s, zone_right_s, block_open_s, f"{block_open_s} = block.open (initial #1 open)", offset=(6, 0), ha="left")
annotate_label(ax_s, zone_right_s, pattern_high_s, f"{pattern_high_s} = pattern.high (= initial #2 high)", offset=(6, 0), ha="left")

for i, (role, o, h, l, c, kind) in enumerate(candles_short):
    color = "#26a69a" if c >= o else "#ef5350"
    pos = h + 0.5 if i in (1, 2) else l - 0.5
    va = "bottom" if i in (1, 2) else "top"
    off = (0, 10) if i in (1, 2) else (0, -12)
    ax_s.annotate(role, (i + 1.0, pos), xytext=off, textcoords="offset points",
                  fontsize=8.5, color=color, fontweight="bold", ha="center", va=va)

ax_s.text(3.0, (block_close_s + pattern_high_s) / 2 + 1.5, f"ZONE [{block_close_s}, {pattern_high_s}]",
          fontsize=12, fontweight="bold", color="#bf360c", ha="center",
          bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#bf360c", alpha=0.85))

ax_s.set_ylabel("Price")
ax_s.set_xticks([])
ax_s.grid(True, alpha=0.25, axis="y")
ax_s.legend(loc="lower left", fontsize=8.5, framealpha=0.92)

fig.suptitle("block_orders — зона интереса = breaker block (подзона) + drop / rally area (подзона)",
             fontsize=14, fontweight="bold", y=1.00)
plt.tight_layout()

OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/block_orders_zone_example.png"
plt.savefig(OUT, dpi=130, bbox_inches="tight")
plt.close()
print(f"Saved {OUT}")
