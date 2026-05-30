"""Стратегия "VWAP Anchored Cross".

- VWAP-FH = anchored на ПОСЛЕДНЕМ confirmed 4h Williams FH (динамически обновляется)
- VWAP-FL = anchored на ПОСЛЕДНЕМ confirmed 4h Williams FL

Signal на каждом 1h close:
- Bull cross: VWAP-FL пересекает VWAP-FH снизу вверх → LONG
- Bear cross: VWAP-FL пересекает VWAP-FH сверху вниз → SHORT

Entry: market по close сигнальной 1h свечи.
SL: 1.5 × ATR(14, 1h) от entry.
TP: RR=1, 2, 3 (sweep).

Anti-noise:
- Игнорируем cross в первые 4h после смены anchor (избегаем synthetic crosses).
- Требуется минимальный gap VWAPs до cross (например 0.3% — фильтрует micro-noise).
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
MS_4H = 4 * MS_HOUR
MAX_HOLD_MIN = 30 * 24 * 60
N_FRACTAL = 2
ATR_PERIOD = 14
SL_ATR_MULT = 1.5
MIN_GAP_PCT = 0.0             # без фильтра gap (полная статистика)
ANCHOR_COOLDOWN_BARS = 0      # без cooldown


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
candles_4h = aggregate(data, 240)
candles_1h_raw = aggregate(data, 60)
candles_1h = [Candle(open=o, high=h, low=l, close=c, open_time=ts) for ts, o, h, l, c, _ in candles_1h_raw]
ts_1m = [r[0] for r in data]
print(f"{len(data):,} 1m → {len(candles_4h):,} 4h, {len(candles_1h):,} 1h")

cum_pv = [0.0] * (len(data) + 1); cum_vol = [0.0] * (len(data) + 1)
for i, (_, _, _, _, c, v) in enumerate(data):
    cum_pv[i + 1] = cum_pv[i] + v * c
    cum_vol[i + 1] = cum_vol[i] + v


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def vwap(a, e):
    pv = cum_pv[e + 1] - cum_pv[a]; vol = cum_vol[e + 1] - cum_vol[a]
    return pv / vol if vol > 0 else 0


# Detect 4h fractals + their confirmation ms
fh_4h = []; fl_4h = []
for i in range(N_FRACTAL, len(candles_4h) - N_FRACTAL):
    h_i = candles_4h[i][2]; l_i = candles_4h[i][3]
    if all(h_i > candles_4h[j][2] for j in range(i - N_FRACTAL, i)) and \
       all(h_i > candles_4h[j][2] for j in range(i + 1, i + N_FRACTAL + 1)):
        fh_4h.append((candles_4h[i][0], candles_4h[i + N_FRACTAL][0] + MS_4H))  # (anchor_ts, confirm_ts)
    elif all(l_i < candles_4h[j][3] for j in range(i - N_FRACTAL, i)) and \
         all(l_i < candles_4h[j][3] for j in range(i + 1, i + N_FRACTAL + 1)):
        fl_4h.append((candles_4h[i][0], candles_4h[i + N_FRACTAL][0] + MS_4H))
print(f"4h fractals: {len(fh_4h)} FH, {len(fl_4h)} FL")


def last_confirmed_at(frac_list, ref_ms):
    """Бинарный поиск последнего фрактала с confirm_ts ≤ ref_ms."""
    lo, hi = 0, len(frac_list)
    while lo < hi:
        mid = (lo + hi) // 2
        if frac_list[mid][1] <= ref_ms: lo = mid + 1
        else: hi = mid
    return frac_list[lo - 1] if lo > 0 else None


# ATR(14) on 1h
atr_arr = [0.0] * len(candles_1h)
trs = [0.0] * len(candles_1h)
for i in range(1, len(candles_1h)):
    trs[i] = max(candles_1h[i].high - candles_1h[i].low,
                 abs(candles_1h[i].high - candles_1h[i - 1].close),
                 abs(candles_1h[i].low - candles_1h[i - 1].close))
for i in range(ATR_PERIOD, len(candles_1h)):
    if i == ATR_PERIOD:
        atr_arr[i] = sum(trs[1:ATR_PERIOD + 1]) / ATR_PERIOD
    else:
        atr_arr[i] = (atr_arr[i - 1] * (ATR_PERIOD - 1) + trs[i]) / ATR_PERIOD


# Идём по 1h барам, отслеживаем VWAP-FH и VWAP-FL, обнаруживаем кроссы
signals = []  # (idx_1h, side, entry, atr, fh_anchor, fl_anchor)
prev_diff_sign = 0   # знак (vwap_fl - vwap_fh) на предыдущем баре
last_fh_anchor_ms = None
last_fl_anchor_ms = None
bars_since_anchor_change = 999  # счётчик

for k in range(ATR_PERIOD + 10, len(candles_1h)):
    bar = candles_1h[k]
    bar_close_ms = bar.open_time + MS_HOUR  # closes at next hour's open

    fh = last_confirmed_at(fh_4h, bar.open_time)
    fl = last_confirmed_at(fl_4h, bar.open_time)
    if fh is None or fl is None:
        continue

    fh_anchor_ms, _ = fh
    fl_anchor_ms, _ = fl

    # Anchor cooldown
    if fh_anchor_ms != last_fh_anchor_ms or fl_anchor_ms != last_fl_anchor_ms:
        bars_since_anchor_change = 0
        last_fh_anchor_ms = fh_anchor_ms
        last_fl_anchor_ms = fl_anchor_ms
    else:
        bars_since_anchor_change += 1

    bar_end_idx = idx_at(bar_close_ms) - 1
    fh_anchor_idx = idx_at(fh_anchor_ms)
    fl_anchor_idx = idx_at(fl_anchor_ms)
    if bar_end_idx < fh_anchor_idx or bar_end_idx < fl_anchor_idx:
        continue
    vw_fh = vwap(fh_anchor_idx, bar_end_idx)
    vw_fl = vwap(fl_anchor_idx, bar_end_idx)
    diff = vw_fl - vw_fh
    diff_sign = 1 if diff > 0 else (-1 if diff < 0 else 0)

    # Cross detection — изменение знака
    if prev_diff_sign != 0 and diff_sign != 0 and diff_sign != prev_diff_sign \
       and bars_since_anchor_change >= ANCHOR_COOLDOWN_BARS:
        # Минимальный gap
        gap_pct = abs(diff) / bar.close
        if gap_pct >= MIN_GAP_PCT:
            side = "long" if diff_sign > 0 else "short"
            signals.append({
                "idx": k, "side": side, "entry": bar.close,
                "atr": atr_arr[k], "open_time": bar.open_time,
                "vw_fh": vw_fh, "vw_fl": vw_fl,
            })

    prev_diff_sign = diff_sign

print(f"\nVWAP-cross signals detected: {len(signals)}")
n_long = sum(1 for s in signals if s["side"] == "long")
n_short = len(signals) - n_long
print(f"  LONG:  {n_long}")
print(f"  SHORT: {n_short}")


# Backtest для RR=1, 2, 3
CONTRARIAN = True  # True = торгуем ПРОТИВ cross (fade), False = по cross

def backtest_rr(rr):
    stats = {"long": {"win": 0, "loss": 0, "open": 0},
             "short": {"win": 0, "loss": 0, "open": 0}}
    total_r = 0.0; r_long = 0.0; r_short = 0.0
    for s in signals:
        side = ("short" if s["side"] == "long" else "long") if CONTRARIAN else s["side"]
        entry = s["entry"]; atr = s["atr"]
        if atr <= 0: continue
        if side == "long":
            sl = entry - SL_ATR_MULT * atr
            tp = entry + SL_ATR_MULT * atr * rr
        else:
            sl = entry + SL_ATR_MULT * atr
            tp = entry - SL_ATR_MULT * atr * rr
        # Entry market на close, start = bar close + 1m
        start_ms = candles_1h[s["idx"]].open_time + MS_HOUR
        j0 = idx_at(start_ms)
        j1 = min(j0 + MAX_HOLD_MIN, len(data))
        outcome = "open"
        for j in range(j0, j1):
            _, _, h_, l_, _, _ = data[j]
            if side == "long":
                if l_ <= sl: outcome = "loss"; r_val = -1.0; break
                if h_ >= tp: outcome = "win"; r_val = +float(rr); break
            else:
                if h_ >= sl: outcome = "loss"; r_val = -1.0; break
                if l_ <= tp: outcome = "win"; r_val = +float(rr); break
        if outcome == "open":
            stats[side]["open"] += 1; continue
        stats[side][outcome] += 1
        total_r += r_val
        if side == "long": r_long += r_val
        else: r_short += r_val
    return stats, total_r, r_long, r_short


print("\n=== Sweep по RR ===")
print(f"{'RR':<6} {'Trades':<8} {'WR%':<7} {'ΣR':<9} {'R/tr':<8} {'WR-L':<7} {'WR-S':<7} {'R-L':<9} {'R-S':<9}")
print("-" * 80)
for rr in (1.0, 1.5, 2.0, 2.5, 3.0):
    stats, total, rl, rs = backtest_rr(rr)
    n_w = stats["long"]["win"] + stats["short"]["win"]
    n_l = stats["long"]["loss"] + stats["short"]["loss"]
    n_t = n_w + n_l
    wr = n_w / n_t * 100 if n_t else 0
    wr_long = stats["long"]["win"] / (stats["long"]["win"] + stats["long"]["loss"]) * 100 if (stats["long"]["win"] + stats["long"]["loss"]) else 0
    wr_short = stats["short"]["win"] / (stats["short"]["win"] + stats["short"]["loss"]) * 100 if (stats["short"]["win"] + stats["short"]["loss"]) else 0
    print(f"RR={rr:<3} {n_t:<8} {wr:<7.2f} {total:<+9.1f} {total/n_t if n_t else 0:<+8.3f} "
          f"{wr_long:<7.2f} {wr_short:<7.2f} {rl:<+9.1f} {rs:<+9.1f}")
