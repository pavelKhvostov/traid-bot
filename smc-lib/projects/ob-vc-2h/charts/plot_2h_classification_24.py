"""Classification 2h ob_vc → 24 типов: extreme=prev → a (strong wick) + b (weak wick).
extreme=cur не разделяется. Канон 1.1.1 swept + fixed TP1R EV.
"""
import pathlib
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

# Counts per T (from reclassify_24_types.py output)
DATA = {
    # LONG SWEPT ≥2
    "T1a": 178, "T1b": 62, "T2": 118,
    # LONG SWEPT 1
    "T3a": 287, "T3b": 121, "T4": 220,
    # LONG no-sw ≥2
    "T5a": 139, "T5b": 47, "T6": 84,
    # LONG no-sw 1
    "T7a": 340, "T7b": 187, "T8": 251,
    # SHORT SWEPT ≥2
    "T9a": 174, "T9b": 49, "T10": 110,
    # SHORT SWEPT 1
    "T11a": 321, "T11b": 127, "T12": 262,
    # SHORT no-sw ≥2
    "T13a": 122, "T13b": 36, "T14": 74,
    # SHORT no-sw 1
    "T15a": 340, "T15b": 154, "T16": 233,
}

# TBM results — OLD rule (entry 0.8 deep FVG / 0.2 deep, SL low_ob_vc)
TBM = {
    "T1a": (52.3, +0.047,  +8),  "T1b": (62.1, +0.241, +14),  "T2":  (57.4, +0.148, +17),
    "T3a": (56.3, +0.125, +35),  "T3b": (45.2, -0.096, -11),  "T4":  (52.2, +0.044,  +9),
    "T5a": (60.2, +0.203, +26),  "T5b": (60.0, +0.200,  +9),  "T6":  (47.5, -0.050,  -4),
    "T7a": (60.2, +0.204, +64),  "T7b": (53.1, +0.061, +11),  "T8":  (60.3, +0.207, +50),
    "T9a": (54.2, +0.084, +14),  "T9b": (62.2, +0.244, +11),  "T10": (52.4, +0.048,  +5),
    "T11a":(55.4, +0.107, +34),  "T11b":(51.6, +0.033,  +4),  "T12": (52.6, +0.052, +13),
    "T13a":(46.8, -0.063,  -7),  "T13b":(48.6, -0.029,  -1),  "T14": (55.4, +0.108,  +7),
    "T15a":(53.8, +0.076, +25),  "T15b":(53.7, +0.075, +11),  "T16": (46.7, -0.067, -15),
}

# TBM results — OLD rule for ALL 24 types (rollback 2026-06-07)
# n_FVG≥2 → Entry 0.8 deep top FVG; n_FVG=1 → Entry 0.2 deep FVG; SL = low_OB_VC
TBM_NEW = {
    "T1a": (52.3, +0.047,  +8),  "T1b": (62.1, +0.241, +14),  "T2":  (57.4, +0.148, +17),
    "T3a": (56.3, +0.125, +35),  "T3b": (45.2, -0.096, -11),  "T4":  (55.1, +0.102, +28),
    "T5a": (60.2, +0.203, +26),  "T5b": (60.0, +0.200,  +9),  "T6":  (47.5, -0.050,  -4),
    "T7a": (60.2, +0.204, +64),  "T7b": (53.1, +0.061, +11),  "T8":  (60.3, +0.207, +50),
    "T9a": (54.2, +0.084, +14),  "T9b": (62.2, +0.244, +11),  "T10": (54.1, +0.082,  +5),
    "T11a":(55.4, +0.107, +34),  "T11b":(51.6, +0.033,  +4),  "T12": (52.6, +0.052, +13),
    "T13a":(46.8, -0.063,  -7),  "T13b":(48.6, -0.029,  -1),  "T14": (55.4, +0.108,  +7),
    "T15a":(53.8, +0.076, +25),  "T15b":(53.7, +0.075, +11),  "T16": (46.7, -0.067, -15),
}
# Rollback: все типы используют OLD rule. NEW/MOVE markers убраны.
PREV_TYPES_SET = set()   # empty — все типы OLD
V3_MOVE_TYPES = set()

