"""Classification 2h ob_vc → 24 типов для BTC + ETH (одинаковая структура).

Top row — BTC с полным TBM (WR/EV/Σ/R%).
Bottom row — ETH с полным TBM (WR/EV/Σ/R%).
Tier 1 row из оригинала убран. SOL убран (Binance spot listing 2020-08-11).
"""
import pathlib
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

# ─── BTC counts + TBM (relaxed canon #7, regenerated 2026-06-09) ──
DATA_BTC = {
    "T1a": 272, "T1b": 107, "T2":  179,
    "T3a": 329, "T3b": 143, "T4":  259,
    "T5a": 223, "T5b": 111, "T6":  161,
    "T7a": 393, "T7b": 246, "T8":  297,
    "T9a": 276, "T9b": 99,  "T10": 183,
    "T11a":334, "T11b":158, "T12": 298,
    "T13a":211, "T13b":112, "T14": 128,
    "T15a":404, "T15b":170, "T16": 285,
}
TBM_BTC = {
    "T1a": (53.3, +0.065, +17),  "T1b": (58.0, +0.160, +16),  "T2":  (58.3, +0.166, +29),
    "T3a": (52.0, +0.040, +13),  "T3b": (50.7, +0.015,  +2),  "T4":  (51.4, +0.029,  +7),
    "T5a": (57.1, +0.143, +30),  "T5b": (45.2, -0.096, -10),  "T6":  (54.5, +0.090, +14),
    "T7a": (62.0, +0.240, +87),  "T7b": (52.3, +0.046, +11),  "T8":  (58.7, +0.175, +50),
    "T9a": (56.8, +0.135, +36),  "T9b": (51.6, +0.032,  +3),  "T10": (46.9, -0.062, -11),
    "T11a":(54.7, +0.095, +30),  "T11b":(51.0, +0.020,  +3),  "T12": (51.6, +0.032,  +9),
    "T13a":(51.3, +0.025,  +5),  "T13b":(56.8, +0.135, +15),  "T14": (51.3, +0.025,  +3),
    "T15a":(52.3, +0.046, +18),  "T15b":(47.8, -0.044,  -7),  "T16": (53.4, +0.069, +19),
}
RPCT_BTC = {
    "T1a": 1.03, "T1b": 0.85, "T2":  0.98, "T3a": 0.88, "T3b": 0.65, "T4":  0.99,
    "T5a": 0.63, "T5b": 0.54, "T6":  0.54, "T7a": 0.60, "T7b": 0.49, "T8":  0.57,
    "T9a": 0.89, "T9b": 0.79, "T10": 0.88, "T11a":0.74, "T11b":0.66, "T12": 0.78,
    "T13a":0.60, "T13b":0.49, "T14": 0.69, "T15a":0.50, "T15b":0.50, "T16": 0.48,
}

# ─── ETH counts + TBM (from classify_24_eth_sol.py ETHUSDT, full 6y from 2020-01-01) ─
DATA_ETH = {
    "T1a": 306, "T1b": 103, "T2": 157,
    "T3a": 317, "T3b": 147, "T4": 219,
    "T5a": 234, "T5b": 100, "T6": 123,
    "T7a": 425, "T7b": 227, "T8": 312,
    "T9a": 297, "T9b": 115, "T10": 178,
    "T11a":344, "T11b":152, "T12": 277,
    "T13a":194, "T13b":76,  "T14": 137,
    "T15a":415, "T15b":215, "T16": 290,
}
TBM_ETH = {
    "T1a": (49.0, -0.021,  -6),  "T1b": (56.6, +0.131, +13),  "T2":  (57.4, +0.149, +22),
    "T3a": (52.1, +0.042, +13),  "T3b": (56.0, +0.121, +17),  "T4":  (53.4, +0.068, +14),
    "T5a": (60.6, +0.212, +48),  "T5b": (54.7, +0.095,  +9),  "T6":  (50.4, +0.009,  +1),
    "T7a": (53.0, +0.061, +25),  "T7b": (53.7, +0.075, +16),  "T8":  (50.0, +0.000,  +0),
    "T9a": (52.5, +0.049, +15),  "T9b": (49.1, -0.019,  -2),  "T10": (50.0, +0.000,  +0),
    "T11a":(54.5, +0.090, +30),  "T11b":(55.8, +0.116, +17),  "T12": (50.2, +0.004,  +1),
    "T13a":(59.1, +0.183, +34),  "T13b":(56.8, +0.135, +10),  "T14": (58.9, +0.178, +23),
    "T15a":(49.0, -0.020,  -8),  "T15b":(50.2, +0.005,  +1),  "T16": (51.6, +0.032,  +9),
}
RPCT_ETH = {
    "T1a": 1.41, "T1b": 1.01, "T2":  1.36, "T3a": 1.17, "T3b": 1.00, "T4":  1.31,
    "T5a": 1.02, "T5b": 0.84, "T6":  0.85, "T7a": 0.77, "T7b": 0.65, "T8":  0.76,
    "T9a": 1.09, "T9b": 1.07, "T10": 1.20, "T11a":0.93, "T11b":0.81, "T12": 1.00,
    "T13a":0.80, "T13b":0.86, "T14": 0.80, "T15a":0.70, "T15b":0.63, "T16": 0.67,
}

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

