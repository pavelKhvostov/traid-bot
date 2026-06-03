"""3-панельный D-обзор зон интереса BTC с 2026-04-04 по сегодня.
Панели: efficiency / inefficiency / liquidity. Общий x-axis."""
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
from elements.ob.code import detect_ob
from elements.block_orders.code import detect_block_orders
from elements.ob_liq.code import detect_ob_liq
from elements.rb.code import detect_rb
from elements.fvg.code import detect_fvg
from elements.i_fvg.code import detect_i_fvg
from elements.rdrb.code import detect_rdrb
from elements.i_rdrb.code import detect_i_rdrb
from patterns.i_rdrb_fvg.code import detect_i_rdrb_fvg
from elements.marubozu.code import detect_marubozu
from elements.fractal.code import detect_fractal

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
TF_MIN = 1440


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


def to_candle(row):
    ts, o, h, l, c = row
    return Candle(open=o, high=h, low=l, close=c, open_time=ts)


def fmt(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK)


print("Loading 1m...")
data = load_1m()
d_all = aggregate(data, TF_MIN)
last_1m_ts = data[-1][0]
if last_1m_ts < d_all[-1][0] + TF_MIN * 60_000 - 60_000:
    d_all = d_all[:-1]

candles_all = [to_candle(r) for r in d_all]


def in_window(ts):
    return fmt(ts).date() >= datetime(2026, 4, 4).date()


idx_in = [i for i, r in enumerate(d_all) if in_window(r[0])]
first_idx, last_idx = min(idx_in), max(idx_in)
print(f"Window: D[{first_idx}..{last_idx}] = {last_idx-first_idx+1} bars")


def center_in_window(i):
    return first_idx <= i <= last_idx


# ============== Детекция (как в survey-скрипте) ==============
hits_eff = []      # efficiency
hits_ineff = []    # inefficiency
hits_liq = []      # liquidity

# OB
for i in range(1, len(candles_all)):
    if not center_in_window(i): continue
    r = detect_ob(candles_all[i-1], candles_all[i])
    if r: hits_eff.append(('OB', d_all[i][0], r.zone, r.direction, r))

# block_orders
seen = set()
for end in range(2, len(candles_all)):
    if not center_in_window(end): continue
    for start in range(max(0, end - 6), end - 1):
        slice_ = candles_all[start:end+1]
        r = detect_block_orders(slice_)
        if r:
            key = (d_all[start+1][0], r.n_initial, r.n_counter)
            if key in seen: continue
            seen.add(key)
            hits_eff.append(('BO', d_all[end][0], r.zone, r.direction, r))

# ob_liq
for i in range(2, len(candles_all) - 2):
    if not center_in_window(i): continue
    r = detect_ob_liq(candles_all[i], candles_all[i+1])
    if r: hits_eff.append(('OBL', d_all[i][0], r.zone, r.direction, r))

# rdrb
for i in range(1, len(candles_all) - 1):
    if not center_in_window(i): continue
    r = detect_rdrb(candles_all[i-1], candles_all[i], candles_all[i+1])
    if r: hits_eff.append(('RDRB', d_all[i+1][0], r.poi, r.direction, r))

# i_rdrb
for i in range(1, len(candles_all) - 2):
    if not center_in_window(i+2): continue
    r = detect_i_rdrb(candles_all[i-1], candles_all[i], candles_all[i+1], candles_all[i+2])
    if r: hits_eff.append(('iRD', d_all[i+2][0], r.rdrb.poi, r.direction, r))

# i_rdrb_fvg → две зоны: одна efficiency (RDRB-POI), одна inefficiency (FVG)
for i in range(1, len(candles_all) - 3):
    if not center_in_window(i+3): continue
    r = detect_i_rdrb_fvg(candles_all[i-1], candles_all[i], candles_all[i+1], candles_all[i+2], candles_all[i+3])
    if r:
        hits_eff.append(('iRDF', d_all[i+3][0], r.irdrb.rdrb.poi, r.direction, r))
        hits_ineff.append(('iRDF.fvg', d_all[i+3][0], r.fvg.zone, r.direction, r))

# FVG
for i in range(1, len(candles_all) - 1):
    if not center_in_window(i): continue
    r = detect_fvg(candles_all[i-1], candles_all[i], candles_all[i+1])
    if r: hits_ineff.append(('FVG', d_all[i+1][0], r.zone, r.direction, r))

# i_fvg
all_fvgs_idx = []
for i in range(1, len(candles_all) - 1):
    r = detect_fvg(candles_all[i-1], candles_all[i], candles_all[i+1])
    if r: all_fvgs_idx.append((i+1, r, i-1, i+1))

