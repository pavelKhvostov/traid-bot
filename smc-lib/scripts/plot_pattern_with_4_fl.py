"""Рендеринг паттерна с 4 15m FLs в зоне [pattern_low, block.bottom]."""
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
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_HOUR = 3600_000
MS_15M = 15 * 60_000
MAX_HOLD_MIN = 30 * 24 * 60
N_FRACTAL = 2


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate(d, tf_min):
    bucket = tf_min * 60_000
    out = []; cb = None; o = h = l = c = 0; v_sum = 0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - (ts % bucket)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v_sum))
            cb = b; o, h, l, c = oo, hh, ll, cc; v_sum = vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v_sum += vv
    if cb is not None: out.append((cb, o, h, l, c, v_sum))
    return out


print("Loading..."); data = load_1m()
candles_15m = aggregate(data, 15)
candles_1h = [Candle(open=o, high=h, low=l, close=c, open_time=ts)
              for ts, o, h, l, c, _ in aggregate(data, 60)]
ts_1m = [r[0] for r in data]
print(f"{len(data):,} 1m → {len(candles_15m):,} 15m, {len(candles_1h):,} 1h")

fl_15m = []
for i in range(N_FRACTAL, len(candles_15m) - N_FRACTAL):
    l_i = candles_15m[i][3]
    if all(l_i < candles_15m[j][3] for j in range(i - N_FRACTAL, i)) and \
       all(l_i < candles_15m[j][3] for j in range(i + 1, i + N_FRACTAL + 1)):
        fl_15m.append({
            "open_ts": candles_15m[i][0],
            "low_price": l_i,
            "confirm_ts": candles_15m[i + N_FRACTAL][0] + MS_15M,
        })


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


# Найти LONG winners с 4 FLs
print("Searching for LONG winner with 4 FLs in zone...")
candidates = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None or ir.direction != "long": continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != "long": continue
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [c1, c2, c3, c4, c5]
    sl = min(c.low for c in all5)
    r_unit = entry - sl
    if r_unit <= 0: continue
    tp = entry + r_unit
    c5_close_ms = c5.open_time + MS_HOUR

    # Backtest
    start_k = idx_at(c5_close_ms)
    end_k = min(start_k + MAX_HOLD_MIN, len(data))
    in_trade = False; outcome = "no_fill"; exit_ms = None; fill_ms = None
    for k in range(start_k, end_k):
        ts, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if l_ <= entry:
                in_trade = True; fill_ms = ts
                if l_ <= sl: outcome = "loss"; exit_ms = ts; break
                if h_ >= tp: outcome = "win"; exit_ms = ts; break
        else:
            if l_ <= sl: outcome = "loss"; exit_ms = ts; break
            if h_ >= tp: outcome = "win"; exit_ms = ts; break
    if outcome != "win": continue

    fls = [f for f in fl_15m
           if c1.open_time <= f["open_ts"] <= c5_close_ms
           and f["confirm_ts"] <= c5_close_ms
           and sl <= f["low_price"] <= block_b]

    if len(fls) == 4:
        candidates.append({
            "ir": ir, "c5": c5, "fls": fls, "entry": entry, "sl": sl, "tp": tp,
            "block": ir.rdrb.block, "poi": ir.rdrb.poi,
            "fill_ms": fill_ms, "exit_ms": exit_ms,
        })

print(f"Found {len(candidates)} winners with exactly 4 FLs in zone")
if not candidates:
    print("Нет таких. Выход."); sys.exit(0)

# Берём самый свежий
pat = max(candidates, key=lambda x: x["ir"].rdrb.c1.open_time)
ir = pat["ir"]; c5 = pat["c5"]


