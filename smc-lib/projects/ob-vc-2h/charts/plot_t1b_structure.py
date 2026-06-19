"""T1b structure: LONG SWEPT n_FVG=≥2 extreme=prev wick_ratio < 2× (weak wick).
OLD rule entry. Пример: 29-05-2026 07:00 МСК (ratio 1.23×).
"""
import sys, pathlib
from datetime import datetime, timezone, timedelta
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib/projects/ob-vc/scripts"))
from _lib import load_1m, aggregate_all_tfs

MSK = timezone(timedelta(hours=3))

WIN_S = int(datetime(2026, 5, 29, 3, 0, tzinfo=MSK).timestamp() * 1000)
WIN_E = int(datetime(2026, 5, 29, 18, 0, tzinfo=MSK).timestamp() * 1000)

OB_CUR_OPEN = int(datetime(2026, 5, 29, 7, 0, tzinfo=MSK).timestamp() * 1000)
OB_CUR_CLOSE = OB_CUR_OPEN + 2 * 3600 * 1000
OB_PREV_OPEN = OB_CUR_OPEN - 2 * 3600 * 1000

PREV = dict(o=73_586.8, h=73_646.7, l=73_189.1, c=73_301.5)
CUR  = dict(o=73_301.5, h=73_719.4, l=73_210.2, c=73_706.0)
OB_ZONE = (PREV["l"], CUR["c"])
DROP_AREA = (PREV["l"], PREV["o"])

FVGS = [
    {"c1_ms": int(datetime(2026,5,29,7,15,tzinfo=MSK).timestamp()*1000),
     "c3_close_ms": int(datetime(2026,5,29,8,0,tzinfo=MSK).timestamp()*1000),
     "zone": (73_380.0, 73_403.6)},
    {"c1_ms": int(datetime(2026,5,29,7,30,tzinfo=MSK).timestamp()*1000),
     "c3_close_ms": int(datetime(2026,5,29,8,15,tzinfo=MSK).timestamp()*1000),
     "zone": (73_440.7, 73_503.3)},
]

# Wick analysis
prev_body_lo = min(PREV["o"], PREV["c"])
cur_body_lo  = min(CUR["o"], CUR["c"])
prev_wick = prev_body_lo - PREV["l"]
cur_wick  = cur_body_lo - CUR["l"]
wick_ratio = prev_wick / cur_wick   # 1.23

# OLD rule (T1b): Entry = 0.8 deep in top FVG, SL = drop_lo
TOP_FVG = max(FVGS, key=lambda f: f["zone"][1])
fvg_lo, fvg_hi = TOP_FVG["zone"]
ENTRY = fvg_hi - 0.8 * (fvg_hi - fvg_lo)
SL = DROP_AREA[0]
R = ENTRY - SL
TPS = [(rr, ENTRY + rr * R) for rr in (1.0, 1.5, 2.0, 2.5, 3.0)]

BORN_MS = int(datetime(2026, 5, 29, 9, 0, tzinfo=MSK).timestamp() * 1000)
ENTRY_TOUCH_MS = int(datetime(2026, 5, 29, 10, 36, tzinfo=MSK).timestamp() * 1000)
TP1R_HIT_MS = int(datetime(2026, 5, 29, 11, 2, tzinfo=MSK).timestamp() * 1000)
SL_HIT_MS = int(datetime(2026, 5, 29, 16, 8, tzinfo=MSK).timestamp() * 1000)


def to_dt(ms): return datetime.fromtimestamp(int(ms)/1000, MSK)

BULL = "#01a648"; BEAR = "#131b1b"; DOJI = "#888"
RED = "#c0392b"; GREEN = "#27ae60"

rows = load_1m()
bars = aggregate_all_tfs(rows)
b15 = [b for b in bars["15m"] if WIN_S <= b[0] < WIN_E]

