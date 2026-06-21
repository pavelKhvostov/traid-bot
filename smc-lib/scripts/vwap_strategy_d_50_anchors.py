"""VWAPs ASVK — 50 крайних D-фракталов, anchor = CLOSE D пивот-бара.

Изменения от vwap_strategy_3d_50_anchors.py:
- TF фракталов: 3D → D
- Anchor: open пивот-бара → CLOSE пивот-бара (= open пивот + 1D)
- LTF cascade: D, 12h, 4h, 1h, 15m → 12h, 4h, 1h, 15m (без D, т.к. D = anchor TF)

Формула VWAP: smc-lib канон (typical_price = (h+l+c)/3 × volume).
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
    "D":   24*MS_H,
    "12h": 12*MS_H,
    "6h":  6*MS_H,
    "4h":  4*MS_H,
    "2h":  2*MS_H,
    "1h":  MS_H,
    "15m": 15*MS_M,
}
ANCHOR_TF = "D"
LTF_CASCADE = ["12h", "6h", "4h", "2h", "1h", "15m"]  # ниже D, расширено +6h, +2h
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

# === Aggregate D ===
bars_d = aggregate(rows, TF_MAP[ANCHOR_TF])
cans_d = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars_d]
print(f"  D bars: {len(bars_d)}")

# Last 50 confirmed D fractals (Williams N=2)
TF_D_MS = TF_MAP[ANCHOR_TF]
fractals = []
for i in range(2, len(cans_d) - 2):
    f = detect_fractal(cans_d[i-2:i+3], n=2)
    if f is None: continue
    confirm_ts = cans_d[i+2].open_time + TF_D_MS
    pivot_open = cans_d[i].open_time
    pivot_close = pivot_open + TF_D_MS    # CLOSE D пивот-бара (= start of next bar)
    fractals.append({
        "pivot_open_ts": pivot_open,
        "anchor_ts": pivot_close,         # ← anchor = close of pivot bar
        "level": f.level,
        "direction": f.direction,
        "confirm_ts": confirm_ts,
    })

last_ts = rows[-1][0]
confirmed = [f for f in fractals if f["confirm_ts"] <= last_ts]
last_50 = confirmed[-N_ANCHORS:]
print(f"  Подтверждённых D-фракталов: {len(confirmed)}, берём последние {len(last_50)}")
oldest_ms = last_50[0]["pivot_open_ts"]
print(f"  Окно (по pivot open): {datetime.fromtimestamp(oldest_ms/1000, MSK).strftime('%Y-%m-%d')} → {datetime.fromtimestamp(last_ts/1000, MSK).strftime('%Y-%m-%d')}")
print(f"  Anchor = close D пивот-бара (= pivot open + 24h)")

# Aggregate LTF cascade
print(f"\nAggregating LTF: {', '.join(LTF_CASCADE)}...")
bars_by_tf = {tf: aggregate(rows, TF_MAP[tf]) for tf in LTF_CASCADE}
last_close = rows[-1][4]
print(f"  last close: {last_close:.2f} @ {datetime.fromtimestamp(last_ts/1000, MSK).strftime('%Y-%m-%d %H:%M')} MSK\n")

rankings = []
print(f"Computing VWAP + effectiveness для {len(last_50)} anchors (formula = typical_price × volume)...")
for f in last_50:
    anchor_ts = f["anchor_ts"]
    per_tf = []
    vwap_now_per_tf = {}
    for tf in LTF_CASCADE:
        bars = bars_by_tf[tf]
        tfms = TF_MAP[tf]
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
        "pivot_open_ts": f["pivot_open_ts"],
        "anchor_ts": anchor_ts,
        "level": f["level"],
        "direction": f["direction"],
        "vwap_now": vwap_avg_now,
        "distance_pct": (vwap_avg_now - last_close) / last_close * 100,
        "composite": comp.composite,
        "total_interactions": comp.total_interactions,
    })

by_effective = sorted(rankings, key=lambda r: -r["composite"])
top5_eff = by_effective[:TOP_N]
by_traded = sorted(rankings, key=lambda r: -r["total_interactions"])
top5_traded = by_traded[:TOP_N]

def fmt_date(ms): return datetime.fromtimestamp(ms/1000, MSK).strftime('%Y-%m-%d')

def print_table(title, rows_list):
    print(f"\n{'='*100}")
    print(f"  {title}")
    print(f"{'='*100}")
    print(f"  {'#':<3} {'Pivot open':<13} {'Type':<5} {'Anchor lvl':>11} {'VWAP_now':>10} {'Δ%close':>9} {'Comp.':>7} {'Touches':>9}")
    for i, r in enumerate(rows_list, 1):
        t = "FH" if r["direction"] == "high" else "FL"
        print(f"  {i:<3} {fmt_date(r['pivot_open_ts']):<13} {t:<5} {r['level']:>11.0f} {r['vwap_now']:>10.0f} {r['distance_pct']:>+8.2f}% {r['composite']:>6.3f} {r['total_interactions']:>9}")

print_table(f"TOP-{TOP_N} most EFFECTIVE (composite)", top5_eff)
print_table(f"TOP-{TOP_N} most TRADED (total_interactions)", top5_traded)

eff_ids = {id(r) for r in top5_eff}
traded_ids = {id(r) for r in top5_traded}
intersect = [r for r in rankings if id(r) in eff_ids and id(r) in traded_ids]
union = [r for r in rankings if id(r) in eff_ids or id(r) in traded_ids]
print(f"\n  Пересечение (EFF ∩ TRD): {len(intersect)}")
print(f"  Union (EFF ∪ TRD): {len(union)} уникальных")

print(f"\n{'='*100}")
print(f"  ИТОГОВАЯ ПОДБОРКА = effective ∪ traded ({len(union)} уровней) — отсорт. по distance к last_close")
print(f"{'='*100}")
by_dist = sorted(union, key=lambda r: abs(r["distance_pct"]))
print(f"  {'#':<3} {'Pivot open':<13} {'Type':<5} {'Anchor lvl':>11} {'VWAP_now':>10} {'Δ%close':>9} {'Comp.':>7} {'Touches':>9}  tags")
for i, r in enumerate(by_dist, 1):
    t = "FH" if r["direction"] == "high" else "FL"
    tags = []
    if id(r) in eff_ids: tags.append("EFF")
    if id(r) in traded_ids: tags.append("TRD")
    print(f"  {i:<3} {fmt_date(r['pivot_open_ts']):<13} {t:<5} {r['level']:>11.0f} {r['vwap_now']:>10.0f} {r['distance_pct']:>+8.2f}% {r['composite']:>6.3f} {r['total_interactions']:>9}  {'+'.join(tags)}")
