"""D-фрактал anchored VWAPs на 1h display — demo по Правилу 6.

Канон (Правило 6, ~/smc-lib/rules.md): VWAPs ASVK строятся ТОЛЬКО от
D-фракталов (Williams N=2 на дневном TF). Anchor — в диапазоне свечи i+1
(следующего D-бара после пивота), окно 24h, сетка 15m → 96 кандидатов.

В этом demo для наглядности anchor = открытие i+1 D-бара (первый кандидат
из 15m-сетки). Полный канон выбирает argmax composite_effectiveness по
cascade (1h/2h/4h/6h/8h/12h), см. ~/smc-lib/indicators/vwap_effectiveness.py.

Дисплей: 1h свечи (один из cascade TFs).
"""
from __future__ import annotations
import csv, pathlib, subprocess, sys
from datetime import datetime, timezone, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.cm import get_cmap

MSK = timezone(timedelta(hours=3))
MS = 60_000
CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts"
OUT.mkdir(parents=True, exist_ok=True)

WINDOW_DAYS = 30        # дней истории на дисплее (D-фракталы редкие)
DISPLAY_TF_MIN = 60     # 1h свечи на дисплее (один из cascade TFs)
FRACTAL_TF_MIN = 1440   # D-фракталы (24h)
N_FRACTAL = 2
CONFIRM_BARS = N_FRACTAL + 1   # 3 D-бара после pivot для подтверждения
MAX_FH = 4              # сколько последних FH показать
MAX_FL = 4              # сколько последних FL показать

BULL = '#01a648'; BEAR = '#131b1b'; DOJI = '#888'
GRID = '#dddddd'

# ── docka свежих 1m ──────────────────────────────────────────────
FETCH = pathlib.Path.home() / "smc-lib/scripts/fetch_btc_1m_missing.py"
if FETCH.exists():
    print("Fetching 1m...")
    r = subprocess.run([sys.executable, str(FETCH)], capture_output=True, text=True, timeout=120)
    print((r.stdout.strip().split('\n')[-1] if r.stdout else '') or '(no fetch output)')

# ── загрузка ─────────────────────────────────────────────────────
print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]),
                     float(r[3]), float(r[4]), float(r[5])))

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

last_ts = rows[-1][0]
win_end = last_ts
win_start = win_end - WINDOW_DAYS*86400*1000

# 1m с запасом 5 дней до начала окна — нужно для D-фракталов
# у границы окна (нужны 1m бары от их pivot+1d → VWAP)
m1 = [r for r in rows if r[0] >= win_start - 5*86400*1000]
b_disp = agg(m1, DISPLAY_TF_MIN*MS)
b_fr = agg(m1, FRACTAL_TF_MIN*MS)
print(f"  display ({DISPLAY_TF_MIN}m) bars: {len(b_disp)}, "
      f"fractal ({FRACTAL_TF_MIN}m) bars: {len(b_fr)}")

# ── D Williams фракталы N=2, с подтверждением ────────────────────
fractals = []   # (kind, pivot_ts, level, ip)  kind ∈ {'FH','FL'}
for i in range(N_FRACTAL, len(b_fr) - N_FRACTAL - CONFIRM_BARS + N_FRACTAL):
    # требуем что после pivot есть как минимум CONFIRM_BARS-N_FRACTAL новых баров (= уже подтверждённых)
    if i + N_FRACTAL >= len(b_fr): continue
    center = b_fr[i]
    others = b_fr[i-N_FRACTAL:i] + b_fr[i+1:i+1+N_FRACTAL]
    if all(center[2] > o[2] for o in others):
        fractals.append(('FH', center[0], center[2], i))
    elif all(center[3] < o[3] for o in others):
        fractals.append(('FL', center[0], center[3], i))

# фильтруем только те, что в окне дисплея
disp_start = win_start
fractals = [f for f in fractals if disp_start <= f[1] <= win_end]
print(f"  D fractals in window: {len(fractals)}")

# ограничиваем до последних MAX_FH FH и MAX_FL FL для читаемости
fh_list = [f for f in fractals if f[0] == 'FH'][-MAX_FH:]
fl_list = [f for f in fractals if f[0] == 'FL'][-MAX_FL:]
fractals = sorted(fh_list + fl_list, key=lambda f: f[1])
print(f"  shown after cap: FH={len(fh_list)} FL={len(fl_list)}")

# ── для каждого фрактала: anchor = open of i+1 D bar; VWAP по 1m ──
TF_FR_MS = FRACTAL_TF_MIN * MS

def anchored_vwap_1m_from(anchor_ts_ms, end_ts_ms):
    """typical-price weighted VWAP по 1m с момента anchor_ts_ms до end_ts_ms (incl)."""
    cum_pv = 0.0; cum_v = 0.0
    points = []   # (ts, vwap)
    for ts, o, h, l, c, v in rows:
        if ts < anchor_ts_ms: continue
        if ts > end_ts_ms: break
        tp = (h + l + c) / 3.0
        cum_pv += tp * v
        cum_v  += v
        if cum_v > 0:
            points.append((ts, cum_pv / cum_v))
    return points