fig = plt.figure(figsize=(22, 11))
gs = fig.add_gridspec(1, 2, width_ratios=[3, 1], wspace=0.04)
ax = fig.add_subplot(gs[0])
ax_info = fig.add_subplot(gs[1])
ax_info.axis("off")
ax_info.set_xlim(0, 1); ax_info.set_ylim(0, 1)

fig.suptitle("T1b structure  —  LONG SWEPT n_FVG≥2 extreme=PREV  wick_ratio < 2×  (OLD rule)",
             fontsize=15, fontweight="bold", y=0.97)

TF_MIN = 15
bar_w = TF_MIN / (60 * 24) * 0.6
for t, o, h, l, c in b15:
    dt = to_dt(t)
    col = BULL if c > o else (BEAR if c < o else DOJI)
    ax.vlines(dt, l, h, color=col, linewidth=0.9, zorder=4)
    ax.add_patch(Rectangle((mdates.date2num(dt) - bar_w/2, min(o, c)),
                            bar_w, max(abs(o-c), 0.01),
                            facecolor=col, edgecolor=col, linewidth=0.9, zorder=4))

xs = mdates.date2num(to_dt(WIN_S))
xe = mdates.date2num(to_dt(WIN_E))

ax.add_patch(Rectangle((xs, OB_ZONE[0]), xe-xs, OB_ZONE[1]-OB_ZONE[0],
                       facecolor="#4a90e2", alpha=0.06, edgecolor="#4a90e2",
                       linewidth=1.2, linestyle=(0, (4, 4)), zorder=1))
ax.text(xs, OB_ZONE[1], "  OB-2h LONG zone", fontsize=10, color="#2169b3",
        fontweight="bold", va="bottom", ha="left", zorder=10)

ax.add_patch(Rectangle((xs, DROP_AREA[0]), xe-xs, DROP_AREA[1]-DROP_AREA[0],
                       facecolor="#f5b041", alpha=0.20, edgecolor="#f5b041",
                       linewidth=1.0, linestyle=(0, (2, 3)), zorder=1.5))
ax.text(xe, DROP_AREA[1], "  drop area  ", fontsize=10, color="#b88420",
        fontweight="bold", va="bottom", ha="right", zorder=10)

# 2 FVGs
for fvg in FVGS:
    c1_dt = to_dt(fvg["c1_ms"])
    c3_dt = to_dt(fvg["c3_close_ms"])
    x1 = mdates.date2num(c1_dt); x2 = mdates.date2num(c3_dt)
    ax.add_patch(Rectangle((x1, fvg["zone"][0]), x2-x1,
                            fvg["zone"][1]-fvg["zone"][0],
                            facecolor=GREEN, alpha=0.30, edgecolor=GREEN,
                            linewidth=1.0, zorder=3))

ax.text(mdates.date2num(to_dt(TOP_FVG["c1_ms"])),
        TOP_FVG["zone"][1] + 6, "TOP 15m FVG", fontsize=9,
        color="#185c34", fontweight="bold", zorder=10)

ax.axhline(ENTRY, color=GREEN, linewidth=2.2, zorder=6)
ax.axhline(SL, color=RED, linewidth=2.2, zorder=6)
for rr, lvl in TPS:
    alpha = 0.7 if rr == 1.0 else 0.4
    lw = 1.6 if rr == 1.0 else 1.1
    ax.axhline(lvl, color="#2980b9", linewidth=lw, linestyle="--", alpha=alpha, zorder=5)

ax.text(xe, ENTRY, f"  ENTRY  ${ENTRY:,.0f}", color=GREEN,
        fontweight="bold", fontsize=11, va="center", ha="left", zorder=11,
        bbox=dict(facecolor="white", edgecolor=GREEN, boxstyle="round,pad=0.3"))
ax.text(xe, SL, f"  SL = prev.low  ${SL:,.0f}", color=RED,
        fontweight="bold", fontsize=11, va="center", ha="left", zorder=11,
        bbox=dict(facecolor="white", edgecolor=RED, boxstyle="round,pad=0.3"))