# Average R% (= R / entry × 100). Важно для leverage: SL_% = R_% × leverage.
RPCT_OLD = {
    "T1a": 1.05, "T1b": 0.94, "T2":  1.08, "T3a": 0.94, "T3b": 0.74, "T4":  1.05,
    "T5a": 0.68, "T5b": 0.52, "T6":  0.55, "T7a": 0.58, "T7b": 0.56, "T8":  0.58,
    "T9a": 0.91, "T9b": 1.01, "T10": 0.93, "T11a":0.83, "T11b":0.75, "T12": 0.85,
    "T13a":0.63, "T13b":0.53, "T14": 0.67, "T15a":0.49, "T15b":0.55, "T16": 0.51,
}
RPCT_HYBRID = RPCT_OLD.copy()  # все типы OLD = используем RPCT_OLD

# Layout: 4 (swept × n_FVG) groups per direction, each with 3 leaves (a/b/cur)
# Direction order: LONG then SHORT
DIR_LAYOUT = {
    "long": [
        ("SWEPT ≥2", ["T1a", "T1b", "T2"]),
        ("SWEPT 1",  ["T3a", "T3b", "T4"]),
        ("no-sw ≥2", ["T5a", "T5b", "T6"]),
        ("no-sw 1",  ["T7a", "T7b", "T8"]),
    ],
    "short": [
        ("SWEPT ≥2", ["T9a", "T9b", "T10"]),
        ("SWEPT 1",  ["T11a","T11b","T12"]),
        ("no-sw ≥2", ["T13a","T13b","T14"]),
        ("no-sw 1",  ["T15a","T15b","T16"]),
    ],
}

LONG_N = 2034; SHORT_N = 2002; TOTAL = 4036

COL_ROOT  = "#34495e"
COL_LONG  = "#27ae60"
COL_SHORT = "#c0392b"


def ev_color(ev):
    if ev < 0:        return "#c0392b"
    if ev >= 0.20:    return "#0a7c2b"
    if ev >= 0.15:    return "#1a8f3f"
    if ev >= 0.10:    return "#27ae60"
    if ev >= 0.05:    return "#f1c40f"
    return "#e67e22"


fig, ax = plt.subplots(figsize=(42, 15))
ax.set_xlim(0, 42)
ax.set_ylim(-1.5, 14)
ax.set_aspect("equal")
ax.axis("off")


def box(x, y, w, h, text, fc="#fafafa", ec="#333", fontsize=10, fontweight="normal",
        text_color="#222", lw=1.3):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05",
                        linewidth=lw, facecolor=fc, edgecolor=ec, zorder=3)
    ax.add_patch(p)
    if text:
        ax.text(x + w/2, y + h/2, text, ha="center", va="center",
                fontsize=fontsize, fontweight=fontweight, color=text_color, zorder=4)


def arrow(x1, y1, x2, y2, color="#7f8c8d", lw=1.4):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="->", color=color, lw=lw,
                                shrinkA=2, shrinkB=2),
                zorder=2)


# Root  (centered at x=21)
ROOT_X, ROOT_Y = 19.5, 13
box(ROOT_X, ROOT_Y, 3.0, 0.7,
    f"2h ob_vc — total {TOTAL:,}", fc=COL_ROOT, ec=COL_ROOT,
    fontsize=13, fontweight="bold", text_color="white")

# Direction split
LONG_X = 8.5; SHORT_X = 30.5
DIR_Y = 11.6
box(LONG_X, DIR_Y, 4.0, 0.65,
    f"LONG  {LONG_N:,}  ({LONG_N/TOTAL*100:.1f}%)",
    fc=COL_LONG, ec=COL_LONG, fontsize=12, fontweight="bold", text_color="white")