vwap_lines = []   # (kind, anchor_ts, level, points, i_plus_1_open, i_plus_1_close)
for kind, pts, lvl, ip in fractals:
    # i+1 окно
    ip1_open = pts + TF_FR_MS
    ip1_close = ip1_open + TF_FR_MS
    # canon: anchor динамический в [ip1_open, ip1_close) с шагом 15m (4 кандидата).
    # В этом demo: берём первый кандидат (ip1_open) для наглядности правила
    # (полный канон: argmax composite_effectiveness; см. caption).
    anchor = ip1_open
    points = anchored_vwap_1m_from(anchor, win_end)
    if points:
        vwap_lines.append((kind, anchor, lvl, points, ip1_open, ip1_close))

# ── рисуем display свечи + VWAP линии ────────────────────────────
b_disp_win = [b for b in b_disp if win_start <= b[0] <= win_end]
print(f"  display bars в окне: {len(b_disp_win)}")

def to_dt(ms): return datetime.fromtimestamp(ms/1000, MSK)

fig, ax = plt.subplots(figsize=(22, 11))
bar_w = (DISPLAY_TF_MIN/60)/24 * 0.5

for ts, o, h, l, c, v in b_disp_win:
    x = mdates.date2num(to_dt(ts + DISPLAY_TF_MIN*MS//2))   # центр бара
    color = BULL if c > o else (BEAR if c < o else DOJI)
    ax.plot([x, x], [l, h], color=color, lw=0.8, alpha=0.7, zorder=2)
    ax.add_patch(plt.Rectangle((x - bar_w/2, min(o, c)), bar_w, abs(c - o) or (h-l)*0.001,
                               color=color, lw=0, zorder=3))

# i+1 окна для каждого фрактала — лёгкая вертикальная заливка
for kind, anchor, lvl, points, ip1o, ip1c in vwap_lines:
    color = '#dc3545' if kind == 'FH' else '#28a745'
    ax.axvspan(mdates.date2num(to_dt(ip1o)), mdates.date2num(to_dt(ip1c)),
               facecolor=color, alpha=0.08, zorder=1)

# VWAP линии с градиентом «свежий → старый»
fh_count = sum(1 for v in vwap_lines if v[0] == 'FH')
fl_count = sum(1 for v in vwap_lines if v[0] == 'FL')
reds = get_cmap('Reds')
greens = get_cmap('Greens')
fh_idx = 0; fl_idx = 0
# самые свежие фракталы = тёмный конец градиента
vwap_lines_sorted = sorted(vwap_lines, key=lambda x: -x[1])  # свежий первым
for kind, anchor, lvl, points, ip1o, ip1c in vwap_lines_sorted:
    xs = [mdates.date2num(to_dt(t)) for t, _ in points]
    ys = [v for _, v in points]
    if kind == 'FH':
        shade = 0.85 - (fh_idx / max(fh_count, 1)) * 0.55
        col = reds(shade)
        fh_idx += 1
    else:
        shade = 0.85 - (fl_idx / max(fl_count, 1)) * 0.55
        col = greens(shade)
        fl_idx += 1
    ax.plot(xs, ys, color=col, lw=2.0, alpha=0.95, zorder=4)
    if points:
        # маркер выбранного anchor'a (точка старта VWAP)
        ax.scatter([mdates.date2num(to_dt(anchor))], [points[0][1]],
                   marker='o', s=70, color=col, edgecolor='black', lw=0.8, zorder=6)
        # маркер pivot (level фрактала) ровно над/под pivot-баром
        pivot_ts = anchor - TF_FR_MS   # pivot bar = i, anchor = i+1.open
        ax.scatter([mdates.date2num(to_dt(pivot_ts + TF_FR_MS//2))], [lvl],
                   marker='v' if kind == 'FH' else '^',
                   s=110, color=col, edgecolor='black', lw=0.7, zorder=6)
        # подпись уровня (цена)
        ax.annotate(f"{kind} {lvl:.0f}",
                    xy=(mdates.date2num(to_dt(pivot_ts + TF_FR_MS//2)), lvl),
                    xytext=(0, 12 if kind == 'FH' else -16),
                    textcoords='offset points', fontsize=8,
                    ha='center', color=col, fontweight='bold', zorder=7)

ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M', tz=MSK))
ax.xaxis.set_major_locator(mdates.AutoDateLocator())
fig.autofmt_xdate()
ax.grid(True, color=GRID, lw=0.5, alpha=0.6)
ax.set_xlim(mdates.date2num(to_dt(win_start)), mdates.date2num(to_dt(win_end)))

# limits Y
all_p = [b[2] for b in b_disp_win] + [b[3] for b in b_disp_win]
ax.set_ylim(min(all_p)*0.998, max(all_p)*1.002)

title = (f"BTCUSDT — D-фрактал anchored VWAPs на 1h (demo по Правилу 6)\n"
         f"display TF=1h, fractal TF=D, N=2 Williams, окно {WINDOW_DAYS}d (МСК)\n"
         f"FH={fh_count}  FL={fl_count}  |  anchor = открытие i+1 D-бара "
         f"(первый из 15m-сетки; канон: argmax composite по cascade)")
ax.set_title(title, fontsize=11, loc='left')
ax.set_ylabel("Price (USDT)")

stamp = datetime.now(MSK).strftime('%Y%m%d_%H%M')
out_path = OUT / f"vwap_1h_fractals_demo_{stamp}.png"
plt.tight_layout()
plt.savefig(out_path, dpi=140)
print(f"\nSaved: {out_path}")
