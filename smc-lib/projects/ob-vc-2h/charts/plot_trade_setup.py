"""Trade setup viz for 2h LONG ob_vc cur 23:00 МСК 05-06-2026.

15m chart с overlay'ом OB.zone, drop area, FVG-components, entry/SL/TP/buffers.
"""
import sys, pathlib
from datetime import datetime, timezone, timedelta
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib/projects/ob-vc/scripts"))
from _lib import load_1m, aggregate_all_tfs, TFS_MS

MSK = timezone(timedelta(hours=3))

# Window: 17:00 МСК 05-06 → 11:00 МСК 07-06 (~42h to cover full trade lifecycle)
WIN_S = int(datetime(2026, 6, 5, 17, 0, tzinfo=MSK).timestamp() * 1000)
WIN_E = int(datetime(2026, 6, 7, 11, 0, tzinfo=MSK).timestamp() * 1000)

# Event timestamps (measured on 1m data)
BORN_MS = int(datetime(2026, 6, 6, 1, 0, tzinfo=MSK).timestamp() * 1000)
ENTRY_TOUCH_MS = int(datetime(2026, 6, 6, 7, 6, tzinfo=MSK).timestamp() * 1000)
TP1R_HIT_MS = int(datetime(2026, 6, 7, 7, 55, tzinfo=MSK).timestamp() * 1000)

# OB params (2h LONG cur 23:00 МСК)
OB_CUR_OPEN = int(datetime(2026, 6, 5, 23, 0, tzinfo=MSK).timestamp() * 1000)
OB_CUR_CLOSE = OB_CUR_OPEN + 2 * 3600 * 1000
OB_PREV_OPEN = OB_CUR_OPEN - 2 * 3600 * 1000
OB_ZONE = (59_130.91, 61_670.38)          # min(prev.low, cur.low) to cur.close
DROP_AREA = (59_130.91, 60_814.00)        # drop_lo to prev.open
FIRST_FH = 62_000.0                        # first opposite Williams N=2 on 15m

# FVG components (canon #1-#9, relaxed #7)
FVGS = [
    {"ltf": "15m", "c1_ms": int(datetime(2026,6,5,22,30,tzinfo=MSK).timestamp()*1000),
     "c3_close_ms": int(datetime(2026,6,5,23,15,tzinfo=MSK).timestamp()*1000),
     "zone": (59_897.3, 59_940.0)},
    {"ltf": "15m", "c1_ms": int(datetime(2026,6,5,22,45,tzinfo=MSK).timestamp()*1000),
     "c3_close_ms": int(datetime(2026,6,5,23,30,tzinfo=MSK).timestamp()*1000),
     "zone": (60_459.4, 60_713.6)},
    {"ltf": "20m", "c1_ms": int(datetime(2026,6,5,22,20,tzinfo=MSK).timestamp()*1000),
     "c3_close_ms": int(datetime(2026,6,5,23,20,tzinfo=MSK).timestamp()*1000),
     "zone": (59_870.0, 59_940.0)},
    {"ltf": "20m", "c1_ms": int(datetime(2026,6,5,22,40,tzinfo=MSK).timestamp()*1000),
     "c3_close_ms": int(datetime(2026,6,5,23,40,tzinfo=MSK).timestamp()*1000),
     "zone": (60_459.4, 60_806.6)},
]

# Trade params (canon per user 2026-06-07)
#   Entry: 0.8 deep into HIGHEST 15m FVG (closest to retest)
#   SL:    low_ob_vc = drop_lo (no buffer)
#   TPs:   1R, 1.5R, 2R, 2.5R, 3R (any = good)
FVG_15M = [f for f in FVGS if f["ltf"] == "15m"]
TOP_FVG_15M = max(FVG_15M, key=lambda f: f["zone"][1])
fvg_lo, fvg_hi = TOP_FVG_15M["zone"]
ENTRY = fvg_hi - 0.8 * (fvg_hi - fvg_lo)   # 0.8 deep from top
SL = DROP_AREA[0]                           # = low_ob_vc, no buffer
R = ENTRY - SL
TP_RR = [1.0, 1.5, 2.0, 2.5, 3.0]
TPS = [(rr, ENTRY + rr * R) for rr in TP_RR]

print(f"Top 15m FVG zone:  [${fvg_lo:,.0f} ; ${fvg_hi:,.0f}]  width ${fvg_hi-fvg_lo:,.0f}")
print(f"Entry (0.8 deep)  = ${ENTRY:,.0f}")
print(f"SL (low_ob_vc)    = ${SL:,.0f}")
print(f"R                 = ${R:,.0f}")
for rr, lvl in TPS:
    print(f"TP{rr:>3.1f}R           = ${lvl:,.0f}")
print(f"first_FH 15m      = ${FIRST_FH:,.0f}")
print(f"drop_hi           = ${DROP_AREA[1]:,.0f}")
print(f"cur.high          = $62,000")


