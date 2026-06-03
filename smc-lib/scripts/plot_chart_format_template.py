"""Шаблон чарта по chart_format.md (итеративное разработка).

Текущее состояние:
  §1. Базовые: ТФ = 6h, окно 90 дней до последней даты.
  §2. Свечи: bull #01a648, bear #131b1b, doji #888.
  §3+ Индикаторы / зоны / маркеры — TBD (отключены).

Сохраняем PNG в ~/Desktop/i-rdrb-charts/
"""
from __future__ import annotations
import csv, pathlib, sys, subprocess
from datetime import datetime, timezone, timedelta
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

# ── Авто-докачка свежих 1m данных (chart_format.md §1) ────────────────────
FETCH_SCRIPT = pathlib.Path.home() / "smc-lib/scripts/fetch_btc_1m_missing.py"
print("Auto-updating 1m data from Binance...")
res = subprocess.run([sys.executable, str(FETCH_SCRIPT)], capture_output=True, text=True, timeout=120)
print(res.stdout.strip().split('\n')[-1] if res.stdout else '(no fetch output)')
if res.returncode != 0:
    print(f"  fetch warning: {res.stderr[:200]}")

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts"; OUT.mkdir(parents=True, exist_ok=True)
MSK = timezone(timedelta(hours=3))
MS = 60_000

# ── §1. Базовые ────────────────────────────────────────────────────────
TF_MIN = 360                # 6h
WINDOW_DAYS = 60            # 2 месяца крайних

# ── §2. Свечи ─────────────────────────────────────────────────────────
BULL_COLOR = '#01a648'
BEAR_COLOR = '#131b1b'
DOJI_COLOR = '#888'
CURRENT_PRICE_COLOR = '#c62828'                 # текущая цена красная (chart_format.md §4)
BAR_GAP_FRACTION = 0.5                          # промежуток между барами (доля TF)
BAR_WIDTH_FRACTION = 1.0 - BAR_GAP_FRACTION     # = 0.5 тела
BAR_LINEWIDTH = 1.1                             # ширина линии бара (chart_format.md §2)


TF_MS = TF_MIN * MS

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
b6h = agg(m1, TF_MS)
win_end = last_ts
win_start = win_end - WINDOW_DAYS*86400*1000
b6h_win = [b for b in b6h if win_start <= b[0] <= win_end]
print(f"  6h в окне: {len(b6h_win)}")

def to_dt(ms): return datetime.fromtimestamp(ms/1000, MSK)

fig, ax = plt.subplots(figsize=(24, 13))

bar_w = (TF_MIN/60)/24 * BAR_WIDTH_FRACTION
for b in b6h_win:
    t = to_dt(b[0])
    o,h,l,c = b[1],b[2],b[3],b[4]
    color = BULL_COLOR if c > o else (BEAR_COLOR if c < o else DOJI_COLOR)
    # Свечи на переднем плане (chart_format.md §6: linии — на заднем)
    ax.vlines(t, l, h, color=color, linewidth=BAR_LINEWIDTH, zorder=3)
    ax.add_patch(plt.Rectangle((mdates.date2num(t)-bar_w/2, min(o,c)), bar_w, max(abs(o-c), 0.01),
                                facecolor=color, edgecolor=color, linewidth=BAR_LINEWIDTH, zorder=3))

# X-ticks: каждый ПОНЕДЕЛЬНИК (открытие торговой недели) + сегодняшняя дата
# (chart_format.md §6)
today_dt = to_dt(win_end)
start_dt = to_dt(win_start)
weekday = today_dt.weekday()
last_monday = today_dt - timedelta(days=weekday)
last_monday = last_monday.replace(hour=0, minute=0, second=0, microsecond=0)
week_ticks = []
d = last_monday
while d >= start_dt:
    week_ticks.append(d)
    d -= timedelta(days=7)
week_ticks.reverse()
today_is_monday = today_dt.date() == last_monday.date()
if not today_is_monday:
    week_ticks.append(today_dt)
ax.set_xticks(week_ticks)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%d-%m', tz=MSK))
ax.grid(False)

# Сегодняшняя дата — только подсветка tick label, БЕЗ вертикальной линии
# (chart_format.md §4)
# Y-шкала справа, шаг 1000 (chart_format.md §6)
ax.yaxis.tick_right()
ax.yaxis.set_label_position('right')
ax.yaxis.set_major_locator(MultipleLocator(1000))

# Текущая цена — горизонтальная линия + дополнительный tick на шкале (chart_format.md §4)
current_price = m1[-1][4]   # close последнего 1m бара
# Тонкая пунктирная горизонтальная линия — на ЗАДНЕМ плане (chart_format.md §6)
ax.axhline(y=current_price, color=CURRENT_PRICE_COLOR, linewidth=0.9, linestyle=':', alpha=1.0, zorder=1)
# Добавляем current_price как tick на right-шкалу, скрываем близкие штатные ticks
fig.canvas.draw()
existing_ticks = list(ax.get_yticks())
# Если есть tick в радиусе 500 от current_price — убрать его (чтобы не перекрывались)
filtered = [t for t in existing_ticks if abs(t - current_price) > 500]
all_ticks = sorted(set(filtered + [current_price]))
ax.set_yticks(all_ticks)
labels = []
for t in all_ticks:
    if abs(t - current_price) < 0.5:
        labels.append(f' {current_price:,.0f} ')
    else:
        labels.append(f'{int(t):,}')
ax.set_yticklabels(labels)
for tick_label, t in zip(ax.get_yticklabels(), all_ticks):
    if abs(t - current_price) < 0.5:
        tick_label.set_color('white')
        tick_label.set_weight('bold')
        tick_label.set_fontsize(11)
        tick_label.set_bbox(dict(facecolor=CURRENT_PRICE_COLOR, edgecolor=CURRENT_PRICE_COLOR, pad=4))
# Заголовок: одна строка у границы картинки, центрирована по горизонтали
# (chart_format.md §5)
ASSET = 'BTC'
TF_LABEL = f"{TF_MIN // 60}h" if TF_MIN >= 60 else f"{TF_MIN}m"
now_dt = to_dt(win_end)
fig.text(0.5, 0.97,
         f"{ASSET}  |  {TF_LABEL}  |  {now_dt.strftime('%d-%m-%Y')}  |  {now_dt.strftime('%H:%M')} MSK",
         ha='center', va='top', fontsize=14, fontweight='bold')
# X-label убран (chart_format.md §5: лишний текст не нужен)

# Подсветить сегодняшний tick label красной плашкой, белым жирным
fig.canvas.draw()
for tick_label, tick_dt in zip(ax.get_xticklabels(), week_ticks):
    if tick_dt == today_dt:
        tick_label.set_color('white')
        tick_label.set_weight('bold')
        tick_label.set_fontsize(11)
        tick_label.set_bbox(dict(facecolor=CURRENT_PRICE_COLOR,
                                  edgecolor=CURRENT_PRICE_COLOR, pad=4))

# Симметричные отступы: правая часть имеет место для tick labels;
# делаем левую с равным отступом (chart_format.md §6)
plt.subplots_adjust(left=0.02, right=0.96, top=0.93, bottom=0.06)
out_path = OUT / f"btc_6h_template_{to_dt(win_end).strftime('%Y-%m-%d')}.png"
plt.savefig(out_path, dpi=140)
print(f"\nSaved: {out_path}")
