"""T1a structure chart: LONG SWEPT n_FVG=≥2 extreme=prev wick_ratio≥2×.

Канон правил entry/SL для T1a + визуализация на нашем 06-06 01:00 МСК born setup'е
(идеальный T1a с wick ratio 3.25×).
"""
import sys, pathlib
from datetime import datetime, timezone, timedelta
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib/projects/ob-vc/scripts"))
from _lib import load_1m, aggregate_all_tfs, TFS_MS

MSK = timezone(timedelta(hours=3))

# Window: фокус на формировании OB пары + entry
WIN_S = int(datetime(2026, 6, 5, 19, 0, tzinfo=MSK).timestamp() * 1000)
WIN_E = int(datetime(2026, 6, 6, 11, 0, tzinfo=MSK).timestamp() * 1000)

OB_CUR_OPEN = int(datetime(2026, 6, 5, 23, 0, tzinfo=MSK).timestamp() * 1000)
OB_CUR_CLOSE = OB_CUR_OPEN + 2 * 3600 * 1000
OB_PREV_OPEN = OB_CUR_OPEN - 2 * 3600 * 1000

# OB candle data (2h)
PREV = dict(o=60_814.0, h=60_950.0, l=59_130.91, c=60_300.2)  # bear, big lower wick
CUR  = dict(o=60_300.2, h=62_000.0, l=59_940.0,  c=61_670.4)  # bull engulf, small lower wick

OB_ZONE = (59_130.91, 61_670.38)
DROP_AREA = (59_130.91, 60_814.00)

# Top 15m FVG (closest to retest)
TOP_FVG = {"c1_ms": int(datetime(2026,6,5,22,45,tzinfo=MSK).timestamp()*1000),
           "c3_close_ms": int(datetime(2026,6,5,23,30,tzinfo=MSK).timestamp()*1000),
           "zone": (60_459.4, 60_713.6)}

# Wick analysis
prev_body_lo = min(PREV["o"], PREV["c"])  # = 60,300
cur_body_lo  = min(CUR["o"], CUR["c"])    # = 60,300
prev_wick = prev_body_lo - PREV["l"]      # = 1,169
cur_wick  = cur_body_lo - CUR["l"]        # = 360
wick_ratio = prev_wick / cur_wick         # = 3.25

# Trade params (T1a NEW: Entry = cur.low, NOT 0.8 deep in FVG)
fvg_lo, fvg_hi = TOP_FVG["zone"]
ENTRY = CUR["l"]                           # = cur.low = $59,940
SL = PREV["l"]                              # = prev.low = $59,131
R = ENTRY - SL                              # = $809
TPS = [(rr, ENTRY + rr * R) for rr in (1.0, 1.5, 2.0, 2.5, 3.0)]

# Events (recompute for new entry — find touch on 1m below)
BORN_MS = int(datetime(2026, 6, 6, 1, 0, tzinfo=MSK).timestamp() * 1000)

# Find touch + TP/SL for new entry on 1m
import csv
CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
INVAL_MS = int(datetime(2026, 6, 7, 11, 0, tzinfo=MSK).timestamp() * 1000)
touch_ms = None; sl_ms = None; tp1_ms = None
with CSV_1M.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if t < BORN_MS: continue
        if t > INVAL_MS + 7*24*3600*1000: break
        h, l = float(r[2]), float(r[3])
        if touch_ms is None and l <= ENTRY:
            touch_ms = t
        if touch_ms is not None:
            if tp1_ms is None and h >= TPS[0][1]:
                tp1_ms = t
            if sl_ms is None and l <= SL:
                sl_ms = t
            if tp1_ms and sl_ms: break
ENTRY_TOUCH_MS = touch_ms
TP1R_HIT_MS = tp1_ms
SL_HIT_MS = sl_ms
print(f"Entry={ENTRY:,.0f} touch={ENTRY_TOUCH_MS}  TP1R={TP1R_HIT_MS}  SL={SL_HIT_MS}")


def to_dt(ms): return datetime.fromtimestamp(int(ms)/1000, MSK)

BULL = "#01a648"; BEAR = "#131b1b"; DOJI = "#888"
RED = "#c0392b"; GREEN = "#27ae60"

# Load 15m bars
rows = load_1m()
bars = aggregate_all_tfs(rows)
b15 = [b for b in bars["15m"] if WIN_S <= b[0] < WIN_E]

# ─── Figure: 2 panels ─────────────────────────────────────
fig = plt.figure(figsize=(22, 11))
gs = fig.add_gridspec(1, 2, width_ratios=[3, 1], wspace=0.04)
ax = fig.add_subplot(gs[0])
ax_info = fig.add_subplot(gs[1])
ax_info.axis("off")
ax_info.set_xlim(0, 1); ax_info.set_ylim(0, 1)

# Title
fig.suptitle("T1a structure  —  LONG SWEPT n_FVG≥2 extreme=PREV  wick_ratio ≥ 2×",
             fontsize=15, fontweight="bold", y=0.97)

