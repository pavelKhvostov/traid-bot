"""Production strategy v3 — visual flowchart of decision logic."""
from __future__ import annotations
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle


OUT_PNG = pathlib.Path("/Users/vadim/Desktop/output PC1 hma/production_strategy_flowchart.png")


# ─── Visual style ───
BOX_COLORS = {
    "detect":  "#3498db",   # blue
    "filter":  "#e67e22",   # orange
    "calc":    "#9b59b6",   # purple
    "wait":    "#f1c40f",   # yellow
    "ml":      "#16a085",   # teal
    "decision":"#2c3e50",   # dark
    "action":  "#27ae60",   # green
    "abort":   "#c0392b",   # red
    "manage":  "#7f8c8d",   # gray
}


fig, ax = plt.subplots(figsize=(18, 26))
ax.set_xlim(0, 100)
ax.set_ylim(0, 200)
ax.axis("off")


def box(x, y, w, h, text, kind="action", fontsize=10, bold=True):
    color = BOX_COLORS.get(kind, "#888")
    p = FancyBboxPatch((x - w/2, y - h/2), w, h, boxstyle="round,pad=0.4",
                        facecolor=color, edgecolor="#222", linewidth=1.6, zorder=3)
    ax.add_patch(p)
    ax.text(x, y, text, ha="center", va="center", color="white",
             fontsize=fontsize, fontweight="bold" if bold else "normal", zorder=4,
             wrap=True)


def diamond(x, y, w, h, text, kind="decision", fontsize=10):
    color = BOX_COLORS.get(kind, "#888")
    from matplotlib.patches import Polygon
    pts = [[x, y + h/2], [x + w/2, y], [x, y - h/2], [x - w/2, y]]
    p = Polygon(pts, facecolor=color, edgecolor="#222", linewidth=1.6, zorder=3)
    ax.add_patch(p)
    ax.text(x, y, text, ha="center", va="center", color="white",
             fontsize=fontsize, fontweight="bold", zorder=4)


def arrow(x1, y1, x2, y2, label="", color="#333", lw=1.6, style="->"):
    a = FancyArrowPatch((x1, y1), (x2, y2),
                          arrowstyle=style, color=color, linewidth=lw,
                          mutation_scale=18, zorder=2)
    ax.add_patch(a)
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        ax.text(mx, my, label, ha="center", va="center", color=color,
                 fontsize=10, fontweight="bold",
                 bbox=dict(facecolor="white", edgecolor=color,
                           boxstyle="round,pad=0.2", linewidth=1.0))


def section(y, text, color="#34495e"):
    ax.add_patch(FancyBboxPatch((2, y - 1.5), 96, 3, boxstyle="round,pad=0.2",
                                  facecolor=color, edgecolor="none", alpha=0.4, zorder=1))
    ax.text(50, y, text, ha="center", va="center", color="white",
             fontsize=14, fontweight="bold", zorder=5)


# ═══════════ HEADER ═══════════
ax.text(50, 197, "HMA v3 Production Strategy — Decision Flowchart",
         ha="center", va="center", fontsize=20, fontweight="bold", color="#222")
ax.text(50, 194, "ob_vc 2h LONG/SHORT  ·  BTC+ETH  ·  RR=1.7  ·  WR target 70%+",
         ha="center", va="center", fontsize=12, color="#444", style="italic")


# ═══════════ SECTION 1: DETECTION ═══════════
section(187, "STEP 1: ob_vc detection (canon #1-#8 with relaxed #7)")

box(50, 181, 70, 5,
    "ob_vc 2h setup fires (born_ms)\nDetected with relaxed canon #7",
    kind="detect", fontsize=12)
arrow(50, 178.5, 50, 174)


# ═══════════ SECTION 2: PRE-ENTRY FILTERS ═══════════
section(170, "STEP 2: Pre-entry filters (skip setup if any FAIL)")

box(20, 162, 26, 5,
    "FILTER A: R% ≥ 0.5%\n(futures viable)",
    kind="filter", fontsize=10)
box(50, 162, 26, 5,
    "FILTER B: drop\nBTC short",
    kind="filter", fontsize=10)
box(80, 162, 26, 5,
    "FILTER C: drop\nT1a, T11a, T9a",
    kind="filter", fontsize=10)

# Arrows from setup to filters
arrow(35, 173, 20, 165)
arrow(50, 174, 50, 165)
arrow(65, 173, 80, 165)

# Arrows to decision diamond
diamond(50, 153, 24, 6, "ALL filters PASS?", kind="decision", fontsize=11)
arrow(20, 159, 41, 156)
arrow(50, 159.5, 50, 156)
arrow(80, 159, 59, 156)

# SKIP if fail
box(15, 153, 16, 5, "✗ SKIP\nsetup", kind="abort", fontsize=11)
arrow(38, 153, 23, 153, label="NO", color="#c0392b")


# ═══════════ SECTION 3: CALCULATE ENTRY/SL/TP ═══════════
section(143, "STEP 3: Calculate entry / SL / TP")

box(50, 137, 78, 6,
    "deep = 0.8 if n_FVG≥2 else 0.2\n"
    "LONG:  entry = fvg_hi - deep×(fvg_hi - fvg_lo)  |  SL = drop_lo  |  TP = entry + 1.7R\n"
    "SHORT: entry = fvg_lo + deep×(fvg_hi - fvg_lo)  |  SL = drop_hi  |  TP = entry - 1.7R",
    kind="calc", fontsize=10)