for rr, lvl in TPS:
    weight = "bold" if rr == 1.0 else "normal"
    fs = 10 if rr == 1.0 else 9
    ax.text(xe, lvl, f"  TP {rr:.1f}R  ${lvl:,.0f}", color="#2980b9",
            fontweight=weight, fontsize=fs, va="center", ha="left", zorder=11)

# Wick annotations
prev_x = mdates.date2num(to_dt(OB_PREV_OPEN + 3600 * 1000))
ax.annotate("", xy=(prev_x, PREV["l"]),
            xytext=(prev_x, prev_body_lo),
            arrowprops=dict(arrowstyle="<->", color=RED, lw=2.2), zorder=12)
ax.text(prev_x - 0.05, (PREV["l"] + prev_body_lo)/2,
        f"prev wick\n${prev_wick:,.0f}",
        ha="right", va="center", fontsize=10, color=RED, fontweight="bold", zorder=13)

cur_x = mdates.date2num(to_dt(OB_CUR_OPEN + 30 * 60 * 1000))
ax.annotate("", xy=(cur_x, CUR["l"]),
            xytext=(cur_x, cur_body_lo),
            arrowprops=dict(arrowstyle="<->", color=GREEN, lw=2.2), zorder=12)
ax.text(cur_x + 0.05, (CUR["l"] + cur_body_lo)/2,
        f"cur wick\n${cur_wick:,.0f}",
        ha="left", va="center", fontsize=10, color=GREEN, fontweight="bold", zorder=13)

# Markers
ax.scatter([to_dt(BORN_MS)], [OB_ZONE[1] + 30], s=380, marker="*",
           color="gold", edgecolors="#7f5c00", linewidths=1.5, zorder=20)
ax.annotate(f"BORN\n{to_dt(BORN_MS):%d-%m %H:%M}",
            xy=(to_dt(BORN_MS), OB_ZONE[1] + 30),
            xytext=(to_dt(BORN_MS), OB_ZONE[1] + 150),
            fontsize=9, fontweight="bold", color="#7f5c00", ha="center",
            arrowprops=dict(arrowstyle="->", color="#7f5c00", lw=1.2), zorder=21)

ax.scatter([to_dt(ENTRY_TOUCH_MS)], [ENTRY], s=320, marker="D",
           color=GREEN, edgecolors="#185c34", linewidths=1.5, zorder=20)
ax.annotate(f"ENTRY FILL\n{to_dt(ENTRY_TOUCH_MS):%d-%m %H:%M}",
            xy=(to_dt(ENTRY_TOUCH_MS), ENTRY),
            xytext=(to_dt(ENTRY_TOUCH_MS), ENTRY - 150),
            fontsize=9, fontweight="bold", color="#185c34", ha="center",
            arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.2), zorder=21)

ax.scatter([to_dt(TP1R_HIT_MS)], [TPS[0][1]], s=320, marker="s",
           color="#2980b9", edgecolors="#1a4f76", linewidths=1.5, zorder=20)
ax.annotate(f"TP 1.0R hit\n{to_dt(TP1R_HIT_MS):%d-%m %H:%M}\n+1R WIN ✓",
            xy=(to_dt(TP1R_HIT_MS), TPS[0][1]),
            xytext=(to_dt(TP1R_HIT_MS), TPS[0][1] + 150),
            fontsize=9, fontweight="bold", color="#1a4f76", ha="center",
            arrowprops=dict(arrowstyle="->", color="#2980b9", lw=1.2), zorder=21)

ax.scatter([to_dt(SL_HIT_MS)], [SL], s=240, marker="X",
           color=RED, edgecolors="#7d0000", linewidths=1.5, zorder=20)
ax.annotate(f"SL hit (post-TP1R)\n{to_dt(SL_HIT_MS):%d-%m %H:%M}",
            xy=(to_dt(SL_HIT_MS), SL),
            xytext=(to_dt(SL_HIT_MS), SL - 120),
            fontsize=8, color="#7d0000", ha="center",
            arrowprops=dict(arrowstyle="->", color=RED, lw=1.0), zorder=21)

