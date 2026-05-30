"""Forensic-анализ 455 победителей vs 343 проигравших i-RDRB+FVG.

Считаем features для каждой сделки, потом сравниваем по WR / R/tr в bucket'ах
и ищем features с наибольшей дискриминирующей силой.

Features:
1. RDRB variant (V1/V2)
2. Side (LONG/SHORT) — уже известно
3. block_pct = block_height / entry
4. liq_pct = liq_height / entry (0 для V2)
5. fvg_pct = FVG height / entry
6. r_unit_pct = R_unit / entry (волатильность сетапа)
7. r_unit_atr = R_unit / ATR(14, 1h)
8. c2_body_pct = |C2.close - C2.open| / entry (сила displacement)
9. EVoT direction in pattern (BULL/BEAR/NONE)
10. EVoT time bucket (C1-C5)
11. EVoT distance from entry in R-unit
12. EVoT volume ratio (dominant / opposite)
13. VWAP-FH 4h distance from entry в R-unit (на C5 close)
14. VWAP-FL 4h distance from entry в R-unit (на C5 close)
15. Hour of fill (UTC, 0-23)
16. Day of week (0=Mon)
17. Year
18. Hours from C5 close to fill (армед-окно)
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT_CSV = pathlib.Path("/tmp/i_rdrb_fvg_forensic_798.csv")
MS_HOUR = 3600_000
MS_4H = 4 * MS_HOUR
MAX_HOLD_MIN = 30 * 24 * 60
N_FRACTAL = 2
ATR_PERIOD = 14


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
print(f"{len(data):,} 1m, {len(candles_4h):,} 4h, {len(candles_1h):,} 1h")

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


# 4h fractals
fh_4h = []; fl_4h = []
for i in range(N_FRACTAL, len(candles_4h) - N_FRACTAL):
    h_i = candles_4h[i][2]; l_i = candles_4h[i][3]
    if all(h_i > candles_4h[j][2] for j in range(i - N_FRACTAL, i)) and \
       all(h_i > candles_4h[j][2] for j in range(i + 1, i + N_FRACTAL + 1)):
        fh_4h.append((candles_4h[i][0], candles_4h[i + N_FRACTAL][0] + MS_4H))
    elif all(l_i < candles_4h[j][3] for j in range(i - N_FRACTAL, i)) and \
         all(l_i < candles_4h[j][3] for j in range(i + 1, i + N_FRACTAL + 1)):
        fl_4h.append((candles_4h[i][0], candles_4h[i + N_FRACTAL][0] + MS_4H))


def last_confirmed_at(frac_list, ref_ms):
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


def evot_in_pattern(c1_ms, c5_close_ms):
    j0 = idx_at(c1_ms); j1 = idx_at(c5_close_ms)
    max_bv = 0; max_bc = None; max_bt = None
    max_sv = 0; max_sc = None; max_st = None
    for k in range(j0, j1):
        ts, o, _, _, c, v = data[k]
        if c > o:
            if v > max_bv: max_bv = v; max_bc = c; max_bt = ts
        elif c < o:
            if v > max_sv: max_sv = v; max_sc = c; max_st = ts
    if max_bv > max_sv:
        return "BULL", max_bc, max_bt, max_bv, max_sv
    elif max_sv > max_bv:
        return "BEAR", max_sc, max_st, max_sv, max_bv
    return "NONE", None, None, 0, 0


# Detect и backtest
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    patterns.append((i, ir, c5, fvg))

records = []
for k1h, ir, c5, fvg in patterns:
    side = ir.direction
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    if side == "long":
        sl = min(c.low for c in all5)
    else:
        sl = max(c.high for c in all5)
    r_unit = (entry - sl) if side == "long" else (sl - entry)
    if r_unit <= 0: continue
    tp = entry + r_unit if side == "long" else entry - r_unit

    # Features
    block_height = block_t - block_b
    liq_height = (ir.rdrb.liq[1] - ir.rdrb.liq[0]) if ir.rdrb.liq else 0.0
    fvg_height = fvg.zone[1] - fvg.zone[0]
    c2_body = abs(ir.rdrb.c2.close - ir.rdrb.c2.open)
    c5_close_ms = c5.open_time + MS_HOUR

    # EVoT
    evot_dir, mv, mv_ts, dom_v, opp_v = evot_in_pattern(ir.rdrb.c1.open_time, c5_close_ms)
    if mv is not None:
        evot_delta_r = ((mv - entry) if side == "long" else (entry - mv)) / r_unit
        evot_t_bucket = f"C{min(5, max(1, int((mv_ts - ir.rdrb.c1.open_time) // MS_HOUR) + 1))}"
        vol_ratio = dom_v / opp_v if opp_v > 0 else 99.0
    else:
        evot_delta_r = 0; evot_t_bucket = "NONE"; vol_ratio = 0

    # 4h VWAPs
    fh_pre = last_confirmed_at(fh_4h, ir.rdrb.c1.open_time)
    fl_pre = last_confirmed_at(fl_4h, ir.rdrb.c1.open_time)
    if fh_pre and fl_pre:
        c5_close_idx = idx_at(c5_close_ms) - 1
        vw_fh = vwap(idx_at(fh_pre[0]), c5_close_idx)
        vw_fl = vwap(idx_at(fl_pre[0]), c5_close_idx)
        vw_fh_r = (vw_fh - entry) / r_unit if side == "long" else (entry - vw_fh) / r_unit
        vw_fl_r = (vw_fl - entry) / r_unit if side == "long" else (entry - vw_fl) / r_unit
    else:
        vw_fh_r = vw_fl_r = None

    # Backtest baseline
    start_k = idx_at(c5_close_ms)
    end_k = min(start_k + MAX_HOLD_MIN, len(data))
    in_trade = False; outcome = "no_fill"; r_val = 0.0; fill_ms = None
    for k in range(start_k, end_k):
        ts, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if side == "long" and l_ <= entry:
                in_trade = True; fill_ms = ts
                if l_ <= sl: outcome = "loss"; r_val = -1.0; break
                if h_ >= tp: outcome = "win"; r_val = +1.0; break
            elif side == "short" and h_ >= entry:
                in_trade = True; fill_ms = ts
                if h_ >= sl: outcome = "loss"; r_val = -1.0; break
                if l_ <= tp: outcome = "win"; r_val = +1.0; break
        else:
            if side == "long":
                if l_ <= sl: outcome = "loss"; r_val = -1.0; break
                if h_ >= tp: outcome = "win"; r_val = +1.0; break
            else:
                if h_ >= sl: outcome = "loss"; r_val = -1.0; break
                if l_ <= tp: outcome = "win"; r_val = +1.0; break
    if outcome not in ("win", "loss"):
        continue
    fill_dt = datetime.fromtimestamp(fill_ms / 1000, tz=timezone.utc) if fill_ms else None
    records.append({
        "side": side, "variant": ir.rdrb.variant, "outcome": outcome, "r": r_val,
        "entry": entry, "sl": sl, "tp": tp,
        "block_pct": block_height / entry * 100,
        "liq_pct": liq_height / entry * 100,
        "fvg_pct": fvg_height / entry * 100,
        "r_unit_pct": r_unit / entry * 100,
        "r_unit_atr": r_unit / atr_arr[k1h] if atr_arr[k1h] > 0 else 0,
        "c2_body_pct": c2_body / entry * 100,
        "evot_dir": evot_dir, "evot_delta_r": evot_delta_r,
        "evot_t_bucket": evot_t_bucket, "evot_vol_ratio": vol_ratio,
        "vw_fh_r": vw_fh_r, "vw_fl_r": vw_fl_r,
        "fill_hour": fill_dt.hour if fill_dt else -1,
        "fill_dow": fill_dt.weekday() if fill_dt else -1,
        "fill_year": fill_dt.year if fill_dt else -1,
        "armed_h": (fill_ms - c5_close_ms) / MS_HOUR if fill_ms else None,
    })


# Сохранить CSV
with OUT_CSV.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(records[0].keys()))
    w.writeheader()
    for r in records: w.writerow(r)
print(f"Saved {OUT_CSV}  ({len(records)} trades)\n")


# Анализ дискриминирующей силы каждой features
n = len(records)
n_w = sum(1 for x in records if x["outcome"] == "win")
n_l = n - n_w
print(f"Total: {n}  Wins: {n_w} ({n_w/n*100:.2f}%)  Losses: {n_l}\n")


def cat_split(records, key):
    """Для категориальной фичи — WR / R/tr по значениям."""
    groups = {}
    for r in records:
        v = r[key]
        groups.setdefault(v, []).append(r)
    out = []
    for v, items in groups.items():
        nw = sum(1 for x in items if x["outcome"] == "win")
        sr = sum(x["r"] for x in items)
        nn = len(items)
        out.append((v, nn, nw / nn * 100, sr, sr / nn))
    return sorted(out, key=lambda x: -x[2])


def num_split(records, key, bins):
    """Для числовой фичи — WR / R/tr по bin'ам."""
    out = []
    for lo, hi, name in bins:
        sub = [r for r in records if r[key] is not None and lo <= r[key] < hi]
        if not sub: continue
        nn = len(sub)
        nw = sum(1 for x in sub if x["outcome"] == "win")
        sr = sum(x["r"] for x in sub)
        out.append((name, nn, nw / nn * 100, sr, sr / nn))
    return out


