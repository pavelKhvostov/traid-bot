"""BTC 6h с канон-индикаторами:

  TrendLine ASVK (Правило 7):
    - HMA-78 на 12h, LIVE
    - HMA-78 на D, LIVE
    - HMA-200 на 12h, LIVE
    - HMA-200 на D, LIVE
    значения проецируем на 6h-бары через "последнее закрытое HTF значение"

  VWAPs ASVK (Правило 6 — упрощённый M1):
    - 100 последних D-фракталов (Williams N=2)
    - composite effectiveness считается на cascade {1h,2h,4h,6h,8h,12h}
    - выбираем: 5 best для LONG (FL), 5 best для SHORT (FH),
      5 "max отработанных" = max interactions independent of direction

Сохраняем PNG в ~/Desktop/i-rdrb-charts/
"""
from __future__ import annotations
import csv, pathlib, sys, bisect
from datetime import datetime, timezone, timedelta
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from indicators.trend_line_asvk import trend_line_hma_78, trend_line_hma_200
from indicators.vwap_effectiveness import effectiveness_per_tf, composite_effectiveness

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts"; OUT.mkdir(parents=True, exist_ok=True)
MSK = timezone(timedelta(hours=3))
MS = 60_000
TF_MIN = 360            # 6h chart
TF_MS = TF_MIN * MS
WINDOW_DAYS = 90
N_FRACTAL = 2
N_LAST_FRACTALS = 100
CASCADE_TFS_MIN = [60, 120, 240, 360, 480, 720]  # 1h..12h

def load_1m():
    rows = []
    with CSV.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows

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

print("Loading 1m...")
m1 = load_1m()
last_ts = m1[-1][0]

b6h  = agg(m1, TF_MS)
b12h = agg(m1, 12*3600*1000)
bD   = agg(m1, 86400*1000)

# окно
win_end = last_ts
win_start = win_end - WINDOW_DAYS*86400*1000
b6h_win = [b for b in b6h if win_start <= b[0] <= win_end]
print(f"  6h в окне: {len(b6h_win)}")

# ── HMA на 12h и D ───────────────────────────────────────────────────────────
def live_shift(arr):
    return [None] + arr[:-1]

closes_12h = [b[4] for b in b12h]
closes_D   = [b[4] for b in bD]

hma78_12h  = live_shift(trend_line_hma_78(closes_12h)['mhull'])
hma200_12h = live_shift(trend_line_hma_200(closes_12h)['mhull'])
hma78_D    = live_shift(trend_line_hma_78(closes_D)['mhull'])
hma200_D   = live_shift(trend_line_hma_200(closes_D)['mhull'])

# Проекция HTF HMA на 6h-бар.
# Канон strict-causal: значение HTF на бар i = последнее закрытое значение HTF (step).
# Для гладкого ОТОБРАЖЕНИЯ (post-hoc, не для торговли) линейно интерполируем
# между двумя последовательными закрытыми HTF значениями. Это сохраняет точное значение
# в моменты закрытия HTF-баров, но рисует плавный наклон между ними.
def htf_series_smooth(ltf_bars_ts, htf_bars, htf_values, htf_tf_ms):
    """linear interpolation between consecutive CLOSED HTF values."""
    out = []
    # для каждого LTF ts находим k = индекс последнего закрытого HTF (htf_bars[k][0]+htf_tf_ms <= ts)
    closed_ends = [b[0] + htf_tf_ms for b in htf_bars]  # время когда HTF бар k закрылся
    for ts in ltf_bars_ts:
        # k = максимальный индекс где closed_ends[k] <= ts
        lo, hi = 0, len(closed_ends)
        while lo < hi:
            m=(lo+hi)//2
            if closed_ends[m] <= ts: lo=m+1
            else: hi=m
        k = lo - 1  # последний закрытый HTF
        if k < 0 or htf_values[k] is None:
            out.append(None); continue
        v_k = htf_values[k]
        # для интерполяции нужен следующий закрытый HTF и его значение
        if k + 1 >= len(htf_values) or htf_values[k+1] is None:
            out.append(v_k); continue
        v_next = htf_values[k+1]
        # доля времени между closing k и closing k+1
        t0, t1 = closed_ends[k], closed_ends[k+1]
        if t1 <= t0:
            out.append(v_k); continue
        alpha = max(0.0, min(1.0, (ts - t0) / (t1 - t0)))
        out.append(v_k + alpha * (v_next - v_k))
    return out

