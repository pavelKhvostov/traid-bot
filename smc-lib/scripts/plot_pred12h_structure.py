"""Визуальная схема проекта Pred-12h fractal.

Layers:
1. BTC 12h data
2. Cascade F1∩F2∩F3 (baseline funnel)
3. Baseline result box
4. OR-basket C1..C9 (parallel pillars)
5. Basket result box
6. C4 sub-basket D1..D6 (zoom-in)
7. C4_v2 result box

Output: ~/Desktop/i-rdrb-charts/pred12h_structure.png
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
from matplotlib.lines import Line2D
import pathlib

# Style
plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["font.size"] = 10

fig = plt.figure(figsize=(18, 28), dpi=130)
ax = fig.add_subplot(111)
ax.set_xlim(0, 100)
ax.set_ylim(-12, 160)
ax.set_aspect("equal")
ax.axis("off")

# Colors
C_DATA = "#2C3E50"     # dark blue
C_CASC = "#7F8C8D"     # gray
C_BASE = "#16A085"     # teal
C_PREC = "#27AE60"     # green — precision Dx/Cx
C_RECL = "#E67E22"     # orange — recall
C_HEAD = "#34495E"     # dark
C_HIGH = "#E74C3C"     # red — highlight today
C_BG = "#ECF0F1"
C_ARROW = "#7F8C8D"
C_NEW = "#FFF5E6"      # light orange highlight

# Helper: rounded box with text
def box(x, y, w, h, text, color, text_color="white", fontsize=11, weight="normal", title=None, title_color="white"):
    bb = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.1,rounding_size=0.5",
                         linewidth=1.5, edgecolor=color, facecolor=color, alpha=0.95)
    ax.add_patch(bb)
    if title:
        ax.text(x + w/2, y + h - 0.9, title, ha="center", va="top",
                fontsize=fontsize+1, fontweight="bold", color=title_color)
        ax.text(x + w/2, y + h/2 - 0.7, text, ha="center", va="center",
                fontsize=fontsize, color=text_color, fontweight=weight)
    else:
        ax.text(x + w/2, y + h/2, text, ha="center", va="center",
                fontsize=fontsize, color=text_color, fontweight=weight)

def boxw(x, y, w, h, text, color="white", border=C_HEAD, text_color="#2C3E50", fontsize=10, weight="normal"):
    bb = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.1,rounding_size=0.4",
                         linewidth=1.2, edgecolor=border, facecolor=color, alpha=0.95)
    ax.add_patch(bb)
    ax.text(x + w/2, y + h/2, text, ha="center", va="center",
            fontsize=fontsize, color=text_color, fontweight=weight)

def arrow(x1, y1, x2, y2, color=C_ARROW, lw=2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="->", color=color, lw=lw))

def label(x, y, text, fontsize=10, color="#2C3E50", weight="normal", ha="center"):
    ax.text(x, y, text, ha=ha, va="center", fontsize=fontsize, color=color, fontweight=weight)

# ─── TITLE ─────────────────────────────────────────────────────
ax.text(50, 158, "Прогноз формирования 12h фрактала",
        ha="center", va="center", fontsize=22, fontweight="bold", color=C_HEAD)
ax.text(50, 155, "2020-01-01 → текущий момент   ·   4 698 12h-баров",
        ha="center", va="center", fontsize=10, color=C_CASC)

# ─── LAYER 2: Cascade F1-F3 ──────────────────────────────────
y = 136
# Container
container = FancyBboxPatch((6, y), 88, 16, boxstyle="round,pad=0.3,rounding_size=0.5",
                             linewidth=1.5, edgecolor=C_CASC, facecolor="#F8F9FA", alpha=0.5)
ax.add_patch(container)
ax.text(50, y + 14.6, "A · Cascade  A1 ∩ A2 ∩ A3 ∩ A4   —   отсекаем лишнее",
        ha="center", va="center", fontsize=12.5, fontweight="bold", color=C_CASC)

# Funnel boxes — три яруса: TITLE (top) · BODY (middle) · COUNT (bottom)
# x_start, y_offset, width, height, title, body, count
cascade_data = [
    (8,  y + 2, 14.5, 10.5, "A1 · Pre-W",    "3-свечный\nлокальный\nэкстремум",      "n = 3 099\nWR 41.59%"),
    (24, y + 2, 14.5, 10.5, "A2 · ext_5",    "5 свечей левее\nменьший\nэкстремум",    "n = 2 031\nWR 42.64%"),
    (40, y + 2, 14.5, 10.5, "A3 · color",    "смена цвета i-1, i\nили\n3 подряд однонапр.\n(без доджей)", "n = 1 507\nWR 44.92%"),
    (56, y + 2, 14.5, 10.5, "A4 · body+wick", "убирает\nпризнаки\nмарубозу",            "n = 1 356\nWR 48.60%"),
    (72, y + 2, 20,   10.5, "BASELINE",      "",                                       "n = 1 356\nWR 48.60%"),
]

# Filler boxes
for i, (x, yy, w, h, *_rest) in enumerate(cascade_data):
    is_baseline = (i == 4)
    boxw(x, yy, w, h, "",
         color=C_BASE if is_baseline else "white",
         border=C_BASE if is_baseline else C_CASC,
         fontsize=9)

# Text composition
for i, (x, yy, w, h, title, body, count) in enumerate(cascade_data):
    is_baseline = (i == 4)
    cx = x + w / 2

    if is_baseline:
        # Two-tier compact layout: title above, n/WR stacked below
        ax.text(cx, yy + h*0.72, title, ha="center", va="center",
                fontsize=14, fontweight="bold", color="white")
        ax.text(cx, yy + h*0.28, count, ha="center", va="center",
                fontsize=11, fontweight="bold", color="white", linespacing=1.4)
    else:
        # Three-tier: title / body / n+WR stacked
        ax.text(cx, yy + h - 1.0, title, ha="center", va="top",
                fontsize=12, fontweight="bold", color="#2C3E50")
        if body:
            n_lines = body.count("\n") + 1
            body_size = 8.5 if n_lines <= 3 else 7.8
            ax.text(cx, yy + h*0.55, body, ha="center", va="center",
                    fontsize=body_size, color="#34495E", linespacing=1.25,
                    style="italic")
        ax.text(cx, yy + 1.8, count, ha="center", va="center",
                fontsize=10, fontweight="bold", color=C_BASE, linespacing=1.4)

# Arrows between cascade boxes (horizontal flow at vertical center of boxes)
for i in range(4):
    sx = cascade_data[i][0] + cascade_data[i][2]
    arrow(sx, y + 7.25, cascade_data[i+1][0], y + 7.25, color=C_CASC, lw=1.5)

# (стрелка между F-каскадом и OR-basket убрана)

# ─── LAYER 6: B1 sub-basket inline ─────────────────────────────
y = 120
container = FancyBboxPatch((3, y), 94, 12.5, boxstyle="round,pad=0.3,rounding_size=0.5",
                             linewidth=2, edgecolor=C_HIGH, facecolor=C_NEW, alpha=0.6)
ax.add_patch(container)

# Layout row: [C4 chip] [FVG box] [D1] [D2] [D3] [D4] [D5] [D6]
row_y = y + 0.75
row_h = 11

# 1) B1 chip
c4_w = 9
c4_x = 5
boxw(c4_x, row_y, c4_w, row_h, "", color=C_HIGH, border=C_HIGH, fontsize=9)
ax.text(c4_x + c4_w/2, row_y + row_h - 2.5, "B1",
        ha="center", va="center", fontsize=17, fontweight="bold", color="white")
ax.text(c4_x + c4_w/2, row_y + 4, "n = 226",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")
ax.text(c4_x + c4_w/2, row_y + 2, "P(W) 71.68%",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")

# 2) FVG box
fvg_w = 7
fvg_x = c4_x + c4_w + 1
boxw(fvg_x, row_y, fvg_w, row_h, "", color="#FFF9F0", border=C_RECL, fontsize=9)
ax.text(fvg_x + fvg_w/2, row_y + row_h/2 + 2.5, "Fair",
        ha="center", va="center", fontsize=10, fontweight="bold", color=C_RECL)
ax.text(fvg_x + fvg_w/2, row_y + row_h/2 + 0.7, "Value",
        ha="center", va="center", fontsize=10, fontweight="bold", color=C_RECL)
ax.text(fvg_x + fvg_w/2, row_y + row_h/2 - 1.1, "Gap",
        ha="center", va="center", fontsize=10, fontweight="bold", color=C_RECL)
ax.text(fvg_x + fvg_w/2, row_y + row_h/2 - 3.2, "inefficiency class",
        ha="center", va="center", fontsize=6, color=C_RECL, style="italic")

# 3) D1..D6 (right side)
d_blocks = [
    ("B1C1", "strict sweep",   "S100/WIDE",      35,  94.29, C_PREC),
    ("B1C2", "strict sweep",   "S50/AGE-W",      63,  87.30, C_PREC),
    ("B1C3", "strict sweep",   "S70/AGE50",     130,  75.38, C_PREC),
    ("B1C4", "strict sweep",   "S50/HTF-W",      53,  77.36, C_PREC),
    ("B1C5", "volume spike",   "S50 + vol_z≥2σ", 66,  72.73, C_PREC),
    ("B1C6", "retest",         "S50 → in (≤3b)", 38,  68.42, C_PREC),
]
d_start = fvg_x + fvg_w + 1.5
d_end = 96
d_total = d_end - d_start
d_gap = 0.4
d_w = (d_total - 5 * d_gap) / 6

for i, (name, kind, params, n_val, wr, color) in enumerate(d_blocks):
    dx = d_start + i * (d_w + d_gap)
    boxw(dx, row_y, d_w, row_h, "", color="white", border=color, fontsize=9)
    # B1Cx name (top)
    ax.text(dx + d_w/2, row_y + row_h - 1.3, name,
            ha="center", va="center", fontsize=10.5, fontweight="bold", color=color)
    # kind badge
    bw = d_w * 0.85
    bh = 1.1
    bx = dx + (d_w - bw) / 2
    by = row_y + row_h - 3.3
    bb = FancyBboxPatch((bx, by), bw, bh, boxstyle="round,pad=0.05,rounding_size=0.2",
                        linewidth=0, facecolor=color, alpha=0.9)
    ax.add_patch(bb)
    ax.text(dx + d_w/2, by + bh/2, kind,
            ha="center", va="center", fontsize=6.5, color="white", fontweight="bold")
    # params
    ax.text(dx + d_w/2, row_y + row_h - 4.8, params,
            ha="center", va="center", fontsize=7, color="#34495E",
            fontweight="bold", family="monospace")
    # n
    ax.text(dx + d_w/2, row_y + 2.7, f"n = {n_val}",
            ha="center", va="center", fontsize=8.5, color="#34495E", fontweight="bold")
    # WR
    ax.text(dx + d_w/2, row_y + 1.2, f"P(W) {wr}%",
            ha="center", va="center", fontsize=9.5, color=color, fontweight="bold")

# ─── LAYER 6b: B2 sub-basket (B2 chip + Order Block + B2C1 + planned) ───
y_b2 = 105
container = FancyBboxPatch((3, y_b2), 94, 12.5, boxstyle="round,pad=0.3,rounding_size=0.5",
                             linewidth=2, edgecolor=C_HIGH, facecolor=C_NEW, alpha=0.6)
ax.add_patch(container)

row_y = y_b2 + 0.75
row_h = 11

# 1) B2 chip
b2_w = 9; b2_x = 5
boxw(b2_x, row_y, b2_w, row_h, "", color=C_HIGH, border=C_HIGH, fontsize=9)
ax.text(b2_x + b2_w/2, row_y + row_h - 2.5, "B2",
        ha="center", va="center", fontsize=17, fontweight="bold", color="white")
ax.text(b2_x + b2_w/2, row_y + 4, "n = 105",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")
ax.text(b2_x + b2_w/2, row_y + 2, "P(W) 75.24%",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")

# 2) Order Block box
C_PURPLE = "#8E44AD"
ob_w = 7; ob_x = b2_x + b2_w + 1
boxw(ob_x, row_y, ob_w, row_h, "", color="#F5EEF8", border=C_PURPLE, fontsize=9)
ax.text(ob_x + ob_w/2, row_y + row_h/2 + 2, "Order",
        ha="center", va="center", fontsize=11, fontweight="bold", color=C_PURPLE)
ax.text(ob_x + ob_w/2, row_y + row_h/2 - 0.3, "Block",
        ha="center", va="center", fontsize=11, fontweight="bold", color=C_PURPLE)
ax.text(ob_x + ob_w/2, row_y + row_h/2 - 3, "block class",
        ha="center", va="center", fontsize=6.5, color=C_PURPLE, style="italic")

# 3) B2C1 + B2C2 — активные sub-условия
d_start_b2 = ob_x + ob_w + 1.5
d_w_b2 = (96 - d_start_b2 - 5 * 0.4) / 6   # геометрия как в B1 row
color_active = C_PREC

b2_subs = [
    ("B2C1", "FIRST 50%-sweep", "OB · multi-TF",      58,  89.66),
    ("B2C2", "FIRST 50%-sweep", "ob_liq · multi-TF",  73,  68.49),
]
for i, (sname, badge_txt, params, n_val, wr) in enumerate(b2_subs):
    dx = d_start_b2 + i * (d_w_b2 + 0.4)
    boxw(dx, row_y, d_w_b2, row_h, "", color="white", border=color_active, fontsize=9)
    ax.text(dx + d_w_b2/2, row_y + row_h - 1.3, sname,
            ha="center", va="center", fontsize=10.5, fontweight="bold", color=color_active)
    bw = d_w_b2 * 0.85; bh = 1.1
    bx = dx + (d_w_b2 - bw) / 2; by = row_y + row_h - 3.3
    bb = FancyBboxPatch((bx, by), bw, bh, boxstyle="round,pad=0.05,rounding_size=0.2",
                        linewidth=0, facecolor=color_active, alpha=0.9)
    ax.add_patch(bb)
    ax.text(dx + d_w_b2/2, by + bh/2, badge_txt,
            ha="center", va="center", fontsize=6.5, color="white", fontweight="bold")
    ax.text(dx + d_w_b2/2, row_y + row_h - 4.8, params,
            ha="center", va="center", fontsize=7, color="#34495E",
            fontweight="bold", family="monospace")
    ax.text(dx + d_w_b2/2, row_y + 2.7, f"n = {n_val}",
            ha="center", va="center", fontsize=8.5, color="#34495E", fontweight="bold")
    ax.text(dx + d_w_b2/2, row_y + 1.2, f"P(W) {wr}%",
            ha="center", va="center", fontsize=9.5, color=color_active, fontweight="bold")

# ─── LAYER 6c: B3 sub-basket (B3 chip + Fractal Liquidity + B3C1) ────
y_b3 = 90
container = FancyBboxPatch((3, y_b3), 94, 12.5, boxstyle="round,pad=0.3,rounding_size=0.5",
                             linewidth=2, edgecolor=C_HIGH, facecolor=C_NEW, alpha=0.6)
ax.add_patch(container)

row_y = y_b3 + 0.75
row_h = 11

# 1) B3 chip
b3_w = 9; b3_x = 5
boxw(b3_x, row_y, b3_w, row_h, "", color=C_HIGH, border=C_HIGH, fontsize=9)
ax.text(b3_x + b3_w/2, row_y + row_h - 2.5, "B3",
        ha="center", va="center", fontsize=17, fontweight="bold", color="white")
ax.text(b3_x + b3_w/2, row_y + 4, "n = 375",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")
ax.text(b3_x + b3_w/2, row_y + 2, "P(W) 75.20%",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")

# 2) Fractal Liquidity box
C_TEAL = "#1ABC9C"
fl_w = 7; fl_x = b3_x + b3_w + 1
boxw(fl_x, row_y, fl_w, row_h, "", color="#E8F8F5", border=C_TEAL, fontsize=9)
ax.text(fl_x + fl_w/2, row_y + row_h/2 + 2, "Fractal",
        ha="center", va="center", fontsize=10, fontweight="bold", color=C_TEAL)
ax.text(fl_x + fl_w/2, row_y + row_h/2 - 0.3, "Liquidity",
        ha="center", va="center", fontsize=10, fontweight="bold", color=C_TEAL)
ax.text(fl_x + fl_w/2, row_y + row_h/2 - 3, "liquidity class",
        ha="center", va="center", fontsize=6.5, color=C_TEAL, style="italic")

# 3) B3C1 — единственное активное условие
d_start_b3 = fl_x + fl_w + 1.5
d_w_b3 = (96 - d_start_b3 - 5 * 0.4) / 6
color_active = C_PREC
dx = d_start_b3
boxw(dx, row_y, d_w_b3, row_h, "", color="white", border=color_active, fontsize=9)
ax.text(dx + d_w_b3/2, row_y + row_h - 1.3, "B3C1",
        ha="center", va="center", fontsize=10.5, fontweight="bold", color=color_active)
bw = d_w_b3 * 0.85; bh = 1.1
bx = dx + (d_w_b3 - bw) / 2; by = row_y + row_h - 3.3
bb = FancyBboxPatch((bx, by), bw, bh, boxstyle="round,pad=0.05,rounding_size=0.2",
                    linewidth=0, facecolor=color_active, alpha=0.9)
ax.add_patch(bb)
ax.text(dx + d_w_b3/2, by + bh/2, "maxV sweep",
        ha="center", va="center", fontsize=6.5, color="white", fontweight="bold")
ax.text(dx + d_w_b3/2, row_y + row_h - 4.8, "maxV(i-1)",
        ha="center", va="center", fontsize=7, color="#34495E",
        fontweight="bold", family="monospace")
ax.text(dx + d_w_b3/2, row_y + 2.7, "n = 375",
        ha="center", va="center", fontsize=8.5, color="#34495E", fontweight="bold")
ax.text(dx + d_w_b3/2, row_y + 1.2, "P(W) 75.20%",
        ha="center", va="center", fontsize=9.5, color=color_active, fontweight="bold")

# ─── LAYER 6d: B4 sub-basket (B4 chip + HMA + B4C1 + B4C2) ────
y_b4 = 75
container = FancyBboxPatch((3, y_b4), 94, 12.5, boxstyle="round,pad=0.3,rounding_size=0.5",
                             linewidth=2, edgecolor=C_HIGH, facecolor=C_NEW, alpha=0.6)
ax.add_patch(container)

row_y = y_b4 + 0.75
row_h = 11

# 1) B4 chip
b4_w = 9; b4_x = 5
boxw(b4_x, row_y, b4_w, row_h, "", color=C_HIGH, border=C_HIGH, fontsize=9)
ax.text(b4_x + b4_w/2, row_y + row_h - 2.5, "B4",
        ha="center", va="center", fontsize=17, fontweight="bold", color="white")
ax.text(b4_x + b4_w/2, row_y + 4, "n = 234",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")
ax.text(b4_x + b4_w/2, row_y + 2, "P(W) 67.09%",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")

# 2) HMA box (deep navy/blue)
C_NAVY = "#2874A6"
hma_w = 7; hma_x = b4_x + b4_w + 1
boxw(hma_x, row_y, hma_w, row_h, "", color="#EBF5FB", border=C_NAVY, fontsize=9)
ax.text(hma_x + hma_w/2, row_y + row_h/2 + 1.5, "HMA",
        ha="center", va="center", fontsize=13, fontweight="bold", color=C_NAVY)
ax.text(hma_x + hma_w/2, row_y + row_h/2 - 1.2, "Hull MA",
        ha="center", va="center", fontsize=8, color=C_NAVY, style="italic")
ax.text(hma_x + hma_w/2, row_y + row_h/2 - 3, "trend-line",
        ha="center", va="center", fontsize=6.5, color=C_NAVY, style="italic")

# 3) B4C1 + B4C2 — два активных sub-условия
d_start_b4 = hma_x + hma_w + 1.5
d_w_b4 = (96 - d_start_b4 - 5 * 0.4) / 6
color_active = C_PREC

b4_subs = [
    ("B4C1", "HMA-78",  "12h ∪ D LIVE", 194, 65.98),
    ("B4C2", "HMA-200", "D LIVE",        54, 77.78),
]
for i, (sname, badge_txt, params, n_val, wr) in enumerate(b4_subs):
    dx = d_start_b4 + i * (d_w_b4 + 0.4)
    boxw(dx, row_y, d_w_b4, row_h, "", color="white", border=color_active, fontsize=9)
    ax.text(dx + d_w_b4/2, row_y + row_h - 1.3, sname,
            ha="center", va="center", fontsize=10.5, fontweight="bold", color=color_active)
    bw = d_w_b4 * 0.85; bh = 1.1
    bx = dx + (d_w_b4 - bw) / 2; by = row_y + row_h - 3.3
    bb = FancyBboxPatch((bx, by), bw, bh, boxstyle="round,pad=0.05,rounding_size=0.2",
                        linewidth=0, facecolor=color_active, alpha=0.9)
    ax.add_patch(bb)
    ax.text(dx + d_w_b4/2, by + bh/2, badge_txt,
            ha="center", va="center", fontsize=6.5, color="white", fontweight="bold")
    ax.text(dx + d_w_b4/2, row_y + row_h - 4.8, params,
            ha="center", va="center", fontsize=7, color="#34495E",
            fontweight="bold", family="monospace")
    ax.text(dx + d_w_b4/2, row_y + 2.7, f"n = {n_val}",
            ha="center", va="center", fontsize=8.5, color="#34495E", fontweight="bold")
    ax.text(dx + d_w_b4/2, row_y + 1.2, f"P(W) {wr}%",
            ha="center", va="center", fontsize=9.5, color=color_active, fontweight="bold")

# ─── LAYER 6e: B5 sub-basket (B5 chip + VWAP + B5C1) ──────────
y_b5 = 60
container = FancyBboxPatch((3, y_b5), 94, 12.5, boxstyle="round,pad=0.3,rounding_size=0.5",
                             linewidth=2, edgecolor=C_HIGH, facecolor=C_NEW, alpha=0.6)
ax.add_patch(container)

row_y = y_b5 + 0.75
row_h = 11

# 1) B5 chip
b5_w = 9; b5_x = 5
boxw(b5_x, row_y, b5_w, row_h, "", color=C_HIGH, border=C_HIGH, fontsize=9)
ax.text(b5_x + b5_w/2, row_y + row_h - 2.5, "B5",
        ha="center", va="center", fontsize=17, fontweight="bold", color="white")
ax.text(b5_x + b5_w/2, row_y + 4, "n = 95",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")
ax.text(b5_x + b5_w/2, row_y + 2, "P(W) 80.00%",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")

# 2) VWAP box (dark amber/gold)
C_AMBER = "#B7950B"
vwap_w = 7; vwap_x = b5_x + b5_w + 1
boxw(vwap_x, row_y, vwap_w, row_h, "", color="#FEF5E7", border=C_AMBER, fontsize=9)
ax.text(vwap_x + vwap_w/2, row_y + row_h/2 + 1.5, "VWAP",
        ha="center", va="center", fontsize=13, fontweight="bold", color=C_AMBER)
ax.text(vwap_x + vwap_w/2, row_y + row_h/2 - 1.5, "anchored",
        ha="center", va="center", fontsize=8, color=C_AMBER, style="italic")
ax.text(vwap_x + vwap_w/2, row_y + row_h/2 - 3.2, "volume MA",
        ha="center", va="center", fontsize=6.5, color=C_AMBER, style="italic")

# 3) B5C1 — единственное активное условие
d_start_b5 = vwap_x + vwap_w + 1.5
d_w_b5 = (96 - d_start_b5 - 5 * 0.4) / 6
color_active = C_PREC
dx = d_start_b5
boxw(dx, row_y, d_w_b5, row_h, "", color="white", border=color_active, fontsize=9)
ax.text(dx + d_w_b5/2, row_y + row_h - 1.3, "B5C1",
        ha="center", va="center", fontsize=10.5, fontweight="bold", color=color_active)
bw = d_w_b5 * 0.85; bh = 1.1
bx = dx + (d_w_b5 - bw) / 2; by = row_y + row_h - 3.3
bb = FancyBboxPatch((bx, by), bw, bh, boxstyle="round,pad=0.05,rounding_size=0.2",
                    linewidth=0, facecolor=color_active, alpha=0.9)
ax.add_patch(bb)
ax.text(dx + d_w_b5/2, by + bh/2, "≥2 W-aligned",
        ha="center", va="center", fontsize=6.5, color="white", fontweight="bold")
ax.text(dx + d_w_b5/2, row_y + row_h - 4.8, "swept VWAPs",
        ha="center", va="center", fontsize=7, color="#34495E",
        fontweight="bold", family="monospace")
ax.text(dx + d_w_b5/2, row_y + 2.7, "n = 95",
        ha="center", va="center", fontsize=8.5, color="#34495E", fontweight="bold")
ax.text(dx + d_w_b5/2, row_y + 1.2, "P(W) 80.00%",
        ha="center", va="center", fontsize=9.5, color=color_active, fontweight="bold")

# ─── LAYER 6f: B6 RSI sub-basket (planned, no B6Cx) ───────────
y_b6 = 45
C_PLAN = "#A9A9A9"
container = FancyBboxPatch((3, y_b6), 94, 12.5, boxstyle="round,pad=0.3,rounding_size=0.5",
                             linewidth=2, edgecolor=C_PLAN, facecolor="#FAFAFA", alpha=0.5,
                             linestyle="dashed")
ax.add_patch(container)
row_y = y_b6 + 0.75
row_h = 11
# B6 chip (planned style — grey)
b6_w = 9; b6_x = 5
boxw(b6_x, row_y, b6_w, row_h, "", color=C_PLAN, border=C_PLAN, fontsize=9)
ax.text(b6_x + b6_w/2, row_y + row_h - 2.5, "B6",
        ha="center", va="center", fontsize=17, fontweight="bold", color="white")
ax.text(b6_x + b6_w/2, row_y + 4, "n = —",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")
ax.text(b6_x + b6_w/2, row_y + 2, "P(W) —",
        ha="center", va="center", fontsize=9.5, color="white", fontweight="bold")
# RSI box (crimson)
C_CRIMSON = "#C0392B"
rsi_x = b6_x + b6_w + 1; rsi_w = 7
bb = FancyBboxPatch((rsi_x, row_y), rsi_w, row_h, boxstyle="round,pad=0.1,rounding_size=0.4",
                    linewidth=1.5, edgecolor=C_CRIMSON, facecolor="#FADBD8",
                    alpha=0.85, linestyle="dashed")
ax.add_patch(bb)
ax.text(rsi_x + rsi_w/2, row_y + row_h/2 + 1.5, "RSI",
        ha="center", va="center", fontsize=14, fontweight="bold", color=C_CRIMSON)
ax.text(rsi_x + rsi_w/2, row_y + row_h/2 - 1.5, "Relative",
        ha="center", va="center", fontsize=7, color=C_CRIMSON, style="italic")
ax.text(rsi_x + rsi_w/2, row_y + row_h/2 - 3, "Strength Idx",
        ha="center", va="center", fontsize=6.5, color=C_CRIMSON, style="italic")
# Right side: no B6Cx placeholder area
right_x = rsi_x + rsi_w + 1.5
right_w = 96 - right_x
ax.text(right_x + right_w/2, row_y + row_h/2 + 1.5, "no B6Cx implemented yet",
        ha="center", va="center", fontsize=11, color="#7F8C8D", style="italic", fontweight="bold")
ax.text(right_x + right_w/2, row_y + row_h/2 - 1, "candidates: overbought/oversold · divergence · multi-TF · StochRSI · cross/breakout",
        ha="center", va="center", fontsize=7.5, color="#95A5A6", style="italic")
ax.text(right_x + right_w/2, row_y + row_h/2 - 3.3, "see ~/smc-lib/projects/12h-fractal-new/B6_rsi.md",
        ha="center", va="center", fontsize=6.5, color="#BDC3C7", family="monospace")

# ─── LAYER 6g: B7 MoneyHands sub-basket (planned, no B7Cx) ────
y_b7 = 30
container = FancyBboxPatch((3, y_b7), 94, 12.5, boxstyle="round,pad=0.3,rounding_size=0.5",
                             linewidth=2, edgecolor=C_PLAN, facecolor="#FAFAFA", alpha=0.5,
                             linestyle="dashed")
ax.add_patch(container)
row_y = y_b7 + 0.75
# B7 chip
b7_w = 9; b7_x = 5
boxw(b7_x, row_y, b7_w, row_h, "", color=C_PLAN, border=C_PLAN, fontsize=9)
ax.text(b7_x + b7_w/2, row_y + row_h - 2.5, "B7",
        ha="center", va="center", fontsize=17, fontweight="bold", color="white")
ax.text(b7_x + b7_w/2, row_y + 4, "n = —",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")
ax.text(b7_x + b7_w/2, row_y + 2, "P(W) —",
        ha="center", va="center", fontsize=9.5, color="white", fontweight="bold")
# MoneyHands box (dark olive/khaki)
C_OLIVE = "#7D6608"
mh_x = b7_x + b7_w + 1; mh_w = 7
bb = FancyBboxPatch((mh_x, row_y), mh_w, row_h, boxstyle="round,pad=0.1,rounding_size=0.4",
                    linewidth=1.5, edgecolor=C_OLIVE, facecolor="#FCF3CF",
                    alpha=0.85, linestyle="dashed")
ax.add_patch(bb)
ax.text(mh_x + mh_w/2, row_y + row_h/2 + 1.5, "Money",
        ha="center", va="center", fontsize=11, fontweight="bold", color=C_OLIVE)
ax.text(mh_x + mh_w/2, row_y + row_h/2 - 1.2, "Hands",
        ha="center", va="center", fontsize=11, fontweight="bold", color=C_OLIVE)
ax.text(mh_x + mh_w/2, row_y + row_h/2 - 3.3, "smart money",
        ha="center", va="center", fontsize=6, color=C_OLIVE, style="italic")
# Right side
right_x = mh_x + mh_w + 1.5
right_w = 96 - right_x
ax.text(right_x + right_w/2, row_y + row_h/2 + 1.5, "no B7Cx implemented yet",
        ha="center", va="center", fontsize=11, color="#7F8C8D", style="italic", fontweight="bold")
ax.text(right_x + right_w/2, row_y + row_h/2 - 1, "candidate B7C1: pivot-money-hands LONG-cascade rule (bear + cascade ≤ 1h → 62.9%)",
        ha="center", va="center", fontsize=7.5, color="#95A5A6", style="italic")
ax.text(right_x + right_w/2, row_y + row_h/2 - 3.3, "see ~/smc-lib/projects/12h-fractal-new/B7_moneyhands.md",
        ha="center", va="center", fontsize=6.5, color="#BDC3C7", family="monospace")

# ─── LAYER 6h: B8 Power Zone sub-basket (B8C1 active) ─────────
y_b8 = 15
container = FancyBboxPatch((3, y_b8), 94, 12.5, boxstyle="round,pad=0.3,rounding_size=0.5",
                             linewidth=2, edgecolor=C_HIGH, facecolor=C_NEW, alpha=0.6)
ax.add_patch(container)
row_y = y_b8 + 0.75
row_h = 11

# B8 chip
b8_w = 9; b8_x = 5
boxw(b8_x, row_y, b8_w, row_h, "", color=C_HIGH, border=C_HIGH, fontsize=9)
ax.text(b8_x + b8_w/2, row_y + row_h - 2.5, "B8",
        ha="center", va="center", fontsize=17, fontweight="bold", color="white")
ax.text(b8_x + b8_w/2, row_y + 4, "n = 63",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")
ax.text(b8_x + b8_w/2, row_y + 2, "P(W) 82.54%",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")

# Power Zone box (dark mahogany/red-brown)
C_POWER = "#922B21"
pz_w = 7; pz_x = b8_x + b8_w + 1
boxw(pz_x, row_y, pz_w, row_h, "", color="#F2D7D5", border=C_POWER, fontsize=9)
ax.text(pz_x + pz_w/2, row_y + row_h/2 + 1.5, "Power",
        ha="center", va="center", fontsize=12, fontweight="bold", color=C_POWER)
ax.text(pz_x + pz_w/2, row_y + row_h/2 - 1.5, "Zone",
        ha="center", va="center", fontsize=12, fontweight="bold", color=C_POWER)
ax.text(pz_x + pz_w/2, row_y + row_h/2 - 3.5, "force extreme",
        ha="center", va="center", fontsize=6, color=C_POWER, style="italic")

# B8C1 — единственное активное условие
d_start_b8 = pz_x + pz_w + 1.5
d_w_b8 = (96 - d_start_b8 - 5 * 0.4) / 6
color_active = C_PREC
dx = d_start_b8
boxw(dx, row_y, d_w_b8, row_h, "", color="white", border=color_active, fontsize=9)
ax.text(dx + d_w_b8/2, row_y + row_h - 1.3, "B8C1",
        ha="center", va="center", fontsize=10.5, fontweight="bold", color=color_active)
bw = d_w_b8 * 0.85; bh = 1.1
bx = dx + (d_w_b8 - bw) / 2; by = row_y + row_h - 3.3
bb = FancyBboxPatch((bx, by), bw, bh, boxstyle="round,pad=0.05,rounding_size=0.2",
                    linewidth=0, facecolor=color_active, alpha=0.9)
ax.add_patch(bb)
ax.text(dx + d_w_b8/2, by + bh/2, "reverse force",
        ha="center", va="center", fontsize=6.5, color="white", fontweight="bold")
ax.text(dx + d_w_b8/2, row_y + row_h - 4.8, "divergence (∪3)",
        ha="center", va="center", fontsize=7, color="#34495E",
        fontweight="bold", family="monospace")
ax.text(dx + d_w_b8/2, row_y + 2.7, "n = 63",
        ha="center", va="center", fontsize=8.5, color="#34495E", fontweight="bold")
ax.text(dx + d_w_b8/2, row_y + 1.2, "P(W) 82.54%",
        ha="center", va="center", fontsize=9.5, color=color_active, fontweight="bold")

# ─── LAYER 6i: B9 Others sub-basket (B9C1 active) ─────────────
y_b9 = 0
container = FancyBboxPatch((3, y_b9), 94, 12.5, boxstyle="round,pad=0.3,rounding_size=0.5",
                             linewidth=2, edgecolor=C_HIGH, facecolor=C_NEW, alpha=0.6)
ax.add_patch(container)
row_y = y_b9 + 0.75

# B9 chip
b9_w = 9; b9_x = 5
boxw(b9_x, row_y, b9_w, row_h, "", color=C_HIGH, border=C_HIGH, fontsize=9)
ax.text(b9_x + b9_w/2, row_y + row_h - 2.5, "B9",
        ha="center", va="center", fontsize=17, fontweight="bold", color="white")
ax.text(b9_x + b9_w/2, row_y + 4, "n = 203",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")
ax.text(b9_x + b9_w/2, row_y + 2, "P(W) 72.91%",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")

# Others box (slate grey)
C_SLATE = "#515A5A"
ot_w = 7; ot_x = b9_x + b9_w + 1
boxw(ot_x, row_y, ot_w, row_h, "", color="#EAEDED", border=C_SLATE, fontsize=9)
ax.text(ot_x + ot_w/2, row_y + row_h/2 + 1.5, "Others",
        ha="center", va="center", fontsize=13, fontweight="bold", color=C_SLATE)
ax.text(ot_x + ot_w/2, row_y + row_h/2 - 1.2, "catch-all",
        ha="center", va="center", fontsize=8, color=C_SLATE, style="italic")
ax.text(ot_x + ot_w/2, row_y + row_h/2 - 3.3, "misc primitives",
        ha="center", va="center", fontsize=6, color=C_SLATE, style="italic")

# B9C1 — единственное активное условие
d_start_b9 = ot_x + ot_w + 1.5
d_w_b9 = (96 - d_start_b9 - 5 * 0.4) / 6
dx = d_start_b9
boxw(dx, row_y, d_w_b9, row_h, "", color="white", border=color_active, fontsize=9)
ax.text(dx + d_w_b9/2, row_y + row_h - 1.3, "B9C1",
        ha="center", va="center", fontsize=10.5, fontweight="bold", color=color_active)
bw = d_w_b9 * 0.85; bh = 1.1
bx = dx + (d_w_b9 - bw) / 2; by = row_y + row_h - 3.3
bb = FancyBboxPatch((bx, by), bw, bh, boxstyle="round,pad=0.05,rounding_size=0.2",
                    linewidth=0, facecolor=color_active, alpha=0.9)
ax.add_patch(bb)
ax.text(dx + d_w_b9/2, by + bh/2, "P11_count",
        ha="center", va="center", fontsize=6.5, color="white", fontweight="bold")
ax.text(dx + d_w_b9/2, row_y + row_h - 4.8, "4-window OR (2/3/4/6h)",
        ha="center", va="center", fontsize=7, color="#34495E",
        fontweight="bold", family="monospace")
ax.text(dx + d_w_b9/2, row_y + 2.7, "n = 203",
        ha="center", va="center", fontsize=8.5, color="#34495E", fontweight="bold")
ax.text(dx + d_w_b9/2, row_y + 1.2, "P(W) 72.91%",
        ha="center", va="center", fontsize=9.5, color=color_active, fontweight="bold")

# ─── FINAL RESULT: Basket union ────────────────────────────────
y = -10
result_container = FancyBboxPatch((6, y), 88, 8.5, boxstyle="round,pad=0.3,rounding_size=0.5",
                                    linewidth=2.5, edgecolor=C_HIGH,
                                    facecolor=C_HIGH, alpha=0.95)
ax.add_patch(result_container)
ax.text(50, y + 7.0, "ИТОГ — Basket B1 ∪ B2 ∪ … ∪ B9",
        ha="center", va="center", fontsize=12, fontweight="bold", color="white")
ax.text(50, y + 4.5,
        "n = 724    ·    conf = 483    ·    P(W) = 66.71%    ·    Δ = +18.11 pp",
        ha="center", va="center", fontsize=13, fontweight="bold", color="white")
ax.text(50, y + 2.0,
        "selectivity 724/1356 ≈ 53%   ·   B1_v4 canonical (causal-only)   ·   B6/B7 planned, не входят в union",
        ha="center", va="center", fontsize=8, color="white", style="italic")

# Save
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/pred12h_structure.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=130, bbox_inches="tight", facecolor="white", edgecolor="none")
print(f"Saved: {out}")
plt.close()
