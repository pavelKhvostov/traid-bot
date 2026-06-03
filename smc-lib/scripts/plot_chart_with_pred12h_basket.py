"""6h чарт по chart_format.md + overlay 12h-баров корзины Pred-12h.

Поверх канон-базы (свечи, ось, текущая цена) подсвечиваем 12h-бары, попавшие
в корзину F1∩F2∩F3 + C1∪…∪C7 за окно чарта (60 дней) + сегодняшние новые,
если они уже сформировали потенциальный паттерн (без подтверждения Williams).

Маркеры (на верх/низ 12h-бара):
  ▼ = potential FH (high pivot)
  ▲ = potential FL (low pivot)
Цвета:
  - синий = baseline (F1∩F2∩F3) но НЕ в корзине
  - зелёный = в корзине (C1∪…∪C7), Williams-confirmed
  - оранжевый = в корзине, Williams ещё не подтверждён (potential)
  - красный outline = сегодняшний (new), не подтверждён
Подпись: какие C-условия сработали.
"""
from __future__ import annotations
import csv, pathlib, sys, subprocess
from datetime import datetime, timezone, timedelta
import math
import numpy as np
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.ob_liq.code import detect_ob_liq
from elements.fvg.code import detect_fvg
from elements.block_orders.code import detect_block_orders
from indicators.trend_line_asvk import wma
from indicators.vwap_effectiveness import effectiveness_per_tf, composite_effectiveness
import bisect

# ── Авто-докачка 1m (canon §1) ───────────────────────────────────────────────
FETCH = pathlib.Path.home() / "smc-lib/scripts/fetch_btc_1m_missing.py"
print("Auto-updating 1m data...")
res = subprocess.run([sys.executable, str(FETCH)], capture_output=True, text=True, timeout=120)
print(res.stdout.strip().split('\n')[-1] if res.stdout else '(no fetch output)')

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts"; OUT.mkdir(parents=True, exist_ok=True)
MSK = timezone(timedelta(hours=3))
MS = 60_000
MS_H = 60*MS
TF_MIN = 360            # 6h base
TF_MS = TF_MIN * MS
TF12 = 12*MS_H
TFD = 24*MS_H
TF2D = 48*MS_H
TF3D = 72*MS_H
TFW  = 7*24*MS_H
MON_ANCHOR = 1483315200000

WINDOW_DAYS = 60

# ── Canon palette (chart_format.md §2-§4) ───────────────────────────────────
BULL_COLOR = '#01a648'
BEAR_COLOR = '#131b1b'
DOJI_COLOR = '#888'
CURRENT_PRICE_COLOR = '#c62828'
BAR_GAP_FRACTION = 0.5
BAR_WIDTH_FRACTION = 1.0 - BAR_GAP_FRACTION
BAR_LINEWIDTH = 1.1

# Marker palette
BASELINE_COLOR = '#1976d2'   # синий — baseline only
BASKET_CONF_COLOR = '#2e7d32'  # зелёный — в корзине, подтверждён
BASKET_NOTCONF_COLOR = '#ef6c00'  # оранжевый — в корзине, не подтверждён
TODAY_COLOR = '#c62828'      # красный — сегодняшний

def load_1m():
    rows = []
    with CSV.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows

def aggregate(d, tfms, anchor=0):
    out=[]; cb=None; o=h=l=c=0.0; v=0.0
    for ts,oo,hh,ll,cc,vv in d:
        b = ts - ((ts - anchor) % tfms)
        if b!=cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c=oo,hh,ll,cc; v=vv
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out

print("Loading 1m...")
rows = load_1m()
last_ts = rows[-1][0]
print(f"  {len(rows)} 1m, последний: {datetime.fromtimestamp(last_ts/1000, MSK)}")

# ── Окно для отображения (chart_format.md §1) ────────────────────────────────
win_end = last_ts
win_start = win_end - WINDOW_DAYS*86400*1000

# 6h для основного чарта
b6h = aggregate(rows, TF_MS)
b6h_win = [b for b in b6h if win_start <= b[0] <= win_end]

# ── HTF aggregation для basket detection (за весь период) ────────────────────
print("Aggregating HTFs...")
bars12 = aggregate(rows, TF12)
barsD  = aggregate(rows, TFD)
bars2D = aggregate(rows, TF2D)
bars3D = aggregate(rows, TF3D)
barsW  = aggregate(rows, TFW, MON_ANCHOR)
bars_by_tf = {"12h":bars12, "D":barsD, "2D":bars2D, "3D":bars3D, "W":barsW}
cans_by_tf = {tf:[Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bb]
              for tf,bb in bars_by_tf.items()}