# ─── Load 15m ───────────────────────────────────────────
rows = load_1m()
bars = aggregate_all_tfs(rows)
b15 = bars["15m"]
bars_win = [b for b in b15 if WIN_S <= b[0] < WIN_E]
print(f"\n15m bars in window: {len(bars_win)}")


# ─── Chart ──────────────────────────────────────────────
def to_dt(ms): return datetime.fromtimestamp(int(ms)/1000, MSK)

BULL = "#01a648"; BEAR = "#131b1b"; DOJI = "#888"
fig, ax = plt.subplots(figsize=(20, 11))
TF_MIN = 15
bar_w = TF_MIN / (60 * 24) * 0.6

for t, o, h, l, c in bars_win:
    dt = to_dt(t)
    col = BULL if c > o else (BEAR if c < o else DOJI)
    ax.vlines(dt, l, h, color=col, linewidth=0.9, zorder=4)
    ax.add_patch(Rectangle((mdates.date2num(dt) - bar_w/2, min(o, c)),
                            bar_w, max(abs(o-c), 0.01),
                            facecolor=col, edgecolor=col, linewidth=0.9, zorder=4))

xs = mdates.date2num(to_dt(WIN_S))
xe = mdates.date2num(to_dt(WIN_E))

# OB.zone (full)
ax.add_patch(Rectangle((xs, OB_ZONE[0]), xe-xs, OB_ZONE[1]-OB_ZONE[0],
                       facecolor="#4a90e2", alpha=0.06, edgecolor="#4a90e2",
                       linewidth=1.2, linestyle=(0, (4, 4)), zorder=1))
ax.text(xs, OB_ZONE[1], "  OB-2h LONG zone  ", fontsize=10, color="#2169b3",
        fontweight="bold", va="bottom", ha="left", zorder=10)

# drop area
ax.add_patch(Rectangle((xs, DROP_AREA[0]), xe-xs, DROP_AREA[1]-DROP_AREA[0],
                       facecolor="#f5b041", alpha=0.18, edgecolor="#f5b041",
                       linewidth=1.0, linestyle=(0, (2, 3)), zorder=1.5))
ax.text(xe, DROP_AREA[1], "  drop area  ", fontsize=10, color="#b88420",
        fontweight="bold", va="bottom", ha="right", zorder=10)

# FVG components
fvg_colors = {"15m": "#27ae60", "20m": "#8e44ad"}
for f in FVGS:
    c1_dt = to_dt(f["c1_ms"])
    c3_dt = to_dt(f["c3_close_ms"])
    x1 = mdates.date2num(c1_dt); x2 = mdates.date2num(c3_dt)
    col = fvg_colors[f["ltf"]]
    ax.add_patch(Rectangle((x1, f["zone"][0]), x2-x1, f["zone"][1]-f["zone"][0],
                            facecolor=col, alpha=0.25, edgecolor=col,
                            linewidth=1.0, zorder=3))

# Trade levels (across full window)
ax.axhline(ENTRY, color="#27ae60", linewidth=2.0, linestyle="-", zorder=6)
ax.axhline(SL, color="#c0392b", linewidth=2.0, linestyle="-", zorder=6)
ax.axhline(DROP_AREA[1], color="#7f8c8d", linewidth=0.8, linestyle=":", zorder=2)
ax.axhline(FIRST_FH, color="#9b59b6", linewidth=0.8, linestyle=":", zorder=2)

tp_colors = ["#2980b9", "#3498db", "#5dade2", "#85c1e9", "#aed6f1"]
tp_styles = ["--", "--", "--", "--", "--"]
tp_widths = [1.5, 1.3, 1.2, 1.0, 0.9]
for (rr, lvl), col, ls, lw in zip(TPS, tp_colors, tp_styles, tp_widths):
    ax.axhline(lvl, color=col, linewidth=lw, linestyle=ls, zorder=5)

xtext = xe
ax.text(xtext, ENTRY, f"  ENTRY  ${ENTRY:,.0f}", color="#27ae60",
        fontweight="bold", fontsize=11, va="center", ha="left", zorder=11,
        bbox=dict(facecolor="white", edgecolor="#27ae60", boxstyle="round,pad=0.3"))
ax.text(xtext, SL, f"  SL = low_ob_vc  ${SL:,.0f}", color="#c0392b",
        fontweight="bold", fontsize=11, va="center", ha="left", zorder=11,
        bbox=dict(facecolor="white", edgecolor="#c0392b", boxstyle="round,pad=0.3"))
for (rr, lvl), col in zip(TPS, tp_colors):
    ax.text(xtext, lvl, f"  TP {rr:.1f}R  ${lvl:,.0f}", color=col,
            fontweight="bold", fontsize=10, va="center", ha="left", zorder=11)

ax.text(xtext, DROP_AREA[1], f"  drop_hi  ${DROP_AREA[1]:,.0f}",
        color="#555", fontsize=8, va="center", ha="left", zorder=11)