def show(title, results, baseline_wr=None):
    if baseline_wr is None: baseline_wr = n_w / n * 100
    print(f"--- {title} ---")
    print(f"  {'value':<22} {'n':<6} {'WR%':<7} {'ΣR':<8} {'R/tr':<8} {'Δprec':<7}")
    for v, nn, wr, sr, rtr in results:
        dprec = wr - baseline_wr
        print(f"  {str(v):<22} {nn:<6} {wr:<7.2f} {sr:<+8.1f} {rtr:<+8.3f} {dprec:<+7.2f}pp")
    print()


print("=== Категориальные ===")
show("side", cat_split(records, "side"))
show("variant (V1/V2)", cat_split(records, "variant"))
show("evot_dir", cat_split(records, "evot_dir"))
show("evot_t_bucket", cat_split(records, "evot_t_bucket"))
show("fill_year", sorted(cat_split(records, "fill_year"), key=lambda x: x[0]))
show("fill_dow (0=Mon)", sorted(cat_split(records, "fill_dow"), key=lambda x: x[0]))
show("fill_hour (UTC)", sorted(cat_split(records, "fill_hour"), key=lambda x: x[0]))

print("\n=== Числовые ===")
show("evot_delta_r", num_split(records, "evot_delta_r",
     [(-99, -1.0, "≤ -1R"), (-1.0, -0.5, "[-1, -0.5)"),
      (-0.5, -0.2, "[-0.5, -0.2)"), (-0.2, 0, "[-0.2, 0)"),
      (0, 0.5, "[0, 0.5)"), (0.5, 99, "≥ 0.5R")]))