t6h = [b[0] for b in b6h_win]
hma78_12h_on_6h  = htf_series_smooth(t6h, b12h, hma78_12h,  12*3600*1000)
hma200_12h_on_6h = htf_series_smooth(t6h, b12h, hma200_12h, 12*3600*1000)
hma78_D_on_6h    = htf_series_smooth(t6h, bD,   hma78_D,    86400*1000)
hma200_D_on_6h   = htf_series_smooth(t6h, bD,   hma200_D,   86400*1000)

# ── Williams D-фракталы (100 последних) ─────────────────────────────────────
def williams(bars, n=N_FRACTAL):
    fh, fl = [], []
    for i in range(n, len(bars)-n):
        h_i = bars[i][2]; l_i = bars[i][3]
        if h_i > max(bars[i-k][2] for k in range(1,n+1)) and h_i > max(bars[i+k][2] for k in range(1,n+1)):
            fh.append({'i':i, 't':bars[i][0], 'price':h_i, 'pivot_close_ts':bars[i][0]+86400*1000})
        if l_i < min(bars[i-k][3] for k in range(1,n+1)) and l_i < min(bars[i+k][3] for k in range(1,n+1)):
            fl.append({'i':i, 't':bars[i][0], 'price':l_i, 'pivot_close_ts':bars[i][0]+86400*1000})
    return fh, fl

fh_all, fl_all = williams(bD)
# anchor должен быть в пределах последних 180 дней до win_end (чтобы VWAP был релевантен текущему окну)
anchor_horizon = win_end - 180*86400*1000
fh = [f for f in fh_all if anchor_horizon <= f['t'] <= win_end][-N_LAST_FRACTALS:]
fl = [f for f in fl_all if anchor_horizon <= f['t'] <= win_end][-N_LAST_FRACTALS:]
print(f"  D-фракталов в anchor-окне (180d): FH={len(fh)}, FL={len(fl)}")

# ── VWAP от anchor ──────────────────────────────────────────────────────────
ts_1m = [r[0] for r in m1]
cum_pv = [0.0]*(len(m1)+1); cum_v = [0.0]*(len(m1)+1)
for i,(_,_,_,_,c,v) in enumerate(m1):
    cum_pv[i+1] = cum_pv[i] + c*v
    cum_v[i+1]  = cum_v[i] + v

def idx_at(ms):
    return bisect.bisect_left(ts_1m, ms)

def vwap_series_for_bars(anchor_ms, bars_list, tf_ms_local):
    """Возвращает [vwap@bar для каждого бара bars_list]. anchor_ms — момент начала накопления."""
    anchor_idx = idx_at(anchor_ms)
    res = []
    for b in bars_list:
        # vwap к концу бара
        end_ms = b[0] + tf_ms_local
        end_idx = min(idx_at(end_ms), len(m1))
        if end_idx <= anchor_idx:
            res.append(None); continue
        pv = cum_pv[end_idx] - cum_pv[anchor_idx]
        vol = cum_v[end_idx] - cum_v[anchor_idx]
        res.append(pv/vol if vol > 0 else None)
    return res

# для effectiveness — используем cascade {1h,2h,4h,6h,8h,12h}
cascade_bars = {tf: agg(m1, tf*MS) for tf in CASCADE_TFS_MIN}

