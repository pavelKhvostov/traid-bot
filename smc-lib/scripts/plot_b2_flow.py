"""B2 flow — горизонтальный план по образцу B1:
[B2] → [Order Block] → [B2C1 active] + [B2C2..B2C6 planned]

Output: ~/Desktop/i-rdrb-charts/b2_flow.png
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import pathlib

plt.rcParams["font.family"] = "DejaVu Sans"

# Colors
C_HEAD = "#34495E"
C_CASC = "#7F8C8D"
C_PREC = "#27AE60"
C_HIGH = "#E74C3C"
C_PURPLE = "#8E44AD"
C_PLACEHOLDER = "#BDC3C7"
C_BG = "#FAFAFA"

fig = plt.figure(figsize=(13, 4.2), dpi=110)
ax = fig.add_subplot(111)
ax.set_xlim(0, 100)
ax.set_ylim(0, 35)
ax.set_aspect("equal")
ax.axis("off")

def box_rounded(x, y, w, h, facecolor, edgecolor, lw=1.5, alpha=0.95, linestyle="solid"):
    bb = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.1,rounding_size=0.5",
                         linewidth=lw, edgecolor=edgecolor, facecolor=facecolor,
                         alpha=alpha, linestyle=linestyle)
    ax.add_patch(bb)

# ─── TITLE ─────────────────────────────────────────────────────
ax.text(50, 33, "B2 — Order Block",
        ha="center", va="center", fontsize=18, fontweight="bold", color=C_HEAD)
ax.text(50, 30.5, "OR-sub-basket  B2C1 ∪ B2C2 ∪ … ∪ B2C6   (1 active / 5 planned)",
        ha="center", va="center", fontsize=9.5, color=C_CASC, style="italic")

# ─── ROW Y ─────────────────────────────────────────────────────
ROW_H = 22
ROW_Y_CENTER = 14
ROW_Y = ROW_Y_CENTER - ROW_H / 2

# ─── 1) B2 main block ────────────────────────────────────────
b2_x = 1; b2_w = 8
box_rounded(b2_x, ROW_Y, b2_w, ROW_H, facecolor=C_HIGH, edgecolor=C_HIGH, alpha=0.95)
ax.text(b2_x + b2_w/2, ROW_Y + ROW_H - 2.7, "B2",
        ha="center", va="center", fontsize=22, fontweight="bold", color="white")
ax.text(b2_x + b2_w/2, ROW_Y + ROW_H - 6.5, "current\n(B2C1 only)",
        ha="center", va="center", fontsize=7, color="white", style="italic",
        linespacing=1.2)
# Stats
ax.text(b2_x + b2_w/2, ROW_Y + 9, "n = 54",
        ha="center", va="center", fontsize=10, color="white", fontweight="bold")
ax.text(b2_x + b2_w/2, ROW_Y + 6.7, "P(W) 88.9%",
        ha="center", va="center", fontsize=11, color="white", fontweight="bold")
ax.text(b2_x + b2_w/2, ROW_Y + 4.3, "Δ +40.3 pp",
        ha="center", va="center", fontsize=7.5, color="white", style="italic")
ax.text(b2_x + b2_w/2, ROW_Y + 1.5, "1 / 6 active",
        ha="center", va="center", fontsize=7, color="white", style="italic")

# ─── 2) Order Block explanation ──────────────────────────────
exp_x = b2_x + b2_w + 1.5; exp_w = 11
box_rounded(exp_x, ROW_Y, exp_w, ROW_H, facecolor="#F5EEF8", edgecolor=C_PURPLE, alpha=0.9)
ax.text(exp_x + exp_w/2, ROW_Y_CENTER + 4, "Order",
        ha="center", va="center", fontsize=13, fontweight="bold", color=C_PURPLE)
ax.text(exp_x + exp_w/2, ROW_Y_CENTER + 1, "Block",
        ha="center", va="center", fontsize=13, fontweight="bold", color=C_PURPLE)
ax.text(exp_x + exp_w/2, ROW_Y_CENTER - 3, "блок-класс\nзоны",
        ha="center", va="center", fontsize=8, color=C_PURPLE, style="italic",
        linespacing=1.2)

# ─── 3) B2C1 active + B2C2..B2C6 planned ─────────────────────
d_blocks = [
    ("B2C1", "active",  "FIRST 50%-sweep",  "multi-TF",   54,  88.9, C_PREC, True),
    ("B2C2", "planned", "OB + AGE50",       "aged",       None, None, C_PLACEHOLDER, False),
    ("B2C3", "planned", "OB + WIDE",        "≥0.7 ATR",   None, None, C_PLACEHOLDER, False),
    ("B2C4", "planned", "OB / S70/S100",    "depth grid", None, None, C_PLACEHOLDER, False),
    ("B2C5", "planned", "OB → retest",      "close in",   None, None, C_PLACEHOLDER, False),
    ("B2C6", "planned", "OB + vol_z≥2σ",    "spike",      None, None, C_PLACEHOLDER, False),
]

d_start_x = exp_x + exp_w + 1.5
d_total_w = 99 - d_start_x
d_gap = 0.7
d_w = (d_total_w - 5 * d_gap) / 6
d_h = ROW_H

for i, (name, kind, params1, params2, n_val, wr, color, active) in enumerate(d_blocks):
    dx = d_start_x + i * (d_w + d_gap)
    edge_style = "solid" if active else "dashed"
    facecolor = "white" if active else "#F4F6F7"
    box_rounded(dx, ROW_Y, d_w, d_h, facecolor=facecolor, edgecolor=color,
                lw=2 if active else 1.3, alpha=0.95, linestyle=edge_style)
    # name
    ax.text(dx + d_w/2, ROW_Y + d_h - 2.3, name,
            ha="center", va="center", fontsize=13, fontweight="bold",
            color=color if active else "#7F8C8D")
    # kind badge
    badge_w = d_w * 0.84
    badge_h = 1.7
    badge_x = dx + (d_w - badge_w) / 2
    badge_y = ROW_Y + d_h - 5.5
    bb = FancyBboxPatch((badge_x, badge_y), badge_w, badge_h,
                        boxstyle="round,pad=0.05,rounding_size=0.25",
                        linewidth=0, facecolor=color, alpha=0.85 if active else 0.45)
    ax.add_patch(bb)
    ax.text(dx + d_w/2, badge_y + badge_h/2, kind,
            ha="center", va="center", fontsize=8,
            color="white", fontweight="bold")
    # params (two lines, compact)
    ax.text(dx + d_w/2, ROW_Y + d_h - 8.2, params1,
            ha="center", va="center", fontsize=8,
            color="#34495E" if active else "#95A5A6",
            fontweight="bold" if active else "normal",
            family="monospace")
    ax.text(dx + d_w/2, ROW_Y + d_h - 10.2, params2,
            ha="center", va="center", fontsize=7,
            color="#7F8C8D" if active else "#BDC3C7",
            style="italic")
    # stats
    if active:
        ax.text(dx + d_w/2, ROW_Y + 4.5, f"n = {n_val}",
                ha="center", va="center", fontsize=10.5, color="#34495E", fontweight="bold")
        ax.text(dx + d_w/2, ROW_Y + 2.5, f"P(W) = {wr}%",
                ha="center", va="center", fontsize=12, color=color, fontweight="bold")
    else:
        ax.text(dx + d_w/2, ROW_Y + 4.5, "TBD",
                ha="center", va="center", fontsize=11, color="#95A5A6",
                style="italic", fontweight="bold")
        ax.text(dx + d_w/2, ROW_Y + 2.3, "causality\naudit req.",
                ha="center", va="center", fontsize=6.5, color="#95A5A6",
                style="italic", linespacing=1.2)

# ─── LEGEND ────────────────────────────────────────────────────
LY = 1.7
box_rounded(1.5, LY - 0.5, 97, 2.7, facecolor=C_BG, edgecolor=C_CASC, lw=1, alpha=0.6)
ax.text(50, LY + 1.3,
        "B2Cx по 3 осям (как B1):  Lifecycle (L0..L4)  ×  Sweep formula (S50/70/100, retest, vol_spike)  ×  Filter (ANY / AGE50 / WIDE / комбинации)",
        ha="center", va="center", fontsize=7.8, color="#34495E")

out = pathlib.Path.home() / "Desktop/i-rdrb-charts/b2_flow.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=130, bbox_inches="tight", facecolor="white", edgecolor="none")
print(f"Saved: {out}")
plt.close()