tfms_map = {"12h":TF12,"D":TFD,"2D":TF2D,"3D":TF3D,"W":TFW}

n12 = len(bars12)
t12 = np.array([b[0] for b in bars12], dtype=np.int64)
h12 = np.array([b[2] for b in bars12])
l12 = np.array([b[3] for b in bars12])
c12 = np.array([b[4] for b in bars12])

ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
op_1m = np.array([r[1] for r in rows], dtype=np.float64)
cl_1m = np.array([r[4] for r in rows], dtype=np.float64)
vol_1m = np.array([r[5] for r in rows], dtype=np.float64)
is_bull_1m = cl_1m > op_1m
is_bear_1m = cl_1m < op_1m

# === С1: sweep maxV(i-1) ===
print("Computing C1 (maxV)...")
maxv = np.full(n12, np.nan)
for k in range(n12):
    b_start = t12[k]; b_end = b_start + TF12
    i_lo = int(np.searchsorted(ts_1m, b_start, side='left'))
    i_hi = int(np.searchsorted(ts_1m, b_end, side='left'))
    if i_hi <= i_lo: continue
    bull_mask = is_bull_1m[i_lo:i_hi]; bear_mask = is_bear_1m[i_lo:i_hi]
    v_slice = vol_1m[i_lo:i_hi]; c_slice = cl_1m[i_lo:i_hi]
    max_bull = v_slice[bull_mask].max() if bull_mask.any() else 0
    max_bear = v_slice[bear_mask].max() if bear_mask.any() else 0
    if max_bull == 0 and max_bear == 0: continue
    if max_bull >= max_bear:
        idx_local = np.where((v_slice == max_bull) & bull_mask)[0][0]
    else:
        idx_local = np.where((v_slice == max_bear) & bear_mask)[0][0]
    maxv[k] = c_slice[idx_local]
sw_maxV_short = np.zeros(n12, dtype=bool)
sw_maxV_long  = np.zeros(n12, dtype=bool)
for i in range(1, n12):
    mv = maxv[i-1]
    if np.isnan(mv): continue
    if h12[i] > mv and c12[i] < mv: sw_maxV_short[i] = True
    if l12[i] < mv and c12[i] > mv: sw_maxV_long[i] = True

# === С3: ob_liq FIRST 50%-sweep ===
print("Computing C3 (ob_liq)...")
all_ob_liq = []
for tf, cans in cans_by_tf.items():
    tfms = tfms_map[tf]
    for i in range(len(cans) - 1):
        ol = detect_ob_liq(cans[i], cans[i+1])
        if ol is None: continue
        ready = cans[i+1].open_time + tfms
        all_ob_liq.append({"tf":tf, "direction":ol.direction,
                           "zone_lo":ol.zone[0], "zone_hi":ol.zone[1],
                           "liq_lo":ol.liq_zone[0], "liq_hi":ol.liq_zone[1],
                           "ready_ms":ready})
def first_sweep50_idx(z, use_liq_zone):
    sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
    if sp >= n12: return None
    zlo, zhi = (z["liq_lo"], z["liq_hi"]) if use_liq_zone else (z["zone_lo"], z["zone_hi"])
    mid = (zlo + zhi) / 2
    for k in range(sp, n12):
        if z["direction"] == "short":
            if h12[k] >= mid and c12[k] < zlo: return k
        else:
            if l12[k] <= mid and c12[k] > zhi: return k
    return None
for z in all_ob_liq:
    z["fs50_liq"] = first_sweep50_idx(z, True)
    z["fs50_ob"]  = first_sweep50_idx(z, False)

# === С4: FVG FIRST 50%-sweep multi-TF ===
print("Computing C4 (FVG)...")
all_fvg = []
for tf, cans in cans_by_tf.items():
    tfms = tfms_map[tf]
    for i in range(len(cans) - 2):
        fv = detect_fvg(cans[i], cans[i+1], cans[i+2])
        if fv is None: continue
        ready = cans[i+2].open_time + tfms
        all_fvg.append({"tf":tf, "direction":fv.direction,
                        "zone_lo":fv.zone[0], "zone_hi":fv.zone[1], "ready_ms":ready})
def fvg_fs50(z):
    sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
    if sp >= n12: return None
    zlo, zhi = z["zone_lo"], z["zone_hi"]; mid = (zlo + zhi)/2
    for k in range(sp, n12):
        if z["direction"] == "short":
            if h12[k] >= mid and c12[k] < zlo: return k
        else:
            if l12[k] <= mid and c12[k] > zhi: return k
    return None
