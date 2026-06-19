"""LONG/SHORT × entry-rule (n_FVG ≥ 2 deep=0.8 / n_FVG = 1 deep=0.2) breakdown for BTC + ETH.

8 cells: 2 assets × 2 directions × 2 rules.
"""
import pathlib
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

CELLS = {
    ('BTC', 'long',  '≥2'): (628,  598,  55.9, +0.117,  +70, 0.86),
    ('BTC', 'long',  '1'):  (1406, 1334, 55.9, +0.118, +158, 0.74),
    ('BTC', 'short', '≥2'): (565,  527,  52.8, +0.055,  +29, 0.81),
    ('BTC', 'short', '1'):  (1437, 1379, 52.6, +0.051,  +72, 0.66),
    ('ETH', 'long',  '≥2'): (1023, 969,  54.5, +0.090,  +87, 1.15),
    ('ETH', 'long',  '1'):  (1647, 1562, 52.7, +0.054,  +85, 0.92),
    ('ETH', 'short', '≥2'): (997,  949,  54.2, +0.083,  +80, 0.99),
    ('ETH', 'short', '1'):  (1693, 1620, 51.5, +0.031,  +50, 0.79),
}

ASSETS = ['BTC', 'ETH']
COLS = [
    ('long',  '≥2', 'LONG · n_FVG ≥ 2',  'deep = 0.8 (into FVG)'),
    ('long',  '1',  'LONG · n_FVG = 1',  'deep = 0.2 (shallow)'),
    ('short', '≥2', 'SHORT · n_FVG ≥ 2', 'deep = 0.8 (into FVG)'),
    ('short', '1',  'SHORT · n_FVG = 1', 'deep = 0.2 (shallow)'),
]

COL_LONG  = "#27ae60"
COL_SHORT = "#c0392b"
COL_BTC   = "#f7931a"
COL_ETH   = "#627eea"


def ev_color(ev):
    if ev < 0:        return "#c0392b"
    if ev >= 0.20:    return "#0a7c2b"
    if ev >= 0.15:    return "#1a8f3f"
    if ev >= 0.10:    return "#27ae60"
    if ev >= 0.05:    return "#f1c40f"
    return "#e67e22"


fig, ax = plt.subplots(figsize=(22, 11))
ax.set_xlim(0, 22)
ax.set_ylim(0, 11)
ax.set_aspect("equal")
ax.axis("off")


def box(x, y, w, h, text, fc="#fafafa", ec="#333", fontsize=10, fontweight="normal",
        text_color="#222", lw=1.3):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08",
                        linewidth=lw, facecolor=fc, edgecolor=ec, zorder=3)
    ax.add_patch(p)
    if text:
        ax.text(x + w/2, y + h/2, text, ha="center", va="center",
                fontsize=fontsize, fontweight=fontweight, color=text_color, zorder=4)


# ─── Title ────────────────────────────────────────────
ax.text(11, 10.45,
        "Entry-rule breakdown · 2h ob_vc · BTC + ETH · 6.4y (2020-01-01 → 2026-06-09)",
        ha="center", va="center", fontsize=15, fontweight="bold", color="#222")
ax.text(11, 10.0,
        "Rule A: n_FVG ≥ 2 → entry deep = 0.8  ·  Rule B: n_FVG = 1 → entry deep = 0.2  ·  SL = low/high_ob_vc · TP = +1R",
        ha="center", va="center", fontsize=11, color="#666", style="italic")

# ─── Column headers ───────────────────────────────────
COL_W = 4.6; COL_GAP = 0.25
ROW_H = 3.6; ROW_GAP = 0.35
LEFT_PAD = 1.6
HDR_Y = 8.6
HDR_H = 0.7

for ci, (dir_, nc, label, sub) in enumerate(COLS):
    cx = LEFT_PAD + ci * (COL_W + COL_GAP)
    color = COL_LONG if dir_ == 'long' else COL_SHORT
    box(cx, HDR_Y, COL_W, HDR_H, "", fc=color, ec=color, lw=1.0)
    ax.text(cx + COL_W/2, HDR_Y + HDR_H/2 + 0.10, label,
            ha="center", va="center", fontsize=12.5, fontweight="bold", color="white", zorder=5)
    ax.text(cx + COL_W/2, HDR_Y + HDR_H/2 - 0.20, sub,
            ha="center", va="center", fontsize=9.5, color="white", alpha=0.85, zorder=5)


# ─── Row labels + cells ──────────────────────────────
def draw_cell(cx, cy, asset, dir_, nc):
    n, n_t, wr, ev, sigR, rpct = CELLS[(asset, dir_, nc)]
    asset_col = COL_BTC if asset == 'BTC' else COL_ETH

    box(cx, cy, COL_W, ROW_H, "", fc="#fafafa", ec="#444", lw=1.5)

    # N (big, top-left area)
    ax.text(cx + COL_W/2, cy + ROW_H - 0.55, f"{n:,}",
            ha="center", va="center", fontsize=28, fontweight="bold",
            color=asset_col, zorder=5)
    ax.text(cx + COL_W/2, cy + ROW_H - 1.15, f"setups  ·  touched {n_t:,} ({n_t/n*100:.1f}%)",
            ha="center", va="center", fontsize=10, color="#555", zorder=5)

    # WR
    ax.text(cx + COL_W/2, cy + ROW_H - 1.85, f"WR  {wr:.1f}%",
            ha="center", va="center", fontsize=15, fontweight="bold", color="#222", zorder=5)

    # EV badge
    ev_bg = ev_color(ev)
    ax.text(cx + COL_W/2, cy + ROW_H - 2.45, f"EV  {ev:+.3f}R",
            ha="center", va="center", fontsize=13, fontweight="bold",
            color="white", zorder=5,
            bbox=dict(facecolor=ev_bg, edgecolor=ev_bg,
                      boxstyle="round,pad=0.32", linewidth=0))

    # Sigma R + R%
    sigma_col = "#c0392b" if sigR < 0 else "#185c34"
    ax.text(cx + COL_W/2, cy + 0.65, f"Σ  {sigR:+}R / 6y",
            ha="center", va="center", fontsize=12.5, fontweight="bold",
            color=sigma_col, zorder=5)
    ax.text(cx + COL_W/2, cy + 0.25, f"avg R% = {rpct:.2f}%",
            ha="center", va="center", fontsize=10.5, fontweight="bold",
            color="#7e3c9e", style="italic", zorder=5)


for ri, asset in enumerate(ASSETS):
    cy = HDR_Y - 0.45 - (ri + 1) * (ROW_H + ROW_GAP) + ROW_GAP
    asset_col = COL_BTC if asset == 'BTC' else COL_ETH
    # Row label box
    box(0.2, cy, 1.3, ROW_H, "", fc=asset_col, ec=asset_col, lw=1.0)
    ax.text(0.2 + 0.65, cy + ROW_H/2, asset,
            ha="center", va="center", fontsize=22, fontweight="bold", color="white", zorder=5)
    for ci, (dir_, nc, _, _) in enumerate(COLS):
        cx = LEFT_PAD + ci * (COL_W + COL_GAP)
        draw_cell(cx, cy, asset, dir_, nc)


plt.subplots_adjust(left=0.005, right=0.995, top=0.99, bottom=0.01)
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/ob_vc_2h_entry_rules_breakdown.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=130, bbox_inches="tight")
print(f"Saved: {out}")
