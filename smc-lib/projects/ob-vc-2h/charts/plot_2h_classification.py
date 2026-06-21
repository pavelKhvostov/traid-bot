"""Block-diagram классификации 2h ob_vc:
  Root → Direction → Swept → n_FVG → Extreme (prev/cur)
8 leaf классов на каждое направление.
"""
import pathlib
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, ConnectionPatch
import pandas as pd

# Counts after 15m-priority dedup AND swept канон 1.1.1 (n-1, n-2 lookback)
DATA = {
    "long": {
        ("swept", "≥2", "prev"): 240,
        ("swept", "≥2", "cur"):  118,
        ("swept", "1",  "prev"): 408,
        ("swept", "1",  "cur"):  220,
        ("no",    "≥2", "prev"): 186,
        ("no",    "≥2", "cur"):   84,
        ("no",    "1",  "prev"): 527,
        ("no",    "1",  "cur"):  251,
    },
    "short": {
        ("swept", "≥2", "prev"): 223,
        ("swept", "≥2", "cur"):  110,
        ("swept", "1",  "prev"): 448,
        ("swept", "1",  "cur"):  262,
        ("no",    "≥2", "prev"): 158,
        ("no",    "≥2", "cur"):   74,
        ("no",    "1",  "prev"): 494,
        ("no",    "1",  "cur"):  233,
    },
}

# TBM results под канон 1.1.1 (fixed TP1R exit)
TBM = {
    "T1":  (54.8, +0.096, +22),  "T2":  (57.4, +0.148, +17),
    "T3":  (53.0, +0.061, +24),  "T4":  (52.2, +0.044,  +9),
    "T5":  (60.1, +0.202, +35),  "T6":  (47.5, -0.050,  -4),
    "T7":  (57.6, +0.152, +75),  "T8":  (60.3, +0.207, +50),
    "T9":  (55.9, +0.118, +25),  "T10": (52.4, +0.048,  +5),
    "T11": (54.3, +0.086, +38),  "T12": (52.6, +0.052, +13),
    "T13": (47.3, -0.055,  -8),  "T14": (55.4, +0.108,  +7),
    "T15": (53.8, +0.076, +36),  "T16": (46.7, -0.067, -15),
}

LONG_TOTAL = sum(DATA["long"].values())
SHORT_TOTAL = sum(DATA["short"].values())
TOTAL = LONG_TOTAL + SHORT_TOTAL

# Colors
COL_ROOT  = "#34495e"
COL_LONG  = "#27ae60"
COL_SHORT = "#c0392b"
COL_SWEPT = "#e67e22"
COL_NOSW  = "#95a5a6"
COL_BOX_BG = "#fafafa"


fig, ax = plt.subplots(figsize=(28, 8))
ax.set_xlim(0, 28)
ax.set_ylim(6.0, 14)
ax.set_aspect("equal")
ax.axis("off")


def box(x, y, w, h, text, fc="#fafafa", ec="#333", fontsize=10, fontweight="normal",
        text_color="#222"):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05",
                        linewidth=1.5, facecolor=fc, edgecolor=ec, zorder=3)
    ax.add_patch(p)
    ax.text(x + w/2, y + h/2, text, ha="center", va="center",
            fontsize=fontsize, fontweight=fontweight, color=text_color, zorder=4)


def line(x1, y1, x2, y2, color="#7f8c8d"):
    ax.plot([x1, x2], [y1, y2], color=color, linewidth=1.2, zorder=2)


# Root — centered at x=14 (half of 28)
box(12.5, 13, 3, 0.7,
    f"2h ob_vc  —  total {TOTAL:,}", fc=COL_ROOT, ec=COL_ROOT,
    fontsize=13, fontweight="bold", text_color="white")

# Direction split
box(6.0, 11.7, 3, 0.6,
    f"LONG  {LONG_TOTAL:,}  ({LONG_TOTAL/TOTAL*100:.1f}%)",
    fc=COL_LONG, ec=COL_LONG, fontsize=12, fontweight="bold", text_color="white")
box(19.0, 11.7, 3, 0.6,
    f"SHORT  {SHORT_TOTAL:,}  ({SHORT_TOTAL/TOTAL*100:.1f}%)",
    fc=COL_SHORT, ec=COL_SHORT, fontsize=12, fontweight="bold", text_color="white")

line(14.0, 13.0, 7.5, 12.3)
line(14.0, 13.0, 20.5, 12.3)


# Layout: 4 columns of leaf boxes per direction (8 leaves)
# Within direction: SWEPT (top 4) vs no-sweep (bottom 4)
# Within row: ≥2 (left 2) vs 1 (right 2), prev vs cur

LEAF_W = 1.55
LEAF_H = 0.85
LEAF_GAP_X = 0.18
LEAF_GAP_Y = 0.25