for z in all_fvg:
    z["fs50"] = fvg_fs50(z)

# === С5+С6: HMA-78 12h/D + HMA-200 D LIVE ===
print("Computing C5+C6 (TrendLine)...")
def hma(values, n):
    half = wma(values, n//2); full = wma(values, n)
    diff = [(2*half[i]-full[i]) if (half[i] is not None and full[i] is not None) else 0.0
            for i in range(len(values))]
    return wma(diff, int(round(math.sqrt(n))))
hma_12     = hma([b[4] for b in bars12], 78)
hma_12_200 = hma([b[4] for b in bars12], 200)
hma_d      = hma([b[4] for b in barsD], 78)
hma_d_200  = hma([b[4] for b in barsD], 200)
td_arr = np.array([b[0] for b in barsD], dtype=np.int64)
def d_idx_for(ts):
    idx = int(np.searchsorted(td_arr, ts, side='right')) - 1
    return idx if 0 <= idx < len(barsD) else None

# === С7: block_orders FIRST 50%-sweep multi-TF ===
print("Computing C7 (block_orders)...")
all_bo = []
for tf, cans in cans_by_tf.items():
    tfms = tfms_map[tf]
    for i in range(len(cans)):
        for L in range(3, 9):
            if i + L > len(cans): break
            bo = detect_block_orders(cans[i:i+L])
            if bo is None: continue
            ready = cans[i].open_time + L*tfms
            zb, zt = bo.zone
            all_bo.append({"tf":tf, "direction":bo.direction,
                           "zone_lo":zb, "zone_hi":zt, "ready_ms":ready})
            break
def bo_fs50(z):
    sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
    if sp >= n12: return None
    zlo, zhi = z["zone_lo"], z["zone_hi"]; mid = (zlo + zhi)/2
    for k in range(sp, n12):
        if z["direction"] == "short":
            if h12[k] >= mid and c12[k] < zlo: return k
        else:
            if l12[k] <= mid and c12[k] > zhi: return k
    return None
for z in all_bo:
    z["fs50"] = bo_fs50(z)

# === F1∩F2∩F3 baseline + detection в окне (с запасом 14 дней слева для left_5_extreme) ===
print("Computing baseline F1∩F2∩F3 + basket flags...")
def color(b):
    if b[4]>b[1]: return "bull"
    if b[4]<b[1]: return "bear"
    return "doji"
# pivots — рассматриваем все 12h бары начиная за win_start − 14 дней
det_start = win_start - 14*86400*1000
pivots = []
for i in range(2, n12-2):
    bi = bars12[i]; bi1=bars12[i-1]; bi2=bars12[i-2]; bip1=bars12[i+1]; bip2=bars12[i+2]
    if bi[0] < det_start: continue
    if bi[0] > win_end: continue
    pre_fh = bi[2]>bi1[2] and bi[2]>bi2[2]
    pre_fl = bi[3]<bi1[3] and bi[3]<bi2[3]
    if not(pre_fh or pre_fl): continue
    for direction in (("high",) if pre_fh else ()) + (("low",) if pre_fl else ()):
        confirmed = (bi[2]>bip1[2] and bi[2]>bip2[2]) if direction=="high" else (bi[3]<bip1[3] and bi[3]<bip2[3])
        rwick = (bi[2]-max(bi[1],bi[4])) if direction=="high" else (min(bi[1],bi[4])-bi[3])
        rng=bi[2]-bi[3] if bi[2]>bi[3] else 1e-9
        body=abs(bi[4]-bi[1])
        c0,c1,c2_=color(bi),color(bi1),color(bi2)
        left_lo=max(0,i-5); left_hi=i
        if direction=="high":
            f1 = bi[2] > max(bars12[j][2] for j in range(left_lo, left_hi)) if left_hi>left_lo else True
        else:
            f1 = bi[3] < min(bars12[j][3] for j in range(left_lo, left_hi)) if left_hi>left_lo else True
        if not f1: continue
        opp = c0!=c1 and "doji" not in (c0,c1); three = c0==c1==c2_ and c0!="doji"
        if not (opp or three): continue
        if body/rng > 0.80 or rwick/rng < 0.03: continue
        pivots.append({"i":i, "direction":direction, "confirmed":confirmed, "ts":bi[0], "bi":bi})

# Also include today's potential bar (last 12h bar even if not pre-pattern fully)
last12 = bars12[-1]
# Already covered by loop if its open_time ≤ win_end; today_bar mark detected later by ts proximity

# Per-pivot basket flags
def p_dir_to_zdir(d): return "short" if d=="high" else "long"
def c3_check(p):
    pdir = p_dir_to_zdir(p["direction"]); pi = p["i"]; pt = t12[pi]
    for z in all_ob_liq:
        if z["direction"] != pdir or z["ready_ms"] > pt: continue
        if z["fs50_liq"] == pi or z["fs50_ob"] == pi: return True
    return False
def c4_check(p):
    pdir = p_dir_to_zdir(p["direction"]); pi = p["i"]; pt = t12[pi]
    for z in all_fvg:
        if z["direction"] != pdir or z["ready_ms"] > pt: continue
        if z["fs50"] == pi: return True
    return False
def c5_check(p):
    pi = p["i"]; bi = bars12[pi]
    hv12 = hma_12[pi-1] if pi-1 >= 0 else None
    if hv12 is not None:
        if p["direction"] == "high":
            if bi[2] > hv12 and bi[4] < hv12: return True
        else:
            if bi[3] < hv12 and bi[4] > hv12: return True
    didx = d_idx_for(bi[0])
    if didx is not None and didx-1 >= 0:
        hvd = hma_d[didx-1]
        if hvd is not None:
            if p["direction"] == "high":
                if bi[2] > hvd and bi[4] < hvd: return True
            else:
                if bi[3] < hvd and bi[4] > hvd: return True
    return False
def c6_check(p):
    pi = p["i"]; bi = bars12[pi]
    didx = d_idx_for(bi[0])
    if didx is None or didx-1 < 0: return False
    hv = hma_d_200[didx-1]
    if hv is None: return False
    if p["direction"] == "high":
        return bi[2] > hv and bi[4] < hv
    else:
        return bi[3] < hv and bi[4] > hv
def c7_check(p):
    pdir = p_dir_to_zdir(p["direction"]); pi = p["i"]; pt = t12[pi]
    for z in all_bo:
        if z["direction"] != pdir or z["ready_ms"] > pt: continue
        if z["fs50"] == pi: return True
    return False
def c2_check(p):
    pt = p["ts"]; pt_end = pt + TF12
    i_hi = int(np.searchsorted(ts_1m, pt_end, side='left'))
    flags = []
    for N, thr in [(8, 0.65), (12, 0.75), (16, 0.65), (24, 0.65)]:
        cut = int(np.searchsorted(ts_1m, pt_end - N*15*MS, side='left'))
        sub = rows[cut:i_hi]
        sub_15m = aggregate(sub, 15*MS)
        if not sub_15m: flags.append(False); continue
        if p["direction"] == "high":
            cnt = sum(1 for b in sub_15m if b[4] < b[1])
        else:
            cnt = sum(1 for b in sub_15m if b[4] > b[1])
        flags.append(cnt/len(sub_15m) >= thr)
    return any(flags)
def c1_check(p):
    return bool(sw_maxV_short[p["i"]]) if p["direction"]=="high" else bool(sw_maxV_long[p["i"]])

for p in pivots:
    p["c1"]=c1_check(p); p["c2"]=c2_check(p); p["c3"]=c3_check(p)
    p["c4"]=c4_check(p); p["c5"]=c5_check(p); p["c6"]=c6_check(p); p["c7"]=c7_check(p)
    p["basket"] = p["c1"] or p["c2"] or p["c3"] or p["c4"] or p["c5"] or p["c6"] or p["c7"]
    p["c_flags"] = [k+1 for k,v in enumerate([p["c1"],p["c2"],p["c3"],p["c4"],p["c5"],p["c6"],p["c7"]]) if v]

# Filter for chart: only those whose ts falls in window
pivots_win = [p for p in pivots if win_start <= p["ts"] <= win_end]
basket_win = [p for p in pivots_win if p["basket"]]
baseline_only_win = [p for p in pivots_win if not p["basket"]]

# Today's potential (within last 24h pivot)
today_threshold = last_ts - 24*3600*1000
today_pivots = [p for p in pivots_win if p["ts"] >= today_threshold]

print(f"\nPivots в окне 60d: {len(pivots_win)}")
print(f"  basket (C1∪…∪C7): {len(basket_win)}")
print(f"  baseline only: {len(baseline_only_win)}")
print(f"  today (last 24h):  {len(today_pivots)}")

# ── РЕНДЕР по канон-базе ────────────────────────────────────────────────────
def to_dt(ms): return datetime.fromtimestamp(ms/1000, MSK)

fig, ax = plt.subplots(figsize=(24, 13))

bar_w = (TF_MIN/60)/24 * BAR_WIDTH_FRACTION
for b in b6h_win:
    t = to_dt(b[0]); o,h,l,c = b[1],b[2],b[3],b[4]
    color_b = BULL_COLOR if c > o else (BEAR_COLOR if c < o else DOJI_COLOR)
    ax.vlines(t, l, h, color=color_b, linewidth=BAR_LINEWIDTH, zorder=3)
    ax.add_patch(plt.Rectangle((mdates.date2num(t)-bar_w/2, min(o,c)), bar_w,
                               max(abs(o-c), 0.01), facecolor=color_b, edgecolor=color_b,
                               linewidth=BAR_LINEWIDTH, zorder=3))

# X-ticks: понедельники + сегодня (DD-MM)
today_dt = to_dt(win_end)
start_dt = to_dt(win_start)
last_monday = (today_dt - timedelta(days=today_dt.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)
week_ticks=[]; d=last_monday
while d >= start_dt:
    week_ticks.append(d); d -= timedelta(days=7)
week_ticks.reverse()
if today_dt.date() != last_monday.date():
    week_ticks.append(today_dt)
ax.set_xticks(week_ticks)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%d-%m', tz=MSK))
ax.grid(False)
ax.yaxis.tick_right()
ax.yaxis.set_label_position('right')
ax.yaxis.set_major_locator(MultipleLocator(1000))

# Текущая цена
current_price = rows[-1][4]
ax.axhline(y=current_price, color=CURRENT_PRICE_COLOR, linewidth=0.9, linestyle=':', alpha=1.0, zorder=1)
fig.canvas.draw()
existing_ticks = list(ax.get_yticks())
filtered = [t for t in existing_ticks if abs(t - current_price) > 500]
all_ticks = sorted(set(filtered + [current_price]))
ax.set_yticks(all_ticks)
labels=[]
for t in all_ticks:
    labels.append(f' {current_price:,.0f} ' if abs(t-current_price)<0.5 else f'{int(t):,}')
ax.set_yticklabels(labels)
for tl,t in zip(ax.get_yticklabels(), all_ticks):
    if abs(t-current_price)<0.5:
        tl.set_color('white'); tl.set_weight('bold'); tl.set_fontsize(11)
        tl.set_bbox(dict(facecolor=CURRENT_PRICE_COLOR, edgecolor=CURRENT_PRICE_COLOR, pad=4))

# Подсветить today tick label
for tl, td in zip(ax.get_xticklabels(), week_ticks):
    if td == today_dt:
        tl.set_color('white'); tl.set_weight('bold'); tl.set_fontsize(11)
        tl.set_bbox(dict(facecolor=CURRENT_PRICE_COLOR, edgecolor=CURRENT_PRICE_COLOR, pad=4))

# ── HMA 12h+D LIVE + плавная проекция на 6h-бары (Правило 7) ────────────────
# Все синие; 12h — solid, D — штрих-пунктирной; на 30% тоньше прежнего (1.8→1.26)
HMA78_COLOR  = '#4a90d9'    # светло-синий — 78
HMA200_COLOR = '#1a3f6f'    # тёмно-синий — 200
HMA_LINEWIDTH = 0.8
HMA_12_STYLE = '--'
HMA_D_STYLE  = '-'

def live_shift(arr):
    return [None] + list(arr[:-1])
hma_12_live     = live_shift(hma_12)
hma_12_200_live = live_shift(hma_12_200)
hma_d_live      = live_shift(hma_d)
hma_d_200_live  = live_shift(hma_d_200)

def htf_series_smooth(ltf_bars_ts, htf_bars, htf_values, htf_tf_ms):
    closed_ends = [b[0] + htf_tf_ms for b in htf_bars]
    out = []
    for ts in ltf_bars_ts:
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

t6h_win = [b[0] for b in b6h_win]
hma78_12_on_6h  = htf_series_smooth(t6h_win, bars12, hma_12_live,     TF12)
hma200_12_on_6h = htf_series_smooth(t6h_win, bars12, hma_12_200_live, TF12)
hma78_D_on_6h   = htf_series_smooth(t6h_win, barsD,  hma_d_live,      TFD)
hma200_D_on_6h  = htf_series_smooth(t6h_win, barsD,  hma_d_200_live,  TFD)

times_plot = [to_dt(ts) for ts in t6h_win]
def plot_hma(series, color, ls, label):
    pts = [(t,v) for t,v in zip(times_plot, series) if v is not None]
    if not pts: return
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, linewidth=HMA_LINEWIDTH, linestyle=ls, zorder=1, label=label)

plot_hma(hma78_12_on_6h,  HMA78_COLOR,  HMA_12_STYLE, 'HMA-78 12h LIVE')
plot_hma(hma200_12_on_6h, HMA200_COLOR, HMA_12_STYLE, 'HMA-200 12h LIVE')
plot_hma(hma78_D_on_6h,   HMA78_COLOR,  HMA_D_STYLE,  'HMA-78 D LIVE')
plot_hma(hma200_D_on_6h,  HMA200_COLOR, HMA_D_STYLE,  'HMA-200 D LIVE')

# ── VWAP: самый эффективный, значение которого ниже текущей цены ─────────────
# (Правило 6, Method 1: anchor = close D-pivot)
print("Searching most-effective VWAP below current price...")
CASCADE_TFS = [60, 120, 240, 360, 480, 720]   # 1h..12h
def williams_d(bars, n=2):
    fh, fl = [], []
    for i in range(n, len(bars)-n):
        h_i = bars[i][2]; l_i = bars[i][3]
        if h_i > max(bars[i-k][2] for k in range(1,n+1)) and h_i > max(bars[i+k][2] for k in range(1,n+1)):
            fh.append({'i':i, 't':bars[i][0], 'price':h_i, 'pivot_close_ts':bars[i][0]+TFD})
        if l_i < min(bars[i-k][3] for k in range(1,n+1)) and l_i < min(bars[i+k][3] for k in range(1,n+1)):
            fl.append({'i':i, 't':bars[i][0], 'price':l_i, 'pivot_close_ts':bars[i][0]+TFD})
    return fh, fl
fh_all, fl_all = williams_d(barsD)

# Cum_pv / cum_v на 1m (numpy для скорости)
cl_arr = cl_1m  # уже numpy
vol_arr = vol_1m
cum_pv_np = np.concatenate(([0.0], np.cumsum(cl_arr * vol_arr)))
cum_v_np  = np.concatenate(([0.0], np.cumsum(vol_arr)))
ts_1m_list = ts_1m.tolist()   # один раз
def idx_at(ms):
    return bisect.bisect_left(ts_1m_list, ms)

def vwap_at(anchor_ms, target_end_ms):
    a = idx_at(anchor_ms); e = idx_at(target_end_ms)
    if e <= a: return None
    pv = cum_pv_np[e] - cum_pv_np[a]
    vol = cum_v_np[e] - cum_v_np[a]
    return pv/vol if vol > 0 else None

def vwap_series_for_bars(anchor_ms, bars_list, tf_ms_local):
    a = idx_at(anchor_ms)
    res = []
    bars_n = len(rows)
    for b in bars_list:
        end_ms = b[0] + tf_ms_local
        end_idx = min(idx_at(end_ms), bars_n)
        if end_idx <= a:
            res.append(None); continue
        pv = cum_pv_np[end_idx] - cum_pv_np[a]
        vol = cum_v_np[end_idx] - cum_v_np[a]
        res.append(float(pv/vol) if vol > 0 else None)
    return res

# Используем anchor-окно последних 180 дней (как раньше)
anchor_horizon = win_end - 180*86400*1000
fractals = [(f, 'FH') for f in fh_all if anchor_horizon <= f['t'] <= win_end] + \
           [(f, 'FL') for f in fl_all if anchor_horizon <= f['t'] <= win_end]

cascade_bars = {tf: aggregate(rows, tf*MS) for tf in CASCADE_TFS}

scored_all = []
for f, side in fractals:
    anchor = f['pivot_close_ts']
    cur_v = vwap_at(anchor, last_ts)
    if cur_v is None: continue
    per_tf = []
    for tf_min in CASCADE_TFS:
        bars_tf = cascade_bars[tf_min]
        bars_after = [b for b in bars_tf if anchor <= b[0] <= win_end]
        if len(bars_after) < 2:
            per_tf.append(effectiveness_per_tf(f"{tf_min}m", [], []))
            continue
        vw_series = vwap_series_for_bars(anchor, bars_after, tf_min*MS)
        ohlc = [(b[1], b[2], b[3], b[4]) for b in bars_after]
        per_tf.append(effectiveness_per_tf(f"{tf_min}m", ohlc, vw_series))
    eff = composite_effectiveness(anchor, per_tf)
    scored_all.append({'f':f, 'side':side, 'composite':eff.composite,
                       'interactions':eff.total_interactions, 'cur_value':cur_v})

scored = [s for s in scored_all if s['cur_value'] < current_price]   # под ценой
scored_above = [s for s in scored_all if s['cur_value'] > current_price]   # над ценой

VWAP_BELOW_COLOR = '#ff7f0e'   # оранжевый (support под ценой)
VWAP_ABOVE_COLOR = '#c62828'   # красный (resistance над ценой)
top_below = sorted(scored, key=lambda x: -x['composite'])[:2]
top_above = sorted(scored_above, key=lambda x: -x['composite'])[:2]

def plot_vwap_item(item, color, label_prefix):
    f = item['f']; side = item['side']
    vw_series_6h = vwap_series_for_bars(f['pivot_close_ts'], b6h_win, TF_MS)
    pts = [(to_dt(b[0]), v) for b, v in zip(b6h_win, vw_series_6h) if v is not None]
    if not pts: return
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, linewidth=HMA_LINEWIDTH, alpha=0.9, zorder=1)
    if win_start <= f['t'] <= win_end:
        ax.scatter(to_dt(f['t']), f['price'],
                   marker=('v' if side=='FH' else '^'),
                   color=color, s=70, zorder=6,
                   edgecolor='black', linewidth=0.5)
    else:
        # Anchor вне окна — подписать линию у ЛЕВОГО края с указанием anchor
        anchor_label = f"{side} {datetime.fromtimestamp(f['t']/1000, MSK).strftime('%d-%m-%y')}"
        ax.annotate(f" {anchor_label} ",
                    xy=(xs[0], ys[0]), xytext=(4, 0),
                    textcoords='offset points',
                    ha='left', va='center', fontsize=8, color='white',
                    fontweight='bold',
                    bbox=dict(facecolor=color, edgecolor=color, pad=2),
                    zorder=7)