# Candles
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

# OB.zone
ax.add_patch(Rectangle((xs, OB_ZONE[0]), xe-xs, OB_ZONE[1]-OB_ZONE[0],
                       facecolor="#4a90e2", alpha=0.06, edgecolor="#4a90e2",
                       linewidth=1.2, linestyle=(0, (4, 4)), zorder=1))
ax.text(xs, OB_ZONE[1], "  OB-2h LONG zone", fontsize=10, color="#2169b3",
        fontweight="bold", va="bottom", ha="left", zorder=10)

# drop area
ax.add_patch(Rectangle((xs, DROP_AREA[0]), xe-xs, DROP_AREA[1]-DROP_AREA[0],
                       facecolor="#f5b041", alpha=0.20, edgecolor="#f5b041",
                       linewidth=1.0, linestyle=(0, (2, 3)), zorder=1.5))
ax.text(xe, DROP_AREA[1], "  drop area  ", fontsize=10, color="#b88420",
        fontweight="bold", va="bottom", ha="right", zorder=10)

# Top FVG
c1_dt = to_dt(TOP_FVG["c1_ms"])
c3_dt = to_dt(TOP_FVG["c3_close_ms"])
x1 = mdates.date2num(c1_dt); x2 = mdates.date2num(c3_dt)
ax.add_patch(Rectangle((x1, TOP_FVG["zone"][0]), x2-x1,
                        TOP_FVG["zone"][1]-TOP_FVG["zone"][0],
                        facecolor="#27ae60", alpha=0.30, edgecolor="#27ae60",
                        linewidth=1.0, zorder=3))
ax.text(x1, TOP_FVG["zone"][1] + 30, "TOP 15m FVG", fontsize=8.5,
        color="#185c34", fontweight="bold", zorder=10)

# Entry / SL / TP lines
ax.axhline(ENTRY, color=GREEN, linewidth=2.2, linestyle="-", zorder=6)
ax.axhline(SL, color=RED, linewidth=2.2, linestyle="-", zorder=6)
for rr, lvl in TPS:
    alpha = 0.7 if rr == 1.0 else 0.4
    lw = 1.6 if rr == 1.0 else 1.1
    ax.axhline(lvl, color="#2980b9", linewidth=lw, linestyle="--", alpha=alpha, zorder=5)

# Labels right side
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
# prev wick (LARGE, red)
prev_x = mdates.date2num(to_dt(OB_PREV_OPEN + 3600 * 1000))   # mid-prev
ax.annotate("", xy=(prev_x, PREV["l"]),
            xytext=(prev_x, prev_body_lo),
            arrowprops=dict(arrowstyle="<->", color=RED, lw=2.2),
            zorder=12)
ax.text(prev_x - 0.04, (PREV["l"] + prev_body_lo)/2,
        f"prev wick\n${prev_wick:,.0f}",
        ha="right", va="center", fontsize=10, color=RED, fontweight="bold",
        zorder=13)

# cur wick (SMALL, green)
cur_x = mdates.date2num(to_dt(OB_CUR_OPEN + 30 * 60 * 1000))   # bit after cur.open
ax.annotate("", xy=(cur_x, CUR["l"]),
            xytext=(cur_x, cur_body_lo),
            arrowprops=dict(arrowstyle="<->", color=GREEN, lw=2.2),
            zorder=12)
ax.text(cur_x + 0.04, (CUR["l"] + cur_body_lo)/2,
        f"cur wick\n${cur_wick:,.0f}",
        ha="left", va="center", fontsize=10, color=GREEN, fontweight="bold",
        zorder=13)

# Markers
ax.scatter([to_dt(BORN_MS)], [OB_ZONE[1] + 100], s=380, marker="*",
           color="gold", edgecolors="#7f5c00", linewidths=1.5, zorder=20)
ax.annotate(f"ob_vc BORN\n{to_dt(BORN_MS):%d-%m %H:%M}",
            xy=(to_dt(BORN_MS), OB_ZONE[1] + 100),
            xytext=(to_dt(BORN_MS), OB_ZONE[1] + 500),
            fontsize=9, fontweight="bold", color="#7f5c00", ha="center",
            arrowprops=dict(arrowstyle="->", color="#7f5c00", lw=1.2), zorder=21)

ax.scatter([to_dt(ENTRY_TOUCH_MS)], [ENTRY], s=320, marker="D",
           color=GREEN, edgecolors="#185c34", linewidths=1.5, zorder=20)
ax.annotate(f"ENTRY FILL\n{to_dt(ENTRY_TOUCH_MS):%d-%m %H:%M}",
            xy=(to_dt(ENTRY_TOUCH_MS), ENTRY),
            xytext=(to_dt(ENTRY_TOUCH_MS), ENTRY - 600),
            fontsize=9, fontweight="bold", color="#185c34", ha="center",
            arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.2), zorder=21)