for a_c3_idx, a, a_c1_idx, _ in all_fvgs_idx:
    for b_c3_idx, b, b_c1_idx, _ in all_fvgs_idx:
        if b.direction == a.direction: continue
        if b_c1_idx <= a_c3_idx: continue
        if not center_in_window(b_c3_idx): continue
        between = candles_all[a_c3_idx+1:b_c1_idx]
        result = detect_i_fvg(
            candles_all[a_c1_idx], candles_all[a_c1_idx+1], candles_all[a_c3_idx],
            between,
            candles_all[b_c1_idx], candles_all[b_c1_idx+1], candles_all[b_c3_idx],
        )
        if result:
            hits_ineff.append(('iFVG', d_all[b_c3_idx][0], result.overlap, result.direction, result))
            break

# marubozu (0 ожидается на D, но проверим)
for i in range(len(candles_all)):
    if not center_in_window(i): continue
    r = detect_marubozu(candles_all[i])
    if r: hits_ineff.append(('MAR', d_all[i][0], r.zone, r.direction, r))

# rb
for i in range(len(candles_all)):
    if not center_in_window(i): continue
    r = detect_rb(candles_all[i])
    if r: hits_liq.append(('RB', d_all[i][0], r.zone, r.direction, r))

# fractal
fractal_hits = []
for i in range(2, len(candles_all) - 2):
    if not center_in_window(i): continue
    r = detect_fractal(candles_all[i-2:i+3], n=2)
    if r: fractal_hits.append((d_all[i][0], r))

print(f"\nDetections: eff={len(hits_eff)}, ineff={len(hits_ineff)}, liq={len(hits_liq)}, fractal={len(fractal_hits)}")

# ============== Plot ==============
display = [d_all[i] for i in range(first_idx - 2, last_idx + 1)]  # +2 свечи слева для контекста
x_first_ms = display[0][0]
x_last_ms = display[-1][0] + TF_MIN * 60_000

fig, axes = plt.subplots(3, 1, figsize=(22, 16), sharex=True)
ax_eff, ax_ineff, ax_liq = axes

W_DAYS = TF_MIN / 60 / 24 * 0.6