if top_below:
    for k, item in enumerate(top_below, 1):
        f = item['f']
        print(f"  BELOW #{k}: {item['side']} {datetime.fromtimestamp(f['t']/1000, MSK).strftime('%Y-%m-%d')}  "
              f"comp={item['composite']:.3f}  inter={item['interactions']}  "
              f"vwap={item['cur_value']:.0f}  (price={current_price:.0f})")
        plot_vwap_item(item, VWAP_BELOW_COLOR, "below")
else:
    print("  No VWAP candidates below current price found.")

if top_above:
    for k, item in enumerate(top_above, 1):
        f = item['f']
        print(f"  ABOVE #{k}: {item['side']} {datetime.fromtimestamp(f['t']/1000, MSK).strftime('%Y-%m-%d')}  "
              f"comp={item['composite']:.3f}  inter={item['interactions']}  "
              f"vwap={item['cur_value']:.0f}  (price={current_price:.0f})")
        plot_vwap_item(item, VWAP_ABOVE_COLOR, "above")
else:
    print("  No VWAP candidates above current price found.")

# ── Самый ОТРАБОТАННЫЙ (max interactions) над и под ценой ────────────────────
VWAP_INTER_COLOR = '#7e57c2'   # фиолетовый
inter_below = max(scored, key=lambda x: x['interactions']) if scored else None
inter_above = max(scored_above, key=lambda x: x['interactions']) if scored_above else None
if inter_below:
    f = inter_below['f']
    print(f"  INTER BELOW: {inter_below['side']} {datetime.fromtimestamp(f['t']/1000, MSK).strftime('%Y-%m-%d')}  "
          f"inter={inter_below['interactions']}  comp={inter_below['composite']:.3f}  "
          f"vwap={inter_below['cur_value']:.0f}")
    plot_vwap_item(inter_below, VWAP_INTER_COLOR, "inter-below")
