"""Визуализация 3 примеров i-RDRB+FVG с VWAP-entry.

Каждый график:
- 5m свечи (контекст)
- Pattern candles C1-C5 (1h) — оранжевые рамки сверху
- VWAP-линия (anchored от 5m candle с pattern extreme)
- POI / block / liq зоны как shaded
- Entry, SL, TP горизонтальные линии
- Маркеры fill и exit
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
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_5M = 5 * 60_000
MS_HOUR = 3600_000


def load_1m_full():
    rows = []
    with CSV_PATH.open() as f:
        reader = csv.reader(f)
        next(reader)
        for r in reader:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate(data_1m, tf_min):
    bucket = tf_min * 60_000
    out = []  # (ts_ms, o, h, l, c, v)
    cur_b = None; o = h = l = c = 0; v = 0
    for ts, oo, hh, ll, cc, vv in data_1m:
        b = ts - (ts % bucket)
        if b != cur_b:
            if cur_b is not None: out.append((cur_b, o, h, l, c, v))
            cur_b = b; o = oo; h = hh; l = ll; c = cc; v = vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cur_b is not None: out.append((cur_b, o, h, l, c, v))
    return out


print("Loading 1m...")
data = load_1m_full()
ts_arr = [r[0] for r in data]
print(f"Loaded {len(data):,} 1m rows")


def idx_at(ms):
    lo, hi = 0, len(ts_arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if ts_arr[mid] < ms: lo = mid + 1
        else: hi = mid
    return lo


# Найдём все паттерны
candles_1h = []
cur_b = None; o = h = l = c = 0
for ts, oo, hh, ll, cc, _ in data:
    b = ts - (ts % MS_HOUR)
    if b != cur_b:
        if cur_b is not None:
            candles_1h.append(Candle(open=o, high=h, low=l, close=c, open_time=cur_b))
        cur_b = b; o = oo; h = hh; l = ll; c = cc
    else:
        h = max(h, hh); l = min(l, ll); c = cc
if cur_b is not None:
    candles_1h.append(Candle(open=o, high=h, low=l, close=c, open_time=cur_b))

patterns_with_fill = []  # (ir, c5, anchor_ms, fill_ms, fill_vwap, outcome, sl, tp)
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue

    side = ir.direction
    all5 = [c1, c2, c3, c4, c5]
    if side == "long":
        sl = min(cn.low for cn in all5)
    else:
        sl = max(cn.high for cn in all5)

    # anchor 1m
    p_start = c1.open_time; p_end = c5.open_time + MS_HOUR
    j0 = idx_at(p_start); j1 = idx_at(p_end)
    anchor_k = None
    for k in range(j0, j1):
        if side == "long" and data[k][3] == sl: anchor_k = k; break
        if side == "short" and data[k][2] == sl: anchor_k = k; break
    if anchor_k is None: continue
    anchor_ms = data[anchor_k][0]
    anchor_5m = anchor_ms - (anchor_ms % MS_5M)
    anchor_idx = idx_at(anchor_5m)

    c5_close_ms = c5.open_time + MS_HOUR

    cum_pv = 0.0; cum_vol = 0.0
    in_trade = False; outcome = "no_fill"; entry = None; tp = None; r_val = None
    fill_ms = None; exit_ms = None
    block_b, block_t = ir.rdrb.block
    for k in range(anchor_idx, len(data)):
        ts, _, hh, ll, cc, vv = data[k]
        cum_pv += vv * cc; cum_vol += vv
        vwap = cum_pv / cum_vol if cum_vol else 0
        if not in_trade:
            if ts < c5_close_ms: continue
            if ll <= vwap <= hh:
                if side == "long" and vwap > block_t: outcome = "filtered"; break
                if side == "short" and vwap < block_b: outcome = "filtered"; break
                in_trade = True; entry = vwap; fill_ms = ts
                r_val = entry - sl if side == "long" else sl - entry
                if r_val <= 0: outcome = "filtered"; break
                tp = entry + r_val if side == "long" else entry - r_val
                if side == "long":
                    if ll <= sl: outcome = "loss"; exit_ms = ts; break
                    if hh >= tp: outcome = "win"; exit_ms = ts; break
                else:
                    if hh >= sl: outcome = "loss"; exit_ms = ts; break
                    if ll <= tp: outcome = "win"; exit_ms = ts; break
        else:
            if side == "long":
                if ll <= sl: outcome = "loss"; exit_ms = ts; break
                if hh >= tp: outcome = "win"; exit_ms = ts; break
            else:
                if hh >= sl: outcome = "loss"; exit_ms = ts; break
                if ll <= tp: outcome = "win"; exit_ms = ts; break

    if outcome in ("win", "loss"):
        patterns_with_fill.append({
            "ir": ir, "c5": c5, "side": side, "sl": sl, "tp": tp, "entry": entry,
            "fill_ms": fill_ms, "exit_ms": exit_ms, "outcome": outcome,
            "anchor_5m": anchor_5m, "anchor_idx": anchor_idx,
            "block": ir.rdrb.block, "poi": ir.rdrb.poi, "liq": ir.rdrb.liq,
        })


# Выбираем 3 примера
wins_long = [p for p in patterns_with_fill if p["outcome"] == "win" and p["side"] == "long"]
losses_long = [p for p in patterns_with_fill if p["outcome"] == "loss" and p["side"] == "long"]
wins_short = [p for p in patterns_with_fill if p["outcome"] == "win" and p["side"] == "short"]

print(f"Win LONG: {len(wins_long)}, Loss LONG: {len(losses_long)}, Win SHORT: {len(wins_short)}")

# Пример 1: эталон 2026-05-23 (LONG, LOSS)
TARGET_REF = int(datetime(2026, 5, 23, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
pat_ref = min(patterns_with_fill, key=lambda p: abs(p["ir"].rdrb.c1.open_time - TARGET_REF) if abs(p["ir"].rdrb.c1.open_time - TARGET_REF) < 2*86400_000 else float("inf"))

# Пример 2: свежий WIN LONG
pat_win = max(wins_long, key=lambda p: p["ir"].rdrb.c1.open_time)

# Пример 3: свежий WIN SHORT (или loss если нет win)
pat_short = max(wins_short, key=lambda p: p["ir"].rdrb.c1.open_time) if wins_short else \
            max([p for p in patterns_with_fill if p["side"] == "short"], key=lambda p: p["ir"].rdrb.c1.open_time)


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime("%m-%d %H:%M")


def plot_pattern(pat, title, out_path):
    ir = pat["ir"]; c5 = pat["c5"]; side = pat["side"]
    sl = pat["sl"]; tp = pat["tp"]; entry = pat["entry"]
    block_b, block_t = pat["block"]; poi_b, poi_t = pat["poi"]
    anchor_5m = pat["anchor_5m"]
    fill_ms = pat["fill_ms"]; exit_ms = pat["exit_ms"]

    # окно: от 2h до anchor — 4h после exit (или max 24h после fill)
    start_ms = ir.rdrb.c1.open_time - 4 * MS_HOUR
    end_ms = exit_ms + 4 * MS_HOUR

    # 5m свечи в окне
    candles_5m = []
    cum_pv = 0.0; cum_vol = 0.0
    j_start = idx_at(anchor_5m)
    bucket = MS_5M
    # сначала аккумулируем VWAP с anchor до конца окна
    vwap_series = []  # (ts, vwap)
    last_b = None; b_o = b_h = b_l = b_c = 0
    for k in range(idx_at(start_ms), idx_at(end_ms)):
        ts, oo, hh, ll, cc, vv = data[k]
        # 5m свеча
        b = ts - (ts % bucket)
        if b != last_b:
            if last_b is not None:
                candles_5m.append((last_b, b_o, b_h, b_l, b_c))
            last_b = b; b_o = oo; b_h = hh; b_l = ll; b_c = cc
        else:
            b_h = max(b_h, hh); b_l = min(b_l, ll); b_c = cc
        # VWAP только с anchor
        if ts >= anchor_5m:
            cum_pv += vv * cc; cum_vol += vv
            if cum_vol > 0:
                vwap_series.append((ts, cum_pv / cum_vol))
    if last_b is not None:
        candles_5m.append((last_b, b_o, b_h, b_l, b_c))

    fig, ax = plt.subplots(figsize=(16, 9))
    width_min = bucket / 60_000 * 0.7
    for ts, o, h, l, c in candles_5m:
        x = mdates.date2num(datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(MSK))
        color = "#26a69a" if c >= o else "#ef5350"
        ax.plot([x, x], [l, h], color=color, linewidth=0.7, zorder=2)
        body_low, body_high = min(o, c), max(o, c)
        if body_high - body_low < 0.01:
            body_high = body_low + 0.01
        rect = mpatches.Rectangle((x - width_min/2/24/60, body_low), width_min/24/60, body_high - body_low,
                                   facecolor=color, edgecolor=color, alpha=0.9, zorder=3)
        ax.add_patch(rect)

    # POI / block / liq как rectangles на 1h интервале паттерна
    p_start_dt = mdates.date2num(datetime.fromtimestamp(ir.rdrb.c1.open_time / 1000, tz=timezone.utc).astimezone(MSK))
    p_end_dt = mdates.date2num(datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).astimezone(MSK))
    width_zone = p_end_dt - p_start_dt
    # POI
    ax.add_patch(mpatches.Rectangle((p_start_dt, poi_b), width_zone, poi_t - poi_b,
                                     facecolor="#fff8e1", edgecolor="#ffb300", alpha=0.4, zorder=1, label="POI"))
    # Block
    ax.add_patch(mpatches.Rectangle((p_start_dt, block_b), width_zone, block_t - block_b,
                                     facecolor="#ffb300", edgecolor="#ff6f00", alpha=0.35, zorder=1, label="block"))

    # SL / Entry / TP горизонтальные линии после fill
    if fill_ms and exit_ms:
        fill_dt = mdates.date2num(datetime.fromtimestamp(fill_ms / 1000, tz=timezone.utc).astimezone(MSK))
        exit_dt = mdates.date2num(datetime.fromtimestamp(exit_ms / 1000, tz=timezone.utc).astimezone(MSK))
        ax.hlines(entry, fill_dt, exit_dt, colors="blue", linewidth=2, label=f"Entry {entry:.2f}")
        ax.hlines(sl, fill_dt, exit_dt, colors="red", linewidth=1.5, linestyles="--", label=f"SL {sl:.2f}")
        ax.hlines(tp, fill_dt, exit_dt, colors="green", linewidth=1.5, linestyles="--", label=f"TP {tp:.2f}")
        ax.scatter([fill_dt], [entry], s=100, c="blue", marker="o", zorder=5, label="Fill")
        exit_y = sl if pat["outcome"] == "loss" else tp
        ax.scatter([exit_dt], [exit_y], s=120, c="green" if pat["outcome"] == "win" else "red",
                   marker="^" if pat["outcome"] == "win" else "v", zorder=5,
                   label=f"Exit ({pat['outcome'].upper()})")

    # VWAP
    if vwap_series:
        vw_x = [mdates.date2num(datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(MSK)) for ts, _ in vwap_series]
        vw_y = [v for _, v in vwap_series]
        ax.plot(vw_x, vw_y, color="#9c27b0", linewidth=1.5, label="VWAP (5m anchor)", zorder=4)

    # Pattern candle markers (C1..C5)
    pattern_candles = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    for idx_p, cp in enumerate(pattern_candles):
        label = f"C{idx_p+1}"
        xt = mdates.date2num(datetime.fromtimestamp((cp.open_time + 30 * 60_000) / 1000, tz=timezone.utc).astimezone(MSK))
        yt = cp.high + (poi_t - poi_b) * 0.1
        ax.annotate(label, (xt, yt), ha="center", fontsize=11, fontweight="bold", color="#1a237e", zorder=6)

    ax.set_title(f"{title}\n{fmt(ir.rdrb.c1.open_time)} → {fmt(exit_ms or end_ms)} MSK  ·  {pat['outcome'].upper()}  ·  side={side}",
                 fontsize=13)
    ax.set_ylabel("Price (USDT)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M", tz=MSK))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(tz=MSK, maxticks=10))
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9, framealpha=0.9)
    plt.xticks(rotation=30)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


OUT_DIR = pathlib.Path.home() / "Desktop/i-rdrb-charts"
OUT_DIR.mkdir(exist_ok=True)


def date_slug(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime("%Y-%m-%d")


plot_pattern(pat_ref,
             "Пример 1: эталон 2026-05-23 LONG (LOSS)",
             OUT_DIR / f"vwap_entry_{date_slug(pat_ref['ir'].rdrb.c1.open_time)}_long_loss.png")
plot_pattern(pat_win,
             f"Пример 2: WIN LONG {fmt(pat_win['ir'].rdrb.c1.open_time)}",
             OUT_DIR / f"vwap_entry_{date_slug(pat_win['ir'].rdrb.c1.open_time)}_long_win.png")
plot_pattern(pat_short,
             f"Пример 3: {pat_short['outcome'].upper()} SHORT {fmt(pat_short['ir'].rdrb.c1.open_time)}",
             OUT_DIR / f"vwap_entry_{date_slug(pat_short['ir'].rdrb.c1.open_time)}_short_{pat_short['outcome']}.png")