def draw_direction(side_x, dir_key, parent_color, t_offset):
    """side_x = starting X of the direction's group (8 leaves).
    Layout: 12 units wide per direction.
    t_offset: base type-ID (0 for LONG → T1-T8; 8 for SHORT → T9-T16).
    """
    sub = DATA[dir_key]
    sub_total = sum(sub.values())
    t_id = [t_offset + 1]  # mutable counter

    swept_total = sum(v for (sw,n,s), v in sub.items() if sw == "swept")
    no_total = sum(v for (sw,n,s), v in sub.items() if sw == "no")

    # SWEPT / no-sweep boxes (5.5 wide each)
    box(side_x, 10.6, 5.5, 0.55,
        f"SWEPT  {swept_total:,}  ({swept_total/sub_total*100:.0f}%)",
        fc=COL_SWEPT, ec=COL_SWEPT, fontsize=11, fontweight="bold", text_color="white")
    box(side_x + 6.0, 10.6, 5.5, 0.55,
        f"no-sweep  {no_total:,}  ({no_total/sub_total*100:.0f}%)",
        fc=COL_NOSW, ec=COL_NOSW, fontsize=11, fontweight="bold", text_color="white")

    dir_y = 11.7
    dir_x = side_x + 5.75
    line(dir_x, dir_y, side_x + 2.75, 11.15)
    line(dir_x, dir_y, side_x + 8.75, 11.15)

    # n_FVG splits — 2.6 wide each
    for sw_key, sw_x_start in [("swept", side_x), ("no", side_x + 6.0)]:
        n_total_2 = sum(v for (sw,n,s), v in sub.items() if sw == sw_key and n == "≥2")
        n_total_1 = sum(v for (sw,n,s), v in sub.items() if sw == sw_key and n == "1")
        box(sw_x_start, 9.6, 2.6, 0.5, f"n_FVG ≥2  {n_total_2:,}",
            fc="#3498db", ec="#3498db", fontsize=10, fontweight="bold", text_color="white")
        box(sw_x_start + 2.9, 9.6, 2.6, 0.5, f"n_FVG = 1  {n_total_1:,}",
            fc="#85c1e9", ec="#3498db", fontsize=10, fontweight="bold", text_color="#1a4f76")

        sw_cx = sw_x_start + 2.75
        line(sw_cx, 10.6, sw_x_start + 1.3, 10.1)
        line(sw_cx, 10.6, sw_x_start + 4.2, 10.1)

        # Leaf boxes: 1.2 wide × 2.2 tall (taller для TBM badge). Tag with T-ID.
        type_col = "#c0392b" if dir_key == "short" else "#27ae60"

        def ev_color(ev):
            # EV-based color (fixed TP1R basis: realistic per-trade R)
            if ev < 0:        return "#c0392b"   # red (negative — avoid)
            if ev >= 0.15:    return "#0a7c2b"   # dark green (top)
            if ev >= 0.10:    return "#27ae60"   # green
            if ev >= 0.05:    return "#f1c40f"   # yellow
            return "#e67e22"                     # orange (weak positive)

        for nc, n_x in [("≥2", sw_x_start), ("1", sw_x_start + 2.9)]:
            prev_n = sub.get((sw_key, nc, "prev"), 0)
            cur_n = sub.get((sw_key, nc, "cur"), 0)

            for col_offset, (lbl, n_val) in enumerate([("PREV", prev_n), ("CUR", cur_n)]):
                lx = n_x + col_offset * 1.4
                tid_str = f"T{t_id[0]}"
                wr, ev, total_r = TBM.get(tid_str, (0, 0, 0))

                box(lx, 6.5, 1.2, 2.7, "",
                    fc=COL_BOX_BG, ec="#444", fontsize=9)

                # T-ID badge top-left
                ax.text(lx + 0.10, 9.05, tid_str,
                        ha="left", va="top", fontsize=10, fontweight="bold",
                        color="white", zorder=6,
                        bbox=dict(facecolor=type_col, edgecolor=type_col,
                                  boxstyle="round,pad=0.18", linewidth=0))

                # Attributes
                ax.text(lx + 0.6, 8.80, f"extreme = {lbl}", ha="center", va="center",
                        fontsize=8.2, fontweight="bold", color="#444", zorder=5)
                ax.text(lx + 0.6, 8.45, f"swept={'Y' if sw_key=='swept' else 'N'}  "
                                          f"n_FVG={nc}",
                        ha="center", va="center", fontsize=7.5, color="#666", zorder=5)

                # Big N
                ax.text(lx + 0.6, 8.05, str(n_val), ha="center", va="center",
                        fontsize=14, fontweight="bold", color=type_col, zorder=5)

                # WR
                ax.text(lx + 0.6, 7.55, f"WR {wr:.0f}%",
                        ha="center", va="center", fontsize=9, fontweight="bold",
                        color="#222", zorder=5)

                # EV per trade badge
                ev_bg = ev_color(ev)
                ax.text(lx + 0.6, 7.18, f"EV {ev:+.3f}R",
                        ha="center", va="center", fontsize=9, fontweight="bold",
                        color="white", zorder=5,
                        bbox=dict(facecolor=ev_bg, edgecolor=ev_bg,
                                  boxstyle="round,pad=0.18", linewidth=0))

                # Total R (6y)
                total_color = "#c0392b" if total_r < 0 else "#185c34"
                ax.text(lx + 0.6, 6.78, f"Σ {total_r:+}R / 6y",
                        ha="center", va="center", fontsize=9, fontweight="bold",
                        color=total_color, zorder=5)

                t_id[0] += 1

            nx_cx = n_x + 1.3
            line(nx_cx, 9.6, n_x + 0.6, 9.2)
            line(nx_cx, 9.6, n_x + 2.0, 9.2)


# Draw direction trees — chart width 28; T1-T8 LONG, T9-T16 SHORT
draw_direction(1.5, "long", COL_LONG, t_offset=0)
draw_direction(15.0, "short", COL_SHORT, t_offset=8)


# Title
fig.suptitle("Классификация 2h ob_vc — 16 классов  "
             "(direction × swept × n_FVG × extreme-source)",
             fontsize=14, fontweight="bold", y=0.97)


plt.tight_layout()
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/ob_vc_2h_classification.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=130, bbox_inches="tight")
print(f"Saved: {out}")
