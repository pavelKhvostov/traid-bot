"""Чарт BTC с применением канонических индикаторов:

  - TrendLine ASVK (Правило 7): HMA-78 + HMA-200, LIVE (значение i = HMA[i-1])
  - VWAPs ASVK (Правило 6, упрощённо M1): anchored на close последних D-фракталов (Williams N=2)

TF графика: 4h, окно 60 дней до последней даты данных.
Сохраняем PNG в ~/Desktop/i-rdrb-charts/
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from indicators.trend_line_asvk import trend_line_hma_78, trend_line_hma_200

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts"; OUT.mkdir(parents=True, exist_ok=True)
MSK = timezone(timedelta(hours=3))
MS = 60_000
TF_MIN = 240            # 4h
TF_MS = TF_MIN * MS
WINDOW_DAYS = 60
N_FRACTAL = 2
N_LAST_FRACTALS = 5     # сколько последних D-фракталов взять для VWAP

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
print(f"  {len(m1)} 1m bars, последний: {datetime.fromtimestamp(last_ts/1000, MSK)}")

# Агрегаты
b4h = agg(m1, TF_MS)
bD  = agg(m1, 86400*1000)

# ── Окно для отображения ─────────────────────────────────────────────────────
win_end = last_ts
win_start = win_end - WINDOW_DAYS*86400*1000
b4h_win = [b for b in b4h if win_start <= b[0] <= win_end]
print(f"  4h в окне: {len(b4h_win)}")

# ── 1) TrendLine на 4h (HMA-78 + HMA-200, LIVE) ──────────────────────────────
# Используем все 4h бары (не только окно), чтобы прогреть HMA, потом срезаем
closes_4h = [b[4] for b in b4h]
hma78 = trend_line_hma_78(closes_4h)['mhull']
hma200 = trend_line_hma_200(closes_4h)['mhull']

# LIVE: на bar i отображаем значение HMA[i-1] (то что было видно при открытии бара i)
def live_shift(arr):
    return [None] + arr[:-1]
hma78_live = live_shift(hma78)
hma200_live = live_shift(hma200)

# Срезаем под окно
idx_first = next(i for i, b in enumerate(b4h) if b[0] >= win_start)
b4h_plot = b4h[idx_first:]
b4h_plot = [b for b in b4h_plot if b[0] <= win_end]
hma78_plot = hma78_live[idx_first:idx_first+len(b4h_plot)]
hma200_plot = hma200_live[idx_first:idx_first+len(b4h_plot)]

# ── 2) Williams D-фракталы (N=2) до win_end ──────────────────────────────────
def williams_fractals(bars, n=N_FRACTAL):
    fh, fl = [], []   # (pivot_idx, pivot_time, pivot_price, confirm_time)
    for i in range(n, len(bars)-n):
        h_i = bars[i][2]; l_i = bars[i][3]
        if h_i > max(bars[i-k][2] for k in range(1,n+1)) and h_i > max(bars[i+k][2] for k in range(1,n+1)):
            confirm_ts = bars[i+n][0] + 86400*1000  # подтверждено после close i+n
            fh.append({'i':i, 't':bars[i][0], 'price':h_i, 'confirm_ts':confirm_ts, 'pivot_close_ts':bars[i][0]+86400*1000})
        if l_i < min(bars[i-k][3] for k in range(1,n+1)) and l_i < min(bars[i+k][3] for k in range(1,n+1)):
            confirm_ts = bars[i+n][0] + 86400*1000
            fl.append({'i':i, 't':bars[i][0], 'price':l_i, 'confirm_ts':confirm_ts, 'pivot_close_ts':bars[i][0]+86400*1000})
    return fh, fl

fh_all, fl_all = williams_fractals(bD)
# Берём последние N до win_end (но чтобы pivot был ≥ win_start - 30d, иначе VWAP далеко)
margin = 30*86400*1000
fh_recent = [f for f in fh_all if win_start - margin <= f['t'] <= win_end][-N_LAST_FRACTALS:]
fl_recent = [f for f in fl_all if win_start - margin <= f['t'] <= win_end][-N_LAST_FRACTALS:]
print(f"  D-fractals: FH={len(fh_recent)}, FL={len(fl_recent)} (anchor для VWAP)")

# ── 3) Anchored VWAP от каждого фрактала (Метод 1: anchor = pivot close) ─────
# Для расчёта: cum_pv и cum_vol на 1m с момента anchor
ts_1m = [r[0] for r in m1]

def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo+hi)//2
        if ts_1m[m] < ms: lo = m+1
        else: hi = m
    return lo

def vwap_from(anchor_ms, end_ms):
    start = idx_at(anchor_ms); end = idx_at(end_ms) + 1
    out = []
    cum_pv = 0.0; cum_v = 0.0
    for i in range(start, min(end, len(m1))):
        ts, o, h, l, c, v = m1[i]
        cum_pv += c * v; cum_v += v
        if cum_v > 0: out.append((ts, cum_pv/cum_v))
    return out

vwaps = []  # (label, color, series, fractal_dict, side)
for f in fh_recent:
    anchor = f['pivot_close_ts']  # close D-бара пивота
    series = vwap_from(anchor, win_end)
    vwaps.append((f"FH {datetime.fromtimestamp(f['t']/1000, MSK).strftime('%m-%d')}", 'crimson', series, f, 'FH'))
for f in fl_recent:
    anchor = f['pivot_close_ts']
    series = vwap_from(anchor, win_end)
    vwaps.append((f"FL {datetime.fromtimestamp(f['t']/1000, MSK).strftime('%m-%d')}", 'seagreen', series, f, 'FL'))

# ── 4) Plot ─────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(20, 11))

# OHLC bars
def to_dt(ms): return datetime.fromtimestamp(ms/1000, MSK)

bar_w = (TF_MIN/60) / 24 * 0.7  # ширина бара в днях
for b in b4h_plot:
    t = to_dt(b[0]); o = b[1]; h = b[2]; l = b[3]; c = b[4]
    color = '#888' if c == o else ('#26a69a' if c > o else '#ef5350')
    ax.vlines(t, l, h, color=color, linewidth=0.7)
    ax.add_patch(plt.Rectangle((mdates.date2num(t) - bar_w/2, min(o,c)), bar_w, abs(o-c) or 0.01,
                                 facecolor=color, edgecolor=color, linewidth=0.5))

# TrendLines
times_plot = [to_dt(b[0]) for b in b4h_plot]
ax.plot([t for t,v in zip(times_plot, hma78_plot) if v is not None],
        [v for v in hma78_plot if v is not None],
        color='royalblue', linewidth=2.2, label='HMA-78 LIVE (Правило 7)')
ax.plot([t for t,v in zip(times_plot, hma200_plot) if v is not None],
        [v for v in hma200_plot if v is not None],
        color='darkorange', linewidth=2.2, label='HMA-200 LIVE (Правило 7)')

# VWAPs
for label, color, series, f, side in vwaps:
    if not series: continue
    series = [(to_dt(t), v) for t, v in series if win_start <= t <= win_end]
    if not series: continue
    xs, ys = zip(*series)
    ax.plot(xs, ys, color=color, linewidth=1.1, alpha=0.65, label=label)
    # маркер anchor
    if win_start <= f['t'] <= win_end:
        ax.scatter(to_dt(f['t']), f['price'],
                   marker='v' if side=='FH' else '^', color=color, s=80, zorder=5,
                   edgecolor='black', linewidth=0.5)

# Грид + ось
ax.xaxis.set_major_locator(mdates.AutoDateLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d', tz=MSK))
ax.grid(True, alpha=0.3)
ax.set_title(f"BTC 4h — TrendLine ASVK (HMA-78 + HMA-200 LIVE) + VWAPs ASVK от D-фракталов\n"
             f"Окно: {to_dt(win_start).strftime('%Y-%m-%d')} → {to_dt(win_end).strftime('%Y-%m-%d')} MSK",
             fontsize=13)
ax.set_xlabel('Date MSK')
ax.set_ylabel('Price USDT')
ax.legend(loc='best', fontsize=8, ncol=2, framealpha=0.85)

# Подпись правил снизу
fig.text(0.01, 0.01,
    "Правило 6 (VWAP): anchor = close D-пивота (Williams N=2), упрощённый M1   |   "
    "Правило 7 (TrendLine): HMA mode Hma, length 78 + 200, value LIVE",
    fontsize=8, color='gray')

plt.tight_layout()
out_path = OUT / f"btc_4h_trendline_vwap_canon_{to_dt(win_end).strftime('%Y-%m-%d')}.png"
plt.savefig(out_path, dpi=130, bbox_inches='tight')
print(f"\nSaved: {out_path}")