if inter_above:
    f = inter_above['f']
    print(f"  INTER ABOVE: {inter_above['side']} {datetime.fromtimestamp(f['t']/1000, MSK).strftime('%Y-%m-%d')}  "
          f"inter={inter_above['interactions']}  comp={inter_above['composite']:.3f}  "
          f"vwap={inter_above['cur_value']:.0f}")
    plot_vwap_item(inter_above, VWAP_INTER_COLOR, "inter-above")

# ── OVERLAY: pivot markers (без заливки, без C/F разделения) ─────────────────
# SHORT (high pivot)  → ▼ СВЕРХУ (над high бара)
# LONG  (low pivot)   → ▲ СНИЗУ (под low бара)
SHORT_COLOR = '#c62828'   # красный
LONG_COLOR  = '#2e7d32'   # зелёный

price_range = max(b[2] for b in b6h_win) - min(b[3] for b in b6h_win)
offset_y = price_range * 0.012

for p in pivots_win:
    t_start = to_dt(p["ts"])
    t_end = to_dt(p["ts"] + TF12)
    t_mid = t_start + (t_end - t_start) / 2
    bi = p["bi"]
    if p["direction"] == "high":  # SHORT
        ax.scatter(t_mid, bi[2] + offset_y, marker='v', s=70,
                   facecolors=SHORT_COLOR, edgecolors=SHORT_COLOR,
                   linewidths=0.8, zorder=6)
    else:  # low → LONG
        ax.scatter(t_mid, bi[3] - offset_y, marker='^', s=70,
                   facecolors=LONG_COLOR, edgecolors=LONG_COLOR,
                   linewidths=0.8, zorder=6)