box(SHORT_X, DIR_Y, 4.0, 0.65,
    f"SHORT  {SHORT_N:,}  ({SHORT_N/TOTAL*100:.1f}%)",
    fc=COL_SHORT, ec=COL_SHORT, fontsize=12, fontweight="bold", text_color="white")

arrow(ROOT_X + 1.5, ROOT_Y, LONG_X + 2.0, DIR_Y + 0.65, color=COL_LONG)
arrow(ROOT_X + 1.5, ROOT_Y, SHORT_X + 2.0, DIR_Y + 0.65, color=COL_SHORT)


def draw_direction(side_x, dir_key):
    """Each direction = 4 (swept × n_FVG) groups × 3 leaves."""
    groups = DIR_LAYOUT[dir_key]
    type_col = COL_SHORT if dir_key == "short" else COL_LONG
    dir_label_x = LONG_X if dir_key == "long" else SHORT_X

    LEAF_W = 1.40
    LEAF_GAP = 0.12
    GROUP_W = 3 * LEAF_W + 2 * LEAF_GAP   # = 4.44
    GROUP_GAP = 0.45
    GROUP_Y = 9.6

    for gi, (label, leaves) in enumerate(groups):
        gx = side_x + gi * (GROUP_W + GROUP_GAP)

        # Group label
        total_in_group = sum(DATA.get(t, 0) for t in leaves)
        sw_color = "#e67e22" if "SWEPT" in label else "#95a5a6"
        box(gx, GROUP_Y, GROUP_W, 0.6,
            f"{label}  ·  {total_in_group:,}",
            fc=sw_color, ec=sw_color, fontsize=11, fontweight="bold", text_color="white")

        # Arrow from direction to group
        arrow(dir_label_x + 2.0, DIR_Y,
              gx + GROUP_W/2, GROUP_Y + 0.6, color=sw_color, lw=1.2)

        # 3 leaves
        leaf_top_y = 8.8
        leaf_bottom_y = 4.5
        leaf_h = leaf_top_y - leaf_bottom_y

        for li, tid in enumerate(leaves):
            lx = gx + li * (LEAF_W + LEAF_GAP)
            n = DATA.get(tid, 0)
            wr, ev, total_r = TBM.get(tid, (0, 0, 0))

            box(lx, leaf_bottom_y, LEAF_W, leaf_h, "",
                fc="#fafafa", ec="#444", lw=1.5)

            # Arrow from group to leaf
            arrow(gx + GROUP_W/2, GROUP_Y,
                  lx + LEAF_W/2, leaf_top_y, color="#999", lw=1.0)

            # T-ID badge (top-left, large)
            ax.text(lx + 0.15, leaf_top_y - 0.15, tid,
                    ha="left", va="top", fontsize=14, fontweight="bold",
                    color="white", zorder=6,
                    bbox=dict(facecolor=type_col, edgecolor=type_col,
                              boxstyle="round,pad=0.25", linewidth=0))

            # Description
            if tid.endswith("a"):
                desc1 = "extreme = PREV"
                desc2 = "wick ≥ 2×"
            elif tid.endswith("b"):
                desc1 = "extreme = PREV"
                desc2 = "wick < 2×"
            else:
                desc1 = "extreme = CUR"
                desc2 = ""

            ax.text(lx + LEAF_W/2, leaf_top_y - 0.75, desc1,
                    ha="center", va="center", fontsize=9, fontweight="bold",
                    color="#444", zorder=5)
            ax.text(lx + LEAF_W/2, leaf_top_y - 1.10, desc2,
                    ha="center", va="center", fontsize=9, fontweight="bold",
                    color="#666", zorder=5)

            # N (big)
            ax.text(lx + LEAF_W/2, leaf_bottom_y + 2.40, f"{n}",
                    ha="center", va="center", fontsize=22,
                    fontweight="bold", color=type_col, zorder=5)

            # WR
            ax.text(lx + LEAF_W/2, leaf_bottom_y + 1.55, f"WR {wr:.1f}%",
                    ha="center", va="center", fontsize=10.5,
                    fontweight="bold", color="#222", zorder=5)

            # EV badge
            ev_bg = ev_color(ev)
            ax.text(lx + LEAF_W/2, leaf_bottom_y + 0.95, f"EV {ev:+.3f}R",
                    ha="center", va="center", fontsize=10.5,
                    fontweight="bold", color="white", zorder=5,
                    bbox=dict(facecolor=ev_bg, edgecolor=ev_bg,
                              boxstyle="round,pad=0.28", linewidth=0))

            # Total R
            total_col = "#c0392b" if total_r < 0 else "#185c34"
            ax.text(lx + LEAF_W/2, leaf_bottom_y + 0.55, f"Σ {total_r:+}R / 6y",
                    ha="center", va="center", fontsize=10,
                    fontweight="bold", color=total_col, zorder=5)
            # R% (avg) — для leverage math
            rpct = RPCT_OLD.get(tid, 0)
            ax.text(lx + LEAF_W/2, leaf_bottom_y + 0.15, f"R% = {rpct:.2f}%",
                    ha="center", va="center", fontsize=9,
                    color="#7e3c9e", fontweight="bold", style="italic", zorder=5)


