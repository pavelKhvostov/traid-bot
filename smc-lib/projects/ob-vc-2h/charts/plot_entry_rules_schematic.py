"""Schematic of the two entry rules: n_FVG = 1 (shallow 0.2) vs n_FVG ≥ 2 (deep 0.8).

LONG-direction illustration (SHORT mirror-image). Shows OB pair, drop_area,
FVG zone(s), entry depth, SL, TP1R. Abstract — not real bars.
"""
import pathlib
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch
from matplotlib.lines import Line2D


# ─── Geometry common to both panels ──────────────────
# Price axis: arbitrary units. Use round numbers for readability.
LOW_OB    = 100.0    # = drop_lo = low_OB_VC = SL
PREV_OPEN = 120.0    # = drop_hi (top of drop area, also prev candle open)
DROP_HI   = PREV_OPEN
CUR_CLOSE = 145.0    # cur candle close

# Candle widths/positions
X_PREV = 1.0; X_CUR = 2.6; CANDLE_W = 0.6


# ─── Panel A: n_FVG = 1 (single FVG, shallow entry deep=0.2) ──
# Single FVG fills more of the drop area
PANEL_A_FVG = (108.0, 118.0)   # zone_lo, zone_hi (medium width)

# ─── Panel B: n_FVG ≥ 2 (stacked FVGs, deep entry 0.8 into top FVG) ──
PANEL_B_FVGS = [
    (105.0, 110.0),   # bottom FVG
    (112.0, 118.0),   # top FVG (← chosen)
]


def deep_entry_long(fvg_lo, fvg_hi, deep):
    return fvg_hi - deep * (fvg_hi - fvg_lo)


# Two-panel figure
fig, (axA, axB) = plt.subplots(1, 2, figsize=(20, 11),
                                gridspec_kw={"wspace": 0.12})

# Title
fig.suptitle("Два правила входа · 2h ob_vc LONG  (SHORT — зеркально)",
             fontsize=17, fontweight="bold", y=0.97)


