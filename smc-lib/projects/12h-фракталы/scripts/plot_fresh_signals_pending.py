"""Свежие сигналы за последние 30 дней — БЕЗ ожидания confirmation.

Показываем:
    1. Basket events (basket fires) — solid filled = confirmed Williams n=2,
       hollow = pending (fresh, ещё не успел подтвердиться)
    2. A4 candidates без B-fires — маленькие серые маркеры (пока не нашлась confluence)
    3. Tier labels + n_confluent stars

Period: последние 30 дней до текущего момента.
Canonical format (HMA-78/200 12h+D LIVE, VWAPs, no grid/spines).
"""
from __future__ import annotations
import csv, math, bisect, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import MultipleLocator

sys.path.insert(0, str(Path.home()/"smc-lib"))
from indicators.trend_line_asvk import wma
from indicators.vwap_effectiveness import effectiveness_per_tf, composite_effectiveness

BULL = '#01a648'; BEAR = '#131b1b'; DOJI = '#888'
CURRENT_PRICE = '#c62828'
FH_COLOR = '#c62828'; FL_COLOR = '#2e7d32'
PENDING_COLOR = '#ff9800'   # ORANGE for pending/fresh
BAR_GAP_FRACTION = 0.5
BAR_WIDTH_FRACTION = 1.0 - BAR_GAP_FRACTION
BAR_LW = 1.1
MSK = timezone(timedelta(hours=3))
TF_MIN = 720
TF_MS = TF_MIN * 60_000
TFD_MS = 24*3600_000

# ─── Window: last 30 days ────────────────────────────────────
END = pd.Timestamp.now(tz="UTC")
START = END - pd.Timedelta(days=30)
START_MS = int(START.timestamp()*1000)
END_MS = int(END.timestamp()*1000)

# ─── Load Basket + A4 baseline ──────────────────────────────
combined = pd.read_parquet(Path.home()/"Desktop/12h-fractal-new-out/D_stage4_combined.parquet")
combined["dt"] = pd.to_datetime(combined["ts_ms"], unit="ms", utc=True)
combined["direction_canon"] = combined["direction"].map({"short":"high","long":"low"})
basket_recent = combined[combined["dt"] >= START].copy()
basket_keys = set(zip(basket_recent["ts_ms"], basket_recent["direction"]))
print(f"Basket events in window: {len(basket_recent)}")

baseline = pd.read_parquet(Path.home()/"Desktop/pred12h_baseline_v2.parquet")
baseline["dt"] = pd.to_datetime(baseline["pivot_open_ts_ms"], unit="ms", utc=True)
baseline_recent = baseline[baseline["dt"] >= START].copy()
baseline_recent["direction_zone"] = baseline_recent["direction"].map({"high":"short","low":"long"})
# Pure A4 (no basket fire)
def in_basket(row):
    return (int(row["pivot_open_ts_ms"]), row["direction_zone"]) in basket_keys
baseline_recent["in_basket"] = baseline_recent.apply(in_basket, axis=1)
pure_a4 = baseline_recent[~baseline_recent["in_basket"]].copy()
print(f"Pure A4 candidates (без B-fires) in window: {len(pure_a4)}")

# ─── Load 1m ─────────────────────────────────────────────────
CSV_PATH = Path.home()/"traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
EXT_START_MS = int(pd.Timestamp("2018-01-01", tz="UTC").timestamp()*1000)
rows_ext = []
with CSV_PATH.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        ts = int(datetime.fromisoformat(r[0]).timestamp()*1000)
        if ts<EXT_START_MS: continue
        if ts>END_MS: break
        rows_ext.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
print(f"1m bars: {len(rows_ext):,}")

def agg(rs, tf_ms):
    out=[]; cb=None; o=h=l=c=v=0.0
    for ts,oo,hh,ll,cc,vv in rs:
        b = ts - (ts % tf_ms)
        if b!=cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c,v=oo,hh,ll,cc,vv
        else: h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out

bars12_ext = agg(rows_ext, TF_MS)
barsD_ext = agg(rows_ext, TFD_MS)
last_close = rows_ext[-1][4]; last_ts = rows_ext[-1][0]
bars12 = [b for b in bars12_ext if b[0] >= START_MS]
print(f"12h в окне: {len(bars12)}, last close: {last_close:,.0f}")