# LONG group starts at x=1.5, SHORT at x=22.5
draw_direction(1.5, "long")
draw_direction(22.5, "short")


# ─── TIER 1 ROW: B1 (HTF cascade aligned) breakdown per type ──────
# Tier 1 stats: (N, WR%, EV, Σ R)
TIER1_DATA = {
    "T1a":(58, 62.3, +0.245, +13),  "T1b":(14, 63.6, +0.273, +3),  "T2":(38, 71.4, +0.429, +15),
    "T3a":(72, 71.2, +0.424, +28),  "T3b":(0,0,0,0),               "T4":(70, 66.1, +0.322, +19),
    "T5a":(54, 66.7, +0.333, +15),  "T5b":(17, 66.7, +0.333, +5),  "T6":(0,0,0,0),
    "T7a":(155, 65.9, +0.319, +43), "T7b":(58, 67.9, +0.358, +19), "T8":(80, 66.7, +0.333, +24),
    "T9a":(65, 61.7, +0.233, +14),  "T9b":(19, 80.0, +0.600, +9),  "T10":(35, 60.0, +0.200, +6),
    "T11a":(87, 61.0, +0.220, +19), "T11b":(39, 59.5, +0.189, +7), "T12":(83, 63.9, +0.278, +20),
    "T13a":(0,0,0,0),               "T13b":(0,0,0,0),              "T14":(37, 64.5, +0.290, +9),
    "T15a":(146, 62.2, +0.244, +33),"T15b":(60, 53.7, +0.074, +4), "T16":(0,0,0,0),
}

TIER_TITLE_Y = 3.5
TIER_Y = -0.8
ax.add_patch(FancyBboxPatch((0.5, TIER_TITLE_Y - 0.4), 41, 0.8,
                              boxstyle="round,pad=0.1",
                              facecolor="#e8f5e9", edgecolor="#27ae60",
                              linewidth=1.5, zorder=2))
ax.text(21, TIER_TITLE_Y,
        "⭐ TIER 1 (B1 HTF cascade aligned: 12h+6h+4h все в направлении trade с body ≥0.3%)   "
        f"·   1,187/3,378 = 35.1% basket   ·   WR 64.5%   ·   EV +0.290R/trade   ·   Σ +308R / 6y",
        ha="center", va="center", fontsize=11.5, fontweight="bold", color="#185c34")


