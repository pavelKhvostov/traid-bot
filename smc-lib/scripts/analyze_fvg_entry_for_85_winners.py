"""Для 85 LONG winners с ≥1 FVG (15m/20m/30m) в [pattern_low, block.bottom]:
1. Если бы entry был на FVG.top (limit) вместо 0.5 block — как часто долетала?
2. Какой RR получился бы (при той же TP-цене)?

Среди нескольких FVG (на разных TF) — берём с highest top (ближайший к block, легче залить).

Логика расчёта RR:
- entry_orig = 0.5 block_mid, sl = pattern_low, tp_abs = entry_orig + (entry_orig - sl)
- entry_new = FVG.top, sl = pattern_low (unchanged), tp_abs = same
- new_RR = (tp_abs - entry_new) / (entry_new - sl)
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
MS_HOUR = 3600_000
MAX_HOLD_MIN = 30 * 24 * 60
TFS = [(15, "15m"), (20, "20m"), (30, "30m")]


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


def detect_bull_fvgs(candles, tf_min):
    tf_ms = tf_min * 60_000
    fvgs = []
    for i in range(len(candles) - 2):
        c1 = candles[i]; c3 = candles[i + 2]
        if c1[2] < c3[3]:
            fvg = {"formed_ts": c3[0] + tf_ms, "top": c3[3], "bottom": c1[2], "c3_idx": i + 2, "tf": tf_min}
            fvg["mit_ts"] = None
            for j in range(i + 3, len(candles)):
                if candles[j][3] <= fvg["top"]:
                    fvg["mit_ts"] = candles[j][0]; break
            fvgs.append(fvg)
    return fvgs


print("Loading..."); data = load_1m()
ts_1m = [r[0] for r in data]
candles_1h = [Candle(open=o, high=h, low=l, close=c, open_time=ts)
              for ts, o, h, l, c, _ in aggregate(data, 60)]
print(f"{len(data):,} 1m → {len(candles_1h):,} 1h")

tf_fvgs = {}
for tf_min, name in TFS:
    fvgs = detect_bull_fvgs(aggregate(data, tf_min), tf_min)
    tf_fvgs[name] = fvgs


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


# Detect patterns
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    if ir.direction != "long": continue
    patterns.append((ir, c5))
print(f"{len(patterns)} LONG i-RDRB+FVG patterns\n")


# Идём по паттернам, баcктестим original, и для winners с FVG — alt-entry симуляция
results = []
for ir, c5 in patterns:
    block_b, block_t = ir.rdrb.block
    entry_orig = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    sl = min(c.low for c in all5)  # pattern_low
    r_unit_orig = entry_orig - sl
    if r_unit_orig <= 0: continue
    tp_abs = entry_orig + r_unit_orig  # фиксированный TP price
    c5_close_ms = c5.open_time + MS_HOUR
    pattern_start = ir.rdrb.c1.open_time

    # Original backtest (RR=1)
    start_k = idx_at(c5_close_ms)
    end_k = min(start_k + MAX_HOLD_MIN, len(data))
    in_trade = False; outcome = "no_fill"
    for k in range(start_k, end_k):
        _, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if l_ <= entry_orig:
                in_trade = True
                if l_ <= sl: outcome = "loss"; break
                if h_ >= tp_abs: outcome = "win"; break
        else:
            if l_ <= sl: outcome = "loss"; break
            if h_ >= tp_abs: outcome = "win"; break
    if outcome not in ("win", "loss"): continue
    if outcome != "win": continue  # только winners

    # Найти все FVG в зоне (15m+20m+30m)
    all_fvgs_in_zone = []
    for _, name in TFS:
        for f in tf_fvgs[name]:
            if pattern_start <= f["formed_ts"] <= c5_close_ms \
               and f["bottom"] >= sl \
               and f["top"] <= block_b \
               and (f["mit_ts"] is None or f["mit_ts"] > c5_close_ms):
                all_fvgs_in_zone.append(f)
    if not all_fvgs_in_zone: continue  # пропускаем wins без FVG

    # Берём FVG с highest top (ближайший к block, легче залить)
    fvg_opt = max(all_fvgs_in_zone, key=lambda f: f["top"])
    new_entry = fvg_opt["top"]
    new_r_unit = new_entry - sl
    if new_r_unit <= 0: continue
    new_RR = (tp_abs - new_entry) / new_r_unit

    # Симуляция: достигла ли цена FVG.top ДО tp_abs после C5 close?
    filled_at_fvg = False
    for k in range(start_k, end_k):
        _, _, h_, l_, _, _ = data[k]
        if l_ <= new_entry:
            filled_at_fvg = True
            break
        if h_ >= tp_abs:
            # TP взят без захода в FVG
            break

    # Также fvg.bottom — самая глубокая граница
    deepest = min(all_fvgs_in_zone, key=lambda f: f["bottom"])["bottom"]
    deepest_RR = (tp_abs - deepest) / (deepest - sl) if (deepest - sl) > 0 else None

    results.append({
        "outcome": outcome,
        "tf": fvg_opt["tf"],
        "n_fvgs_in_zone": len(all_fvgs_in_zone),
        "entry_orig": entry_orig,
        "new_entry": new_entry,
        "deepest": deepest,
        "sl": sl,
        "tp_abs": tp_abs,
        "r_unit_orig": r_unit_orig,
        "new_r_unit": new_r_unit,
        "new_RR": new_RR,
        "deepest_RR": deepest_RR,
        "filled_at_fvg": filled_at_fvg,
    })


n = len(results)
n_filled = sum(1 for r in results if r["filled_at_fvg"])
print(f"=== {n} LONG WINNERS с ≥1 FVG в зоне [pattern_low, block.bottom] ===\n")
print(f"Сколько ДОШЛО до FVG.top после C5 close: {n_filled} / {n} = {n_filled/n*100:.1f}%")
print(f"Сколько НЕ дошло (TP взят с 0.5 block без захода в FVG): {n - n_filled} / {n} = {(n-n_filled)/n*100:.1f}%\n")

print("=== RR при alt-entry на FVG.top ===\n")

rrs = [r["new_RR"] for r in results]
print(f"Средний new_RR (по 85): {sum(rrs)/len(rrs):.2f}")
print(f"Медианный new_RR:       {sorted(rrs)[len(rrs)//2]:.2f}")
print(f"Min:                    {min(rrs):.2f}")
print(f"Max:                    {max(rrs):.2f}")

# Только те, что дошли — реалистичный RR
filled = [r for r in results if r["filled_at_fvg"]]
if filled:
    rrs_f = [r["new_RR"] for r in filled]
    print(f"\nДля {len(filled)} реально заполнившихся:")
    print(f"  Средний new_RR: {sum(rrs_f)/len(rrs_f):.2f}")
    print(f"  Медиана:        {sorted(rrs_f)[len(rrs_f)//2]:.2f}")

# Глубочайшая граница (FVG.bottom)
print("\n=== Если бы entry был на FVG.bottom (самая глубокая граница) ===\n")
deepest_rrs = [r["deepest_RR"] for r in results if r["deepest_RR"] is not None]
print(f"Средний RR на самой глубокой границе: {sum(deepest_rrs)/len(deepest_rrs):.2f}")
print(f"Медиана:                              {sorted(deepest_rrs)[len(deepest_rrs)//2]:.2f}")
print(f"Max:                                  {max(deepest_rrs):.2f}")

# Сколько достигало самого глубокого FVG?
n_deep_filled = 0
for r in results:
    deepest_price = r["deepest"]
    # Re-simulate filling to deepest
    # (для упрощения: если low где-то достиг deepest до tp_abs)
    start_k = idx_at(r.get("c5_close_ms_unused", 0)) if False else None
    # Используем ту же симуляцию (только нужно сохранить c5_close_ms)
    # Перепишем: добавим в records
    pass

# Простой подход — учесть факт fill в основной симуляции через FVG.bottom
# Пропустим повторно, просто посчитаем гипотетический RR
print("\n=== Распределение new_RR по бакетам (alt-entry FVG.top) ===")
buckets = [(0, 1, "<1"), (1, 1.5, "[1, 1.5)"), (1.5, 2, "[1.5, 2)"),
           (2, 3, "[2, 3)"), (3, 5, "[3, 5)"), (5, 100, "≥5")]
for lo, hi, name in buckets:
    sub = [r for r in results if lo <= r["new_RR"] < hi]
    f_sub = sum(1 for r in sub if r["filled_at_fvg"])
    print(f"  RR {name:<10}: {len(sub):>4} winners,  fill {f_sub} ({f_sub/len(sub)*100 if sub else 0:.0f}%)")

# Сколько TF использовалось
print("\n=== По исходному TF FVG (с highest-top) ===")
for _, name in TFS:
    tf_min = int(name[:-1])
    sub = [r for r in results if r["tf"] == tf_min]
    if sub:
        f_sub = sum(1 for r in sub if r["filled_at_fvg"])
        rrs_s = [r["new_RR"] for r in sub]
        print(f"  {name}: {len(sub):>4} winners,  fill {f_sub}/{len(sub)} ({f_sub/len(sub)*100:.0f}%),  avg RR={sum(rrs_s)/len(rrs_s):.2f}")
