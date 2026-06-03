"""Chart TrendLine HMA-78 на 12h+D от 2026-02-01.

Показывает:
- 12h BTC candles от 2026-02-01 до конца данных
- HMA-78 на 12h (LIVE — отображается как prev-bar value на текущем баре)
- HMA-78 на D (значение текущего D бара протягивается через 2 × 12h)
- Маркеры для 3 user-указанных pivots: #11 (02-28 low), #26 (03-25 high), #47 (04-29 low)
"""
from __future__ import annotations
import csv, pathlib, sys, math
from datetime import datetime, timezone, timedelta
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from indicators.trend_line_asvk import wma

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/trendline_l78_l200_12h_d_from_feb1.png"
MSK = timezone(timedelta(hours=3))
UTC = timezone.utc
MS_M = 60_000
TF12 = 12*60*MS_M
TFD = 24*60*MS_M
HMA_LEN_DEFAULT = 78
HMA_LEN_LONG = 200

# Window
T_LO = int(datetime(2026, 2, 1, 0, 0, tzinfo=UTC).timestamp()*1000)

print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        ts = int(t.timestamp()*1000)
        rows.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4])))

last_ts = rows[-1][0]
T_HI = last_ts
print(f"  window: {datetime.fromtimestamp(T_LO/1000,MSK).strftime('%Y-%m-%d %H:%M')} → {datetime.fromtimestamp(T_HI/1000,MSK).strftime('%Y-%m-%d %H:%M')} MSK")

def aggregate(d, tfms):
    out=[]; cb=None; o=h=l=c=0.0
    for ts,oo,hh,ll,cc in d:
        b = ts - (ts % tfms)
        if b!=cb:
            if cb is not None: out.append((cb,o,h,l,c))
            cb=b; o,h,l,c=oo,hh,ll,cc
        else:
            h=max(h,hh); l=min(l,ll); c=cc
    if cb is not None: out.append((cb,o,h,l,c))
    return out

bars12 = aggregate(rows, TF12)
bars_d = aggregate(rows, TFD)

def hma(values, n):
    half = wma(values, n//2)
    full = wma(values, n)
    diff = [(2*half[i]-full[i]) if (half[i] is not None and full[i] is not None) else 0.0 for i in range(len(values))]
    sqrt_n = int(round(math.sqrt(n)))
    return wma(diff, sqrt_n)

closes_12 = [b[4] for b in bars12]
closes_d  = [b[4] for b in bars_d]
hma_12 = hma(closes_12, HMA_LEN_DEFAULT)
hma_d  = hma(closes_d,  HMA_LEN_DEFAULT)
hma_12_long = hma(closes_12, HMA_LEN_LONG)
hma_d_long  = hma(closes_d,  HMA_LEN_LONG)

# Filter to window
bars12_w = [(i, b) for i, b in enumerate(bars12) if T_LO <= b[0] <= T_HI]
print(f"  12h bars in window: {len(bars12_w)}")

td = np.array([b[0] for b in bars_d], dtype=np.int64)

# Plot
fig, ax = plt.subplots(figsize=(20, 10))
fig.patch.set_facecolor('#0e1117')
ax.set_facecolor('#0e1117')

width = timedelta(hours=4)
for i_global, b in bars12_w:
    ts, o, h, l, c = b
    x = datetime.fromtimestamp(ts/1000, MSK)
    is_bull = c >= o
    color = '#26a69a' if is_bull else '#ef5350'
    body_lo, body_hi = min(o,c), max(o,c)
    ax.plot([x,x],[l,h], color=color, lw=0.6, zorder=2)
    rect = mpatches.Rectangle((x - width/2, body_lo), width, max(body_hi-body_lo, 1), facecolor=color, edgecolor=color, lw=0.5, zorder=3)
    ax.add_patch(rect)

# 12h HMA LIVE — value at bar i = HMA[i-1] (предыдущий бар close)
x_12h = [datetime.fromtimestamp(b[0]/1000, MSK) for _, b in bars12_w]
y_12h_live = []
y_12h_long = []
for i_global, _ in bars12_w:
    y_12h_live.append(hma_12[i_global-1] if i_global-1 >= 0 else None)
    y_12h_long.append(hma_12_long[i_global-1] if i_global-1 >= 0 else None)
ax.plot(x_12h, y_12h_live, color='#2196f3', lw=1.6, label=f'HMA-{HMA_LEN_DEFAULT} on 12h (LIVE)', zorder=5)
ax.plot(x_12h, y_12h_long, color='#00bcd4', lw=2.2, label=f'HMA-{HMA_LEN_LONG} on 12h (LIVE)', zorder=5)

# D HMA LIVE — для каждого 12h бара берём HMA[D bar idx − 1] где D bar содержит 12h
def d_idx_for_ts(ts):
    idx = int(np.searchsorted(td, ts, side='right')) - 1
    return idx if 0 <= idx < len(bars_d) else None

y_d_live = []
y_d_long = []
for i_global, b in bars12_w:
    didx = d_idx_for_ts(b[0])
    if didx is None or didx-1 < 0:
        y_d_live.append(None); y_d_long.append(None); continue
    y_d_live.append(hma_d[didx-1])
    y_d_long.append(hma_d_long[didx-1])
ax.plot(x_12h, y_d_live, color='#ff9800', lw=2.0, label=f'HMA-{HMA_LEN_DEFAULT} on D (LIVE)', zorder=5)
ax.plot(x_12h, y_d_long, color='#e91e63', lw=2.4, label=f'HMA-{HMA_LEN_LONG} on D (LIVE)', zorder=5)

# Markers for 3 user-noted pivots
markers = [
    (11, datetime(2026,2,28,3,0,tzinfo=MSK), 'low'),
    (26, datetime(2026,3,25,3,0,tzinfo=MSK), 'high'),
    (47, datetime(2026,4,29,15,0,tzinfo=MSK), 'low'),
]
for num, dt, direction in markers:
    ax.axvline(dt, color='#ffeb3b', lw=1.5, ls='--', alpha=0.7, zorder=4)
    y_pos = ax.get_ylim()[0] if direction == 'low' else ax.get_ylim()[1]
    txt_y = 0.97 if direction == 'high' else 0.03
    ax.text(dt, txt_y, f'  #{num}', color='#ffeb3b', fontsize=11, fontweight='bold',
            transform=ax.get_xaxis_transform(), va=('top' if direction=='high' else 'bottom'),
            bbox=dict(facecolor='#1e2128', edgecolor='#ffeb3b', alpha=0.8, pad=3))

# Title and legend
ax.set_title(f'BTC 12h + HMA-{HMA_LEN_DEFAULT} & HMA-{HMA_LEN_LONG} (LIVE) на 12h и D — от 2026-02-01', color='white', fontsize=14, fontweight='bold', pad=15)
ax.legend(loc='upper left', facecolor='#1e2128', edgecolor='#444', labelcolor='white', fontsize=11)
ax.set_ylabel('BTC, USDT', color='white')
ax.tick_params(colors='white')
for spine in ax.spines.values(): spine.set_color('#444')
ax.grid(True, color='#222', lw=0.5, alpha=0.5)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d', tz=MSK))
ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
plt.setp(ax.get_xticklabels(), rotation=30, ha='right')

ax.set_xlim(x_12h[0], x_12h[-1])

plt.tight_layout()
OUT.parent.mkdir(exist_ok=True, parents=True)
plt.savefig(OUT, dpi=130, facecolor='#0e1117')
print(f"Saved: {OUT}")
