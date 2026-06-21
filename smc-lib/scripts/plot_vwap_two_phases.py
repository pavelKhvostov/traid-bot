"""VWAP: две фазы жизни линии.

Phase 1 — «Эффективная» (anchor → 2026-03-03): цена приходит к линии и
чисто отскакивает. Мало касаний, каждое — clean reaction.

Phase 2 — «Проработанная» (2026-03-03 → now): череда реакций и пробоев.
Цена «живёт» вокруг линии. Линия накапливает track record.
"""
from __future__ import annotations
import csv, pathlib, sys, subprocess, bisect
from datetime import datetime, timezone, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

MSK = timezone(timedelta(hours=3))
UTC = timezone.utc
MS = 60_000
CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts"; OUT.mkdir(parents=True, exist_ok=True)

PIVOT_DATE = "2026-01-28"
ANCHOR_DT = datetime(2026, 1, 31, 14, 0, tzinfo=UTC)   # 17:00 МСК
ANCHOR_TS = int(ANCHOR_DT.timestamp() * 1000)
PHASE_BORDER_DT = datetime(2026, 3, 3, 0, 0, tzinfo=UTC)
PHASE_BORDER_TS = int(PHASE_BORDER_DT.timestamp() * 1000)
END_DT = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
END_TS = int(END_DT.timestamp() * 1000)
DISPLAY_TF_MIN = 360
WINDOW_START = datetime(2026, 1, 26, tzinfo=UTC)
WINDOW_START_TS = int(WINDOW_START.timestamp() * 1000)
H48_TS = ANCHOR_TS + 48*3600*1000

BULL = '#01a648'; BEAR = '#131b1b'; DOJI = '#888'
VWAP_COL = '#5d3fd3'
REACT_COL = '#01a648'
BREAK_COL = '#c62828'
CALIB_BAND = '#fff4b5'
PHASE1_BG = '#e3f2fd'     # светло-голубой — эффективная фаза
PHASE2_BG = '#ffe8d6'     # светло-оранжевый — проработанная фаза
PIVOT_COL = '#c62828'
ANCHOR_COL = '#5d3fd3'

# ── Загрузка ─────────────────────────────────────────────────────
FETCH = pathlib.Path.home() / "smc-lib/scripts/fetch_btc_1m_missing.py"
if FETCH.exists():
    subprocess.run([sys.executable, str(FETCH)], capture_output=True, text=True, timeout=120)

print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]),
                     float(r[3]), float(r[4]), float(r[5])))
rows = [r for r in rows if WINDOW_START_TS <= r[0] <= END_TS]

def agg(d, tf_ms):
    out=[]; cb=None; o=h=l=c=0.0; v=0.0
    for ts,oo,hh,ll,cc,vv in d:
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c,v = oo,hh,ll,cc,vv
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v += vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out

b6h = agg(rows, DISPLAY_TF_MIN*MS)

# ── VWAP ─────────────────────────────────────────────────────────
vwap_pts = []
cum_pv = 0.0; cum_v = 0.0
for ts, o, h, l, c, v in rows:
    if ts < ANCHOR_TS: continue
    if ts > END_TS: break
    tp = (h + l + c) / 3.0
    cum_pv += tp * v
    cum_v += v
    if cum_v > 0:
        vwap_pts.append((ts, cum_pv / cum_v))

vwap_ts = [p[0] for p in vwap_pts]
vwap_val = [p[1] for p in vwap_pts]
def vwap_at(t):
    i = bisect.bisect_right(vwap_ts, t) - 1
    return vwap_val[i] if i >= 0 else None