def fmt(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M')


print(f"\nReference pattern:")
print(f"  C1: {fmt(ir.rdrb.c1.open_time)} MSK")
print(f"  Fill: {fmt(pat['fill_ms'])} MSK")
print(f"  Exit (WIN/TP): {fmt(pat['exit_ms'])} MSK")
print(f"  Block: {pat['block']}, POI: {pat['poi']}")
print(f"  Entry={pat['entry']:.2f}, SL={pat['sl']:.2f}, TP={pat['tp']:.2f}")
print(f"  4 FLs:")
for f in pat['fls']:
    print(f"    {fmt(f['open_ts'])} MSK  low={f['low_price']:.2f}")

# Plot 5m свечи + 15m FL маркеры
candles_5m = aggregate(data, 5)
display_start = ir.rdrb.c1.open_time - 2 * MS_HOUR
display_end = pat["exit_ms"] + 2 * MS_HOUR
display = [c for c in candles_5m if display_start <= c[0] <= display_end]

fig, ax = plt.subplots(figsize=(18, 9))
WIDTH = 5 * 0.7
for ts, o, h, l, c, _ in display:
    x = mdates.date2num(datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(MSK))
    color = "#26a69a" if c >= o else "#ef5350"
    ax.plot([x, x], [l, h], color=color, linewidth=0.6, zorder=2)
    body_low, body_high = min(o, c), max(o, c)
    if body_high - body_low < 0.01: body_high = body_low + 0.01
    ax.add_patch(mpatches.Rectangle((x - WIDTH / 2 / 24 / 60, body_low), WIDTH / 24 / 60, body_high - body_low,
                                    facecolor=color, edgecolor=color, alpha=0.9, zorder=3))

# POI / block
p_start = mdates.date2num(datetime.fromtimestamp(ir.rdrb.c1.open_time / 1000, tz=timezone.utc).astimezone(MSK))
p_end = mdates.date2num(datetime.fromtimestamp(display_end / 1000, tz=timezone.utc).astimezone(MSK))
ax.add_patch(mpatches.Rectangle((p_start, pat["poi"][0]), p_end - p_start, pat["poi"][1] - pat["poi"][0],
                                facecolor="#fff8e1", edgecolor="#ffb300", alpha=0.4, zorder=1, label="POI"))
ax.add_patch(mpatches.Rectangle((p_start, pat["block"][0]), p_end - p_start, pat["block"][1] - pat["block"][0],
                                facecolor="#ffb300", edgecolor="#ff6f00", alpha=0.35, zorder=1, label="block"))

# Зона между pattern_low и block.bottom — где FL живут
zone_top = pat["block"][0]; zone_bot = pat["sl"]
ax.add_patch(mpatches.Rectangle((p_start, zone_bot), p_end - p_start, zone_top - zone_bot,
                                facecolor="#a0d8a0", edgecolor="green", alpha=0.15, zorder=0,
                                label="FL zone [pattern_low, block.bottom]"))

# FL markers
for i, f in enumerate(pat["fls"], 1):
    x = mdates.date2num(datetime.fromtimestamp(f["open_ts"] / 1000, tz=timezone.utc).astimezone(MSK))
    ax.scatter([x], [f["low_price"]], s=300, marker="^", color="#388e3c", zorder=6,
               edgecolor="black", linewidth=1.5)
    ax.annotate(f"FL{i}\n{f['low_price']:.0f}", (x, f["low_price"]), xytext=(0, -25),
                textcoords="offset points", ha="center", fontsize=9, fontweight="bold", color="#1b5e20")

# Entry / SL / TP
fill_x = mdates.date2num(datetime.fromtimestamp(pat["fill_ms"] / 1000, tz=timezone.utc).astimezone(MSK))
exit_x = mdates.date2num(datetime.fromtimestamp(pat["exit_ms"] / 1000, tz=timezone.utc).astimezone(MSK))
ax.hlines(pat["entry"], fill_x, exit_x, colors="blue", linewidth=2, label=f"Entry {pat['entry']:.2f}")
ax.hlines(pat["sl"], fill_x, exit_x, colors="red", linewidth=1.5, linestyles="--", label=f"SL (pattern_low) {pat['sl']:.2f}")
ax.hlines(pat["tp"], fill_x, exit_x, colors="green", linewidth=1.5, linestyles="--", label=f"TP {pat['tp']:.2f}")
ax.scatter([fill_x], [pat["entry"]], s=120, c="blue", marker="o", zorder=5)
ax.scatter([exit_x], [pat["tp"]], s=150, c="green", marker="^", zorder=5, label="Exit (WIN)")

# Pattern C1-C5 labels
for idx, cnd in enumerate([ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]):
    x = mdates.date2num(datetime.fromtimestamp((cnd.open_time + 30 * 60_000) / 1000, tz=timezone.utc).astimezone(MSK))
    y = cnd.high + (pat["poi"][1] - pat["poi"][0]) * 0.3
    ax.annotate(f"C{idx+1}", (x, y), ha="center", fontsize=11, fontweight="bold", color="#1a237e", zorder=6)

ax.set_title(f"LONG i-RDRB+FVG (WIN, 4× 15m FL в зоне) — {fmt(ir.rdrb.c1.open_time)} MSK", fontsize=13)
ax.set_ylabel("Price (USDT)")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M", tz=MSK))
ax.xaxis.set_major_locator(mdates.AutoDateLocator(tz=MSK, maxticks=10))
ax.grid(True, alpha=0.3)
ax.legend(loc="best", fontsize=9, framealpha=0.9)
plt.xticks(rotation=30)
plt.tight_layout()

date_slug = datetime.fromtimestamp(ir.rdrb.c1.open_time / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d')
OUT = pathlib.Path.home() / f"Desktop/i-rdrb-charts/pattern_4fl_15m_{date_slug}.png"
plt.savefig(OUT, dpi=120, bbox_inches="tight")
plt.close()
print(f"\nSaved {OUT}")