# HMA
def hma(values, n):
    half = wma(values, n//2); full = wma(values, n)
    diff = [(2*half[i]-full[i]) if (half[i] is not None and full[i] is not None) else 0.0
            for i in range(len(values))]
    return wma(diff, int(round(math.sqrt(n))))
hma_12_78  = hma([b[4] for b in bars12_ext], 78)
hma_12_200 = hma([b[4] for b in bars12_ext], 200)
hma_D_78   = hma([b[4] for b in barsD_ext], 78)
hma_D_200  = hma([b[4] for b in barsD_ext], 200)
def live_shift(arr): return [None] + list(arr[:-1])
hma_12_78_live  = live_shift(hma_12_78)
hma_12_200_live = live_shift(hma_12_200)
hma_D_78_live   = live_shift(hma_D_78)
hma_D_200_live  = live_shift(hma_D_200)

def htf_smooth(ltf_ts_list, htf_bars, htf_values, htf_tf_ms):
    closed_ends = [b[0] + htf_tf_ms for b in htf_bars]
    out = []
    for ts in ltf_ts_list:
        lo, hi = 0, len(closed_ends)
        while lo < hi:
            m = (lo+hi)//2
            if closed_ends[m] <= ts: lo = m+1
            else: hi = m
        k = lo - 1
        if k < 0 or htf_values[k] is None: out.append(None); continue
        v_k = htf_values[k]
        if k+1 >= len(htf_values) or htf_values[k+1] is None:
            out.append(v_k); continue
        v_next = htf_values[k+1]
        t0, t1 = closed_ends[k], closed_ends[k+1]
        if t1 <= t0: out.append(v_k); continue
        alpha = max(0.0, min(1.0, (ts - t0) / (t1 - t0)))
        out.append(v_k + alpha * (v_next - v_k))
    return out

t12h_win = [b[0] for b in bars12]
hma78_12  = htf_smooth(t12h_win, bars12_ext, hma_12_78_live, TF_MS)
hma200_12 = htf_smooth(t12h_win, bars12_ext, hma_12_200_live, TF_MS)
hma78_D   = htf_smooth(t12h_win, barsD_ext,  hma_D_78_live,   TFD_MS)
hma200_D  = htf_smooth(t12h_win, barsD_ext,  hma_D_200_live,  TFD_MS)

# Figure
fig, ax = plt.subplots(figsize=(24, 12))
def to_dt(ms): return datetime.fromtimestamp(ms/1000, MSK)
bar_w = (TF_MIN/60)/24 * BAR_WIDTH_FRACTION

for b in bars12:
    t = to_dt(b[0] + TF_MS//2)
    o,h,l,c = b[1],b[2],b[3],b[4]
    color_b = BULL if c>o else (BEAR if c<o else DOJI)
    ax.vlines(t, l, h, color=color_b, linewidth=BAR_LW, zorder=2)
    ax.add_patch(plt.Rectangle((mdates.date2num(t)-bar_w/2, min(o,c)),
                               bar_w, max(abs(o-c), 0.01),
                               facecolor=color_b, edgecolor=color_b,
                               linewidth=BAR_LW, zorder=2))

HMA78_COLOR  = '#4a90d9'; HMA200_COLOR = '#1a3f6f'
HMA_LW = 0.9
times_plot = [to_dt(ts) for ts in t12h_win]
def plot_hma(series, color, ls, lw=HMA_LW):
    pts = [(t,v) for t,v in zip(times_plot, series) if v is not None]
    if not pts: return
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, linewidth=lw, linestyle=ls, zorder=1)
plot_hma(hma78_12,  HMA78_COLOR,  '--')
plot_hma(hma200_12, HMA200_COLOR, '--')
plot_hma(hma78_D,   HMA78_COLOR,  '-')
plot_hma(hma200_D,  HMA200_COLOR, '-')

# VWAPs
print("Computing VWAPs...")
ts_1m_arr = np.array([r[0] for r in rows_ext], dtype=np.int64)
cl_1m_arr = np.array([r[4] for r in rows_ext])
vol_1m_arr = np.array([r[5] for r in rows_ext])
cum_pv = np.concatenate(([0.0], np.cumsum(cl_1m_arr * vol_1m_arr)))
cum_v = np.concatenate(([0.0], np.cumsum(vol_1m_arr)))
ts_1m_list = ts_1m_arr.tolist()
def idx_at(ms): return bisect.bisect_left(ts_1m_list, ms)
def vwap_at(anchor_ms, target_end_ms):
    a = idx_at(anchor_ms); e = idx_at(target_end_ms)
    if e <= a: return None
    pv = cum_pv[e] - cum_pv[a]; vol = cum_v[e] - cum_v[a]
    return pv/vol if vol > 0 else None

fh_all=[]; fl_all=[]
for i in range(2, len(barsD_ext)-2):
    h_i, l_i = barsD_ext[i][2], barsD_ext[i][3]
    if all(h_i > barsD_ext[i+j][2] for j in [-2,-1,1,2]):
        fh_all.append({'t':barsD_ext[i][0], 'price':h_i, 'pivot_close_ts':barsD_ext[i][0]+TFD_MS})
    if all(l_i < barsD_ext[i+j][3] for j in [-2,-1,1,2]):
        fl_all.append({'t':barsD_ext[i][0], 'price':l_i, 'pivot_close_ts':barsD_ext[i][0]+TFD_MS})
fractals = [(f, 'FH') for f in fh_all] + [(f, 'FL') for f in fl_all]
CASCADE_TFS = [60, 120, 240, 360, 480, 720]
cascade_bars = {tf: agg(rows_ext, tf*60_000) for tf in CASCADE_TFS}

def vwap_series_for_bars(anchor_ms, bars_list, tf_ms_local):
    a = idx_at(anchor_ms)
    res = []
    for b in bars_list:
        end_ms = b[0] + tf_ms_local
        e = idx_at(end_ms)
        if e <= a: res.append(None); continue
        pv = cum_pv[e] - cum_pv[a]; vol = cum_v[e] - cum_v[a]
        res.append(float(pv/vol) if vol > 0 else None)
    return res

scored = []
for f, side in fractals:
    anchor = f['pivot_close_ts']
    cur_v = vwap_at(anchor, last_ts)
    if cur_v is None: continue
    per_tf = []
    for tf_min in CASCADE_TFS:
        bars_tf = cascade_bars[tf_min]
        bars_after = [b for b in bars_tf if anchor <= b[0] <= END_MS]
        if len(bars_after) < 2:
            per_tf.append(effectiveness_per_tf(f"{tf_min}m", [], [])); continue
        vws = vwap_series_for_bars(anchor, bars_after, tf_min*60_000)
        ohlc = [(b[1],b[2],b[3],b[4]) for b in bars_after]
        per_tf.append(effectiveness_per_tf(f"{tf_min}m", ohlc, vws))
    eff = composite_effectiveness(anchor, per_tf)
    scored.append({'f':f,'composite':eff.composite,'interactions':eff.total_interactions,'cur':cur_v})

below = [s for s in scored if last_close - 8000 <= s['cur'] < last_close]
above = [s for s in scored if last_close < s['cur'] <= last_close + 8000]
def pick_diverse(cands, n, min_dist_pct=1.0, key='composite'):
    cands = sorted(cands, key=lambda x: -x[key])
    picked=[]
    for c in cands:
        if len(picked)>=n: break
        if all(abs(c['cur']-p['cur'])/c['cur']*100 >= min_dist_pct for p in picked):
            picked.append(c)
    return picked
eff_below = pick_diverse(below, 2, 1.0, 'composite')
eff_above = pick_diverse(above, 2, 1.0, 'composite')
worked_below = pick_diverse(below, 1, 1.0, 'interactions')
worked_above = pick_diverse(above, 1, 1.0, 'interactions')

VWAP_BELOW = '#ff7f0e'; VWAP_ABOVE = '#c62828'; VWAP_WORKED = '#7e57c2'
def plot_vwap_line(item, color):
    f = item['f']
    vws = vwap_series_for_bars(f['pivot_close_ts'], bars12, TF_MS)
    pts = [(to_dt(b[0]), v) for b,v in zip(bars12, vws) if v is not None]
    if not pts: return
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, linewidth=0.9, alpha=0.85, zorder=1)
for s in eff_below: plot_vwap_line(s, VWAP_BELOW)
for s in eff_above: plot_vwap_line(s, VWAP_ABOVE)
for s in worked_below: plot_vwap_line(s, VWAP_WORKED)
for s in worked_above: plot_vwap_line(s, VWAP_WORKED)

