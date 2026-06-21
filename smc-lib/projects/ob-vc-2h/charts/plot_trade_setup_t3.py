"""Trade setup viz для T3 example — LONG SWEPT n_FVG=1 extreme=prev.
2h ob_vc cur 04-06-2026 15:00 МСК. Entry 0.2 deep в 15m FVG (n=1 правило).
"""
import sys, pathlib
from datetime import datetime, timezone, timedelta
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib/projects/ob-vc/scripts"))
from _lib import load_1m, aggregate_all_tfs, TFS_MS

MSK = timezone(timedelta(hours=3))

WIN_S = int(datetime(2026, 6, 4, 12, 0, tzinfo=MSK).timestamp() * 1000)
WIN_E = int(datetime(2026, 6, 5, 13, 0, tzinfo=MSK).timestamp() * 1000)

OB_CUR_OPEN = int(datetime(2026, 6, 4, 15, 0, tzinfo=MSK).timestamp() * 1000)
OB_CUR_CLOSE = OB_CUR_OPEN + 2 * 3600 * 1000
OB_PREV_OPEN = OB_CUR_OPEN - 2 * 3600 * 1000

# From parquet (T3 example)
OB_ZONE = (62_205.0, 64_230.0)
DROP_AREA = (62_205.0, 62_730.0)        # need to verify drop_hi
FIRST_FH = 63_178.0                      # approximation, refine if needed

FVG_15M = {
    "c1_ms": int(datetime(2026, 6, 4, 15, 0, tzinfo=MSK).timestamp() * 1000),
    "c3_close_ms": int(datetime(2026, 6, 4, 15, 45, tzinfo=MSK).timestamp() * 1000),
    "zone": (62_706.0, 63_149.0),
}

# Trade params (n_FVG=1 → entry 0.2 deep)
fvg_lo, fvg_hi = FVG_15M["zone"]
ENTRY = fvg_hi - 0.2 * (fvg_hi - fvg_lo)
SL = OB_ZONE[0]   # = low_ob_vc = drop_lo
R = ENTRY - SL
TP_RR = [1.0, 1.5, 2.0, 2.5, 3.0]
TPS = [(rr, ENTRY + rr * R) for rr in TP_RR]

# Events
BORN_MS = int(datetime(2026, 6, 4, 17, 0, tzinfo=MSK).timestamp() * 1000)
ENTRY_TOUCH_MS = int(datetime(2026, 6, 4, 20, 33, tzinfo=MSK).timestamp() * 1000)
TP1R_HIT_MS = int(datetime(2026, 6, 4, 21, 29, tzinfo=MSK).timestamp() * 1000)
SL_HIT_MS = int(datetime(2026, 6, 5, 9, 1, tzinfo=MSK).timestamp() * 1000)

print(f"FVG 15m zone:    [${fvg_lo:,.0f} ; ${fvg_hi:,.0f}]  width ${fvg_hi-fvg_lo:,.0f}")
print(f"Entry (0.2 deep) = ${ENTRY:,.0f}")
print(f"SL (low_ob_vc)   = ${SL:,.0f}")
print(f"R = ${R:,.0f}")
for rr, lvl in TPS: print(f"TP{rr:.1f}R = ${lvl:,.0f}")


def to_dt(ms): return datetime.fromtimestamp(int(ms)/1000, MSK)

rows = load_1m()
bars = aggregate_all_tfs(rows)
b15 = bars["15m"]
bars_win = [b for b in b15 if WIN_S <= b[0] < WIN_E]
print(f"15m bars in window: {len(bars_win)}")


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

# OB.zone
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

# Single 15m FVG
c1_dt = to_dt(FVG_15M["c1_ms"])
c3_dt = to_dt(FVG_15M["c3_close_ms"])
x1 = mdates.date2num(c1_dt); x2 = mdates.date2num(c3_dt)
ax.add_patch(Rectangle((x1, FVG_15M["zone"][0]), x2-x1,
                        FVG_15M["zone"][1]-FVG_15M["zone"][0],
                        facecolor="#27ae60", alpha=0.30, edgecolor="#27ae60",
                        linewidth=1.0, zorder=3))

# Trade levels
ax.axhline(ENTRY, color="#27ae60", linewidth=2.0, linestyle="-", zorder=6)
ax.axhline(SL, color="#c0392b", linewidth=2.0, linestyle="-", zorder=6)
tp_colors = ["#2980b9", "#3498db", "#5dade2", "#85c1e9", "#aed6f1"]
for (rr, lvl), col in zip(TPS, tp_colors):
    ax.axhline(lvl, color=col, linewidth=1.3, linestyle="--", zorder=5)

xtext = xe
ax.text(xtext, ENTRY, f"  ENTRY 0.2 deep  ${ENTRY:,.0f}", color="#27ae60",
        fontweight="bold", fontsize=11, va="center", ha="left", zorder=11,
        bbox=dict(facecolor="white", edgecolor="#27ae60", boxstyle="round,pad=0.3"))
ax.text(xtext, SL, f"  SL = low_ob_vc  ${SL:,.0f}", color="#c0392b",
        fontweight="bold", fontsize=11, va="center", ha="left", zorder=11,
        bbox=dict(facecolor="white", edgecolor="#c0392b", boxstyle="round,pad=0.3"))