BTC_LONG = 2720; BTC_SHORT = 2658; BTC_TOT = 5378
ETH_LONG = 2670; ETH_SHORT = 2690; ETH_TOT = 5360
BTC_SIG = 389    # Σ R за 6y (relaxed canon, regenerated 2026-06-09)
ETH_SIG = 302

COL_ROOT  = "#34495e"
COL_LONG  = "#27ae60"
COL_SHORT = "#c0392b"
COL_ETH_HDR = "#627eea"


def ev_color(ev):
    if ev < 0:        return "#c0392b"
    if ev >= 0.20:    return "#0a7c2b"
    if ev >= 0.15:    return "#1a8f3f"
    if ev >= 0.10:    return "#27ae60"
    if ev >= 0.05:    return "#f1c40f"
    return "#e67e22"


fig, ax = plt.subplots(figsize=(42, 22))
ax.set_xlim(0, 42)
ax.set_ylim(-7.0, 14)
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


# ─── Root (BTC) ────────────────────────────────────────
ROOT_X, ROOT_Y = 19.5, 13
box(ROOT_X, ROOT_Y, 3.0, 0.7,
    f"2h ob_vc — BTC {BTC_TOT:,}", fc=COL_ROOT, ec=COL_ROOT,
    fontsize=13, fontweight="bold", text_color="white")

LONG_X = 8.5; SHORT_X = 30.5
DIR_Y = 11.6
box(LONG_X, DIR_Y, 4.0, 0.65,
    f"LONG  {BTC_LONG:,}  ({BTC_LONG/BTC_TOT*100:.1f}%)",
    fc=COL_LONG, ec=COL_LONG, fontsize=12, fontweight="bold", text_color="white")
box(SHORT_X, DIR_Y, 4.0, 0.65,
    f"SHORT  {BTC_SHORT:,}  ({BTC_SHORT/BTC_TOT*100:.1f}%)",
    fc=COL_SHORT, ec=COL_SHORT, fontsize=12, fontweight="bold", text_color="white")

arrow(ROOT_X + 1.5, ROOT_Y, LONG_X + 2.0, DIR_Y + 0.65, color=COL_LONG)
arrow(ROOT_X + 1.5, ROOT_Y, SHORT_X + 2.0, DIR_Y + 0.65, color=COL_SHORT)


def draw_asset_row(side_x, dir_key, data, tbm, rpct, *,
                   group_y, leaf_top_y, leaf_bottom_y,
                   draw_group_label=True, draw_dir_arrow=True):
    """Render one asset's row of 4 groups × 3 leaves with full TBM detail."""
    groups = DIR_LAYOUT[dir_key]
    type_col = COL_SHORT if dir_key == "short" else COL_LONG
    dir_label_x = LONG_X if dir_key == "long" else SHORT_X

    LEAF_W = 1.40; LEAF_GAP = 0.12
    GROUP_W = 3 * LEAF_W + 2 * LEAF_GAP
    GROUP_GAP = 0.45
    leaf_h = leaf_top_y - leaf_bottom_y

    for gi, (label, leaves) in enumerate(groups):
        gx = side_x + gi * (GROUP_W + GROUP_GAP)
        if draw_group_label:
            total_in_group = sum(data.get(t, 0) for t in leaves)
            sw_color = "#e67e22" if "SWEPT" in label else "#95a5a6"
            box(gx, group_y, GROUP_W, 0.6,
                f"{label}  ·  {total_in_group:,}",
                fc=sw_color, ec=sw_color, fontsize=11, fontweight="bold", text_color="white")
            if draw_dir_arrow:
                arrow(dir_label_x + 2.0, DIR_Y,
                      gx + GROUP_W/2, group_y + 0.6, color=sw_color, lw=1.2)

        for li, tid in enumerate(leaves):
            lx = gx + li * (LEAF_W + LEAF_GAP)
            n = data.get(tid, 0)
            wr, ev, total_r = tbm.get(tid, (0, 0, 0))

            box(lx, leaf_bottom_y, LEAF_W, leaf_h, "",
                fc="#fafafa", ec="#444", lw=1.5)
            if draw_group_label:
                arrow(gx + GROUP_W/2, group_y,
                      lx + LEAF_W/2, leaf_top_y, color="#999", lw=1.0)

            ax.text(lx + 0.15, leaf_top_y - 0.15, tid,
                    ha="left", va="top", fontsize=14, fontweight="bold",
                    color="white", zorder=6,
                    bbox=dict(facecolor=type_col, edgecolor=type_col,
                              boxstyle="round,pad=0.25", linewidth=0))
            if tid.endswith("a"):
                desc1, desc2 = "extreme = PREV", "wick ≥ 2×"
            elif tid.endswith("b"):
                desc1, desc2 = "extreme = PREV", "wick < 2×"
            else:
                desc1, desc2 = "extreme = CUR", ""
            ax.text(lx + LEAF_W/2, leaf_top_y - 0.75, desc1,
                    ha="center", va="center", fontsize=9, fontweight="bold",
                    color="#444", zorder=5)
            ax.text(lx + LEAF_W/2, leaf_top_y - 1.10, desc2,
                    ha="center", va="center", fontsize=9, fontweight="bold",
                    color="#666", zorder=5)
            ax.text(lx + LEAF_W/2, leaf_bottom_y + 2.40, f"{n}",
                    ha="center", va="center", fontsize=22,
                    fontweight="bold", color=type_col, zorder=5)
            ax.text(lx + LEAF_W/2, leaf_bottom_y + 1.55, f"WR {wr:.1f}%",
                    ha="center", va="center", fontsize=10.5,
                    fontweight="bold", color="#222", zorder=5)
            ev_bg = ev_color(ev)
            ax.text(lx + LEAF_W/2, leaf_bottom_y + 0.95, f"EV {ev:+.3f}R",
                    ha="center", va="center", fontsize=10.5,
                    fontweight="bold", color="white", zorder=5,
                    bbox=dict(facecolor=ev_bg, edgecolor=ev_bg,
                              boxstyle="round,pad=0.28", linewidth=0))
            total_col = "#c0392b" if total_r < 0 else "#185c34"
            ax.text(lx + LEAF_W/2, leaf_bottom_y + 0.55, f"Σ {total_r:+}R / 6y",
                    ha="center", va="center", fontsize=10,
                    fontweight="bold", color=total_col, zorder=5)
            rp = rpct.get(tid, 0)
            ax.text(lx + LEAF_W/2, leaf_bottom_y + 0.15, f"R% = {rp:.2f}%",
                    ha="center", va="center", fontsize=9,
                    color="#7e3c9e", fontweight="bold", style="italic", zorder=5)