def draw_candles(ax):
    for ts, o, h, l, c in display:
        x = mdates.date2num(fmt(ts + TF_MIN * 60_000 // 2))
        color = "#26a69a" if c >= o else "#ef5350"
        ax.plot([x, x], [l, h], color=color, linewidth=0.5, zorder=3)
        body_low, body_high = min(o, c), max(o, c)
        if body_high - body_low < 1: body_high = body_low + 1
        ax.add_patch(mpatches.Rectangle((x - W_DAYS / 2, body_low), W_DAYS, body_high - body_low,
                                        facecolor=color, edgecolor=color, alpha=0.85, zorder=4))


# Цветовая палитра по типу (efficiency)
eff_colors = {
    'OB':   ('#ff6f00', '#ffe0b2'),   # оранжевый
    'BO':   ('#bf360c', '#ffccbc'),   # тёмно-оранжевый
    'OBL':  ('#6a1b9a', '#e1bee7'),   # фиолетовый
    'RDRB': ('#1565c0', '#bbdefb'),   # синий
    'iRD':  ('#0d47a1', '#90caf9'),   # тёмно-синий
    'iRDF': ('#004d40', '#b2dfdb'),   # бирюзовый
}
ineff_colors = {
    'FVG':       ('#01579b', '#b3e5fc'),
    'iFVG':      ('#f57f17', '#fff59d'),
    'iRDF.fvg':  ('#004d40', '#b2dfdb'),
    'MAR':       ('#37474f', '#cfd8dc'),
}
liq_colors = {
    'RB':       ('#558b2f', '#dcedc8'),
    'fractal_h': '#c62828',
    'fractal_l': '#2e7d32',
}


def draw_zones(ax, hits, palette, extend_bars=4):
    """Рисует короткие прямоугольники от формирования вперёд на extend_bars баров."""
    for kind, ts, zone, direction, r in hits:
        edge_c, face_c = palette.get(kind, ('#666', '#ccc'))
        x_start = mdates.date2num(fmt(ts))
        x_end = mdates.date2num(fmt(ts + extend_bars * TF_MIN * 60_000))
        ax.add_patch(mpatches.Rectangle(
            (x_start, zone[0]), x_end - x_start, zone[1] - zone[0],
            facecolor=face_c, edgecolor=edge_c, linewidth=0.9, alpha=0.55, zorder=2))
        # Маркер с типом + направлением
        marker = "▲" if direction == "long" else "▼"
        ax.text(x_start, zone[1 if direction == 'long' else 0],
                f"{marker}{kind}", fontsize=6.5, color=edge_c, fontweight="bold",
                ha="left", va=("bottom" if direction == 'long' else 'top'),
                zorder=7,
                bbox=dict(boxstyle="round,pad=0.1", facecolor="white", edgecolor=edge_c,
                          linewidth=0.4, alpha=0.85))


# Panel 1: Efficiency
draw_candles(ax_eff)
draw_zones(ax_eff, hits_eff, eff_colors, extend_bars=4)
ax_eff.set_title(f"BTC D — Efficiency zones (OB / block_orders / RDRB / i_rdrb / i_rdrb_fvg / ob_liq)  ·  {len(hits_eff)} зон",
                 fontsize=12, fontweight="bold")
ax_eff.set_ylabel("Price")
ax_eff.grid(True, alpha=0.25)
ax_eff.set_ylim(min(c[3] for c in display) - 1500, max(c[2] for c in display) + 1500)

# Legend efficiency
legend_eff = [mpatches.Patch(facecolor=eff_colors[k][1], edgecolor=eff_colors[k][0], label=k) for k in eff_colors]
ax_eff.legend(handles=legend_eff, loc="upper left", fontsize=8, framealpha=0.92, ncol=3)

# Panel 2: Inefficiency (🧲 magnets)
draw_candles(ax_ineff)
draw_zones(ax_ineff, hits_ineff, ineff_colors, extend_bars=4)
ax_ineff.set_title(f"BTC D — Inefficiency zones 🧲 (FVG / i_FVG / marubozu / i_rdrb_fvg.fvg)  ·  {len(hits_ineff)} зон",
                   fontsize=12, fontweight="bold")
ax_ineff.set_ylabel("Price")
ax_ineff.grid(True, alpha=0.25)
ax_ineff.set_ylim(min(c[3] for c in display) - 1500, max(c[2] for c in display) + 1500)

legend_ineff = [mpatches.Patch(facecolor=ineff_colors[k][1], edgecolor=ineff_colors[k][0], label=k) for k in ineff_colors]
ax_ineff.legend(handles=legend_ineff, loc="upper left", fontsize=8, framealpha=0.92)

# Panel 3: Liquidity (RB + fractals as point levels)
draw_candles(ax_liq)
draw_zones(ax_liq, hits_liq, liq_colors, extend_bars=4)

# Fractals — горизонтальные линии от формирования вперёд
for ts, r in fractal_hits:
    x_start = mdates.date2num(fmt(ts))
    x_end = mdates.date2num(fmt(ts + 12 * TF_MIN * 60_000))  # тянем на 12 дней
    color = liq_colors['fractal_h'] if r.direction == 'high' else liq_colors['fractal_l']
    marker_plot = "v" if r.direction == 'high' else "^"
    marker_text = "▼" if r.direction == 'high' else "▲"
    ax_liq.hlines(r.level, x_start, x_end, colors=color, linewidth=1.5, linestyles='--',
                  alpha=0.7, zorder=5)
    ax_liq.scatter([x_start], [r.level], s=60, c=color, marker=marker_plot, zorder=6,
                   edgecolor="black", linewidths=0.4)
    ax_liq.text(x_start, r.level, f" {marker_text}{r.level:.0f}", fontsize=7, color=color,
                ha="left", va="center", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor=color,
                          linewidth=0.4, alpha=0.85), zorder=8)

ax_liq.set_title(f"BTC D — Liquidity zones 🧲 (RB {len(hits_liq)} + Fractals {len(fractal_hits)})",
                 fontsize=12, fontweight="bold")
ax_liq.set_ylabel("Price")
ax_liq.grid(True, alpha=0.25)
ax_liq.set_ylim(min(c[3] for c in display) - 1500, max(c[2] for c in display) + 1500)

legend_liq = [
    mpatches.Patch(facecolor=liq_colors['RB'][1], edgecolor=liq_colors['RB'][0], label="RB"),
    plt.Line2D([], [], color=liq_colors['fractal_h'], linestyle='--', label="FH"),
    plt.Line2D([], [], color=liq_colors['fractal_l'], linestyle='--', label="FL"),
]
ax_liq.legend(handles=legend_liq, loc="upper left", fontsize=8, framealpha=0.92)

# Common x-axis
for ax in axes:
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d", tz=MSK))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3, tz=MSK))

axes[-1].tick_params(axis='x', rotation=45)

fig.suptitle(f"BTC D — все зоны интереса с 2026-04-04 по {fmt(d_all[last_idx][0]).strftime('%Y-%m-%d')}  ·  всего {len(hits_eff) + len(hits_ineff) + len(hits_liq) + len(fractal_hits)} зон по 11 элементам",
             fontsize=14, fontweight="bold", y=0.995)

plt.tight_layout()

OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/zones_d_2026_04_04_now.png"
plt.savefig(OUT, dpi=120, bbox_inches="tight")
plt.close()
print(f"Saved {OUT}")
