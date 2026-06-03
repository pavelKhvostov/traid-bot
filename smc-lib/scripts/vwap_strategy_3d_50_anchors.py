"""VWAPs ASVK — 50 крайних 3D-фракталов как anchors, селекция top-5 effective + top-5 traded.

Шаги:
1. Aggregate BTC 1m → 3D
2. Найти 50 последних подтверждённых 3D-фракталов (Williams N=2)
3. Для каждого anchor построить anchored VWAP
4. Посчитать effectiveness через LTF cascade (D, 12h, 4h, 1h, 15m)
5. Селекция:
   - Top 5 по composite (most effective = WR взаимодействий)
   - Top 5 по total_interactions (most traded = max touches)
6. Печать обеих таблиц + общий список

Display TF для подсчёта effectiveness — LTFs ниже 3D.
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fractal.code import detect_fractal
from indicators.vwap_anchored import anchored_vwap
from indicators.vwap_effectiveness import effectiveness_per_tf, composite_effectiveness

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_M = 60_000
MS_H = 60*MS_M
TF_MAP = {
    "3D": 3*24*MS_H,
    "D":  24*MS_H,
    "12h": 12*MS_H,
    "4h": 4*MS_H,
    "1h": MS_H,
    "15m": 15*MS_M,
}
LTF_CASCADE = ["D", "12h", "4h", "1h", "15m"]  # для effectiveness scoring
N_ANCHORS = 50
TOP_N = 5

print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
print(f"  {len(rows)} 1m bars")

def aggregate(d, tfms, anchor=0):
    out = []; cb = None; o = h = l = c = 0.0; v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - ((ts - anchor) % tfms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c = oo, hh, ll, cc; v = vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out

# === 1. Aggregate 3D ===
bars_3d = aggregate(rows, TF_MAP["3D"])
cans_3d = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars_3d]
print(f"  3D bars: {len(bars_3d)}")

# === 2. Last 50 confirmed 3D fractals ===
fractals = []
TF_3D_MS = TF_MAP["3D"]
for i in range(2, len(cans_3d) - 2):
    f = detect_fractal(cans_3d[i-2:i+3], n=2)
    if f is None: continue
    confirm_ts = cans_3d[i+2].open_time + TF_3D_MS  # подтверждается после i+2 закрылся
    fractals.append({
        "anchor_ts": cans_3d[i].open_time,
        "level": f.level,
        "direction": f.direction,
        "confirm_ts": confirm_ts,
    })

last_ts = rows[-1][0]
# Берём 50 последних, у которых confirm_ts ≤ last_ts (подтверждены)
confirmed = [f for f in fractals if f["confirm_ts"] <= last_ts]
last_50 = confirmed[-N_ANCHORS:]
print(f"  Подтверждённых 3D-фракталов всего: {len(confirmed)}, берём последние {len(last_50)}")
oldest_ms = last_50[0]["anchor_ts"]
print(f"  Окно: {datetime.fromtimestamp(oldest_ms/1000, MSK).strftime('%Y-%m-%d')} → {datetime.fromtimestamp(last_ts/1000, MSK).strftime('%Y-%m-%d')}")

# === 3-4. VWAP + effectiveness для каждого anchor ===
print(f"\nAggregating LTF cascade: {', '.join(LTF_CASCADE)}...")
bars_by_tf = {tf: aggregate(rows, TF_MAP[tf]) for tf in LTF_CASCADE}

last_close = rows[-1][4]
print(f"  last close: {last_close:.2f} @ {datetime.fromtimestamp(last_ts/1000, MSK).strftime('%Y-%m-%d %H:%M')} MSK\n")

rankings = []
print(f"Computing VWAP + effectiveness для {len(last_50)} anchors...")
for f in last_50:
    anchor_ts = f["anchor_ts"]
    per_tf = []
    vwap_now_per_tf = {}
    for tf in LTF_CASCADE:
        bars = bars_by_tf[tf]
        tfms = TF_MAP[tf]
        # Найти anchor bar (первый bar где open_time >= anchor_ts bucket)
        anchor_bucket = anchor_ts - (anchor_ts % tfms)
        anchor_idx = None
        for idx, b in enumerate(bars):
            if b[0] >= anchor_bucket:
                anchor_idx = idx
                break
        if anchor_idx is None: continue
        ohlcv = [(b[1], b[2], b[3], b[4], b[5]) for b in bars]
        vw_series = anchored_vwap(ohlcv, anchor_idx)
        vw_now = vw_series[-1]
        vwap_now_per_tf[tf] = vw_now
        ohlc_pairs = [(b[1], b[2], b[3], b[4]) for b in bars[anchor_idx:]]
        vw_pairs = vw_series[anchor_idx:]
        eff = effectiveness_per_tf(tf, ohlc_pairs, vw_pairs)
        per_tf.append(eff)
    comp = composite_effectiveness(anchor_ts, per_tf)
    valid_now = [v for v in vwap_now_per_tf.values() if v is not None]
    vwap_avg_now = sum(valid_now) / len(valid_now) if valid_now else f["level"]
    rankings.append({
        "anchor_ts": anchor_ts,
        "level": f["level"],
        "direction": f["direction"],
        "vwap_now": vwap_avg_now,
        "distance_pct": (vwap_avg_now - last_close) / last_close * 100,
        "composite": comp.composite,
        "total_interactions": comp.total_interactions,
        "per_tf": per_tf,
    })

# === 5. Селекция ===
by_effective = sorted(rankings, key=lambda r: -r["composite"])
top5_eff = by_effective[:TOP_N]
by_traded = sorted(rankings, key=lambda r: -r["total_interactions"])
top5_traded = by_traded[:TOP_N]

def fmt_date(ms): return datetime.fromtimestamp(ms/1000, MSK).strftime('%Y-%m-%d')

def print_table(title, rows_list):
    print(f"\n{'='*100}")
    print(f"  {title}")
    print(f"{'='*100}")
    print(f"  {'#':<3} {'Anchor date':<13} {'Type':<5} {'Anchor lvl':>11} {'VWAP_now':>10} {'Δ%close':>9} {'Comp.':>7} {'Touches':>9}")
    for i, r in enumerate(rows_list, 1):
        t = "FH" if r["direction"] == "high" else "FL"
        print(f"  {i:<3} {fmt_date(r['anchor_ts']):<13} {t:<5} {r['level']:>11.0f} {r['vwap_now']:>10.0f} {r['distance_pct']:>+8.2f}% {r['composite']:>6.3f} {r['total_interactions']:>9}")

print_table(f"TOP-{TOP_N} most EFFECTIVE (по composite — взвешенный WR взаимодействий)", top5_eff)
print_table(f"TOP-{TOP_N} most TRADED (по total_interactions — суммарное число touches)", top5_traded)

# Пересечение
eff_ids = {id(r) for r in top5_eff}
traded_ids = {id(r) for r in top5_traded}
intersect = [r for r in rankings if id(r) in eff_ids and id(r) in traded_ids]
union = [r for r in rankings if id(r) in eff_ids or id(r) in traded_ids]
print(f"\n  Пересечение (effective ∩ traded): {len(intersect)}")
print(f"  Union (effective ∪ traded): {len(union)} уникальных")

# Сводка по выбранным 10 (или меньше при пересечении)
print(f"\n{'='*100}")
print(f"  ИТОГОВАЯ ПОДБОРКА = effective ∪ traded ({len(union)} VWAP-уровней) — отсортировано по distance к last_close")
print(f"{'='*100}")
by_dist = sorted(union, key=lambda r: abs(r["distance_pct"]))
print(f"  {'#':<3} {'Anchor date':<13} {'Type':<5} {'Anchor lvl':>11} {'VWAP_now':>10} {'Δ%close':>9} {'Comp.':>7} {'Touches':>9}  tags")
for i, r in enumerate(by_dist, 1):
    t = "FH" if r["direction"] == "high" else "FL"
    tags = []
    if id(r) in eff_ids: tags.append("EFF")
    if id(r) in traded_ids: tags.append("TRD")
    print(f"  {i:<3} {fmt_date(r['anchor_ts']):<13} {t:<5} {r['level']:>11.0f} {r['vwap_now']:>10.0f} {r['distance_pct']:>+8.2f}% {r['composite']:>6.3f} {r['total_interactions']:>9}  {'+'.join(tags)}")
