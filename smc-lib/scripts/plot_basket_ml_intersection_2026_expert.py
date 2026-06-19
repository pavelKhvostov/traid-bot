"""Expert chart format: basket ∩ Andrey ML за 2026 год.

Canon: chart_format.md (BULL/BEAR colors, right Y axis, Monday ticks).
Markers: ▼ красный (FH SHORT), ▲ зелёный (FL LONG) — filled/hollow по confirmation.
Tier через размер маркера.
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

# === Expert canon palette ===
BULL = '#01a648'
BEAR = '#131b1b'
DOJI = '#888'
CURRENT_PRICE = '#c62828'
FH_COLOR = '#c62828'      # short
FL_COLOR = '#2e7d32'      # long
BAR_GAP_FRACTION = 0.5
BAR_WIDTH_FRACTION = 1.0 - BAR_GAP_FRACTION
BAR_LW = 1.1

MSK = timezone(timedelta(hours=3))
MS = 60_000
MS_H = 60 * MS
TF_MIN = 720            # 12h base (events are 12h pivots → marker over its own candle)
TF_MS = TF_MIN * MS

# Load intersection data
df_m = pd.read_csv(Path.home()/"Desktop/basket_andrey_magnitude_full.csv")
df_m["dt"] = pd.to_datetime(df_m["dt"], utc=True)
df_m["key"] = df_m["ts"].astype(str)+"_"+df_m["direction"]

# Hybrid: оригинальный signals_caught + synthetic для свежих 22-05+
sig = pd.read_csv(Path.home()/"Desktop/etap_173_signals_hybrid.csv")
sig["time_utc"] = pd.to_datetime(sig["time_utc"], format="mixed", utc=True)
sig["ts_ms"] = sig["time_utc"].apply(lambda t: int(t.timestamp()*1000))
sig["dir_us"] = sig["side"].map({"SHORT":"high","LONG":"low"})
sig["key"] = sig["ts_ms"].astype(str)+"_"+sig["dir_us"]
sig_sub = sig[["key","p_main","tier"]]

df_join = df_m.merge(sig_sub, on="key", how="inner")

# Подсчёт количества fired C1-C9 на каждое событие
# C1-C7 из pred12h_baseline_c1c7.parquet
c1c7_full = pd.read_parquet(Path.home()/"Desktop/pred12h_baseline_c1c7.parquet")
c1c7_full["key"] = c1c7_full["pivot_open_ts_ms"].astype(str)+"_"+c1c7_full["direction"]
# C8 из c1c8 parquet
c1c8_full = pd.read_parquet(Path.home()/"Desktop/pred12h_basket_c1c8.parquet")
c1c8_full["key"] = c1c8_full["ts"].astype(str)+"_"+c1c8_full["direction"]
# C9 — recompute
df_f_all = pd.read_parquet(Path.home()/"Desktop/force_all_bars_per_tf.parquet")
TF_LIST_F = ["1h","2h","4h","6h","8h","12h","1d","2d","3d"]
df_f_all["buyer"] = sum(df_f_all[f"buyer_{t}"] for t in TF_LIST_F)
df_f_all["seller"] = sum(df_f_all[f"seller_{t}"] for t in TF_LIST_F)
df_f_all["net"] = df_f_all["buyer"] - df_f_all["seller"]
df_f_all["net_w2"] = df_f_all["net"].rolling(2).sum()
df_f_idx = df_f_all.set_index("open_ts_ms")

def count_C(row):
    ts = int(row["ts"]); dir_ = row["direction"]
    key = f"{ts}_{dir_}"
    n = 0
    # C1-C7
    cmatch = c1c7_full[c1c7_full["key"]==key]
    if len(cmatch):
        m = cmatch.iloc[0]
        for c in ["c1","c2","c3","c4","c5","c6","c7"]:
            if c in m and bool(m[c]): n+=1
    # C8
    c8match = c1c8_full[(c1c8_full["key"]==key) & (c1c8_full["c8"]==True)]
    if len(c8match): n += 1
    # C9
    if ts in df_f_idx.index:
        netv = df_f_idx.loc[ts, "net"]
        net_w2 = df_f_idx.loc[ts, "net_w2"]
        c9 = False
        if dir_=="low" and netv<=-1000: c9 = True
        if dir_=="high" and netv>=500: c9 = True
        if dir_=="low" and pd.notna(net_w2) and net_w2<=-2000: c9 = True
        if c9: n += 1
    return n

END = pd.Timestamp.now(tz="UTC")
START_WIN = END - pd.Timedelta(days=180)
df_2026 = df_join[(df_join["dt"]>=START_WIN) & (df_join["dt"]<=END)].copy()
df_2026["n_C"] = df_2026.apply(count_C, axis=1)
print(f"Intersection в окне последних 6 мес: {len(df_2026)}")
print(f"  n_C distribution: {df_2026['n_C'].value_counts().to_dict()}")

# Window: последние 6 месяцев (180 дней)
END = pd.Timestamp.now(tz="UTC")
START = END - pd.Timedelta(days=180)
START_MS = int(START.timestamp()*1000)
END_MS = int(END.timestamp()*1000)

# Load 1m
CSV_PATH = Path.home()/"traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
rows = []
with CSV_PATH.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        ts = int(datetime.fromisoformat(r[0]).timestamp()*1000)
        if ts<START_MS: continue
        if ts>END_MS: break
        rows.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))

# Aggregate 6h
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

bars12h = agg(rows, TF_MS)
last_close = rows[-1][4]
last_ts = rows[-1][0]
print(f"12h bars: {len(bars12h)}")

# === Загружаем расширенную историю для HMA-200 и VWAP (нужно >1100 дней) ===
print("Loading extended history for HMA-200 + VWAP anchors (1100 days)...")
EXT_START_MS = int(pd.Timestamp("2018-01-01", tz="UTC").timestamp()*1000)  # 2018+ macro anchor
rows_ext = []
with CSV_PATH.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        ts = int(datetime.fromisoformat(r[0]).timestamp()*1000)
        if ts<EXT_START_MS: continue
        if ts>END_MS: break
        rows_ext.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
TFD_MS = 24*3600_000
bars12_ext = agg(rows_ext, TF_MS)
barsD_ext = agg(rows_ext, TFD_MS)
print(f"  Ext: 12h={len(bars12_ext)}, D={len(barsD_ext)}")

# === HMA ===
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

# Только bars12h в окне отображения
bars12h_win = [b for b in bars12h if b[0] >= START_MS]
t12h_win = [b[0] for b in bars12h_win]

hma78_12 = htf_smooth(t12h_win, bars12_ext, hma_12_78_live, TF_MS)
hma200_12 = htf_smooth(t12h_win, bars12_ext, hma_12_200_live, TF_MS)
hma78_D = htf_smooth(t12h_win, barsD_ext, hma_D_78_live, TFD_MS)
hma200_D = htf_smooth(t12h_win, barsD_ext, hma_D_200_live, TFD_MS)

# === Figure ===
fig, ax = plt.subplots(figsize=(24, 12))

def to_dt(ms): return datetime.fromtimestamp(ms/1000, MSK)

y_min = 50000
y_max = 100000

bar_w = (TF_MIN/60)/24 * BAR_WIDTH_FRACTION

for b in bars12h:
    t = to_dt(b[0] + TF_MS//2)
    o,h,l,c = b[1],b[2],b[3],b[4]
    color_b = BULL if c>o else (BEAR if c<o else DOJI)
    ax.vlines(t, l, h, color=color_b, linewidth=BAR_LW, zorder=2)
    ax.add_patch(plt.Rectangle((mdates.date2num(t)-bar_w/2, min(o,c)),
                               bar_w, max(abs(o-c), 0.01),
                               facecolor=color_b, edgecolor=color_b,
                               linewidth=BAR_LW, zorder=2))

# === Intersection markers ===
# Aggregate per-event location: place on the 12h bar's high/low (not 6h)
# Each intersection event is a 12h bar (ts = 12h bar open)
# === HMA lines on chart ===
HMA78_COLOR  = '#4a90d9'
HMA200_COLOR = '#1a3f6f'
HMA_LW = 0.9

times_plot = [to_dt(ts) for ts in t12h_win]

def plot_hma(series, color, ls, lw=HMA_LW):
    pts = [(t,v) for t,v in zip(times_plot, series) if v is not None]
    if not pts: return
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, linewidth=lw, linestyle=ls, zorder=1)

plot_hma(hma78_12,  HMA78_COLOR,  '--')   # 12h dashed
plot_hma(hma200_12, HMA200_COLOR, '--')
plot_hma(hma78_D,   HMA78_COLOR,  '-')    # D solid
plot_hma(hma200_D,  HMA200_COLOR, '-')

# === VWAPs (top-2 эффективных + 1 проработанный — под/над ценой) ===
print("Computing anchored VWAPs from D fractals (last 1100 days)...")
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

# Williams N=2 fractals on D
fh_all=[]; fl_all=[]
for i in range(2, len(barsD_ext)-2):
    h_i, l_i = barsD_ext[i][2], barsD_ext[i][3]
    if all(h_i > barsD_ext[i+j][2] for j in [-2,-1,1,2]):
        fh_all.append({'t':barsD_ext[i][0], 'price':h_i, 'pivot_close_ts':barsD_ext[i][0]+TFD_MS})
    if all(l_i < barsD_ext[i+j][3] for j in [-2,-1,1,2]):
        fl_all.append({'t':barsD_ext[i][0], 'price':l_i, 'pivot_close_ts':barsD_ext[i][0]+TFD_MS})

# anchor окно: вся доступная история 1m (с 2020-01-01)
anchor_horizon = EXT_START_MS
fractals = [(f, 'FH') for f in fh_all if anchor_horizon <= f['t'] <= END_MS] + \
           [(f, 'FL') for f in fl_all if anchor_horizon <= f['t'] <= END_MS]
print(f"  D fractals since 2018 (full history): {len(fractals)}")

CASCADE_TFS = [60, 120, 240, 360, 480, 720]  # минуты
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
    scored.append({'f':f,'side':side,'composite':eff.composite,
                   'interactions':eff.total_interactions,'cur':cur_v})

below = [s for s in scored if 50000 <= s['cur'] < last_close]   # 50k → current price
above = [s for s in scored if last_close < s['cur'] <= 70000]   # current price → 70k

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

VWAP_BELOW = '#ff7f0e'   # эффективный под ценой - orange
VWAP_ABOVE = '#c62828'   # эффективный над ценой - red
VWAP_WORKED = '#7e57c2'  # проработанный - purple

def plot_vwap_line(item, color):
    f = item['f']
    vws = vwap_series_for_bars(f['pivot_close_ts'], bars12h_win, TF_MS)
    pts = [(to_dt(b[0]), v) for b,v in zip(bars12h_win, vws) if v is not None]
    if not pts: return
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, linewidth=0.9, alpha=0.85, zorder=1)

for s in eff_below: plot_vwap_line(s, VWAP_BELOW)
for s in eff_above: plot_vwap_line(s, VWAP_ABOVE)
for s in worked_below: plot_vwap_line(s, VWAP_WORKED)
for s in worked_above: plot_vwap_line(s, VWAP_WORKED)
print(f"  Plotted: {len(eff_below)} eff_below, {len(eff_above)} eff_above, {len(worked_below)+len(worked_above)} worked")

# Все маркеры одинакового размера + точно над/под СВОЕЙ 12h-свечой
MARKER_SIZE = 180
bars12h_map = {b[0]: b for b in bars12h}

for _, r in df_2026.iterrows():
    ts = int(r["ts"])
    bar = bars12h_map.get(ts)
    if bar is None: continue
    t_center = to_dt(bar[0] + TF_MS//2)   # центр СВОЕЙ свечи
    high_p = bar[2]; low_p = bar[3]
    confirmed = bool(r["confirmed"])

    nC = int(r["n_C"])
    stars = "★" * nC
    if r["direction"]=="high":
        col = FH_COLOR
        fc = col if confirmed else "white"
        ax.scatter(t_center, high_p*1.004, marker="v", s=MARKER_SIZE,
                   facecolor=fc, edgecolor=col, linewidth=1.5, zorder=8)
        if nC > 0:
            ax.annotate(stars, (t_center, high_p*1.004), xytext=(0, 13),
                        textcoords="offset points", ha='center', va='bottom',
                        fontsize=10, color=col, zorder=9)
    else:
        col = FL_COLOR
        fc = col if confirmed else "white"
        ax.scatter(t_center, low_p*0.996, marker="^", s=MARKER_SIZE,
                   facecolor=fc, edgecolor=col, linewidth=1.5, zorder=8)
        if nC > 0:
            ax.annotate(stars, (t_center, low_p*0.996), xytext=(0, -13),
                        textcoords="offset points", ha='center', va='top',
                        fontsize=10, color=col, zorder=9)

# === Format: right Y-axis with 1000 step, Monday X-ticks ===
ax.yaxis.tick_right()
ax.yaxis.set_label_position('right')
ax.yaxis.set_major_locator(MultipleLocator(2000))

start_dt = to_dt(int(START.timestamp()*1000))
today_dt = to_dt(int(END.timestamp()*1000))
last_monday = (today_dt - timedelta(days=today_dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
week_ticks = []; d = last_monday
while d >= start_dt:
    week_ticks.append(d); d -= timedelta(days=7)
week_ticks.reverse()
if today_dt.date() != last_monday.date():
    week_ticks.append(today_dt)
ax.set_xticks(week_ticks)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%d-%m', tz=MSK))
ax.grid(False, which='both', axis='both')
ax.tick_params(axis='both', which='both', length=0)
for spine in ax.spines.values():
    spine.set_visible(False)

# Current price line + tick
ax.axhline(y=last_close, color=CURRENT_PRICE, linewidth=0.9, linestyle=':', alpha=1.0, zorder=3)
future_end = today_dt + timedelta(hours=24*12)  # 24 баров × 12h = 12 дней
ax.set_xlim(start_dt, future_end)
ax.set_ylim(y_min, y_max)
fig.canvas.draw()
existing_ticks = list(ax.get_yticks())
filtered = [t for t in existing_ticks if abs(t - last_close) > 1000]
all_ticks = sorted(set(filtered + [last_close]))
ax.set_yticks(all_ticks)
labels = []
for t in all_ticks:
    if abs(t - last_close) < 0.5:
        labels.append(f' {last_close:,.0f} ')
    else:
        labels.append(f'{int(t):,}')
ax.set_yticklabels(labels)
for tl, t in zip(ax.get_yticklabels(), all_ticks):
    if abs(t - last_close) < 0.5:
        tl.set_color('white'); tl.set_weight('bold'); tl.set_fontsize(11)
        tl.set_bbox(dict(facecolor=CURRENT_PRICE, edgecolor=CURRENT_PRICE, pad=4))

for tl, td in zip(ax.get_xticklabels(), week_ticks):
    if td == today_dt:
        tl.set_color('white'); tl.set_weight('bold'); tl.set_fontsize(11)
        tl.set_bbox(dict(facecolor=CURRENT_PRICE, edgecolor=CURRENT_PRICE, pad=4))

# === Title ===
n_total = len(df_2026)
n_conf = int(df_2026["confirmed"].sum())
n_fh = (df_2026["direction"]=="high").sum()
n_fl = (df_2026["direction"]=="low").sum()
wr = n_conf/n_total*100 if n_total else 0
fig.text(0.5, 0.97,
         f"BTC  |  12h  |  {today_dt.strftime('%d-%m-%Y')}  |  {today_dt.strftime('%H:%M')} MSK   +   "
         f"Basket ∩ Andrey ML (p≥0.3) за последние 6 мес  "
         f"|  N={n_total} (FH={n_fh}, FL={n_fl})  |  confirmed {n_conf}/{n_total} = {wr:.1f}%",
         ha='center', va='top', fontsize=14, fontweight='bold')

# Легенда убрана (заголовок + цветовая семантика интуитивна)

plt.subplots_adjust(left=0.02, right=0.96, top=0.94, bottom=0.06)
out = Path.home()/"Desktop/i-rdrb-charts/btc_12h_basket_ml_intersection_6mo.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=140)
print(f"\nSaved: {out}")
