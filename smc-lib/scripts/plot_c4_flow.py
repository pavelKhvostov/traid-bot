"""C4 как основной пример — горизонтальный flow:
[C4] → [Пояснение: неэффективность FVG] → [D1 D2 D3 D4 D5 D6]

Output: ~/Desktop/i-rdrb-charts/c4_flow.png
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
import pathlib

plt.rcParams["font.family"] = "DejaVu Sans"

# Colors
C_HEAD = "#34495E"
C_CASC = "#7F8C8D"
C_PREC = "#27AE60"
C_RECL = "#E67E22"
C_HIGH = "#E74C3C"
C_BASE = "#16A085"
C_BLUE = "#2980B9"
C_BG = "#FAFAFA"

fig = plt.figure(figsize=(11, 3.4), dpi=110)
ax = fig.add_subplot(111)
ax.set_xlim(0, 100)
ax.set_ylim(0, 30)
ax.set_aspect("equal")
ax.axis("off")

def box_rounded(x, y, w, h, facecolor, edgecolor, lw=1.5, alpha=0.95):
    bb = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.1,rounding_size=0.5",
                         linewidth=lw, edgecolor=edgecolor, facecolor=facecolor, alpha=alpha)
    ax.add_patch(bb)

def arrow(x1, y1, x2, y2, color=C_CASC, lw=2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="->", color=color, lw=lw))

# ─── TITLE ─────────────────────────────────────────────────────
ax.text(50, 28.3, "C4 — учебный пример: ловим «неэффективность FVG»",
        ha="center", va="center", fontsize=18, fontweight="bold", color=C_HEAD)
ax.text(50, 26.3, "OR-sub-basket из 6 параллельных Dx по 3 осям  (Lifecycle × Sweep × Filter)",
        ha="center", va="center", fontsize=9.5, color=C_CASC, style="italic")

# ─── ROW Y CENTER ─────────────────────────────────────────────
ROW_H = 13
ROW_Y_CENTER = 17.5
ROW_Y = ROW_Y_CENTER - ROW_H / 2

# ─── 1) C4 main block (LEFT, narrow) ──────────────────────────
c4_x = 1; c4_w = 7
box_rounded(c4_x, ROW_Y, c4_w, ROW_H, facecolor=C_HIGH, edgecolor=C_HIGH, alpha=0.95)
ax.text(c4_x + c4_w/2, ROW_Y + ROW_H - 1.7, "C4",
        ha="center", va="center", fontsize=18, fontweight="bold", color="white")
ax.text(c4_x + c4_w/2, ROW_Y + ROW_H - 3.9, "OR-sub-basket\nFVG",
        ha="center", va="center", fontsize=7, color="white", linespacing=1.2)
# Stats
ax.text(c4_x + c4_w/2, ROW_Y + 5, "n = 251",
        ha="center", va="center", fontsize=9, color="white", fontweight="bold")
ax.text(c4_x + c4_w/2, ROW_Y + 3, "P(W) 64.5%",
        ha="center", va="center", fontsize=10, color="white", fontweight="bold")
ax.text(c4_x + c4_w/2, ROW_Y + 1.2, "Δ +15.6 pp",
        ha="center", va="center", fontsize=6.5, color="white", style="italic")

# (стрелка C4 → Fair Value Gap убрана)

# ─── 2) Пояснение «Fair Value Gap» (LEFT, narrow) ─────────────
exp_x = c4_x + c4_w + 2; exp_w = 11
box_rounded(exp_x, ROW_Y, exp_w, ROW_H, facecolor="#FFF9F0", edgecolor=C_RECL, alpha=0.9)
ax.text(exp_x + exp_w/2, ROW_Y_CENTER + 2.0, "Fair",
        ha="center", va="center", fontsize=12, fontweight="bold", color=C_RECL)
ax.text(exp_x + exp_w/2, ROW_Y_CENTER, "Value",
        ha="center", va="center", fontsize=12, fontweight="bold", color=C_RECL)
ax.text(exp_x + exp_w/2, ROW_Y_CENTER - 2.0, "Gap",
        ha="center", va="center", fontsize=12, fontweight="bold", color=C_RECL)

# (стрелка Fair Value Gap → D-блоки и подпись «6 ракурсов» убраны)
arrow_x = exp_x + exp_w + 0.2

# ─── 3) D1..D6 blocks (RIGHT, dominant) ───────────────────────
d_start_x = arrow_x + 2
d_total_w = 99 - d_start_x
d_gap = 0.7
d_w = (d_total_w - 5 * d_gap) / 6
d_h = ROW_H

d_blocks = [
    ("D1", "strict sweep", "L0 / S100 / WIDE",    33,  93.9, "precision\nanchor",     C_PREC),
    ("D2", "strict sweep", "L0 / S50 / AGE-WIDE", 64,  89.1, "aged-wide\nclassic",    C_PREC),
    ("D3", "strict sweep", "L0 / S70 / AGE50",   126,  76.2, "aged\ndeeper sweep",    C_PREC),
    ("D4", "strict sweep", "L0 / S50 / HTF-WIDE", 53,  79.2, "HTF wide\nprecision",   C_PREC),
    ("D5", "wick-fill",    "L1 / W50 / AGE50",    94,  55.3, "wick-fill",             C_RECL),
    ("D6", "wick-fill",    "L2 / W100 / AGE50",   96,  52.1, "full-fill\nrebalance",  C_RECL),
]

for i, (name, kind, params, n_val, wr, role, color) in enumerate(d_blocks):
    dx = d_start_x + i * (d_w + d_gap)
    # background
    box_rounded(dx, ROW_Y, d_w, d_h, facecolor="white", edgecolor=color, lw=2, alpha=0.95)
    # title (Dx) — top
    ax.text(dx + d_w/2, ROW_Y + d_h - 1.4, name,
            ha="center", va="center", fontsize=15, fontweight="bold", color=color)
    # kind badge (strict sweep / wick-fill)
    badge_w = d_w * 0.84
    badge_h = 1.3
    badge_x = dx + (d_w - badge_w) / 2
    badge_y = ROW_Y + d_h - 3.7
    bb = FancyBboxPatch((badge_x, badge_y), badge_w, badge_h,
                        boxstyle="round,pad=0.05,rounding_size=0.25",
                        linewidth=0, facecolor=color, alpha=0.85)
    ax.add_patch(bb)
    ax.text(dx + d_w/2, badge_y + badge_h/2, kind,
            ha="center", va="center", fontsize=7.5, color="white", fontweight="bold")
    # params
    ax.text(dx + d_w/2, ROW_Y + d_h - 5.2, params,
            ha="center", va="center", fontsize=8, color="#34495E",
            fontweight="bold", family="monospace")
    # role
    ax.text(dx + d_w/2, ROW_Y + d_h - 7.4, role,
            ha="center", va="center", fontsize=7.5, color="#7F8C8D",
            style="italic", linespacing=1.15)
    # stats
    ax.text(dx + d_w/2, ROW_Y + 2.7, f"n = {n_val}",
            ha="center", va="center", fontsize=9.5, color="#34495E", fontweight="bold")
    ax.text(dx + d_w/2, ROW_Y + 1.1, f"P(W) = {wr}%",
            ha="center", va="center", fontsize=11, color=color, fontweight="bold")

# (группировочные скобки убраны — теперь strict sweep / wick-fill метка
# выведена бэйджем внутри каждого D-блока)

# ─── AXES LEGEND ────────────────────────────────────────────────
LY = 4.5
box_rounded(1.5, LY - 1, 97, 5.2, facecolor=C_BG, edgecolor=C_CASC, lw=1, alpha=0.6)
ax.text(3, LY + 3.5, "Расшифровка осей Dx:",
        ha="left", va="center", fontsize=9.5, fontweight="bold", color=C_HEAD)
axes_text = [
    ("Lifecycle:", "L0 = никогда не abandon  ·  L1 = wick≥50% mitigates  ·  L2 = wick≥100% full fill  ·  L3 = close inside  ·  L4 = timeout 120 bars"),
    ("Sweep:",     "S50/70/100 = wick ≥ X% + close OUTSIDE (rejection)  ·  W50/W100 = pure wick-fill  ·  CINS = wick + close inside"),
    ("Filter:",    "ANY  ·  HTF (D+)  ·  12h  ·  AGE50 (FVG age ≥ 50 12h-bars)  ·  WIDE (zone ≥ 0.7 ATR)  ·  комбинации"),
]
for i, (axis, vals) in enumerate(axes_text):
    yy = LY + 2.3 - i * 1.15
    ax.text(3, yy, axis, ha="left", va="center", fontsize=8, family="monospace",
            color="#2C3E50", fontweight="bold")
    ax.text(13, yy, vals, ha="left", va="center", fontsize=7.5, color="#34495E")

# ─── FOOTER ───────────────────────────────────────────────────
ax.text(50, 1.2, "C4 = D1 ∪ D2 ∪ D3 ∪ D4 ∪ D5 ∪ D6     (default C4: n=182 / WR 59.9% → C4_v2: n=251 / WR 64.5%, Δ +4.7 pp)",
        ha="center", va="center", fontsize=9, color=C_HEAD, fontweight="bold")

out = pathlib.Path.home() / "Desktop/i-rdrb-charts/c4_flow.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=130, bbox_inches="tight", facecolor="white", edgecolor="none")
print(f"Saved: {out}")
plt.close()