def compute_eff(anchor_ms):
    per_tf = []
    for tf_min in CASCADE_TFS_MIN:
        bars_tf = cascade_bars[tf_min]
        # только бары после anchor и до win_end
        bars_after = [b for b in bars_tf if anchor_ms <= b[0] <= win_end]
        if len(bars_after) < 2:
            per_tf.append(effectiveness_per_tf(f"{tf_min}m", [], []))
            continue
        vw_series = vwap_series_for_bars(anchor_ms, bars_after, tf_min*MS)
        # подадим OHLC tuples (o,h,l,c)
        ohlc = [(b[1], b[2], b[3], b[4]) for b in bars_after]
        per_tf.append(effectiveness_per_tf(f"{tf_min}m", ohlc, vw_series))
    return composite_effectiveness(anchor_ms, per_tf)

print("\nВычисление effectiveness для VWAPs...")
fh_scored = []
for k, f in enumerate(fh):
    eff = compute_eff(f['pivot_close_ts'])
    fh_scored.append({**f, 'composite': eff.composite, 'interactions': eff.total_interactions})
    if k % 20 == 0: print(f"  FH {k+1}/{len(fh)}")
fl_scored = []
for k, f in enumerate(fl):
    eff = compute_eff(f['pivot_close_ts'])
    fl_scored.append({**f, 'composite': eff.composite, 'interactions': eff.total_interactions})
    if k % 20 == 0: print(f"  FL {k+1}/{len(fl)}")

# выборы
top_short = sorted(fh_scored, key=lambda x: -x['composite'])[:5]    # 5 SHORT (FH)
top_long  = sorted(fl_scored, key=lambda x: -x['composite'])[:5]    # 5 LONG (FL)
top_inter = sorted(fh_scored + fl_scored, key=lambda x: -x['interactions'])[:5]  # 5 max interactions

def _cs(arr): return [round(x['composite'], 3) for x in arr]
print(f"\nTOP 5 SHORT (FH): composites = {_cs(top_short)}")
print(f"TOP 5 LONG  (FL): composites = {_cs(top_long)}")
print(f"TOP 5 max INTER: counts     = {[x['interactions'] for x in top_inter]}")

# ── Plot ─────────────────────────────────────────────────────────────────────
def to_dt(ms): return datetime.fromtimestamp(ms/1000, MSK)

fig, ax = plt.subplots(figsize=(24, 13))

# Канон chart_format.md §2: bull=#01a648, bear=#131b1b
BULL_COLOR = '#01a648'
BEAR_COLOR = '#131b1b'
DOJI_COLOR = '#888'
bar_w = (TF_MIN/60)/24 * 0.7
for b in b6h_win:
    t = to_dt(b[0])
    o,h,l,c = b[1],b[2],b[3],b[4]
    color = BULL_COLOR if c > o else (BEAR_COLOR if c < o else DOJI_COLOR)
    ax.vlines(t, l, h, color=color, linewidth=0.6)
    ax.add_patch(plt.Rectangle((mdates.date2num(t)-bar_w/2, min(o,c)), bar_w, max(abs(o-c), 0.01),
                                facecolor=color, edgecolor=color, linewidth=0.4))

times = [to_dt(b[0]) for b in b6h_win]

def plot_line(ys, color, label, lw=2.0, ls='-'):
    pts = [(t,y) for t,y in zip(times, ys) if y is not None]
    if not pts: return
    xs, ys2 = zip(*pts)
    ax.plot(xs, ys2, color=color, linewidth=lw, linestyle=ls, label=label)

plot_line(hma78_12h_on_6h,  'royalblue',  'HMA-78 на 12h LIVE',  lw=2.2)
plot_line(hma78_D_on_6h,    'navy',       'HMA-78 на D LIVE',    lw=2.2, ls='--')
plot_line(hma200_12h_on_6h, 'darkorange', 'HMA-200 на 12h LIVE', lw=2.2)
plot_line(hma200_D_on_6h,   'saddlebrown','HMA-200 на D LIVE',   lw=2.2, ls='--')