# ─── Markers ──────────────────────────────────────────────────
MARKER_SIZE = 220
bars12_map = {b[0]: b for b in bars12}

# Pure A4 candidates (no B fires) — small grey markers
for _, r in pure_a4.iterrows():
    ts = int(r["pivot_open_ts_ms"])
    bar = bars12_map.get(ts)
    if bar is None: continue
    t_center = to_dt(bar[0] + TF_MS//2)
    high_p = bar[2]; low_p = bar[3]
    if r["direction"] == "high":
        ax.scatter(t_center, high_p*1.004, marker="v", s=60,
                   facecolor="white", edgecolor="#999", linewidth=1.0, zorder=7)
    else:
        ax.scatter(t_center, low_p*0.996, marker="^", s=60,
                   facecolor="white", edgecolor="#999", linewidth=1.0, zorder=7)

# Basket events — big markers with tier annotation
for _, r in basket_recent.iterrows():
    ts = int(r["ts_ms"])
    bar = bars12_map.get(ts)
    if bar is None: continue
    t_center = to_dt(bar[0] + TF_MS//2)
    high_p = bar[2]; low_p = bar[3]
    confirmed = bool(r["confirmed"])
    nC = int(r["n_confluent"]) if not pd.isna(r["n_confluent"]) else 0
    tier = r["tier"]
    stars = "★" * nC

    if r["direction"] == "short":
        col = FH_COLOR
        fc = col if confirmed else "white"
        ax.scatter(t_center, high_p*1.005, marker="v", s=MARKER_SIZE,
                   facecolor=fc, edgecolor=col, linewidth=2.0, zorder=8)
        label = f"{stars}\n{tier[0]}"
        ax.annotate(label, (t_center, high_p*1.005), xytext=(0, 18),
                    textcoords="offset points", ha='center', va='bottom',
                    fontsize=10, color=col, fontweight='bold', zorder=9)
        if not confirmed:
            # PENDING badge
            ax.annotate("PENDING", (t_center, high_p*1.005), xytext=(0, 42),
                        textcoords="offset points", ha='center', va='bottom',
                        fontsize=8, color=PENDING_COLOR, fontweight='bold',
                        bbox=dict(facecolor='white', edgecolor=PENDING_COLOR, lw=1, pad=2),
                        zorder=10)
    else:
        col = FL_COLOR
        fc = col if confirmed else "white"
        ax.scatter(t_center, low_p*0.995, marker="^", s=MARKER_SIZE,
                   facecolor=fc, edgecolor=col, linewidth=2.0, zorder=8)
        label = f"{stars}\n{tier[0]}"
        ax.annotate(label, (t_center, low_p*0.995), xytext=(0, -18),
                    textcoords="offset points", ha='center', va='top',
                    fontsize=10, color=col, fontweight='bold', zorder=9)
        if not confirmed:
            ax.annotate("PENDING", (t_center, low_p*0.995), xytext=(0, -42),
                        textcoords="offset points", ha='center', va='top',
                        fontsize=8, color=PENDING_COLOR, fontweight='bold',
                        bbox=dict(facecolor='white', edgecolor=PENDING_COLOR, lw=1, pad=2),
                        zorder=10)

# Axes format
ax.yaxis.tick_right()
ax.yaxis.set_label_position('right')
ax.yaxis.set_major_locator(MultipleLocator(1000))

start_dt = to_dt(START_MS); today_dt = to_dt(END_MS)
last_monday = (today_dt - timedelta(days=today_dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
week_ticks = []; d = last_monday
while d >= start_dt:
    week_ticks.append(d); d -= timedelta(days=7)
week_ticks.reverse()
if today_dt.date() != last_monday.date():
    week_ticks.append(today_dt)
ax.set_xticks(week_ticks)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%d-%m', tz=MSK))
ax.grid(False)
ax.tick_params(axis='both', which='both', length=0)
for spine in ax.spines.values(): spine.set_visible(False)

ax.axhline(y=last_close, color=CURRENT_PRICE, linewidth=0.9, linestyle=':', alpha=1.0, zorder=3)
future_end = today_dt + timedelta(days=5)
ax.set_xlim(start_dt, future_end)
y_lo = min(b[3] for b in bars12) - 1500
y_hi = max(b[2] for b in bars12) + 1500
ax.set_ylim(y_lo, y_hi)

fig.canvas.draw()
existing = list(ax.get_yticks())
filtered = [t for t in existing if abs(t - last_close) > 500]
all_ticks = sorted(set(filtered + [last_close]))
ax.set_yticks(all_ticks)
labels = [f' {last_close:,.0f} ' if abs(t - last_close) < 0.5 else f'{int(t):,}' for t in all_ticks]
ax.set_yticklabels(labels)
for tl, t in zip(ax.get_yticklabels(), all_ticks):
    if abs(t - last_close) < 0.5:
        tl.set_color('white'); tl.set_weight('bold'); tl.set_fontsize(11)
        tl.set_bbox(dict(facecolor=CURRENT_PRICE, edgecolor=CURRENT_PRICE, pad=4))
for tl, td in zip(ax.get_xticklabels(), week_ticks):
    if td == today_dt:
        tl.set_color('white'); tl.set_weight('bold'); tl.set_fontsize(11)
        tl.set_bbox(dict(facecolor=CURRENT_PRICE, edgecolor=CURRENT_PRICE, pad=4))

# Title
n_basket = len(basket_recent)
n_conf = int(basket_recent["confirmed"].sum())
n_pending = n_basket - n_conf
n_a4_only = len(pure_a4)
fig.text(0.5, 0.97,
         f"BTC  |  12h  |  {today_dt.strftime('%d-%m-%Y')}  |  {today_dt.strftime('%H:%M')} MSK  "
         f"+   Свежие сигналы за 30 дней (без ожидания confirmation)  |  "
         f"Basket: {n_basket} ({n_conf} confirmed + {n_pending} PENDING)  |  "
         f"Pure A4 (без B-fires): {n_a4_only}",
         ha='center', va='top', fontsize=13, fontweight='bold')

# Legend
ax.text(0.005, 0.99,
        "▼ FH SHORT  |  ▲ FL LONG\n"
        "Заполнен = Williams n=2 confirmed\n"
        "Пустой = PENDING (свежий, ждём confirmation 24-36h)\n"
        "Серый маленький = A4 candidate без B-fires\n"
        "★ = n_confluent (B-блоков сработало)\n"
        "Буква = tier (P/S/Sd/W)",
        transform=ax.transAxes, ha="left", va="top", fontsize=9,
        bbox=dict(facecolor="white", edgecolor="#888", alpha=0.9, pad=6),
        zorder=10)

plt.subplots_adjust(left=0.02, right=0.96, top=0.94, bottom=0.06)
out = Path.home()/"Desktop/i-rdrb-charts/btc_12h_fresh_signals_30d.png"
plt.savefig(out, dpi=140)
print(f"\nSaved: {out}")

# ─── Print recent signals table ────────────────────────────────
print("\n" + "="*100)
print("СВЕЖИЕ СИГНАЛЫ (basket + pure A4) за последние 30 дней")
print("="*100)
recent = basket_recent.sort_values("ts_ms").copy()
recent["dt_msk"] = recent["dt"].dt.tz_convert(MSK)
print(f"\n{'Date (MSK)':<18} {'Side':<6} {'Tier':<10} {'n_C':>4} {'Conf?':>6}  Source")
for _, r in recent.iterrows():
    date_s = r["dt_msk"].strftime("%Y-%m-%d %H:%M")
    nC = int(r["n_confluent"]) if not pd.isna(r["n_confluent"]) else 0
    conf = "✓" if r["confirmed"] else "PENDING"
    print(f"  {date_s:<18} {r['direction']:<6} {r['tier']:<10} {nC:>4} {conf:>10}  Basket")

print("\nPure A4 candidates (no B-fires yet):")
pure_a4_sorted = pure_a4.sort_values("pivot_open_ts_ms")
for _, r in pure_a4_sorted.iterrows():
    dt_msk = r["dt"].tz_convert(MSK)
    date_s = dt_msk.strftime("%Y-%m-%d %H:%M")
    conf = "✓" if r["confirmed"] else "PENDING"
    print(f"  {date_s:<18} {r['direction_zone']:<6} {'—':<10} {'—':>4} {conf:>10}  A4 only")