show("vw_fl_r (4h VWAP-FL distance, LONG side; for SHORT — это FL уровень относительно entry)",
     num_split(records, "vw_fl_r",
     [(-99, -0.5, "≤ -0.5R"), (-0.5, 0, "[-0.5, 0)"),
      (0, 1, "[0, 1)R"), (1, 2, "[1, 2)R"), (2, 3, "[2, 3)R"), (3, 99, "≥ 3R")]))
show("r_unit_pct (R размер в % от entry)",
     num_split(records, "r_unit_pct",
     [(0, 0.3, "<0.3%"), (0.3, 0.5, "[0.3, 0.5)"), (0.5, 0.8, "[0.5, 0.8)"),
      (0.8, 1.2, "[0.8, 1.2)"), (1.2, 99, "≥1.2%")]))
show("r_unit_atr (R / ATR1h)",
     num_split(records, "r_unit_atr",
     [(0, 0.5, "<0.5"), (0.5, 0.85, "[0.5, 0.85)"), (0.85, 1.1, "[0.85, 1.1)"),
      (1.1, 1.5, "[1.1, 1.5)"), (1.5, 99, "≥1.5")]))
show("block_pct",
     num_split(records, "block_pct",
     [(0, 0.05, "<0.05%"), (0.05, 0.15, "[0.05, 0.15)"),
      (0.15, 0.3, "[0.15, 0.3)"), (0.3, 99, "≥0.3%")]))
show("armed_h (часы до fill)",
     num_split(records, "armed_h",
     [(0, 1, "<1h"), (1, 4, "[1, 4)"), (4, 12, "[4, 12)"),
      (12, 48, "[12, 48)"), (48, 99999, "≥48h")]))