# ── Классификация touches по фазам ───────────────────────────────
touches_p1 = {'reaction': [], 'break': []}
touches_p2 = {'reaction': [], 'break': []}
prev_side = None
for ts, o, hi, lo, cl, _ in b6h:
    if ts < ANCHOR_TS: continue
    if ts > END_TS: break
    bar_close_ts = ts + DISPLAY_TF_MIN*MS - 1
    vw = vwap_at(bar_close_ts)
    if vw is None: prev_side = None; continue
    touched = (lo <= vw <= hi)
    side = 'above' if cl > vw else ('below' if cl < vw else None)
    if touched and side is not None and prev_side is not None:
        kind = 'reaction' if side == prev_side else 'break'
        bucket = touches_p1 if ts < PHASE_BORDER_TS else touches_p2
        bucket[kind].append((ts + DISPLAY_TF_MIN*MS//2, vw))
    prev_side = side

n_p1_r = len(touches_p1['reaction']); n_p1_b = len(touches_p1['break'])
n_p2_r = len(touches_p2['reaction']); n_p2_b = len(touches_p2['break'])
print(f"  Phase 1 (anchor→03-03): reactions={n_p1_r}, breaks={n_p1_b}")
print(f"  Phase 2 (03-03→now):    reactions={n_p2_r}, breaks={n_p2_b}")

# ── Plot ─────────────────────────────────────────────────────────
def to_dt(ms): return datetime.fromtimestamp(ms/1000, MSK)

fig, ax = plt.subplots(figsize=(24, 12))
bar_w = (DISPLAY_TF_MIN/60)/24 * 0.5

# Phase backgrounds — light tints across full Y range
ax.axvspan(mdates.date2num(to_dt(ANCHOR_TS)),
           mdates.date2num(to_dt(PHASE_BORDER_TS)),
           facecolor=PHASE1_BG, alpha=0.45, zorder=0)
ax.axvspan(mdates.date2num(to_dt(PHASE_BORDER_TS)),
           mdates.date2num(to_dt(END_TS)),
           facecolor=PHASE2_BG, alpha=0.35, zorder=0)

# 48h calibration band — на фоне Phase 1
ax.axvspan(mdates.date2num(to_dt(ANCHOR_TS)), mdates.date2num(to_dt(H48_TS)),
           facecolor=CALIB_BAND, alpha=0.65, zorder=1)

# 6h candles
for ts, o, h, l, c, v in b6h:
    x = mdates.date2num(to_dt(ts + DISPLAY_TF_MIN*MS//2))
    color = BULL if c > o else (BEAR if c < o else DOJI)
    ax.plot([x, x], [l, h], color=color, lw=0.9, alpha=0.75, zorder=2)
    ax.add_patch(plt.Rectangle((x - bar_w/2, min(o, c)), bar_w, abs(c - o) or (h-l)*0.001,
                               color=color, lw=0, zorder=3))

# Phase border vertical
phase_x = mdates.date2num(to_dt(PHASE_BORDER_TS))
ax.axvline(phase_x, color='#888', lw=1.8, linestyle='--', alpha=0.85, zorder=4)

# VWAP line
sample_step_ms = 60*60*1000
sx = []; sy = []; last = -1
for ts, vw in vwap_pts:
    if ts - last < sample_step_ms: continue
    last = ts
    sx.append(mdates.date2num(to_dt(ts))); sy.append(vw)
ax.plot(sx, sy, color=VWAP_COL, lw=2.7, alpha=0.96, zorder=5,
        label=f'Anchored VWAP (anchor: {to_dt(ANCHOR_TS).strftime("%Y-%m-%d %H:%M МСК")})')

# Touches per phase
def scatter_touches(touches_dict, marker, color, alpha, size, label_prefix, phase_name):
    pts = touches_dict[marker]
    if not pts: return
    xs = [mdates.date2num(to_dt(t[0])) for t in pts]
    ys = [t[1] for t in pts]
    if marker == 'reaction':
        ax.scatter(xs, ys, s=size, color=color, marker='o', edgecolor='black', lw=0.6,
                   alpha=alpha, zorder=7, label=f'{label_prefix} reaction ({len(pts)})')
    else:
        ax.scatter(xs, ys, s=size+10, color=color, marker='X', edgecolor='black', lw=0.6,
                   alpha=alpha, zorder=7, label=f'{label_prefix} break ({len(pts)})')

scatter_touches(touches_p1, 'reaction', REACT_COL, 0.95, 90, "Ph1", "Phase 1")
scatter_touches(touches_p1, 'break', BREAK_COL, 0.95, 90, "Ph1", "Phase 1")
scatter_touches(touches_p2, 'reaction', REACT_COL, 0.75, 65, "Ph2", "Phase 2")
scatter_touches(touches_p2, 'break', BREAK_COL, 0.75, 65, "Ph2", "Phase 2")

# Pivot marker
pivot_ts = int(datetime(2026, 1, 28, 12, 0, tzinfo=UTC).timestamp()*1000)
ax.scatter([mdates.date2num(to_dt(pivot_ts))], [90600],
           marker='v', s=240, color=PIVOT_COL, edgecolor='black', lw=1.2, zorder=8)
ax.annotate(f"Pivot D-fractal\n2026-01-28 FH @ 90600",
            xy=(mdates.date2num(to_dt(pivot_ts)), 90600),
            xytext=(25, 8), textcoords='offset points', fontsize=10,
            color=PIVOT_COL, fontweight='bold',
            arrowprops=dict(arrowstyle='->', color=PIVOT_COL, lw=1.2))

# Anchor marker
anchor_vw_init = vwap_pts[0][1] if vwap_pts else None
if anchor_vw_init is not None:
    ax.scatter([mdates.date2num(to_dt(ANCHOR_TS))], [anchor_vw_init],
               marker='*', s=380, color=ANCHOR_COL, edgecolor='black', lw=1.2, zorder=8)

# Phase labels at top
ymin, ymax = min(b[3] for b in b6h)*0.985, max(b[2] for b in b6h)*1.015
label_y = ymax - (ymax-ymin)*0.04
mid_p1 = (ANCHOR_TS + PHASE_BORDER_TS) // 2
mid_p2 = (PHASE_BORDER_TS + END_TS) // 2

ax.text(mdates.date2num(to_dt(mid_p1)), label_y,
        f"PHASE 1 — ЭФФЕКТИВНАЯ\nцена отталкивается чисто\nреакций={n_p1_r}  пробоев={n_p1_b}",
        ha='center', va='top', fontsize=12, fontweight='bold',
        color='#1565c0',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor='#1565c0', alpha=0.85))

ax.text(mdates.date2num(to_dt(mid_p2)), label_y,
        f"PHASE 2 — ПРОРАБОТАННАЯ\nчереда реакций и пробоев, line «живёт»\nреакций={n_p2_r}  пробоев={n_p2_b}",
        ha='center', va='top', fontsize=12, fontweight='bold',
        color='#d84315',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor='#d84315', alpha=0.85))

# Phase border label
ax.text(phase_x, ymin + (ymax-ymin)*0.02, "2026-03-03\nграница фаз",
        ha='center', va='bottom', fontsize=9, color='#555', fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='#888', alpha=0.85))

# Axes/legend
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d', tz=MSK))
ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=20))
fig.autofmt_xdate()
ax.grid(True, color='#dddddd', lw=0.5, alpha=0.5)
ax.set_xlim(mdates.date2num(to_dt(WINDOW_START_TS)), mdates.date2num(to_dt(END_TS)))
ax.set_ylim(ymin, ymax)

ax.legend(loc='lower left', fontsize=9, framealpha=0.95, ncol=2)
ax.set_ylabel("BTCUSDT (USDT)", fontsize=12)
title = (f"VWAP — две фазы жизни линии (anchor 2026-01-31 17:00 МСК от pivot D-fractal 2026-01-28 FH 90600)\n"
         f"Фаза 1 (эффективная, anchor→03-03): {n_p1_r}R / {n_p1_b}B = clean repulsion mode\n"
         f"Фаза 2 (проработанная, 03-03→now): {n_p2_r}R / {n_p2_b}B = линия «живёт», накапливает track record")
ax.set_title(title, fontsize=11, loc='left')

stamp = datetime.now(MSK).strftime('%Y%m%d_%H%M')
out_path = OUT / f"vwap_two_phases_{stamp}.png"
plt.tight_layout()
plt.savefig(out_path, dpi=140)
print(f"\nSaved: {out_path}")
