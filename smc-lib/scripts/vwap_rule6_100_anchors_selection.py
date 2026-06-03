"""По Правилу 6: 100 крайних D-фракталов, dynamic anchor (96 candidates в i+1 D,
шаг 15m, max composite). Затем селекция:
  - 5 most EFFECTIVE LONG (FL, top composite)
  - 5 most EFFECTIVE SHORT (FH, top composite)
  - 5 most ANCHORED (top total_interactions across all 100)

Cascade: 1h, 2h, 4h, 6h, 8h, 12h.
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
UTC = timezone.utc
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
STEP_MIN = 15
N_CANDIDATES = 24*60 // STEP_MIN   # = 96
TOP_N = 5

print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
print(f"  {len(rows)} 1m bars")

def aggregate(d, tfms):
    out=[]; cb=None; o=h=l=c=0.0; v=0.0
    for ts,oo,hh,ll,cc,vv in d:
        b = ts - (ts % tfms)
        if b!=cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c=oo,hh,ll,cc; v=vv
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out

# D bars + fractals
bars_d = aggregate(rows, TF_MAP["D"])
cans_d = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars_d]
print(f"  D bars: {len(bars_d)}")

fractals = []
TF_D_MS = TF_MAP["D"]
for i in range(2, len(cans_d) - 2):
    f = detect_fractal(cans_d[i-2:i+3], n=2)
    if f is None: continue
    confirm_ts = cans_d[i+2].open_time + TF_D_MS
    pivot_open = cans_d[i].open_time
    fractals.append({
        "pivot_open_ts": pivot_open,
        "pivot_close_ts": pivot_open + TF_D_MS,    # start of i+1 D bar
        "i_plus_1_end_ts": pivot_open + 2*TF_D_MS,  # end of i+1 D bar
        "level": f.level,
        "direction": f.direction,
        "confirm_ts": confirm_ts,
    })

last_ts = rows[-1][0]
confirmed = [f for f in fractals if f["confirm_ts"] <= last_ts]
last_N = confirmed[-N_ANCHORS:]
print(f"  Подтверждённых D-фракталов: {len(confirmed)}, берём последние {len(last_N)}")
print(f"  Окно (по pivot open): {datetime.fromtimestamp(last_N[0]['pivot_open_ts']/1000, MSK).strftime('%Y-%m-%d')} → {datetime.fromtimestamp(last_ts/1000, MSK).strftime('%Y-%m-%d')}")
print(f"  Cascade: {', '.join(LTF_CASCADE)}, step={STEP_MIN}m → {N_CANDIDATES} candidates per fractal\n")

# Pre-aggregate LTF cascade once
print("Aggregating LTF cascade...")
bars_by_tf = {tf: aggregate(rows, TF_MAP[tf]) for tf in LTF_CASCADE}
last_close = rows[-1][4]

def compute_at_anchor(anchor_ts):
    """Returns (composite, total_interactions, vwap_now_avg)."""
    per_tf = []
    vwap_now_per_tf = {}
    for tf in LTF_CASCADE:
        bars = bars_by_tf[tf]
        tfms = TF_MAP[tf]
        anchor_bucket = anchor_ts - (anchor_ts % tfms)
        anchor_idx = None
        for idx, b in enumerate(bars):
            if b[0] >= anchor_bucket:
                anchor_idx = idx; break
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
    vwap_avg = sum(valid_now)/len(valid_now) if valid_now else None
    return comp.composite, comp.total_interactions, vwap_avg

# Dynamic anchor per Rule 6: пробуем 96 candidates в i+1, выбираем max composite
print(f"Applying Rule 6 (dynamic anchor) для {len(last_N)} фракталов...")
results = []
for k, f in enumerate(last_N):
    if k % 20 == 0: print(f"  {k}/{len(last_N)}", flush=True)
    base = f["pivot_close_ts"]   # = open i+1
    candidates = []
    for off in range(N_CANDIDATES):
        a_ts = base + off * STEP_MIN * MS_M
        if a_ts >= last_ts: break
        comp, inter, vw_now = compute_at_anchor(a_ts)
        candidates.append({"anchor_ts": a_ts, "off_min": off*STEP_MIN, "comp": comp,
                           "inter": inter, "vwap_now": vw_now})
    if not candidates: continue
    best = max(candidates, key=lambda c: c["comp"])
    results.append({
        "pivot_open_ts": f["pivot_open_ts"],
        "level": f["level"],
        "direction": f["direction"],
        "best_anchor_ts": best["anchor_ts"],
        "best_offset_min": best["off_min"],
        "composite": best["comp"],
        "total_interactions": best["inter"],
        "vwap_now": best["vwap_now"],
    })
print(f"  ✓ Computed: {len(results)} фракталов\n")

# Selection
fl_pool = [r for r in results if r["direction"] == "low"]
fh_pool = [r for r in results if r["direction"] == "high"]
print(f"Распределение: FL = {len(fl_pool)}, FH = {len(fh_pool)}\n")

top5_long  = sorted(fl_pool, key=lambda r: -r["composite"])[:TOP_N]
top5_short = sorted(fh_pool, key=lambda r: -r["composite"])[:TOP_N]
top5_anchor = sorted(results, key=lambda r: -r["total_interactions"])[:TOP_N]

def fmt_anchor(ts): return datetime.fromtimestamp(ts/1000, MSK).strftime('%Y-%m-%d %H:%M')
def fmt_pivot(ts): return datetime.fromtimestamp(ts/1000, MSK).strftime('%Y-%m-%d')

def print_table(title, rows_list):
    print(f"\n{'='*125}")
    print(f"  {title}")
    print(f"{'='*125}")
    print(f"  {'#':<3} {'Pivot date':<13} {'Type':<5} {'Anchor (MSK)':<19} {'+off':>6} {'Anchor lvl':>11} {'VWAP_now':>10} {'Δ%close':>8} {'Comp.':>7} {'Touches':>9}")
    for i, r in enumerate(rows_list, 1):
        t = "FH" if r["direction"] == "high" else "FL"
        delta_pct = (r["vwap_now"] - last_close) / last_close * 100 if r["vwap_now"] else 0
        off_h = r["best_offset_min"] / 60
        print(f"  {i:<3} {fmt_pivot(r['pivot_open_ts']):<13} {t:<5} {fmt_anchor(r['best_anchor_ts']):<19} {off_h:>+5.1f}h {r['level']:>11.0f} {r['vwap_now']:>10.0f} {delta_pct:>+7.2f}% {r['composite']:>6.3f} {r['total_interactions']:>9}")

print(f"\nlast close: {last_close:.2f} @ {datetime.fromtimestamp(last_ts/1000, MSK).strftime('%Y-%m-%d %H:%M')} MSK")
print_table(f"TOP-{TOP_N} EFFECTIVE для LONG (FL фракталы, max composite)", top5_long)
print_table(f"TOP-{TOP_N} EFFECTIVE для SHORT (FH фракталы, max composite)", top5_short)
print_table(f"TOP-{TOP_N} ANCHOR (по total_interactions — самые отторгованные)", top5_anchor)

# Combined: union, sorted by distance to last close
print(f"\n{'='*125}")
print(f"  ОБЪЕДИНЁННАЯ ПОДБОРКА: union 3 списков, сортировка по distance к last close ({last_close:.0f})")
print(f"{'='*125}")
union_ids = {id(r) for r in top5_long+top5_short+top5_anchor}
union = [r for r in results if id(r) in union_ids]
print(f"  Уникальных уровней: {len(union)}\n")
by_dist = sorted(union, key=lambda r: abs(r["vwap_now"] - last_close) if r["vwap_now"] else 1e9)
print(f"  {'#':<3} {'Pivot date':<13} {'Type':<5} {'Anchor MSK':<19} {'+off':>6} {'Anchor lvl':>11} {'VWAP_now':>10} {'Δ%close':>8} {'Comp.':>7} {'Touches':>9}  tags")
for i, r in enumerate(by_dist, 1):
    t = "FH" if r["direction"] == "high" else "FL"
    delta_pct = (r["vwap_now"] - last_close) / last_close * 100 if r["vwap_now"] else 0
    off_h = r["best_offset_min"] / 60
    tags = []
    if r in top5_long:  tags.append("LONG")
    if r in top5_short: tags.append("SHORT")
    if r in top5_anchor: tags.append("ANCH")
    print(f"  {i:<3} {fmt_pivot(r['pivot_open_ts']):<13} {t:<5} {fmt_anchor(r['best_anchor_ts']):<19} {off_h:>+5.1f}h {r['level']:>11.0f} {r['vwap_now']:>10.0f} {delta_pct:>+7.2f}% {r['composite']:>6.3f} {r['total_interactions']:>9}  {'+'.join(tags)}")