ax.text(xtext, FIRST_FH, f"  first_FH 15m  ${FIRST_FH:,.0f}",
        color="#7e3c9e", fontsize=8, va="center", ha="left", zorder=11)

# OB cur/prev vertical boundaries
for ms, lbl in [(OB_PREV_OPEN, "prev.open 21:00"), (OB_CUR_OPEN, "cur.open 23:00"),
                 (OB_CUR_CLOSE, "cur.close 01:00")]:
    dt = to_dt(ms)
    ax.axvline(dt, color="#7f8c8d", linewidth=0.6, linestyle=":", zorder=2)
    ax.text(dt, ax.get_ylim()[0], f" {lbl} ", fontsize=8, color="#555",
            rotation=90, va="bottom", ha="right", zorder=12)

# Trade event markers
# 1) ob_vc BORN (= когда все 9 условий канона выполнены)
ax.scatter([to_dt(BORN_MS)], [OB_ZONE[1] + (OB_ZONE[1] - OB_ZONE[0]) * 0.04],
           s=380, marker="*", color="gold", edgecolors="#7f5c00",
           linewidths=1.5, zorder=20)
ax.annotate(f"ob_vc BORN\n{to_dt(BORN_MS):%d-%m %H:%M} МСК",
            xy=(to_dt(BORN_MS), OB_ZONE[1] + (OB_ZONE[1] - OB_ZONE[0]) * 0.04),
            xytext=(to_dt(BORN_MS), OB_ZONE[1] + (OB_ZONE[1] - OB_ZONE[0]) * 0.22),
            fontsize=10, fontweight="bold", color="#7f5c00", ha="center",
            arrowprops=dict(arrowstyle="->", color="#7f5c00", lw=1.2), zorder=21)

# 2) ENTRY TOUCH (= цена впервые достигла $60,510 после born)
ax.scatter([to_dt(ENTRY_TOUCH_MS)], [ENTRY], s=320, marker="D",
           color="#27ae60", edgecolors="#185c34", linewidths=1.5, zorder=20)
ax.annotate(f"ENTRY FILL\n{to_dt(ENTRY_TOUCH_MS):%d-%m %H:%M} МСК\n@ ${ENTRY:,.0f}",
            xy=(to_dt(ENTRY_TOUCH_MS), ENTRY),
            xytext=(to_dt(ENTRY_TOUCH_MS), ENTRY - 1200),
            fontsize=10, fontweight="bold", color="#185c34", ha="center",
            arrowprops=dict(arrowstyle="->", color="#27ae60", lw=1.2), zorder=21)

# 3) TP1R hit
ax.scatter([to_dt(TP1R_HIT_MS)], [TPS[0][1]], s=320, marker="s",
           color="#2980b9", edgecolors="#1a4f76", linewidths=1.5, zorder=20)
ax.annotate(f"TP 1.0R\n{to_dt(TP1R_HIT_MS):%d-%m %H:%M} МСК\n+1R achieved ✓",
            xy=(to_dt(TP1R_HIT_MS), TPS[0][1]),
            xytext=(to_dt(TP1R_HIT_MS), TPS[0][1] + 1200),
            fontsize=10, fontweight="bold", color="#1a4f76", ha="center",
            arrowprops=dict(arrowstyle="->", color="#2980b9", lw=1.2), zorder=21)

# Axes
ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m %H:%M", tz=MSK))
plt.setp(ax.xaxis.get_majorticklabels(), rotation=0, ha="center")
ax.grid(False)
ax.yaxis.tick_right()
ax.yaxis.set_label_position("right")

# Title
fig.suptitle(
    f"2h LONG ob_vc  |  cur {to_dt(OB_CUR_OPEN):%d-%m %H:%M}→{to_dt(OB_CUR_CLOSE):%H:%M} МСК  "
    f"|  Entry ${ENTRY:,.0f}  •  SL ${SL:,.0f}  •  R ${R:,.0f}  "
    f"|  TPs 1.0R…3.0R",
    fontsize=12, fontweight="bold", y=0.97
)

# Legend
legend_text = (
    "OB zone (blue) — full imbalance\n"
    "drop area (orange) — где prev продавал\n"
    "15m FVG (green ×2)   20m FVG (purple ×2)\n"
    f"Entry = 0.8 deep in top 15m FVG = ${ENTRY:,.0f}\n"
    f"SL = low_ob_vc = drop_lo = ${SL:,.0f}\n"
    f"R = ${R:,.0f}   TPs: 1.0R/1.5R/2.0R/2.5R/3.0R\n"
)
ax.text(0.005, 0.99, legend_text, transform=ax.transAxes, ha="left", va="top",
        fontsize=9, bbox=dict(facecolor="white", edgecolor="#888", alpha=0.95, pad=8),
        zorder=15)

plt.subplots_adjust(left=0.025, right=0.86, top=0.93, bottom=0.07)
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/ob_vc_2h_long_trade_setup.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=140)
print(f"\nSaved: {out}")
