"""Эффективная и проработанная VWAP — визуализация.

Показывает на одном чарте всё, что делает VWAP «хорошей» (по нашему сегодняшнему
анализу):
1. Pivot — Williams N=2 D-фрактал, источник по Правилу 6 (2026-01-28 FH @ 90600)
2. Anchor — оптимум argmax composite (2026-01-31 17:00 МСК = 14:00 UTC)
3. 48h calibration band — окно где линия «определяется»
4. Touch markers per 6h bar — ● зелёный = reaction (close на той же стороне),
   ✗ красный = break (close flip)
5. Per-TF score table — score = reactions/(reactions+breaks), composite weighted
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from indicators.vwap_effectiveness import effectiveness_per_tf, composite_effectiveness

MSK = timezone(timedelta(hours=3))
UTC = timezone.utc
MS = 60_000
CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts"; OUT.mkdir(parents=True, exist_ok=True)

# ── Параметры ────────────────────────────────────────────────────
PIVOT_DATE = "2026-01-28"           # Williams N=2 FH @ 90600
ANCHOR_DT = datetime(2026, 1, 31, 14, 0, tzinfo=UTC)   # 17:00 МСК
ANCHOR_TS = int(ANCHOR_DT.timestamp() * 1000)
END_DT = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
END_TS = int(END_DT.timestamp() * 1000)
DISPLAY_TF_MIN = 360                 # 6h candles
WINDOW_START = datetime(2026, 1, 26, tzinfo=UTC)
WINDOW_START_TS = int(WINDOW_START.timestamp() * 1000)
H48_TS = ANCHOR_TS + 48*3600*1000

CASCADE_TFS = [('1h', 60), ('2h', 120), ('4h', 240), ('6h', 360), ('8h', 480), ('12h', 720)]

# ── Стили ────────────────────────────────────────────────────────
BULL = '#01a648'; BEAR = '#131b1b'; DOJI = '#888'
VWAP_COL = '#5d3fd3'                # фиолетовая линия VWAP
REACT_COL = '#01a648'               # зелёный — reaction
BREAK_COL = '#c62828'               # красный — break
CALIB_BAND = '#fff4b5'              # светло-жёлтая 48h полоса
PIVOT_COL = '#c62828'               # FH красный
ANCHOR_COL = '#5d3fd3'

# ── Загрузка 1m ──────────────────────────────────────────────────
import subprocess
FETCH = pathlib.Path.home() / "smc-lib/scripts/fetch_btc_1m_missing.py"
if FETCH.exists():
    print("Fetching 1m...")
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
print(f"  1m in window: {len(rows)}")

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
print(f"  6h bars: {len(b6h)}")

# ── VWAP по 1m от anchor → end ───────────────────────────────────
def vwap_at_each_1m(rows_1m, anchor_ts, end_ts):
    out = []   # (ts, vwap_now)
    cum_pv = 0.0; cum_v = 0.0
    for ts, o, h, l, c, v in rows_1m:
        if ts < anchor_ts: continue
        if ts > end_ts: break
        tp = (h + l + c) / 3.0
        cum_pv += tp * v
        cum_v  += v
        out.append((ts, cum_pv / cum_v if cum_v > 0 else None))
    return out

vwap_pts = vwap_at_each_1m(rows, ANCHOR_TS, END_TS)
print(f"  VWAP series points: {len(vwap_pts)}")

# fast lookup of vwap at any ts (binary search-friendly)
import bisect
vwap_ts = [p[0] for p in vwap_pts]
vwap_val = [p[1] for p in vwap_pts]

def vwap_at(t):
    i = bisect.bisect_right(vwap_ts, t) - 1
    if i < 0: return None
    return vwap_val[i]

# ── Классифицируем touches 6h баров для маркеров ─────────────────
touch_events = []   # (ts, vwap_at_close, kind)  kind ∈ {'reaction','break'}
prev_side = None
for ts, o, hi, lo, cl, _ in b6h:
    if ts < ANCHOR_TS: continue
    if ts > END_TS: break
    bar_close_ts = ts + DISPLAY_TF_MIN*MS - 1
    vw = vwap_at(bar_close_ts)
    if vw is None:
        prev_side = None; continue
    touched = (lo <= vw <= hi)
    side = 'above' if cl > vw else ('below' if cl < vw else None)
    if touched and side is not None and prev_side is not None:
        kind = 'reaction' if side == prev_side else 'break'
        touch_events.append((ts + DISPLAY_TF_MIN*MS//2, vw, kind))
    prev_side = side

reacts = [t for t in touch_events if t[2]=='reaction']
breaks = [t for t in touch_events if t[2]=='break']
print(f"  6h touches: {len(touch_events)}  (reactions={len(reacts)}, breaks={len(breaks)})")

# ── Cascade per-TF effectiveness для подписи ────────────────────
per_tf_results = []
for tf_name, tf_min in CASCADE_TFS:
    tf_ms = tf_min*MS
    # bars and aligned vwap-at-close
    bars_tf = []
    vw_at = []
    cur_bucket = None; cur=[0.0]*4; cur_v=0.0; prev_vwap=None
    cum_pv=0.0; cum_v=0.0
    for ts, o, h, l, c, v in rows:
        if ts < ANCHOR_TS: continue
        tp = (h + l + c)/3.0
        cum_pv += tp*v; cum_v += v
        vw_now = cum_pv/cum_v if cum_v>0 else None
        b = ts - (ts % tf_ms)
        if b != cur_bucket:
            if cur_bucket is not None:
                bars_tf.append(tuple(cur))
                vw_at.append(prev_vwap)
            cur_bucket = b
            cur = [o, h, l, c]
        else:
            cur[1] = max(cur[1], h); cur[2] = min(cur[2], l); cur[3] = c
        prev_vwap = vw_now
    if cur_bucket is not None:
        bars_tf.append(tuple(cur)); vw_at.append(prev_vwap)
    eff = effectiveness_per_tf(tf_name, bars_tf, vw_at)
    per_tf_results.append(eff)
comp = composite_effectiveness(ANCHOR_TS, per_tf_results)

# ── Plot ─────────────────────────────────────────────────────────
def to_dt(ms): return datetime.fromtimestamp(ms/1000, MSK)

fig, ax = plt.subplots(figsize=(24, 12))
bar_w = (DISPLAY_TF_MIN/60)/24 * 0.5

# 6h candles
for ts, o, h, l, c, v in b6h:
    x = mdates.date2num(to_dt(ts + DISPLAY_TF_MIN*MS//2))
    color = BULL if c > o else (BEAR if c < o else DOJI)
    ax.plot([x, x], [l, h], color=color, lw=0.9, alpha=0.7, zorder=2)
    ax.add_patch(plt.Rectangle((x - bar_w/2, min(o, c)), bar_w, abs(c - o) or (h-l)*0.001,
                               color=color, lw=0, zorder=3))

# 48h calibration band — vertical light yellow band
ax.axvspan(mdates.date2num(to_dt(ANCHOR_TS)), mdates.date2num(to_dt(H48_TS)),
           facecolor=CALIB_BAND, alpha=0.55, zorder=1,
           label='48h calibration window')

# VWAP line — sample every hour for plotting
sample_step = 60   # min between samples
sampled_x = []; sampled_y = []
last_ts = -1
for ts, vw in vwap_pts:
    if vw is None: continue
    if ts - last_ts < sample_step*60*1000: continue
    last_ts = ts
    sampled_x.append(mdates.date2num(to_dt(ts)))
    sampled_y.append(vw)
ax.plot(sampled_x, sampled_y, color=VWAP_COL, lw=2.5, alpha=0.95, zorder=5,
        label=f'Anchored VWAP (anchor: {to_dt(ANCHOR_TS).strftime("%Y-%m-%d %H:%M МСК")})')

# Touch markers
if reacts:
    xs = [mdates.date2num(to_dt(t[0])) for t in reacts]
    ys = [t[1] for t in reacts]
    ax.scatter(xs, ys, s=70, color=REACT_COL, marker='o', edgecolor='black', lw=0.5,
               zorder=7, label=f'reaction ({len(reacts)})')
if breaks:
    xs = [mdates.date2num(to_dt(t[0])) for t in breaks]
    ys = [t[1] for t in breaks]
    ax.scatter(xs, ys, s=80, color=BREAK_COL, marker='X', edgecolor='black', lw=0.5,
               zorder=7, label=f'break ({len(breaks)})')

# Pivot marker — Williams N=2 FH @ 2026-01-28
pivot_ts = int(datetime(2026, 1, 28, 0, 0, tzinfo=UTC).timestamp()*1000) + 12*3600*1000   # mid-day
pivot_level = 90600
ax.scatter([mdates.date2num(to_dt(pivot_ts))], [pivot_level],
           marker='v', s=240, color=PIVOT_COL, edgecolor='black', lw=1.2, zorder=8)
ax.annotate(f"Pivot D-fractal\nFH 2026-01-28\n@ 90600",
            xy=(mdates.date2num(to_dt(pivot_ts)), pivot_level),
            xytext=(20, 25), textcoords='offset points', fontsize=11,
            color=PIVOT_COL, fontweight='bold',
            arrowprops=dict(arrowstyle='->', color=PIVOT_COL, lw=1.2))

# Anchor marker
anchor_vw_init = vwap_pts[0][1] if vwap_pts else None
if anchor_vw_init is not None:
    ax.scatter([mdates.date2num(to_dt(ANCHOR_TS))], [anchor_vw_init],
               marker='*', s=380, color=ANCHOR_COL, edgecolor='black', lw=1.2, zorder=8)
    ax.annotate(f"Anchor\n2026-01-31 17:00 МСК\n(i+3 от pivot, NY-open hours)",
                xy=(mdates.date2num(to_dt(ANCHOR_TS)), anchor_vw_init),
                xytext=(20, -55), textcoords='offset points', fontsize=11,
                color=ANCHOR_COL, fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=ANCHOR_COL, lw=1.2))

# Per-TF score box
score_lines = []
score_lines.append(f"composite = {comp.composite:.4f}   total_int = {comp.total_interactions}")
score_lines.append("")
score_lines.append(f"{'TF':<4} {'int':>5} {'react':>6} {'break':>6} {'score':>7}")
for p in per_tf_results:
    score_lines.append(f"{p.tf:<4} {p.interactions:>5} {p.reactions:>6} {p.breaks:>6} {p.score:>7.3f}")
score_text = "\n".join(score_lines)
ax.text(0.985, 0.98, score_text, transform=ax.transAxes, fontsize=10,
        verticalalignment='top', horizontalalignment='right', fontfamily='monospace',
        bbox=dict(boxstyle='round,pad=0.6', facecolor='#fafafa', edgecolor='#555', alpha=0.95))

# Axes/legend
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d', tz=MSK))
ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=20))
fig.autofmt_xdate()
ax.grid(True, color='#dddddd', lw=0.5, alpha=0.6)
ax.set_xlim(mdates.date2num(to_dt(WINDOW_START_TS)), mdates.date2num(to_dt(END_TS)))
all_p = [b[2] for b in b6h] + [b[3] for b in b6h]
ax.set_ylim(min(all_p)*0.985, max(all_p)*1.015)

ax.legend(loc='lower left', fontsize=11, framealpha=0.95)
ax.set_ylabel("BTCUSDT (USDT)", fontsize=12)
title = (f"Эффективная и проработанная VWAP — BTCUSDT 6h display\n"
         f"Pivot: Williams N=2 D-fractal 2026-01-28 FH @ 90600  |  "
         f"Anchor: 2026-01-31 17:00 МСК (i+3, NY-open hours, argmax composite внутри окна 30-01 → 02-01)\n"
         f"6h touches: reactions={len(reacts)}, breaks={len(breaks)}  |  "
         f"4.5 месяца жизни линии (anchor → 2026-06-13)")
ax.set_title(title, fontsize=11, loc='left')

stamp = datetime.now(MSK).strftime('%Y%m%d_%H%M')
out_path = OUT / f"effective_vwap_{stamp}.png"
plt.tight_layout()
plt.savefig(out_path, dpi=140)
print(f"\nSaved: {out_path}")