def draw_panel(ax, title, subtitle, fvgs, chosen_idx, deep, color_accent):
    """Draw schematic on ax. fvgs = list of (lo, hi); chosen_idx — index of FVG used for entry."""
    ax.set_xlim(0, 6.5)
    ax.set_ylim(85, 165)
    ax.set_aspect("auto")

    # Subtitle
    ax.set_title(f"{title}\n{subtitle}",
                 fontsize=13.5, fontweight="bold", color=color_accent, pad=12)

    # ─── Prev candle (red, body PREV_OPEN → low; wick to LOW_OB) ─
    prev_body_lo = LOW_OB + 5
    prev_body_hi = PREV_OPEN
    ax.add_patch(Rectangle((X_PREV - CANDLE_W/2, prev_body_lo), CANDLE_W,
                            prev_body_hi - prev_body_lo,
                            fc="#e74c3c", ec="#c0392b", lw=1.5, zorder=4))
    # Wick
    ax.plot([X_PREV, X_PREV], [LOW_OB, prev_body_hi], color="#c0392b", lw=2, zorder=4)
    ax.plot([X_PREV, X_PREV], [prev_body_hi, prev_body_hi + 3], color="#c0392b", lw=2, zorder=4)
    ax.text(X_PREV, prev_body_hi + 4.5, "prev",
            ha="center", va="bottom", fontsize=10, color="#c0392b", fontweight="bold")

    # ─── Cur candle (green, body PREV_OPEN → CUR_CLOSE, wick down to drop_lo+2) ─
    cur_body_lo = PREV_OPEN
    cur_body_hi = CUR_CLOSE
    ax.add_patch(Rectangle((X_CUR - CANDLE_W/2, cur_body_lo), CANDLE_W,
                            cur_body_hi - cur_body_lo,
                            fc="#27ae60", ec="#1e8449", lw=1.5, zorder=4))
    ax.plot([X_CUR, X_CUR], [LOW_OB + 2, cur_body_lo], color="#1e8449", lw=2, zorder=4)
    ax.plot([X_CUR, X_CUR], [cur_body_hi, cur_body_hi + 3], color="#1e8449", lw=2, zorder=4)
    ax.text(X_CUR, cur_body_hi + 4.5, "cur",
            ha="center", va="bottom", fontsize=10, color="#1e8449", fontweight="bold")

    # ─── Drop area (light orange band) ─────────────────
    DROP_X0, DROP_X1 = 0.2, 6.3
    ax.add_patch(Rectangle((DROP_X0, LOW_OB), DROP_X1 - DROP_X0, DROP_HI - LOW_OB,
                            fc="#fff3e0", ec="none", alpha=0.55, zorder=1))
    ax.text(DROP_X1 - 0.1, LOW_OB + (DROP_HI - LOW_OB)/2,
            f"drop area\n[low_OB ; prev.open]",
            ha="right", va="center", fontsize=10, color="#b35900",
            fontweight="bold", zorder=5,
            bbox=dict(facecolor="white", edgecolor="#b35900", alpha=0.85,
                      boxstyle="round,pad=0.3", linewidth=0.8))

    # ─── FVG zones (blue rectangles) ───────────────────
    fvg_x0, fvg_x1 = 3.7, 5.0
    for i, (lo, hi) in enumerate(fvgs):
        is_chosen = (i == chosen_idx)
        fc = "#3498db" if is_chosen else "#aed6f1"
        ec = "#1f618d" if is_chosen else "#5dade2"
        ax.add_patch(Rectangle((fvg_x0, lo), fvg_x1 - fvg_x0, hi - lo,
                                fc=fc, ec=ec, lw=2 if is_chosen else 1.2,
                                alpha=0.65 if is_chosen else 0.45, zorder=3))
        label = "top FVG ★" if is_chosen and len(fvgs) > 1 else "FVG"
        ax.text(fvg_x0 + (fvg_x1 - fvg_x0)/2, lo + (hi - lo)/2,
                label, ha="center", va="center",
                fontsize=11 if is_chosen else 9.5,
                fontweight="bold", color=ec, zorder=5)

    # ─── Entry, SL, TP1R ───────────────────────────────
    chosen_lo, chosen_hi = fvgs[chosen_idx]
    entry = deep_entry_long(chosen_lo, chosen_hi, deep)
    sl = LOW_OB
    R = entry - sl
    tp1r = entry + R

    # SL line (red dashed)
    ax.axhline(sl, xmin=0.04, xmax=0.96, color="#c0392b", ls="--", lw=2, zorder=6)
    ax.text(0.25, sl - 1.5, f"SL = low_OB_VC = {sl:.0f}",
            ha="left", va="top", fontsize=11, fontweight="bold", color="#c0392b", zorder=7)

    # Entry line (purple solid)
    ax.axhline(entry, xmin=0.04, xmax=0.96, color="#8e44ad", ls="-", lw=2.5, zorder=6)
    ax.text(0.25, entry + 1.0,
            f"Entry = FVG.hi − {deep} × (hi − lo) = {entry:.1f}",
            ha="left", va="bottom", fontsize=11.5, fontweight="bold", color="#8e44ad", zorder=7)

    # TP1R (green dashed)
    ax.axhline(tp1r, xmin=0.04, xmax=0.96, color="#27ae60", ls="--", lw=2, zorder=6)
    ax.text(0.25, tp1r + 1.0, f"TP +1R = {tp1r:.1f}",
            ha="left", va="bottom", fontsize=11, fontweight="bold", color="#27ae60", zorder=7)

    # R bracket on right side
    bracket_x = 6.05
    ax.annotate("", xy=(bracket_x, entry), xytext=(bracket_x, sl),
                arrowprops=dict(arrowstyle="<->", color="#7e3c9e", lw=2), zorder=7)
    ax.text(bracket_x + 0.08, sl + R/2, f"R = {R:.1f}",
            ha="left", va="center", fontsize=12, fontweight="bold", color="#7e3c9e", zorder=7)

    # Depth arrow inside chosen FVG (from hi towards entry)
    if chosen_hi - entry > 0.3:
        ax.annotate("", xy=(fvg_x0 + 0.15, entry), xytext=(fvg_x0 + 0.15, chosen_hi),
                    arrowprops=dict(arrowstyle="->", color="#8e44ad", lw=2.0), zorder=8)
        ax.text(fvg_x0 - 0.1, (chosen_hi + entry)/2,
                f"deep\n{deep}",
                ha="right", va="center", fontsize=10, fontweight="bold",
                color="#8e44ad", zorder=8,
                bbox=dict(facecolor="white", edgecolor="#8e44ad",
                          boxstyle="round,pad=0.2", linewidth=1.0))

    # Hide spines, ticks (clean schematic)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([])
    ax.tick_params(axis="y", labelsize=9)
    ax.set_ylabel("price (abstract units)", fontsize=10, color="#777")
    ax.grid(axis="y", color="#ddd", lw=0.5, alpha=0.7)


# ─── Panel A: n_FVG = 1 ──────────────────────────────
draw_panel(axA,
           title="Rule B  ·  n_FVG = 1",
           subtitle="entry deep = 0.2  (shallow, ближе к верху FVG)",
           fvgs=[PANEL_A_FVG],
           chosen_idx=0,
           deep=0.2,
           color_accent="#e67e22")

# ─── Panel B: n_FVG ≥ 2 ──────────────────────────────
draw_panel(axB,
           title="Rule A  ·  n_FVG ≥ 2",
           subtitle="entry deep = 0.8  (глубокий, в нижнюю часть top-FVG)",
           fvgs=PANEL_B_FVGS,
           chosen_idx=1,           # top FVG (highest hi)
           deep=0.8,
           color_accent="#27ae60")


# ─── Bottom legend bar ───────────────────────────────
fig.text(0.5, 0.04,
         "SL = low_OB_VC (всегда)   ·   TP = entry + 1·R (fixed TP1R)   ·   "
         "Top-FVG для LONG = FVG с максимальным hi (для SHORT — с минимальным lo)",
         ha="center", va="center", fontsize=12, color="#444", style="italic")

plt.subplots_adjust(left=0.04, right=0.99, top=0.90, bottom=0.08)
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/ob_vc_2h_entry_rules_schematic.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=130, bbox_inches="tight")
print(f"Saved: {out}")