ax.scatter([to_dt(TP1R_HIT_MS)], [TPS[0][1]], s=320, marker="s",
           color="#2980b9", edgecolors="#1a4f76", linewidths=1.5, zorder=20)
ax.annotate(f"TP 1.0R hit\n+1R WIN ✓",
            xy=(to_dt(TP1R_HIT_MS), TPS[0][1]),
            xytext=(to_dt(TP1R_HIT_MS), TPS[0][1] + 600),
            fontsize=9, fontweight="bold", color="#1a4f76", ha="center",
            arrowprops=dict(arrowstyle="->", color="#2980b9", lw=1.2), zorder=21)

# OB pair boundaries
for ms, lbl in [(OB_PREV_OPEN, "prev opens 21:00"),
                 (OB_CUR_OPEN, "cur opens 23:00"),
                 (OB_CUR_CLOSE, "cur closes 01:00")]:
    dt = to_dt(ms)
    ax.axvline(dt, color="#7f8c8d", linewidth=0.6, linestyle=":", zorder=2)

ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m %H:%M", tz=MSK))
ax.grid(False)
ax.yaxis.tick_right()
ax.yaxis.set_label_position("right")


# ─── Right info panel ────────────────────────────────────
def info_text(y, text, **kw):
    ax_info.text(0.5, y, text, ha="center", va="top", **kw)

# T1a badge
info_text(0.98, "T1a", fontsize=28, fontweight="bold", color="white",
          bbox=dict(facecolor=GREEN, edgecolor=GREEN, boxstyle="round,pad=0.4"))

info_text(0.88,
          "LONG  •  SWEPT  •  n_FVG ≥ 2\n"
          "extreme = PREV  •  wick ≥ 2×",
          fontsize=11.5, fontweight="bold", color="#222")

# Rules box (NEW: Entry = cur.low)
rules_text = (
    "📋 Правила T1a (новые)\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "Entry  =  cur.low\n"
    "       (= drop area ABOVE extreme,\n"
    "        ближе чем 0.8 deep FVG)\n\n"
    "SL     =  prev.low\n"
    "       =  extreme low (= drop_area_lo)\n\n"
    "R      =  cur.low − prev.low\n"
    "       (компактный R)\n\n"
    "TP1R   =  Entry + 1R  (fixed exit)\n"
)
ax_info.text(0.05, 0.78, rules_text, ha="left", va="top", fontsize=10,
             family="monospace", color="#222",
             bbox=dict(facecolor="#f0f8ff", edgecolor="#4a90e2",
                       boxstyle="round,pad=0.5", linewidth=1.5))

# Numbers for our case
tp1r = TPS[0][1]
nums_text = (
    f"📐 Этот сетап (06-06 01:00 МСК)\n"
    f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    f"prev.low      =  ${PREV['l']:,.0f}\n"
    f"cur.low       =  ${CUR['l']:,.0f}  ← Entry\n"
    f"extreme       =  PREV ✓\n\n"
    f"prev wick     =  ${prev_wick:,.0f}\n"
    f"cur wick      =  ${cur_wick:,.0f}\n"
    f"ratio         =  {wick_ratio:.2f}×  ≥ 2 ✓\n\n"
    f"Top 15m FVG   =  [{fvg_lo:,.0f} ; {fvg_hi:,.0f}]\n"
    f"  (не используем для entry)\n\n"
    f"Entry ${ENTRY:,.0f}  •  SL ${SL:,.0f}\n"
    f"R = ${R:,.0f}  •  TP1R ${tp1r:,.0f}\n\n"
    f"Outcome:  ✅  WIN +1R"
)
ax_info.text(0.05, 0.40, nums_text, ha="left", va="top", fontsize=9.5,
             family="monospace", color="#222",
             bbox=dict(facecolor="#eafaf1", edgecolor=GREEN,
                       boxstyle="round,pad=0.5", linewidth=1.5))

# T1a aggregate stats (под старое правило — c новым правилом нужен пересчёт TBM)
stats_text = (
    "📊 T1a stats (старое правило)\n"
    "─────────────────\n"
    "N = 178  •  touch 96.6%\n"
    "WR @ TP1R = 52.3%\n"
    "EV = +0.047R / trade\n"
    "Σ = +8R за 6y\n"
    "\n"
    "⚠ Новое правило (cur.low entry)\n"
    "    требует re-TBM прогон"
)
ax_info.text(0.05, 0.08, stats_text, ha="left", va="top", fontsize=9,
             family="monospace", color="#444",
             bbox=dict(facecolor="#fef9e7", edgecolor="#f1c40f",
                       boxstyle="round,pad=0.4", linewidth=1.2))


plt.subplots_adjust(left=0.025, right=0.985, top=0.94, bottom=0.06)
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/ob_vc_2h_T1a_structure.png"
plt.savefig(out, dpi=140)
print(f"Saved: {out}")
