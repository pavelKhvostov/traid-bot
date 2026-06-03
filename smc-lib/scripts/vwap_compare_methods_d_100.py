"""Сравнение двух методов anchor для VWAPs ASVK на 100 крайних D-фракталах.

Cascade: 1h, 2h, 4h, 6h, 8h, 12h.

Methods:
  M1: anchor = close D пивот-бара (= open D-bar i+1)
  M2: anchor — любая свеча внутри D-bar i+1. Тестируем 6 позиций:
       +0h (open i+1), +4h, +8h, +12h, +16h, +20h. Возвращаем best composite.

Метрики per fractal:
  - M1_comp: composite anchored на close pivot
  - M2_best_comp: max composite среди 6 позиций M2
  - M2_avg_comp: средний composite по 6 позициям M2
  - M2_best_offset: какой offset (часы) дал max

Aggregate:
  - mean / median composite для M1 и M2
  - per fractal: ΔM2_best - M1
  - distribution best_offset
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
    "8h":  8*MS_H,
    "6h":  6*MS_H,
    "4h":  4*MS_H,
    "2h":  2*MS_H,
    "1h":  MS_H,
}
LTF_CASCADE = ["12h", "8h", "6h", "4h", "2h", "1h"]
N_ANCHORS = 100
M2_OFFSETS_H = [0, 4, 8, 12, 16, 20]   # hours into i+1 D bar

print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
print(f"  {len(rows)} 1m bars")

def aggregate(d, tfms):
    out = []; cb = None; o = h = l = c = 0.0; v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - (ts % tfms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c = oo, hh, ll, cc; v = vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out

# Aggregate D for fractal detection
bars_d = aggregate(rows, TF_MAP["D"])
cans_d = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars_d]
print(f"  D bars: {len(bars_d)}")

# Last N confirmed D fractals
fractals = []
TF_D_MS = TF_MAP["D"]
for i in range(2, len(cans_d) - 2):
    f = detect_fractal(cans_d[i-2:i+3], n=2)
    if f is None: continue
    confirm_ts = cans_d[i+2].open_time + TF_D_MS
    pivot_open = cans_d[i].open_time
    pivot_close = pivot_open + TF_D_MS    # = open of i+1
    fractals.append({
        "pivot_open_ts": pivot_open,
        "close_pivot_ts": pivot_close,
        "level": f.level,
        "direction": f.direction,
        "confirm_ts": confirm_ts,
    })

last_ts = rows[-1][0]
confirmed = [f for f in fractals if f["confirm_ts"] <= last_ts]
last_N = confirmed[-N_ANCHORS:]
print(f"  Подтверждённых D-фракталов: {len(confirmed)}, берём последние {len(last_N)}")
print(f"  Окно (по pivot open): {datetime.fromtimestamp(last_N[0]['pivot_open_ts']/1000, MSK).strftime('%Y-%m-%d')} → {datetime.fromtimestamp(last_ts/1000, MSK).strftime('%Y-%m-%d')}")
print(f"  Cascade: {', '.join(LTF_CASCADE)}")
print(f"  Anchor M1: close D pivot (= open D i+1)")
print(f"  Anchor M2: best among offsets {M2_OFFSETS_H} часов внутри D i+1\n")

# Pre-aggregate LTF cascade once
print("Aggregating LTF cascade...")
bars_by_tf = {tf: aggregate(rows, TF_MAP[tf]) for tf in LTF_CASCADE}

def compute_composite_at_anchor(anchor_ts):
    """Возвращает (composite, total_interactions) для anchor_ts."""
    per_tf = []
    for tf in LTF_CASCADE:
        bars = bars_by_tf[tf]
        tfms = TF_MAP[tf]
        anchor_bucket = anchor_ts - (anchor_ts % tfms)
        anchor_idx = None
        # бинарный поиск был бы быстрее, но bars небольшие
        for idx, b in enumerate(bars):
            if b[0] >= anchor_bucket:
                anchor_idx = idx; break
        if anchor_idx is None: continue
        ohlcv = [(b[1], b[2], b[3], b[4], b[5]) for b in bars]
        vw_series = anchored_vwap(ohlcv, anchor_idx)
        ohlc_pairs = [(b[1], b[2], b[3], b[4]) for b in bars[anchor_idx:]]
        vw_pairs = vw_series[anchor_idx:]
        eff = effectiveness_per_tf(tf, ohlc_pairs, vw_pairs)
        per_tf.append(eff)
    comp = composite_effectiveness(anchor_ts, per_tf)
    return comp.composite, comp.total_interactions

# Compute M1 and M2 per fractal
print(f"Computing M1 и M2 для {len(last_N)} фракталов...")
results = []
for k, f in enumerate(last_N):
    if k % 20 == 0: print(f"  {k}/{len(last_N)}", flush=True)
    # M1: close pivot
    m1_anchor = f["close_pivot_ts"]
    m1_comp, m1_inter = compute_composite_at_anchor(m1_anchor)
    # M2: try 6 offsets within i+1 D bar
    m2_results = []
    for off_h in M2_OFFSETS_H:
        a_ts = m1_anchor + off_h * MS_H
        if a_ts >= last_ts: continue
        comp, inter = compute_composite_at_anchor(a_ts)
        m2_results.append((off_h, comp, inter))
    if not m2_results: continue
    m2_best_off, m2_best_comp, m2_best_inter = max(m2_results, key=lambda x: x[1])
    m2_avg_comp = sum(r[1] for r in m2_results) / len(m2_results)
    results.append({
        "pivot": f["pivot_open_ts"],
        "dir": f["direction"],
        "level": f["level"],
        "m1_comp": m1_comp, "m1_inter": m1_inter,
        "m2_best_comp": m2_best_comp, "m2_best_off": m2_best_off, "m2_best_inter": m2_best_inter,
        "m2_avg_comp": m2_avg_comp,
        "m2_all": m2_results,
    })

print(f"\n  Computed: {len(results)}\n")

# Aggregate
m1_comps = [r["m1_comp"] for r in results]
m2_best_comps = [r["m2_best_comp"] for r in results]
m2_avg_comps = [r["m2_avg_comp"] for r in results]
delta_m2_m1 = [r["m2_best_comp"] - r["m1_comp"] for r in results]

print(f"{'='*100}")
print(f"  СВОДНАЯ СРАВНИТЕЛЬНАЯ СТАТИСТИКА (n={len(results)} D-фракталов)")
print(f"{'='*100}")
print(f"  {'Metric':<35} {'mean':>9} {'median':>9} {'std':>8} {'min':>8} {'max':>8}")
print(f"  {'M1 composite (close pivot)':<35} {np.mean(m1_comps):>9.3f} {np.median(m1_comps):>9.3f} {np.std(m1_comps):>8.3f} {min(m1_comps):>8.3f} {max(m1_comps):>8.3f}")
print(f"  {'M2_best composite (best of 6)':<35} {np.mean(m2_best_comps):>9.3f} {np.median(m2_best_comps):>9.3f} {np.std(m2_best_comps):>8.3f} {min(m2_best_comps):>8.3f} {max(m2_best_comps):>8.3f}")
print(f"  {'M2_avg composite (avg of 6)':<35} {np.mean(m2_avg_comps):>9.3f} {np.median(m2_avg_comps):>9.3f} {np.std(m2_avg_comps):>8.3f} {min(m2_avg_comps):>8.3f} {max(m2_avg_comps):>8.3f}")
print(f"  {'Δ (M2_best - M1) per fractal':<35} {np.mean(delta_m2_m1):>+9.3f} {np.median(delta_m2_m1):>+9.3f} {np.std(delta_m2_m1):>8.3f} {min(delta_m2_m1):>+8.3f} {max(delta_m2_m1):>+8.3f}")

# Win rate of M2 over M1
m2_wins = sum(1 for d in delta_m2_m1 if d > 0.01)
m2_ties = sum(1 for d in delta_m2_m1 if abs(d) <= 0.01)
m2_loses = sum(1 for d in delta_m2_m1 if d < -0.01)
print(f"\n  M2_best vs M1 на per-fractal базе:")
print(f"    M2 win (>+0.01): {m2_wins}/{len(results)} = {m2_wins/len(results)*100:.1f}%")
print(f"    Tie (±0.01):     {m2_ties}/{len(results)} = {m2_ties/len(results)*100:.1f}%")
print(f"    M2 lose (<-0.01): {m2_loses}/{len(results)} = {m2_loses/len(results)*100:.1f}%")

# Distribution of best offset
from collections import Counter
off_dist = Counter(r["m2_best_off"] for r in results)
print(f"\n  Распределение «best offset» (час внутри i+1):")
for off in sorted(off_dist.keys()):
    cnt = off_dist[off]
    bar = "█" * int(cnt/len(results)*40)
    print(f"    +{off:>2}h  {cnt:>3}  ({cnt/len(results)*100:>4.1f}%)  {bar}")

# Per-offset average composite (across all fractals)
print(f"\n  Средний composite по каждому offset (по всем {len(results)} фракталам):")
offset_comps = {off: [] for off in M2_OFFSETS_H}
for r in results:
    for off, comp, _ in r["m2_all"]:
        offset_comps[off].append(comp)
for off in M2_OFFSETS_H:
    if offset_comps[off]:
        mc = np.mean(offset_comps[off])
        print(f"    +{off:>2}h  mean={mc:.3f}  n={len(offset_comps[off])}")