for (rr, lvl), col in zip(TPS, tp_colors):
    ax.text(xtext, lvl, f"  TP {rr:.1f}R  ${lvl:,.0f}", color=col,
            fontweight="bold", fontsize=10, va="center", ha="left", zorder=11)

# OB vertical boundaries
for ms, lbl in [(OB_PREV_OPEN, "prev.open 13:00"), (OB_CUR_OPEN, "cur.open 15:00"),
                 (OB_CUR_CLOSE, "cur.close 17:00")]:
    dt = to_dt(ms)
    ax.axvline(dt, color="#7f8c8d", linewidth=0.6, linestyle=":", zorder=2)
    ax.text(dt, ax.get_ylim()[0], f" {lbl} ", fontsize=8, color="#555",
            rotation=90, va="bottom", ha="right", zorder=12)

# Markers
# 1) ob_vc BORN
ax.scatter([to_dt(BORN_MS)], [OB_ZONE[1] + 80], s=380, marker="*",
           color="gold", edgecolors="#7f5c00", linewidths=1.5, zorder=20)
ax.annotate(f"ob_vc BORN\n{to_dt(BORN_MS):%d-%m %H:%M}",
            xy=(to_dt(BORN_MS), OB_ZONE[1] + 80),
            xytext=(to_dt(BORN_MS), OB_ZONE[1] + 400),
            fontsize=10, fontweight="bold", color="#7f5c00", ha="center",
            arrowprops=dict(arrowstyle="->", color="#7f5c00", lw=1.2), zorder=21)

# 2) Entry fill
ax.scatter([to_dt(ENTRY_TOUCH_MS)], [ENTRY], s=320, marker="D",
           color="#27ae60", edgecolors="#185c34", linewidths=1.5, zorder=20)
ax.annotate(f"ENTRY FILL\n{to_dt(ENTRY_TOUCH_MS):%d-%m %H:%M}\n@ ${ENTRY:,.0f}",
            xy=(to_dt(ENTRY_TOUCH_MS), ENTRY),
            xytext=(to_dt(ENTRY_TOUCH_MS), ENTRY - 700),
            fontsize=10, fontweight="bold", color="#185c34", ha="center",
            arrowprops=dict(arrowstyle="->", color="#27ae60", lw=1.2), zorder=21)

# 3) TP1R hit
ax.scatter([to_dt(TP1R_HIT_MS)], [TPS[0][1]], s=320, marker="s",
           color="#2980b9", edgecolors="#1a4f76", linewidths=1.5, zorder=20)
ax.annotate(f"TP 1.0R\n{to_dt(TP1R_HIT_MS):%d-%m %H:%M}\n+1R WIN ✓",
            xy=(to_dt(TP1R_HIT_MS), TPS[0][1]),
            xytext=(to_dt(TP1R_HIT_MS), TPS[0][1] + 700),
            fontsize=10, fontweight="bold", color="#1a4f76", ha="center",
            arrowprops=dict(arrowstyle="->", color="#2980b9", lw=1.2), zorder=21)

# 4) SL hit (after TP1R already triggered → academic)
ax.scatter([to_dt(SL_HIT_MS)], [SL], s=280, marker="X",
           color="#c0392b", edgecolors="#7d0000", linewidths=1.5, zorder=20)
ax.annotate(f"SL hit (post-TP1R)\n{to_dt(SL_HIT_MS):%d-%m %H:%M}\nакадемич.",
            xy=(to_dt(SL_HIT_MS), SL),
            xytext=(to_dt(SL_HIT_MS), SL - 500),
            fontsize=9, fontweight="bold", color="#7d0000", ha="center",
            arrowprops=dict(arrowstyle="->", color="#c0392b", lw=1.2), zorder=21)


ax.xaxis.set_major_locator(mdates.HourLocator(interval=3))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m %H:%M", tz=MSK))
ax.grid(False)
ax.yaxis.tick_right()
ax.yaxis.set_label_position("right")

fig.suptitle(
    f"2h LONG ob_vc T3 (SWEPT, n_FVG=1, extreme=prev)  |  "
    f"cur {to_dt(OB_CUR_OPEN):%d-%m %H:%M}→{to_dt(OB_CUR_CLOSE):%H:%M} МСК  |  "
    f"Entry ${ENTRY:,.0f}  •  SL ${SL:,.0f}  •  R ${R:,.0f}  |  TPs 1.0R…3.0R",
    fontsize=12, fontweight="bold", y=0.97
)

legend_text = (
    "T3 = LONG SWEPT n_FVG=1 extreme=prev  (n=552 / 4,036 = 13.7%)\n"
    "OB zone (blue) — full imbalance\n"
    "drop area (orange) — где prev продавал\n"
    "15m FVG (green) — единственный FVG component\n"
    f"Entry = 0.2 deep in 15m FVG (n_FVG=1 правило) = ${ENTRY:,.0f}\n"
    f"SL = low_ob_vc = ${SL:,.0f}     R = ${R:,.0f}\n"
    "OUTCOME: +1R WIN @ 04-06 21:29 (56 мин после entry)"
)
ax.text(0.005, 0.99, legend_text, transform=ax.transAxes, ha="left", va="top",
        fontsize=9, bbox=dict(facecolor="white", edgecolor="#888", alpha=0.95, pad=8),
        zorder=15)

plt.subplots_adjust(left=0.025, right=0.86, top=0.93, bottom=0.07)
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/ob_vc_2h_T3_trade_setup.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=140)
print(f"\nSaved: {out}")