# Заголовок (canon §5)
ASSET='BTC'; TF_LABEL='6h'
now_dt = to_dt(win_end)
fig.text(0.5, 0.97,
         f"{ASSET}  |  {TF_LABEL}  |  {now_dt.strftime('%d-%m-%Y')}  |  {now_dt.strftime('%H:%M')} MSK   +   Pred-12h basket overlay",
         ha='center', va='top', fontsize=14, fontweight='bold')

# Легенда
from matplotlib.lines import Line2D
legend_handles = [
    Line2D([0],[0], marker='v', color='w', markerfacecolor=SHORT_COLOR, markeredgecolor=SHORT_COLOR,
           markersize=8, label='SHORT (FH pivot 12h)'),
    Line2D([0],[0], marker='^', color='w', markerfacecolor=LONG_COLOR, markeredgecolor=LONG_COLOR,
           markersize=8, label='LONG  (FL pivot 12h)'),
    Line2D([0],[0], color=HMA78_COLOR,  linewidth=HMA_LINEWIDTH, linestyle='--', label='HMA-78 12h LIVE'),
    Line2D([0],[0], color=HMA200_COLOR, linewidth=HMA_LINEWIDTH, linestyle='--', label='HMA-200 12h LIVE'),
    Line2D([0],[0], color=HMA78_COLOR,  linewidth=HMA_LINEWIDTH, linestyle='-',  label='HMA-78 D LIVE'),
    Line2D([0],[0], color=HMA200_COLOR, linewidth=HMA_LINEWIDTH, linestyle='-',  label='HMA-200 D LIVE'),
]
if top_below:
    legend_handles.append(Line2D([0],[0], color=VWAP_BELOW_COLOR, linewidth=HMA_LINEWIDTH,
                                  label='VWAP эффективный'))