arrow(50, 150, 50, 140, label="YES", color="#27ae60")


# ═══════════ SECTION 4: PLACE ORDER + WAIT ═══════════
section(128, "STEP 4-5: Place limit order, WAIT for entry fill")

box(50, 122, 50, 5, "Place limit order at entry\nLifetime: 14 days", kind="wait", fontsize=10)
arrow(50, 134, 50, 124.5)

diamond(50, 115, 30, 5, "Entry touched within 14d?", kind="decision", fontsize=11)
arrow(50, 119.5, 50, 117.5)

box(15, 115, 16, 5, "✗ Order\ncancelled", kind="abort", fontsize=10)
arrow(35, 115, 23, 115, label="NO", color="#c0392b")


# ═══════════ SECTION 5: AT FILL — RECOMPUTE FEATURES ═══════════
section(108, "STEP 5: AT entry_fill_ms — recompute features (KEY!)")

box(50, 102, 88, 7,
    "Compute 601 features at entry_fill_ms (NOT born_ms!)\n"
    "  590 HMA features (10 lengths × 11 TFs × 5 derivs + aggregates)\n"
    "  11 wait-window features (fill_delay, max_high/low, touched_SL, vol_change, ...)",
    kind="ml", fontsize=10)
arrow(50, 112.5, 50, 105.5, label="YES", color="#27ae60")


# ═══════════ SECTION 6: VALIDATION GATE ═══════════
section(92, "STEP 5.4: Validation gate (CRITICAL)")

diamond(50, 86, 50, 6, "wait_touched_sl_before_entry == 1?", kind="decision", fontsize=11)
arrow(50, 98.5, 50, 89)

box(15, 86, 16, 5, "✗ ABORT\nat market", kind="abort", fontsize=10)
arrow(25, 86, 23, 86, label="YES", color="#c0392b")


# ═══════════ SECTION 7: ML SCORING ═══════════
section(78, "STEP 5.3-5.5: ML scoring & threshold decision")

box(50, 72, 65, 5,
    "Apply LightGBM ensemble (3 seeds avg)\nproba = mean(model.predict_proba)",
    kind="ml", fontsize=10)
arrow(50, 83, 50, 74.5, label="NO", color="#27ae60")

diamond(50, 64, 35, 5.5, "proba ≥ 0.5888?", kind="decision", fontsize=12)
arrow(50, 69.5, 50, 66.5)

box(15, 64, 16, 5, "✗ CLOSE\nat market", kind="abort", fontsize=10)
arrow(33, 64, 23, 64, label="NO", color="#c0392b")


# ═══════════ SECTION 8: KEEP TRADE ═══════════
section(56, "STEP 6: KEEP trade (hold until SL/TP)")

box(50, 50, 75, 5,
    "✓ KEEP trade — let it run to TP or SL\n"
    "No moving SL, no partial exits, no trailing\n"
    "Horizon: 14 days timeout",
    kind="action", fontsize=11)
arrow(50, 61, 50, 53, label="YES", color="#27ae60")


# ═══════════ SECTION 9: TRADE EXIT ═══════════
section(40, "STEP 6 (cont.): Trade exit")

box(20, 33, 22, 5, "+1.7R\n(TP hit)", kind="action", fontsize=11)
box(50, 33, 22, 5, "-1.0R\n(SL hit)", kind="abort", fontsize=11)
box(80, 33, 22, 5, "Close at\nmarket (14d)", kind="manage", fontsize=10)

arrow(40, 47.5, 25, 36)
arrow(50, 47.5, 50, 36)
arrow(60, 47.5, 75, 36)


# ═══════════ SECTION 10: RISK MANAGEMENT (sidebar) ═══════════
section(22, "STEP 7: Risk management (always-on rules)")

ax.text(8, 16,
        "Position sizing:",
        ha="left", fontsize=11, fontweight="bold", color="#222")
ax.text(8, 13.5,
        "  1% account risk per trade\n"
        "  size = 1% / (R% × leverage)",
        ha="left", fontsize=10, color="#444")

ax.text(40, 16,
        "Concurrent trades:",
        ha="left", fontsize=11, fontweight="bold", color="#222")
ax.text(40, 13.5,
        "  Max 3 simultaneously\n"
        "  Max 2 in same direction",
        ha="left", fontsize=10, color="#444")

ax.text(72, 16,
        "Risk-off triggers:",
        ha="left", fontsize=11, fontweight="bold", color="#222")
ax.text(72, 13.5,
        "  6 losses straight → 24h pause\n"
        "  10% DD → full review\n"
        "  -3% daily → stop day",
        ha="left", fontsize=10, color="#444")


# ═══════════ EXPECTED PERFORMANCE BAR ═══════════
section(6, "Expected performance (refinement D)")

ax.text(50, 2.5,
        "WR 74.5%   |   ~10 trades/month   |   E[R] = +1.12R/trade   |   "
        "+137R/year   |   Max DD = -6R",
        ha="center", fontsize=12, fontweight="bold", color="#27ae60")


plt.savefig(OUT_PNG, dpi=110, bbox_inches="tight")
print(f"Saved: {OUT_PNG}")
