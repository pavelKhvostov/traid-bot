"""24-types classification + v3.3 strategy row per asset (BTC, ETH).

Extends plot_2h_classification_24_multi.py:
- Top row per asset (BTC, ETH): base TBM (WR/EV/Σ/R%) — original
- NEW row per asset under base: v3.3 strategy stats (N_sel, WR_sel, EV_sel, ΣR_sel)

v3.3 strategy = hit_RR_20 lgb @ proba ≥ 0.6088 (top-1100 events)
Global: N=1100, WR=72.4%, +1288R
"""
import pathlib
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


# ─── Base counts + TBM (unchanged from original) ──
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

DATA_ETH = {}  # disabled
#
TBM_ETH = {}  # disabled
#
RPCT_ETH = {}  # disabled
#


# ─── Compute v3.3 strategy stats per (asset, t_id) ──
def compute_strategy_stats():
    return {'BTC': {}, 'ETH': {}}

STRAT = compute_strategy_stats()
print("BTC strategy:", STRAT['BTC'])
print()
print("ETH strategy:", STRAT['ETH'])


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
BTC_SIG = 389
ETH_SIG = 302

COL_ROOT  = "#34495e"
COL_LONG  = "#27ae60"
COL_SHORT = "#c0392b"
COL_ETH_HDR = "#627eea"
COL_STRAT_HDR = "#2980b9"
COL_STRAT_BG  = "#ecf3fb"


def ev_color(ev):
    if ev < 0:        return "#c0392b"
    if ev >= 0.20:    return "#0a7c2b"
    if ev >= 0.15:    return "#1a8f3f"
    if ev >= 0.10:    return "#27ae60"
    if ev >= 0.05:    return "#f1c40f"
    return "#e67e22"


def strat_ev_color(ev):
    """Strategy EV color (in R, not in %). EV in R: 0.8+, 1.0+, 1.2+, 1.4+."""
    if ev < 0.5:    return "#c0392b"
    if ev >= 1.4:   return "#0a7c2b"
    if ev >= 1.2:   return "#1a8f3f"
    if ev >= 1.0:   return "#27ae60"
    if ev >= 0.8:   return "#f1c40f"
    return "#e67e22"


fig, ax = plt.subplots(figsize=(42, 14))
ax.set_xlim(0, 42)
ax.set_ylim(2, 14)
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
    """Base 24-type row."""
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


def draw_strategy_row(side_x, dir_key, strat, asset, *, leaf_top_y, leaf_bottom_y):
    """v3.3 strategy row — N_sel / WR_sel / EV_sel / ΣR_sel."""
    groups = DIR_LAYOUT[dir_key]
    type_col = COL_SHORT if dir_key == "short" else COL_LONG

    LEAF_W = 1.40; LEAF_GAP = 0.12
    GROUP_W = 3 * LEAF_W + 2 * LEAF_GAP
    GROUP_GAP = 0.45
    leaf_h = leaf_top_y - leaf_bottom_y

    for gi, (label, leaves) in enumerate(groups):
        gx = side_x + gi * (GROUP_W + GROUP_GAP)
        for li, tid in enumerate(leaves):
            lx = gx + li * (LEAF_W + LEAF_GAP)
            tup = strat.get(tid)

            box(lx, leaf_bottom_y, LEAF_W, leaf_h, "",
                fc=COL_STRAT_BG, ec=COL_STRAT_HDR, lw=1.4)

            if tup is None:
                ax.text(lx + LEAF_W/2, leaf_bottom_y + leaf_h/2,
                        "— no signal —", ha="center", va="center",
                        fontsize=10, fontweight="bold", color="#7f8c8d",
                        style="italic", zorder=5)
                continue

            n_sel, wr_sel, ev_sel, sum_r_sel = tup

            ax.text(lx + 0.15, leaf_top_y - 0.15, tid,
                    ha="left", va="top", fontsize=11, fontweight="bold",
                    color="white", zorder=6,
                    bbox=dict(facecolor=type_col, edgecolor=type_col,
                              boxstyle="round,pad=0.15", linewidth=0))
            ax.text(lx + LEAF_W - 0.15, leaf_top_y - 0.15, "v3.3",
                    ha="right", va="top", fontsize=9, fontweight="bold",
                    color="white", zorder=6,
                    bbox=dict(facecolor=COL_STRAT_HDR, edgecolor=COL_STRAT_HDR,
                              boxstyle="round,pad=0.15", linewidth=0))
            ax.text(lx + LEAF_W/2, leaf_bottom_y + 1.85, f"N = {n_sel}",
                    ha="center", va="center", fontsize=12,
                    fontweight="bold", color="#222", zorder=5)
            wr_col = "#0a7c2b" if wr_sel >= 75 else "#27ae60" if wr_sel >= 70 else \
                      "#f1c40f" if wr_sel >= 60 else "#e67e22" if wr_sel >= 50 else "#c0392b"
            ax.text(lx + LEAF_W/2, leaf_bottom_y + 1.30, f"WR {wr_sel:.1f}%",
                    ha="center", va="center", fontsize=11,
                    fontweight="bold", color="white", zorder=5,
                    bbox=dict(facecolor=wr_col, edgecolor=wr_col,
                              boxstyle="round,pad=0.22", linewidth=0))
            ev_bg = strat_ev_color(ev_sel)
            ax.text(lx + LEAF_W/2, leaf_bottom_y + 0.75, f"EV {ev_sel:+.2f}R",
                    ha="center", va="center", fontsize=10.5,
                    fontweight="bold", color="white", zorder=5,
                    bbox=dict(facecolor=ev_bg, edgecolor=ev_bg,
                              boxstyle="round,pad=0.22", linewidth=0))
            sr_col = "#c0392b" if sum_r_sel < 0 else "#185c34"
            ax.text(lx + LEAF_W/2, leaf_bottom_y + 0.25, f"Σ {sum_r_sel:+.0f}R",
                    ha="center", va="center", fontsize=10,
                    fontweight="bold", color=sr_col, zorder=5)


# ═══════════ BTC ═══════════════════════════════════════
# BTC base row (top): leaf 8.8 → 4.5
draw_asset_row(1.5,  "long",  DATA_BTC, TBM_BTC, RPCT_BTC,
               group_y=9.6, leaf_top_y=8.8, leaf_bottom_y=4.5,
               draw_group_label=True, draw_dir_arrow=True)
draw_asset_row(22.5, "short", DATA_BTC, TBM_BTC, RPCT_BTC,
               group_y=9.6, leaf_top_y=8.8, leaf_bottom_y=4.5,
               draw_group_label=True, draw_dir_arrow=True)

fig.suptitle(
    f"Классификация 2h ob_vc — 24 типа BTC (TBM TP1R, 6y)\n"
    f"BTC: {BTC_TOT:,} setups, Σ {BTC_SIG:+}R / 6y",
    fontsize=14, fontweight="bold", y=0.98)

plt.subplots_adjust(left=0.005, right=0.995, top=0.92, bottom=0.02)
out = pathlib.Path.home() / 'smc-lib/projects/ob_vc/data/ob_vc_2h_24_btc_canon_format.png'
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=110, bbox_inches='tight')
print(f'Saved: {out}')
