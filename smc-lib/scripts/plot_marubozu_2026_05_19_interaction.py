"""Иллюстрация взаимодействия с marubozu BTC 90m, 2026-05-19 19:30 MSK.

Цель = уровень open (76611.99). Цена должна вернуться к нему, проторговать
и продолжить в направлении исходного импульса (LONG).
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.marubozu.code import detect_marubozu

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
TF_MIN = 90


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def aggregate(d, tf_min):
    bucket = tf_min * 60_000
    out = []; cb = None; o = h = l = c = 0
    for ts, oo, hh, ll, cc in d:
        b = ts - (ts % bucket)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append((cb, o, h, l, c))
    return out


def fmt(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK)


print("Loading 1m..."); data = load_1m()
candles_90m = aggregate(data, TF_MIN)

# Marubozu 2026-05-19 19:30 MSK = 2026-05-19 16:30 UTC
marubozu_open_ms = int(datetime(2026, 5, 19, 16, 30, tzinfo=timezone.utc).timestamp() * 1000)
# Окно: за день до и до 2026-05-20 18:00 MSK = 15:00 UTC
window_start_ms = int(datetime(2026, 5, 19, 6, 0, tzinfo=timezone.utc).timestamp() * 1000)  # 09:00 MSK 19-го
window_end_ms = int(datetime(2026, 5, 20, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)   # 18:00 MSK 20-го
display = [c for c in candles_90m if window_start_ms <= c[0] <= window_end_ms]

# Найдём marubozu в окне
marubozu = None
for ts, o, h, l, c in display:
    r = detect_marubozu(Candle(open=o, high=h, low=l, close=c, open_time=ts))
    if r is not None and ts == marubozu_open_ms:
        marubozu = (ts, o, h, l, c, r.direction)
        break

assert marubozu is not None, "marubozu not found at expected time"
m_ts, m_o, m_h, m_l, m_c, m_dir = marubozu
open_level = m_o  # = m_l, для LONG это нижняя граница тела и сам low
print(f"Marubozu found: {fmt(m_ts).strftime('%Y-%m-%d %H:%M MSK')} {m_dir.upper()} open=low={m_o:.2f} close={m_c:.2f}")

# Найти первое касание open-уровня после marubozu close (= ts + 90m)
touch_idx = None; touch_ts = None; touch_low = None
m_close_ts = m_ts + TF_MIN * 60_000
for i, (ts, o, h, l, c) in enumerate(display):
    if ts < m_close_ts:
        continue
    if l <= open_level <= h:
        touch_idx = i; touch_ts = ts; touch_low = l
        break
print(f"First touch of open-level {open_level:.2f}: {fmt(touch_ts).strftime('%Y-%m-%d %H:%M MSK')} (bar low {touch_low:.2f})")

# Plot
fig, ax = plt.subplots(figsize=(18, 9))
WIDTH_DAYS = TF_MIN / 60 / 24 * 0.7

for i, (ts, o, h, l, c) in enumerate(display):
    x = mdates.date2num(fmt(ts + TF_MIN * 60_000 // 2))  # центр бара
    is_marubozu = (ts == m_ts)
    color = "#26a69a" if c >= o else "#ef5350"
    lw = 1.6 if is_marubozu else 0.7
    edgecolor = "#01579b" if is_marubozu else color
    ax.plot([x, x], [l, h], color=color, linewidth=lw, zorder=3)
    body_low, body_high = min(o, c), max(o, c)
    if body_high - body_low < 0.01: body_high = body_low + 0.01
    ax.add_patch(mpatches.Rectangle((x - WIDTH_DAYS / 2, body_low), WIDTH_DAYS, body_high - body_low,
                                    facecolor=color, edgecolor=edgecolor,
                                    linewidth=lw, alpha=0.9, zorder=4))

# Подсветка marubozu (рамка вокруг свечи + body fill)
m_x = mdates.date2num(fmt(m_ts + TF_MIN * 60_000 // 2))
ax.add_patch(mpatches.Rectangle(
    (m_x - WIDTH_DAYS / 1.4, m_l), WIDTH_DAYS / 0.7, m_h - m_l,
    facecolor="none", edgecolor="#01579b", linewidth=1.8,
    linestyle="--", alpha=0.7, zorder=5))

# Open-уровень — горизонтальная линия через всё окно (магнит)
x_start = mdates.date2num(fmt(m_ts))
x_end = mdates.date2num(fmt(window_end_ms))
ax.hlines(open_level, x_start, x_end, colors="#01579b", linewidth=2.2,
          linestyles="--", zorder=6,
          label=f"open level (магнит) = {open_level:.2f}")

# Тело marubozu — фон от формирования до касания
body_end_x = mdates.date2num(fmt(touch_ts + TF_MIN * 60_000 // 2))
ax.add_patch(mpatches.Rectangle(
    (x_start, m_o), body_end_x - x_start, m_c - m_o,
    facecolor="#e1f5fe", edgecolor="none", alpha=0.45, zorder=1,
    label=f"body (геометрия) [{m_o:.2f}, {m_c:.2f}]"))

# Маркер касания
ax.scatter([mdates.date2num(fmt(touch_ts + TF_MIN * 60_000 // 2))], [touch_low],
           s=240, marker="o", facecolor="#fff59d", edgecolor="#f57f17",
           linewidth=2, zorder=8, label=f"touch open @ {fmt(touch_ts).strftime('%m-%d %H:%M MSK')} (low={touch_low:.2f})")

# Аннотация на marubozu
ax.annotate("MARUBOZU LONG\n2026-05-19 19:30 MSK\nO=L=76611.99 → C=76856.76",
            xy=(m_x, m_l), xytext=(m_x - 0.4, m_l - 350),
            fontsize=10, fontweight="bold", color="#01579b",
            arrowprops=dict(arrowstyle="->", color="#01579b", lw=1.4),
            ha="center", va="top",
            bbox=dict(boxstyle="round,pad=0.35", facecolor="#e1f5fe",
                      edgecolor="#01579b", alpha=0.92))

# Аннотация на touch
t_x = mdates.date2num(fmt(touch_ts + TF_MIN * 60_000 // 2))
ax.annotate("ВОЗВРАТ К OPEN\n2026-05-20 03:00 MSK\nцена проторговала уровень",
            xy=(t_x, touch_low), xytext=(t_x + 0.3, touch_low - 350),
            fontsize=10, fontweight="bold", color="#f57f17",
            arrowprops=dict(arrowstyle="->", color="#f57f17", lw=1.4),
            ha="left", va="top",
            bbox=dict(boxstyle="round,pad=0.35", facecolor="#fff8e1",
                      edgecolor="#f57f17", alpha=0.92))

# Аннотация continuation
last_ts, _, last_h, _, _ = display[-1]
cont_x = mdates.date2num(fmt(last_ts))
ax.annotate("LONG continuation\nпосле проторговки open",
            xy=(cont_x, last_h), xytext=(cont_x - 0.5, last_h + 150),
            fontsize=10, fontweight="bold", color="#2e7d32",
            arrowprops=dict(arrowstyle="->", color="#2e7d32", lw=1.4),
            ha="center", va="bottom",
            bbox=dict(boxstyle="round,pad=0.35", facecolor="#e8f5e9",
                      edgecolor="#2e7d32", alpha=0.92))

ax.set_title("BTC 90m — взаимодействие с marubozu 2026-05-19 19:30 MSK: возврат к open → проторговка → LONG continuation",
             fontsize=12, fontweight="bold")
ax.set_ylabel("Price (USDT)")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M", tz=MSK))
ax.xaxis.set_major_locator(mdates.AutoDateLocator(tz=MSK, maxticks=14))
ax.grid(True, alpha=0.3)
ax.legend(loc="upper left", fontsize=10, framealpha=0.92)
plt.xticks(rotation=30)
plt.tight_layout()

OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/marubozu_2026_05_19_interaction.png"
plt.savefig(OUT, dpi=130, bbox_inches="tight")
plt.close()
print(f"Saved {OUT}")

# Дополнительная статистика по эффекту касания
post_touch = [c for c in display if c[0] >= touch_ts]
prices_after = [c[4] for c in post_touch]  # closes
max_after = max(prices_after)
min_after = min(prices_after)
print(f"\nПосле касания open ({fmt(touch_ts).strftime('%m-%d %H:%M MSK')}):")
print(f"  max close = {max_after:.2f}  ({(max_after - open_level)/open_level*100:+.2f}% от open)")
print(f"  min close = {min_after:.2f}  ({(min_after - open_level)/open_level*100:+.2f}% от open)")
print(f"  bar count = {len(post_touch)} (включая касание)")