# VWAPs (top short = crimson, top long = seagreen, top interactions = purple)
def plot_vwap(f, color, label, lw=1.4, alpha=0.85):
    anchor = f['pivot_close_ts']
    series = vwap_series_for_bars(anchor, b6h_win, TF_MS)
    pts = [(to_dt(t[0]), v) for t,v in zip(b6h_win, series) if v is not None]
    if not pts: return
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, linewidth=lw, alpha=alpha, label=label)
    if win_start <= f['t'] <= win_end:
        ax.scatter(to_dt(f['t']), f['price'],
                   marker='v' if 'FH' in label or 'SHORT' in label else '^',
                   color=color, s=90, zorder=5, edgecolor='black', linewidth=0.6)

# определяем y-диапазон чарта по price action
prices_in_view = [b[2] for b in b6h_win] + [b[3] for b in b6h_win]
y_min, y_max = min(prices_in_view), max(prices_in_view)
y_pad = (y_max - y_min) * 0.1
y_lo, y_hi = y_min - y_pad, y_max + y_pad

def vwap_in_view(f):
    """True если хотя бы половина VWAP попадает в y-диапазон чарта."""
    series = vwap_series_for_bars(f['pivot_close_ts'], b6h_win, TF_MS)
    vis = sum(1 for v in series if v is not None and y_lo <= v <= y_hi)
    total = sum(1 for v in series if v is not None)
    return total > 0 and vis / total >= 0.5

for i, f in enumerate(top_short):
    if vwap_in_view(f):
        plot_vwap(f, 'crimson', f"SHORT #{i+1} FH {to_dt(f['t']).strftime('%m-%d')} comp={f['composite']:.2f}")
for i, f in enumerate(top_long):
    if vwap_in_view(f):
        plot_vwap(f, 'seagreen', f"LONG #{i+1} FL {to_dt(f['t']).strftime('%m-%d')} comp={f['composite']:.2f}")
for i, f in enumerate(top_inter):
    side = 'FH' if any(x is f for x in fh_scored) else 'FL'
    if vwap_in_view(f):
        plot_vwap(f, 'purple', f"MAX-INT #{i+1} {side} {to_dt(f['t']).strftime('%m-%d')} n={f['interactions']}",
                  lw=1.6, alpha=0.65)

ax.set_ylim(y_lo, y_hi)

ax.xaxis.set_major_locator(mdates.AutoDateLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d', tz=MSK))
ax.grid(True, alpha=0.3)
ax.set_title(f"BTC 6h — TrendLine HMA-78/200 на 12h+D LIVE  +  VWAPs ASVK (TOP 5 LONG / 5 SHORT / 5 max-interactions)\n"
             f"100 последних D-фракталов  |  cascade composite {{1h,2h,4h,6h,8h,12h}}  |  "
             f"{to_dt(win_start).strftime('%Y-%m-%d')} → {to_dt(win_end).strftime('%Y-%m-%d')} MSK",
             fontsize=12)
ax.set_xlabel('Date MSK'); ax.set_ylabel('Price USDT')
ax.legend(loc='upper left', fontsize=7, ncol=2, framealpha=0.85)

fig.text(0.01, 0.005,
    "Правило 7 (TrendLine): HMA Hma mode, length 78+200, LIVE; HTF проецируется на 6h как последнее закрытое значение.   |   "
    "Правило 6 (VWAP): anchor = close D-pivot (упрощённый M1), composite eff по cascade {1h,2h,4h,6h,8h,12h}.",
    fontsize=8, color='gray')

plt.tight_layout()
out_path = OUT / f"btc_6h_trendline_vwap_top5_{to_dt(win_end).strftime('%Y-%m-%d')}.png"
plt.savefig(out_path, dpi=140, bbox_inches='tight')
print(f"\nSaved: {out_path}")