for ms, lbl in [(OB_PREV_OPEN, "prev open"), (OB_CUR_OPEN, "cur open"), (OB_CUR_CLOSE, "cur close")]:
    dt = to_dt(ms)
    ax.axvline(dt, color="#7f8c8d", linewidth=0.6, linestyle=":", zorder=2)

ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m %H:%M", tz=MSK))
ax.grid(False)
ax.yaxis.tick_right()


# Info panel
def info_text(y, text, **kw):
    ax_info.text(0.5, y, text, ha="center", va="top", **kw)

info_text(0.98, "T1b", fontsize=28, fontweight="bold", color="white",
          bbox=dict(facecolor=GREEN, edgecolor=GREEN, boxstyle="round,pad=0.4"))

info_text(0.88,
          "LONG  •  SWEPT  •  n_FVG ≥ 2\n"
          "extreme = PREV  •  wick < 2×",
          fontsize=11.5, fontweight="bold", color="#222")

rules_text = (
    "📋 Правила T1b (OLD rule)\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "Entry  =  fvg_hi − 0.8 × width\n"
    "       =  0.8 deep в TOP 15m FVG\n\n"
    "SL     =  prev.low\n"
    "       =  drop_area_lo\n\n"
    "R      =  Entry − SL\n\n"
    "TP1R   =  Entry + 1R (fixed exit)\n"
)
ax_info.text(0.05, 0.78, rules_text, ha="left", va="top", fontsize=10,
             family="monospace", color="#222",
             bbox=dict(facecolor="#f0f8ff", edgecolor="#4a90e2",
                       boxstyle="round,pad=0.5", linewidth=1.5))

tp1r = TPS[0][1]
nums_text = (
    f"📐 Этот сетап (29-05 09:00 МСК)\n"
    f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    f"prev.low      =  ${PREV['l']:,.1f}\n"
    f"cur.low       =  ${CUR['l']:,.1f}\n"
    f"extreme       =  PREV ✓\n\n"
    f"prev wick     =  ${prev_wick:,.1f}\n"
    f"cur wick      =  ${cur_wick:,.1f}\n"
    f"ratio         =  {wick_ratio:.2f}×  < 2 ✓ → b\n\n"
    f"Top 15m FVG   =  [{fvg_lo:,.0f}; {fvg_hi:,.0f}]\n\n"
    f"Entry ${ENTRY:,.0f}  •  SL ${SL:,.0f}\n"
    f"R = ${R:,.0f} ({R/ENTRY*100:.2f}%)\n"
    f"TP1R = ${tp1r:,.0f}\n\n"
    f"Outcome:  ✅  WIN +1R за 26 мин"
)
ax_info.text(0.05, 0.40, nums_text, ha="left", va="top", fontsize=9.5,
             family="monospace", color="#222",
             bbox=dict(facecolor="#eafaf1", edgecolor=GREEN,
                       boxstyle="round,pad=0.5", linewidth=1.5))

stats_text = (
    "📊 T1b stats на 6y BTC\n"
    "─────────────────\n"
    "N = 62  •  WR = 62.1%\n"
    "EV = +0.241R / trade\n"
    "avg R% = 0.94%\n"
    "Σ = +14R за 6y\n"
    "\n"
    "⚠ Малый sample (62)\n"
    "  Хорошая WR но low EV"
)
ax_info.text(0.05, 0.05, stats_text, ha="left", va="top", fontsize=9,
             family="monospace", color="#444",
             bbox=dict(facecolor="#fef9e7", edgecolor="#f1c40f",
                       boxstyle="round,pad=0.4", linewidth=1.2))


plt.subplots_adjust(left=0.025, right=0.985, top=0.94, bottom=0.06)
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/ob_vc_2h_T1b_structure.png"
plt.savefig(out, dpi=140)
print(f"Saved: {out}")