# ─── BTC row (top, with group labels and arrows from DIR badges) ──
draw_asset_row(1.5,  "long",  DATA_BTC, TBM_BTC, RPCT_BTC,
               group_y=9.6, leaf_top_y=8.8, leaf_bottom_y=4.5,
               draw_group_label=True, draw_dir_arrow=True)
draw_asset_row(22.5, "short", DATA_BTC, TBM_BTC, RPCT_BTC,
               group_y=9.6, leaf_top_y=8.8, leaf_bottom_y=4.5,
               draw_group_label=True, draw_dir_arrow=True)


# ─── ETH header banner ────────────────────────────────
ETH_HDR_Y = 2.7
ax.add_patch(FancyBboxPatch((0.5, ETH_HDR_Y - 0.45), 41, 0.9,
                              boxstyle="round,pad=0.1",
                              facecolor=COL_ETH_HDR, edgecolor=COL_ETH_HDR,
                              alpha=0.18, linewidth=1.5, zorder=2))
ax.text(21, ETH_HDR_Y,
        f"ETH · 2h ob_vc total {ETH_TOT:,}   ·   "
        f"LONG {ETH_LONG:,} ({ETH_LONG/ETH_TOT*100:.1f}%)   ·   "
        f"SHORT {ETH_SHORT:,} ({ETH_SHORT/ETH_TOT*100:.1f}%)   ·   "
        f"Σ {ETH_SIG:+}R / 6y",
        ha="center", va="center", fontsize=13, fontweight="bold", color=COL_ETH_HDR)


# ─── ETH row (bottom, no group label, same TBM detail) ────────
ETH_GROUP_Y = 1.7   # unused (draw_group_label=False) but kept for layout
ETH_LEAF_TOP = 1.7
ETH_LEAF_BOT = -2.6
draw_asset_row(1.5,  "long",  DATA_ETH, TBM_ETH, RPCT_ETH,
               group_y=ETH_GROUP_Y, leaf_top_y=ETH_LEAF_TOP, leaf_bottom_y=ETH_LEAF_BOT,
               draw_group_label=False, draw_dir_arrow=False)
draw_asset_row(22.5, "short", DATA_ETH, TBM_ETH, RPCT_ETH,
               group_y=ETH_GROUP_Y, leaf_top_y=ETH_LEAF_TOP, leaf_bottom_y=ETH_LEAF_BOT,
               draw_group_label=False, draw_dir_arrow=False)


fig.suptitle(f"Классификация 2h ob_vc — 24 типа · BTC ({BTC_TOT:,}, Σ {BTC_SIG:+}R) "
             f"+ ETH ({ETH_TOT:,}, Σ {ETH_SIG:+}R)  "
             "(direction × swept × n_FVG × extreme × wick-ratio)",
             fontsize=15, fontweight="bold", y=0.985)

plt.subplots_adjust(left=0.005, right=0.995, top=0.96, bottom=0.02)
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/ob_vc_2h_classification_24_multi.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=110, bbox_inches="tight")
print(f"Saved: {out}")