def draw_tier1_row(side_x, dir_key):
    """Same layout as top leaves: 1.4 wide × 4.3 tall."""
    groups = DIR_LAYOUT[dir_key]
    type_col = COL_SHORT if dir_key == "short" else COL_LONG
    LEAF_W = 1.40; LEAF_GAP = 0.12
    GROUP_W = 3 * LEAF_W + 2 * LEAF_GAP
    GROUP_GAP = 0.45
    tier_top = TIER_Y + 4.3
    for gi, (label, leaves) in enumerate(groups):
        gx = side_x + gi * (GROUP_W + GROUP_GAP)
        for li, tid in enumerate(leaves):
            lx = gx + li * (LEAF_W + LEAF_GAP)
            n_t1, wr_t1, ev_t1, sigR_t1 = TIER1_DATA.get(tid, (0, 0, 0, 0))
            is_dropped = n_t1 == 0

            # Box (same dimensions as top leaf)
            box_fc = "#f5f5f5" if is_dropped else "#fafafa"
            box_ec = "#bbb" if is_dropped else "#27ae60"
            box(lx, TIER_Y, LEAF_W, 4.3, "",
                fc=box_fc, ec=box_ec, lw=1.5 if not is_dropped else 1.0)

            # T-ID badge (top-left, same style as top)
            badge_col = type_col if not is_dropped else "#999"
            ax.text(lx + 0.15, tier_top - 0.15, tid,
                    ha="left", va="top", fontsize=14, fontweight="bold",
                    color="white", zorder=6,
                    bbox=dict(facecolor=badge_col, edgecolor=badge_col,
                              boxstyle="round,pad=0.25", linewidth=0))

            if is_dropped:
                ax.text(lx + LEAF_W/2, tier_top - 1.5, "DROPPED",
                        ha="center", va="center", fontsize=11,
                        fontweight="bold", color="#999", zorder=5)
                ax.text(lx + LEAF_W/2, tier_top - 2.1, "(Stage A neg)",
                        ha="center", va="center", fontsize=8,
                        color="#999", style="italic", zorder=5)
                continue

            # Description (corresponds to "extreme=PREV" in top)
            ax.text(lx + LEAF_W/2, tier_top - 0.75, "⭐ TIER 1",
                    ha="center", va="center", fontsize=9, fontweight="bold",
                    color="#185c34", zorder=5)
            ax.text(lx + LEAF_W/2, tier_top - 1.10, "B1: HTF aligned",
                    ha="center", va="center", fontsize=9, fontweight="bold",
                    color="#666", zorder=5)

            # N (big, same as top N)
            ax.text(lx + LEAF_W/2, TIER_Y + 2.40, f"{n_t1}",
                    ha="center", va="center", fontsize=22,
                    fontweight="bold", color=type_col, zorder=5)

            # WR (same format as top)
            ax.text(lx + LEAF_W/2, TIER_Y + 1.55, f"WR {wr_t1:.1f}%",
                    ha="center", va="center", fontsize=10.5,
                    fontweight="bold", color="#222", zorder=5)

            # EV badge (same colored badge as top)
            ev_bg = ev_color(ev_t1)
            ax.text(lx + LEAF_W/2, TIER_Y + 0.95, f"EV {ev_t1:+.3f}R",
                    ha="center", va="center", fontsize=10.5,
                    fontweight="bold", color="white", zorder=5,
                    bbox=dict(facecolor=ev_bg, edgecolor=ev_bg,
                              boxstyle="round,pad=0.28", linewidth=0))

            # Σ R (same as top)
            total_col = "#c0392b" if sigR_t1 < 0 else "#185c34"
            ax.text(lx + LEAF_W/2, TIER_Y + 0.30, f"Σ {sigR_t1:+}R / 6y",
                    ha="center", va="center", fontsize=10,
                    fontweight="bold", color=total_col, zorder=5)


draw_tier1_row(1.5, "long")
draw_tier1_row(22.5, "short")

fig.suptitle("Классификация 2h ob_vc — 24 типа  "
             "(direction × swept × n_FVG × extreme × wick-ratio для extreme=prev)",
             fontsize=15, fontweight="bold", y=0.985)

plt.subplots_adjust(left=0.005, right=0.995, top=0.95, bottom=0.02)
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/ob_vc_2h_classification_24.png"
plt.savefig(out, dpi=110, bbox_inches="tight")
print(f"Saved: {out}")