if top_above:
    legend_handles.append(Line2D([0],[0], color=VWAP_ABOVE_COLOR, linewidth=HMA_LINEWIDTH,
                                  label='VWAP эффективный'))
if inter_below or inter_above:
    legend_handles.append(Line2D([0],[0], color=VWAP_INTER_COLOR, linewidth=HMA_LINEWIDTH,
                                  label='VWAP проработанный'))
ax.legend(handles=legend_handles, loc='upper left', fontsize=9, framealpha=0.92)

plt.subplots_adjust(left=0.02, right=0.96, top=0.93, bottom=0.06)
out_path = OUT / f"btc_6h_pred12h_basket_{to_dt(win_end).strftime('%Y-%m-%d')}.png"
plt.savefig(out_path, dpi=140)
print(f"\nSaved: {out_path}")

# Распечатать список basket-pivot'ов в окне
print(f"\n{'='*100}\nBasket pivots в окне:\n{'='*100}")
for p in basket_win:
    flags = ",".join(f"C{x}" for x in p["c_flags"])
    conf = "✓" if p["confirmed"] else "?"
    today_mark = " [TODAY]" if p in today_pivots else ""
    print(f"  {datetime.fromtimestamp(p['ts']/1000, MSK).strftime('%Y-%m-%d %H:%M')} MSK  "
          f"dir={p['direction']:<4}  conf={conf}  {flags}{today_mark}")

if today_pivots:
    print(f"\nTODAY ({to_dt(today_threshold).strftime('%H:%M')} → now):")
    for p in today_pivots:
        flags = ",".join(f"C{x}" for x in p["c_flags"]) if p["c_flags"] else "—"
        print(f"  {datetime.fromtimestamp(p['ts']/1000, MSK).strftime('%Y-%m-%d %H:%M')} MSK  "
              f"dir={p['direction']:<4}  basket={p['basket']}  {flags}")
